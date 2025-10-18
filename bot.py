# marketplace_bot.py
import json
import logging
import re
import datetime
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ========================
# CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282
DATA_PATH = Path("data.json")

PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$",
}

SELL_ENABLED = True

# ========================
# LOGGING
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# DATA HELPERS
# ========================
def load_data():
    if not DATA_PATH.exists():
        default = {"users": {}, "pending_groups": {}, "pending_withdrawals": {}}
        DATA_PATH.write_text(json.dumps(default, indent=2, ensure_ascii=False), encoding="utf8")
        return default
    return json.loads(DATA_PATH.read_text(encoding="utf8"))

def save_data(d):
    DATA_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf8")

data = load_data()

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {
            "balance": 0.0,
            "groups": [],
            "sales": 0,
            "daily_sales": {},
            "withdraw_history": [],
        }
        save_data(data)

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

# ========================
# REGEX
# ========================
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/)[A-Za-z0-9_-]+$",
    flags=re.IGNORECASE,
)

# ========================
# CANCEL
# ========================
async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operation cancelled.")

# ========================
# CALLBACKS (Admin approve/reject)
# ========================
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    payload = q.data

    # Group approval
    if payload.startswith("approve_group:") or payload.startswith("reject_group:"):
        action, uid_s = payload.split(":", 1)
        if uid_s not in data["pending_groups"]:
            await q.edit_message_text("⚠️ Already processed or not found.")
            return
        info = data["pending_groups"].pop(uid_s)
        user = data["users"].get(uid_s)
        if not user:
            # ensure user exists
            data["users"].setdefault(uid_s, {"balance":0.0,"groups":[],"sales":0,"daily_sales":{}})
            user = data["users"][uid_s]
        if action == "approve_group":
            user["sales"] = user.get("sales", 0) + 1
            today = datetime.datetime.utcnow().date().isoformat()
            user["daily_sales"][today] = user["daily_sales"].get(today, 0) + 1
            save_data(data)
            try:
                await context.bot.send_message(int(uid_s), f"✅ Your group {info['link']} has been approved by admin.")
            except:
                pass
            await q.edit_message_text("✅ Group approved.")
        else:
            try:
                await context.bot.send_message(int(uid_s), f"❌ Your group {info['link']} was rejected by admin.")
            except:
                pass
            await q.edit_message_text("❌ Group rejected.")
        save_data(data)
        return

    # Withdraw approval
    if payload.startswith("approve_withdraw:") or payload.startswith("reject_withdraw:"):
        action, uid_s = payload.split(":", 1)
        wd = data["pending_withdrawals"].pop(uid_s, None)
        if not wd:
            await q.edit_message_text("⚠️ Already processed or not found.")
            return
        # update withdraw history if exists
        hist = data["users"].get(uid_s, {}).get("withdraw_history", [])
        for rec in reversed(hist):
            if rec.get("amount") == wd.get("amount") and rec.get("status") == "Pending":
                rec["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break
        if action == "approve_withdraw":
            # deduct balance
            data["users"].setdefault(uid_s, {"balance":0.0,"groups":[],"sales":0,"daily_sales":{}, "withdraw_history":[]})
            data["users"][uid_s]["balance"] = max(0.0, data["users"][uid_s]["balance"] - float(wd["amount"]))
            try:
                await context.bot.send_message(int(uid_s), f"✅ Your withdrawal of ${wd['amount']} has been approved and processed.")
            except:
                pass
            await q.edit_message_text("✅ Withdrawal approved and processed.")
        else:
            try:
                await context.bot.send_message(int(uid_s), f"❌ Your withdrawal of ${wd['amount']} has been rejected.")
            except:
                pass
            await q.edit_message_text("❌ Withdrawal rejected.")
        save_data(data)
        return

# ========================
# USER INPUT HANDLER (non-admin)
# - price
# - group link submission
# - withdraw (multi-step using user_data flags)
# - otherwise: invalid message auto-reply
# ========================
async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    s_uid = str(uid)
    text = (update.message.text or "").strip()

    # Check for live withdraw flow steps in context.user_data
    if context.user_data.get("withdraw_step"):
        step = context.user_data["withdraw_step"]
        if step == "method":
            context.user_data["withdraw_method"] = text
            context.user_data["withdraw_step"] = "address"
            await update.message.reply_text("📨 Enter payment address / UPI ID / UID:")
            return
        if step == "address":
            context.user_data["withdraw_address"] = text
            context.user_data["withdraw_step"] = "amount"
            await update.message.reply_text("💰 Enter amount to withdraw (numbers only):")
            return
        if step == "amount":
            try:
                amount = float(text)
                if amount <= 0:
                    raise ValueError()
            except:
                await update.message.reply_text("❌ Invalid amount. Send numeric value or /cancel to stop.")
                return
            bal = data["users"][s_uid]["balance"]
            if amount > bal:
                await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal:.2f}")
                context.user_data.pop("withdraw_step", None)
                return
            # store pending withdrawal
            data["pending_withdrawals"][s_uid] = {
                "method": context.user_data.get("withdraw_method"),
                "address": context.user_data.get("withdraw_address"),
                "amount": amount,
                "time": now(),
            }
            rec = {"method": context.user_data.get("withdraw_method"), "address": context.user_data.get("withdraw_address"), "amount": amount, "status": "Pending", "time": now()}
            data["users"][s_uid].setdefault("withdraw_history", []).append(rec)
            save_data(data)
            context.user_data.pop("withdraw_step", None)
            # notify admin with approve/dismiss
            kb = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{s_uid}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{s_uid}"),
                ]
            ]
            try:
                await context.bot.send_message(ADMIN_ID, f"💸 Withdrawal request\nUser: {s_uid}\n{amount}$ via {rec['method']}\nAddress: {rec['address']}\nTime: {rec['time']}", reply_markup=InlineKeyboardMarkup(kb))
            except:
                pass
            await update.message.reply_text("✅ Withdrawal request sent to admin.")
            return

    # Standard user commands via text
    lower = text.lower()

    # price
    if lower == "price":
        msg = "📊 *Current Group Prices*\n\n"
        for k, v in PRICES.items():
            msg += f"📅 {k}: {v}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # withdraw start
    if lower == "withdraw":
        if not SELL_ENABLED:
            await update.message.reply_text("🚫 Withdrawals are available but selling toggle is unrelated. Proceeding with withdraw.")
        # check balance
        bal = data["users"][s_uid]["balance"]
        if bal <= 0:
            await update.message.reply_text("❌ You have no balance to withdraw.")
            return
        context.user_data["withdraw_step"] = "method"
        await update.message.reply_text("🏦 Enter withdraw method (e.g. UPI, Binance, BEP20, Polygon):")
        return

    # group invite link submission
    if INVITE_RE.match(text):
        if not SELL_ENABLED:
            await update.message.reply_text("🚫 Selling is currently disabled by admin.")
            return
        # store pending group keyed by user id (latest submission)
        data["pending_groups"][s_uid] = {"link": text, "time": now()}
        data["users"][s_uid].setdefault("groups", []).append(text)
        save_data(data)
        # notify admin with approve/reject inline buttons
        kb = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{s_uid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{s_uid}")
            ]
        ]
        try:
            await context.bot.send_message(ADMIN_ID, f"🆕 New group submission\nUser: {uid}\nLink: {text}\nTime: {now()}", reply_markup=InlineKeyboardMarkup(kb))
        except:
            pass
        await update.message.reply_text("✅ Group submitted to admin for review.")
        return

    # help / guidance for common messages
    if lower in ("help", "menu", "home"):
        await update.message.reply_text(
            "🧭 Use the input box:\n"
            "- Paste your *group invite link* to submit it for sale.\n"
            "- Send `price` to view current prices.\n"
            "- Send `withdraw` to start a withdrawal.\n"
            "If you want to cancel at any time, send /cancel."
        )
        return

    # fallback: invalid user input
    await update.message.reply_text(
        "❓ I didn't understand that. Send your group invite link to sell, `price` to see prices, `withdraw` to withdraw, or /cancel to stop."
    )

