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
    ReplyKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ========================
# CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"   # Replace with your bot token
ADMIN_ID = 5405985282               # Replace with your Telegram user ID
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
# Utils
# ========================
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/)[A-Za-z0-9_-]+$",
    flags=re.IGNORECASE,
)

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

# ========================
# Conversation states
# ========================
SELL_LINK = 1
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 13)
ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER, ADMIN_BROADCAST, ADMIN_UPDATE_PRICE, ADMIN_UPDATE_PRICE_FINAL = range(20, 27)

# ========================
# Commands
# ========================
COMMANDS_USER = [
    BotCommand("start", "Open bot"),
    BotCommand("price", "Show prices"),
    BotCommand("sell", "Sell group"),
    BotCommand("withdraw", "Request withdrawal"),
    BotCommand("cancel", "Cancel action"),
]

COMMANDS_ADMIN = [
    BotCommand("start", "Open bot"),
    BotCommand("admin", "Admin panel"),
    BotCommand("cancel", "Cancel action"),
]

# ========================
# Keyboards
# ========================
def get_keyboard(is_admin=False):
    if is_admin:
        kb = [
            ["👥 Pending Groups", "💸 Pending Withdrawals"],
            ["➕ Add Balance", "🔍 Inspect User"],
            ["🪙 Toggle Sell On/Off", "📢 Broadcast"],
            ["💰 Update Prices", "📊 Sales Today"]
        ]
    else:
        kb = [
            ["🏠 Start", "💰 Prices"],
            ["🛍 Sell", "💸 Withdraw"],
            ["💵 Balance"]
        ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# START / PRICE / BALANCE
# ========================
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if uid == ADMIN_ID:
        await context.bot.set_my_commands(COMMANDS_ADMIN)
    else:
        await context.bot.set_my_commands(COMMANDS_USER)
    await update.message.reply_text("👋 Welcome to the Group Marketplace Bot!", reply_markup=get_keyboard(uid == ADMIN_ID))

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for k, v in PRICES.items():
        text += f"📅 {k}: {v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("⚠️ Admin has no balance.")
        return
    uid = update.effective_user.id
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"💰 Your balance: ${bal:.2f}")

# ========================
# SELL
# ========================
async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SELL_ENABLED
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("⚠️ Admin cannot sell groups.")
        return ConversationHandler.END
    if not SELL_ENABLED:
        await update.message.reply_text("🚫 Selling is currently disabled by Admin.")
        return ConversationHandler.END
    context.user_data["in_sell"] = True
    await update.message.reply_text("📎 Send your *Telegram group invite link* (https://t.me/+ABC)", parse_mode="Markdown")
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    if not INVITE_RE.match(text):
        await update.message.reply_text("❌ Invalid link. Please send a correct Telegram invite link.")
        return SELL_LINK

    s_uid = str(uid)
    data["pending_groups"][s_uid] = {"link": text, "time": now()}
    data["users"][s_uid]["groups"].append(text)
    save_data(data)

    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}")
        ]
    ]
    await context.bot.send_message(ADMIN_ID, f"🆕 New group submission:\nUser ID: {uid}\nLink: {text}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Submitted to admin for review.")
    return ConversationHandler.END

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

