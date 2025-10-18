# marketplace_bot_final.py
import json
import logging
import re
import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, CommandHandler, ContextTypes, filters

# ========================
# CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282
DATA_PATH = Path("data.json")
SELL_ENABLED = True

PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$",
}

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
        data["users"][s] = {"balance": 0.0, "groups": [], "sales": 0, "daily_sales": {}, "withdraw_history": [], "state": None}
        save_data(data)

# ========================
# Utils
# ========================
INVITE_RE = re.compile(r"^(https?://)?(t\.me/joinchat/|t\.me/\+|t\.me/)[A-Za-z0-9_-]+$", flags=re.IGNORECASE)
def now(): return datetime.datetime.utcnow().isoformat() + "Z"

def get_keyboard(is_admin=False):
    if is_admin:
        kb = [["💰 Update Prices", "📊 Sales Today"],
              ["➕ Add Balance", "🔍 Inspect User"],
              ["🪙 Toggle Sell On/Off", "📢 Broadcast"]]
    else:
        kb = [["🛍 Sell", "💸 Withdraw"], ["💵 Balance"]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# Universal cancel
# ========================
async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    ensure_user(uid)
    data["users"][uid]["state"] = None
    context.user_data.clear()
    await update.message.reply_text("❌ Operation cancelled.", reply_markup=get_keyboard(uid == ADMIN_ID))

# ========================
# Message router
# ========================
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    text = (update.message.text or "").strip()

    # Admin input
    if uid == ADMIN_ID:
        await handle_admin_input(update, context, text)
        return

    # User input
    await handle_user_input(update, context, text)

# ========================
# User input handler
# ========================
async def handle_user_input(update, context, text):
    uid = str(update.effective_user.id)
    user = data["users"][uid]

    # SELL FLOW
    if user["state"] == "selling":
        if not INVITE_RE.match(text):
            await update.message.reply_text("❌ Invalid invite link. Send correct link or /cancel.")
            return
        # Prevent spam
        if uid in data["pending_groups"]:
            await update.message.reply_text("⚠️ You already have a pending group. Wait for admin approval or /cancel.")
            return
        # Save pending group
        data["pending_groups"][uid] = {"link": text, "time": now()}
        user["groups"].append(text)
        user["state"] = None
        save_data(data)
        # Notify admin
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}")]]
        await context.bot.send_message(ADMIN_ID, f"🆕 New group submission from {uid}:\n{text}", reply_markup=InlineKeyboardMarkup(kb))
        await update.message.reply_text("✅ Submitted to admin for review.", reply_markup=get_keyboard(False))
        return

    # WITHDRAW FLOW
    if user["state"] == "withdrawing_method":
        user["withdraw_method"] = text
        user["state"] = "withdrawing_address"
        await update.message.reply_text("📨 Enter payment address:")
        return
    if user["state"] == "withdrawing_address":
        user["withdraw_address"] = text
        user["state"] = "withdrawing_amount"
        await update.message.reply_text("💰 Enter amount to withdraw:")
        return
    if user["state"] == "withdrawing_amount":
        try:
            amt = float(text)
        except:
            await update.message.reply_text("❌ Invalid amount. Send numeric value.")
            return
        if amt > user["balance"]:
            await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: {user['balance']}")
            user["state"] = None
            return
        # Save pending withdrawal
        data["pending_withdrawals"][uid] = {"method": user["withdraw_method"], "address": user["withdraw_address"], "amount": amt, "time": now()}
        user["withdraw_history"].append({"method": user["withdraw_method"], "address": user["withdraw_address"], "amount": amt, "status": "Pending", "time": now()})
        user["state"] = None
        save_data(data)
        # Notify admin
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}")]]
        await context.bot.send_message(ADMIN_ID, f"💸 Withdrawal request {uid}: {amt}$ via {user['withdraw_method']}", reply_markup=InlineKeyboardMarkup(kb))
        await update.message.reply_text("✅ Withdrawal request sent to admin.", reply_markup=get_keyboard(False))
        return

    # Normal commands from user input box
    if text == "🛍 Sell":
        global SELL_ENABLED
        if not SELL_ENABLED:
            await update.message.reply_text("🚫 Selling is disabled by admin.")
            return
        user["state"] = "selling"
        await update.message.reply_text("📎 Send your Telegram group invite link:")
        return
    if text == "💸 Withdraw":
        if user["balance"] <= 0:
            await update.message.reply_text("❌ Insufficient balance.")
            return
        user["state"] = "withdrawing_method"
        await update.message.reply_text("💳 Enter payment method name:")
        return
    if text == "💵 Balance":
        await update.message.reply_text(f"💰 Your balance: ${user['balance']:.2f}")
        return