# ========================
# ADMIN INPUT HANDLER
# - stats
# - price <year> <newprice>
# - add <user_id> <amount>
# - inspect <user_id>
# - broadcast <message>
# - toggle
# - help/menu
# ========================
async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("❌ Empty message.")
        return

    parts = text.split()
    cmd = parts[0].lower()

    # toggle selling
    if cmd == "toggle":
        global SELL_ENABLED
        SELL_ENABLED = not SELL_ENABLED
        await update.message.reply_text(f"✅ Sell mode set to: {'ON' if SELL_ENABLED else 'OFF'}")
        return

    # stats
    if cmd == "stats":
        today = datetime.datetime.utcnow().date().isoformat()
        total = sum(u.get("daily_sales", {}).get(today, 0) for u in data["users"].values())
        await update.message.reply_text(f"📊 Total groups sold today: {total}")
        return

    # price update: price <year-key> <newprice>
    if cmd == "price" and len(parts) >= 3:
        year_key = " ".join(parts[1:-1])
        new_price = parts[-1]
        if year_key not in PRICES:
            await update.message.reply_text("❌ Invalid price key. Valid keys:\n" + ", ".join(PRICES.keys()))
            return
        PRICES[year_key] = new_price
        await update.message.reply_text(f"✅ Price for {year_key} updated to {new_price}")
        return

    # add balance: add <user_id> <amount>
    if cmd == "add" and len(parts) == 3:
        target = parts[1]
        try:
            amt = float(parts[2])
        except:
            await update.message.reply_text("❌ Invalid amount.")
            return
        ensure_user(int(target))
        data["users"][target]["balance"] = data["users"][target].get("balance", 0.0) + amt
        save_data(data)
        try:
            await context.bot.send_message(int(target), f"💵 Admin added ${amt:.2f} to your balance.")
        except:
            pass
        await update.message.reply_text(f"✅ Added ${amt:.2f} to user {target}")
        return

    # inspect user: inspect <user_id>
    if cmd == "inspect" and len(parts) == 2:
        target = parts[1]
        if target not in data["users"]:
            await update.message.reply_text("❌ User not found.")
            return
        u = data["users"][target]
        pending_g = data["pending_groups"].get(target)
        pending_w = data["pending_withdrawals"].get(target)
        text_msg = (
            f"📊 User: {target}\n"
            f"💰 Balance: ${u.get('balance',0.0):.2f}\n"
            f"🛒 Total groups submitted: {len(u.get('groups',[]))}\n"
            f"✅ Sales (approved): {u.get('sales',0)}\n"
            f"⏳ Pending group: {pending_g['link'] if pending_g else 'None'}\n"
            f"⏳ Pending withdraw: {pending_w['amount'] if pending_w else 'None'}\n"
        )
        await update.message.reply_text(text_msg)
        return

    # broadcast: broadcast <message...>
    if cmd == "broadcast" and len(parts) >= 2:
        msg = text[len(parts[0])+1:]
        count = 0
        for uid in list(data["users"].keys()):
            try:
                await context.bot.send_message(int(uid), f"📢 Broadcast from admin:\n\n{msg}")
                count += 1
            except:
                pass
        await update.message.reply_text(f"✅ Broadcast sent to {count} users.")
        return

    # list prices
    if cmd == "prices" or cmd == "price" and len(parts) == 1:
        msg = "📊 *Current Group Prices*\n\n"
        for k, v in PRICES.items():
            msg += f"📅 {k}: {v}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # help/menu
    if cmd in ("help", "menu"):
        await update.message.reply_text(
            "Admin commands:\n"
            "- `stats` — total sold today\n"
            "- `price <year key> <newprice>` — update price (e.g. price 2023 7$)\n"
            "- `add <user_id> <amount>` — add balance\n"
            "- `inspect <user_id>` — show user info\n"
            "- `broadcast <message>` — send to all users\n"
            "- `toggle` — enable/disable selling\n"
            "Use /cancel to stop flows."
        )
        return

    # fallback
    await update.message.reply_text("❓ Unknown admin command. Send `help` to see available admin commands.")

# ========================
# ROUTER: incoming text -> admin or user handler
# ========================
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        await handle_admin_input(update, context)
    else:
        await handle_user_input(update, context)

# ========================
# MAIN
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Only /cancel command persists
    app.add_handler(CommandHandler("cancel", universal_cancel))

    # CallbackQuery handler for inline approve/reject
    app.add_handler(CallbackQueryHandler(admin_callback_handler))

    # All text messages routed here
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    print("🤖 Bot is running (input-based).")
    app.run_polling()

if __name__ == "__main__":
    main()