# ========================
# WITHDRAW
# ========================
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("⚠️ Admin cannot withdraw.")
        return ConversationHandler.END
    uid = str(update.effective_user.id)
    ensure_user(uid)
    if data["users"][uid]["balance"] <= 0:
        await update.message.reply_text("❌ Insufficient balance.")
        return ConversationHandler.END
    await update.message.reply_text("💳 Enter payment method name:")
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["method"] = update.message.text.strip()
    await update.message.reply_text("📨 Enter payment address:")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text.strip()
    await update.message.reply_text("💰 Enter withdrawal amount:")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    amount = float(update.message.text.strip())
    if amount > data["users"][uid]["balance"]:
        await update.message.reply_text("❌ Not enough balance.")
        return ConversationHandler.END
    data["pending_withdrawals"][uid] = {
        "method": context.user_data["method"],
        "address": context.user_data["address"],
        "amount": amount,
        "time": now()
    }
    save_data(data)
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}")
        ]
    ]
    await context.bot.send_message(ADMIN_ID, f"💸 New withdrawal request:\nUser ID: {uid}\nAmount: ${amount}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

# ========================
# ADMIN CALLBACKS
# ========================
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data_payload = q.data

    # Group approval
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
            await context.bot.send_message(int(uid_s), f"✅ Your group {info['link']} has been approved.")
            await q.edit_message_text("✅ Group approved.")
        else:
            await context.bot.send_message(int(uid_s), f"❌ Your group {info['link']} was rejected.")
            await q.edit_message_text("❌ Group rejected.")
        save_data(data)
        return

    # Withdraw approval
    if data_payload.startswith("approve_withdraw:") or data_payload.startswith("reject_withdraw:"):
        action, uid_s = data_payload.split(":")
        wd = data["pending_withdrawals"].pop(uid_s, None)
        if not wd:
            await q.edit_message_text("⚠️ Already processed.")
            return
        if action == "approve_withdraw":
            data["users"][uid_s]["balance"] -= wd["amount"]
            await context.bot.send_message(int(uid_s), f"✅ Your withdrawal of ${wd['amount']} has been approved.")
            await q.edit_message_text("✅ Withdrawal approved.")
        else:
            await context.bot.send_message(int(uid_s), f"❌ Your withdrawal was rejected.")
            await q.edit_message_text("❌ Withdrawal rejected.")
        save_data(data)
        return

# ========================
# ADMIN PANEL
# ========================
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("🛠 *Admin Panel*", parse_mode="Markdown", reply_markup=get_keyboard(True))
    return ADMIN_PANEL

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🪙 Toggle Sell On/Off":
        global SELL_ENABLED
        SELL_ENABLED = not SELL_ENABLED
        await update.message.reply_text(f"✅ Sell mode set to: {'ON' if SELL_ENABLED else 'OFF'}")
    elif text == "💰 Update Prices":
        await update.message.reply_text("📌 Send year/category to update (e.g. 2016-22):")
        return ADMIN_UPDATE_PRICE
    elif text == "📊 Sales Today":
        today = datetime.datetime.utcnow().date().isoformat()
        total = sum(u.get("daily_sales", {}).get(today, 0) for u in data["users"].values())
        await update.message.reply_text(f"📊 Total groups sold today: {total}")
    elif text == "➕ Add Balance":
        await update.message.reply_text("🆔 Send user ID:")
        return ADMIN_ADD_USER
    elif text == "🔍 Inspect User":
        await update.message.reply_text("🆔 Send user ID:")
        return ADMIN_INSPECT_USER
    elif text == "📢 Broadcast":
        await update.message.reply_text("📩 Send message to broadcast:")
        return ADMIN_BROADCAST
    return ADMIN_PANEL

async def admin_update_prices_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    if key not in PRICES:
        await update.message.reply_text("❌ Invalid key. Use one from /price list.")
        return ADMIN_UPDATE_PRICE
    context.user_data["price_key"] = key
    await update.message.reply_text(f"✏️ Send new price for {key}:")
    return ADMIN_UPDATE_PRICE_FINAL

async def admin_update_prices_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.pop("price_key")
    PRICES[key] = update.message.text.strip()
    await update.message.reply_text(f"✅ Price for {key} updated to {PRICES[key]}")
    return ADMIN_PANEL

async def admin_add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["target_uid"] = update.message.text.strip()
    await update.message.reply_text("💰 Enter amount to add:")
    return ADMIN_ADD_AMOUNT

async def admin_add_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_uid = context.user_data.pop("target_uid")
    amt = float(update.message.text.strip())
    ensure_user(int(target_uid))
    data["users"][target_uid]["balance"] += amt
    save_data(data)
    await update.message.reply_text(f"✅ Added ${amt} to user {target_uid}")
    return ADMIN_PANEL

async def admin_inspect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text.strip()
    if uid not in data["users"]:
        await update.message.reply_text("❌ User not found.")
        return ADMIN_PANEL
    u = data["users"][uid]
    await update.message.reply_text(
        f"📊 *User Info*\nID: {uid}\nBalance: ${u['balance']}\nSales: {u['sales']}\nGroups: {len(u['groups'])}",
        parse_mode="Markdown"
    )
    return ADMIN_PANEL

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    for uid in data["users"].keys():
        try:
            await context.bot.send_message(int(uid), msg)
        except:
            pass
    await update.message.reply_text("✅ Broadcast sent.")
    return ADMIN_PANEL

# ========================
# MAIN
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))

    # Sell
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)]},
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    app.add_handler(sell_conv)

    # Withdraw
    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", cmd_withdraw_entry)],
        states={
            WITHDRAW_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_choose_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    app.add_handler(withdraw_conv)

    # Admin
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel_entry)],
        states={
            ADMIN_PANEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_callback)],
            ADMIN_UPDATE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_update_prices_amount)],
            ADMIN_UPDATE_PRICE_FINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_update_prices_final)],
            ADMIN_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_handler)],
            ADMIN_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_amount_handler)],
            ADMIN_INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inspect_handler)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_handler)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    app.add_handler(admin_conv)

    # Callbacks
    app.add_handler(CallbackQueryHandler(admin_callback_handler))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
