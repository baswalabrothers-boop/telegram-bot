# advanced_marketplace_bot_final.py
import json
import logging
import re
import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========================
# CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282
DATA_PATH = Path("data.json")

PRICES = {
    "2016-22": 11.0,
    "2023": 6.0,
    "2024 (1-3)": 5.0,
    "2024 (4)": 4.0,
    "2024 (5-6)": 1.0,
}

SELL_ENABLED = True

# ========================
# Logging
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# Persistence
# ========================
def load_data():
    if not DATA_PATH.exists():
        return {"users": {}, "pending_groups": {}, "pending_withdrawals": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf8"))

def save_data(data):
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf8")

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

# ========================
# Regex / utils
# ========================
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/)[A-Za-z0-9_-]+$",
    flags=re.IGNORECASE,
)

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

def get_keyboard(is_admin=False):
    if is_admin:
        kb = [
            ["➕ Add Balance", "💰 Update Prices"],
            ["📊 Sales Today", "📢 Broadcast"],
            ["🧑‍💻 Pending Groups"]
        ]
    else:
        kb = [
            ["🏠 Start", "💰 Prices"],
            ["🛍 Sell", "💸 Withdraw"],
            ["💵 Balance"]
        ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# /start & /cancel
# ========================
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    await update.message.reply_text(
        "👋 Welcome to Group Marketplace Bot!",
        reply_markup=get_keyboard(uid == ADMIN_ID)
    )

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operation cancelled.")

# ========================
# /price & /balance
# ========================
async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    # For normal users
    if uid != ADMIN_ID:
        text = "📊 *Current Group Prices*\n\n"
        for k, v in PRICES.items():
            text += f"📅 {k}: ${v}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    # Admin interactive price update
    text_prices = "📊 *Current Group Prices*\n\n"
    for k, v in PRICES.items():
        text_prices += f"📅 {k}: ${v}\n"
    text_prices += "\nType the year to update (e.g., 2023, 2024 (1-3)) or /cancel"
    context.user_data["admin_mode"] = "update_price_year"
    await update.message.reply_text(text_prices, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"💰 Your balance: ${bal:.2f}")

# ========================
# Main Input Box Handler
# ========================
async def main_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    s_uid = str(uid)
    ensure_user(uid)

    # ------------------ Admin Flow ------------------
    if uid == ADMIN_ID:
        mode = context.user_data.get("admin_mode")

        # Buttons flow
        if text == "➕ Add Balance":
            context.user_data["admin_mode"] = "add_balance_user"
            await update.message.reply_text("Send user ID to add balance:")
            return
        if text == "💰 Update Prices":
            context.user_data["admin_mode"] = "update_price_year"
            await update.message.reply_text("Type the year to update (e.g., 2023, 2024 (1-3)):")
            return
        if text == "📊 Sales Today":
            today = datetime.datetime.utcnow().date().isoformat()
            total = sum(u.get("daily_sales", {}).get(today, 0) for u in data["users"].values())
            await update.message.reply_text(f"📈 Total groups sold today: {total}")
            return
        if text == "📢 Broadcast":
            context.user_data["admin_mode"] = "broadcast"
            await update.message.reply_text("Send broadcast message to all users:")
            return
        if text == "🧑‍💻 Pending Groups":
            if not data["pending_groups"]:
                await update.message.reply_text("📭 No pending groups.")
                return
            for puid, info in data["pending_groups"].items():
                kb = [
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{puid}"),
                     InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{puid}")]
                ]
                await update.message.reply_text(f"👤 {puid} ➝ {info['link']}\nSubmitted: {info['time']}",
                                                reply_markup=InlineKeyboardMarkup(kb))
            return

        # Admin input-box modes
        if mode == "add_balance_user":
            try:
                target_uid = int(text)
            except:
                await update.message.reply_text("❌ Invalid user ID.")
                return
            context.user_data["target_uid"] = target_uid
            context.user_data["admin_mode"] = "add_balance_amount"
            await update.message.reply_text(f"Send amount to add to {target_uid}:")
            return
        if mode == "add_balance_amount":
            try:
                amt = float(text)
            except:
                await update.message.reply_text("❌ Invalid amount.")
                return
            target_uid = context.user_data.pop("target_uid")
            ensure_user(target_uid)
            data["users"][str(target_uid)]["balance"] += amt
            save_data(data)
            await update.message.reply_text(f"✅ Added ${amt} to {target_uid}")
            try:
                await update.bot.send_message(target_uid, f"💵 Admin added ${amt} to your balance.")
            except: pass
            context.user_data["admin_mode"] = None
            return
        if mode == "update_price_year":
            if text not in PRICES:
                await update.message.reply_text("❌ Invalid year. Type exact year.")
                return
            context.user_data["price_year"] = text
            context.user_data["admin_mode"] = "update_price_amount"
            await update.message.reply_text(f"Send new price for {text}:")
            return
        if mode == "update_price_amount":
            try:
                amt = float(text)
            except:
                await update.message.reply_text("❌ Invalid price.")
                return
            year = context.user_data.pop("price_year")
            PRICES[year] = amt
            await update.message.reply_text(f"✅ Updated price for {year} to ${amt}")
            context.user_data["admin_mode"] = None
            return
        if mode == "broadcast":
            for u in data["users"]:
                try:
                    await update.bot.send_message(int(u), text)
                except: pass
            await update.message.reply_text("✅ Broadcast sent to all users.")
            context.user_data["admin_mode"] = None
            return

    # ------------------ User Flow ------------------
    # Sell
    if text.lower() in ["🛍 sell", "/sell"] and uid != ADMIN_ID:
        if not SELL_ENABLED:
            await update.message.reply_text("🚫 Selling is disabled by admin.")
            return
        context.user_data["selling"] = True
        await update.message.reply_text("📎 Send your Telegram group invite link:")
        return

    if context.user_data.get("selling"):
        if not INVITE_RE.match(text):
            await update.message.reply_text("❌ Invalid invite link.")
            return
        data["pending_groups"][s_uid] = {"link": text, "time": now()}
        data["users"][s_uid]["groups"].append(text)
        save_data(data)
        context.user_data.pop("selling")
        await update.message.reply_text("✅ Submitted to admin for approval.")
        kb = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}")
        ]]
        await update.bot.send_message(ADMIN_ID, f"🆕 New group submission: {text}", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Withdraw
    if text.lower() in ["💸 withdraw", "/withdraw"] and uid != ADMIN_ID:
        context.user_data["withdrawing"] = True
        context.user_data["withdraw_stage"] = 0
        await update.message.reply_text("Select withdraw method (UPI / Binance / BEP20 / Polygon):")
        return

    if context.user_data.get("withdrawing"):
        stage = context.user_data.get("withdraw_stage", 0)
        if stage == 0:
            method = text.strip().lower()
            context.user_data["withdraw_method"] = method
            context.user_data["withdraw_stage"] = 1
            await update.message.reply_text("Enter your address / UID / UPI ID:")
            return
        if stage == 1:
            context.user_data["withdraw_address"] = text.strip()
            context.user_data["withdraw_stage"] = 2
            await update.message.reply_text("Enter amount to withdraw:")
            return
        if stage == 2:
            try:
                amount = float(text.strip())
            except:
                await update.message.reply_text("❌ Invalid amount.")
                return
            bal = data["users"][s_uid]["balance"]
            if amount > bal:
                await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal:.2f}")
                context.user_data.pop("withdrawing")
                context.user_data.pop("withdraw_stage", None)
                return
            # save pending withdrawal
            data["pending_withdrawals"][s_uid] = {
                "method": context.user_data.pop("withdraw_method"),
                "address": context.user_data.pop("withdraw_address"),
                "amount": amount,
                "time": now()
            }
            data["users"][s_uid]["withdraw_history"].append({
                "method": data["pending_withdrawals"][s_uid]["method"],
                "address": data["pending_withdrawals"][s_uid]["address"],
                "amount": amount,
                "status": "Pending",
                "time": now()
            })
            save_data(data)
            await update.message.reply_text("✅ Withdrawal request sent to admin.")
            kb = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}")
            ]]
            await update.bot.send_message(ADMIN_ID, f"💸 Withdrawal request {amount}$ by {uid}", reply_markup=InlineKeyboardMarkup(kb))
            context.user_data.pop("withdrawing")
            context.user_data.pop("withdraw_stage", None)
            return