# ========================
# Admin input handler
# ========================
async def handle_admin_input(update, context, text):
    uid = str(update.effective_user.id)
    user = data["users"][uid]

    # Admin state check
    state = user.get("state")

    if state == "update_price_key":
        if text not in PRICES:
            await update.message.reply_text("❌ Invalid key. Use one from price list.")
            return
        user["price_key"] = text
        user["state"] = "update_price_value"
        await update.message.reply_text(f"✏️ Send new price for {text}:")
        return
    if state == "update_price_value":
        key = user.pop("price_key")
        PRICES[key] = text
        user["state"] = None
        await update.message.reply_text(f"✅ Price for {key} updated to {PRICES[key]}")
        return
    if state == "add_balance_uid":
        try:
            user["target_uid"] = text
            user["state"] = "add_balance_amount"
            await update.message.reply_text("💰 Send amount to add:")
        except:
            await update.message.reply_text("❌ Invalid user ID.")
        return
    if state == "add_balance_amount":
        try:
            amt = float(text)
            target_uid = user.pop("target_uid")
            ensure_user(int(target_uid))
            data["users"][target_uid]["balance"] += amt
            save_data(data)
            user["state"] = None
            await update.message.reply_text(f"✅ Added ${amt} to {target_uid}")
        except:
            await update.message.reply_text("❌ Invalid amount.")
        return
    if state == "inspect_user":
        if text not in data["users"]:
            await update.message.reply_text("❌ User not found.")
        else:
            u = data["users"][text]
            await update.message.reply_text(f"📊 User {text}: Balance: {u['balance']}, Sales: {u['sales']}, Groups: {len(u['groups'])}")
        user["state"] = None
        return
    if state == "broadcast":
        for uid_send in data["users"].keys():
            try:
                await context.bot.send_message(int(uid_send), text)
            except:
                continue
        await update.message.reply_text("✅ Broadcast sent.")
        user["state"] = None
        return

    # Admin menu selections
    if text == "💰 Update Prices":
        user["state"] = "update_price_key"
        await update.message.reply_text("📌 Send year/category to update (e.g. 2016-22):")
        return
    if text == "📊 Sales Today":
        today = datetime.datetime.utcnow().date().isoformat()
        total = sum(u.get("daily_sales", {}).get(today, 0) for u in data["users"].values())
        await update.message.reply_text(f"📊 Total groups sold today: {total}")
        return
    if text == "➕ Add Balance":
        user["state"] = "add_balance_uid"
        await update.message.reply_text("🆔 Send user ID to add balance:")
        return
    if text == "🔍 Inspect User":
        user["state"] = "inspect_user"
        await update.message.reply_text("🆔 Send user ID to inspect:")
        return
    if text == "📢 Broadcast":
        user["state"] = "broadcast"
        await update.message.reply_text("📩 Send message to broadcast:")
        return
    if text == "🪙 Toggle Sell On/Off":
        global SELL_ENABLED
        SELL_ENABLED = not SELL_ENABLED
        await update.message.reply_text(f"✅ Sell mode set to {'ON' if SELL_ENABLED else 'OFF'}")
        return

# ========================
# Admin callback (approve/reject)
# ========================
async def admin_callback_handler(update, context):
    q = update.callback_query
    await q.answer()
    action, uid_s = q.data.split(":")
    if action in ["approve_group", "reject_group"]:
        info = data["pending_groups"].pop(uid_s, None)
        if not info:
            await q.edit_message_text("⚠️ Already processed.")
            return
        u = data["users"][uid_s]
        if action == "approve_group":
            u["sales"] += 1
            today = datetime.datetime.utcnow().date().isoformat()
            u["daily_sales"][today] = u["daily_sales"].get(today, 0) + 1
            await context.bot.send_message(int(uid_s), f"✅ Your group {info['link']} has been approved.")
            await q.edit_message_text("✅ Group approved.")
        else:
            await context.bot.send_message(int(uid_s), f"❌ Your group {info['link']} was rejected.")
            await q.edit_message_text("❌ Group rejected.")
        save_data(data)
    elif action in ["approve_withdraw", "reject_withdraw"]:
        wd = data["pending_withdrawals"].pop(uid_s, None)
        if not wd:
            await q.edit_message_text("⚠️ Already processed.")
            return
        u = data["users"][uid_s]
        if action == "approve_withdraw":
            u["balance"] -= wd["amount"]
            await context.bot.send_message(int(uid_s), f"✅ Your withdrawal of ${wd['amount']} has been approved.")
            await q.edit_message_text("✅ Withdrawal approved.")
        else:
            await context.bot.send_message(int(uid_s), f"❌ Your withdrawal was rejected.")
            await q.edit_message_text("❌ Withdrawal rejected.")
        save_data(data)

# ========================
# Bot main
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("cancel", universal_cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    app.add_handler(CallbackQueryHandler(admin_callback_handler))
    print("🤖 Marketplace bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