# ========================
# CallbackQueryHandler for Approve/Reject
# ========================
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data_payload = q.data

    # Approve/Reject group
    if data_payload.startswith("approve_group:") or data_payload.startswith("reject_group:"):
        action, uid_s = data_payload.split(":")
        if uid_s not in data["pending_groups"]:
            await q.edit_message_text("⚠️ Already processed.")
            return
        info = data["pending_groups"].pop(uid_s)
        user = data["users"][uid_s]
        if action == "approve_group":
            user["sales"] += 1
            today = datetime.datetime.utcnow().date().isoformat()
            user["daily_sales"][today] = user["daily_sales"].get(today, 0) + 1
            await context.bot.send_message(int(uid_s), f"✅ Your group {info['link']} approved.")
            await q.edit_message_text("✅ Group approved.")
        else:
            await context.bot.send_message(int(uid_s), f"❌ Your group {info['link']} rejected.")
            await q.edit_message_text("❌ Group rejected.")
        save_data(data)
        return

    # Approve/Reject withdraw
    if data_payload.startswith("approve_withdraw:") or data_payload.startswith("reject_withdraw:"):
        action, uid_s = data_payload.split(":")
        if uid_s not in data["pending_withdrawals"]:
            await q.edit_message_text("⚠️ Already processed.")
            return
        wd = data["pending_withdrawals"].pop(uid_s)
        hist = data["users"][uid_s]["withdraw_history"]
        for rec in reversed(hist):
            if rec["status"] == "Pending" and rec["amount"] == wd["amount"]:
                rec["status"] = "Approved" if action.startswith("approve") else "Rejected"
                break
        if action.startswith("approve"):
            data["users"][uid_s]["balance"] -= wd["amount"]
            await context.bot.send_message(int(uid_s), f"✅ Withdrawal of ${wd['amount']} approved.")
            await q.edit_message_text("✅ Withdrawal approved.")
        else:
            await context.bot.send_message(int(uid_s), f"❌ Withdrawal of ${wd['amount']} rejected.")
            await q.edit_message_text("❌ Withdrawal rejected.")
        save_data(data)

# ========================
# RUN BOT
# ========================
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("cancel", universal_cancel))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_input_handler))
    app.add_handler(CallbackQueryHandler(admin_callback_handler))

    print("🤖 Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except RuntimeError:
        # if loop already running, use this fallback
        loop = asyncio.get_event_loop()
        loop.create_task(main())
        loop.run_forever()

