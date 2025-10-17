import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)

# ========================
# 🔐 CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282

# 🪙 Prices
PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# 🧾 Data Storage
user_balances = {}
pending_withdrawals = {}
pending_groups = {}

# ========================
# 📝 Welcome Text
# ========================
WELCOME_TEXT = (
    "👋 Welcome to the Official Telegram Group Marketplace Bot!\n\n"
    "🛒 *Buy & Sell Telegram Groups*\n"
    "💰 Withdrawals via: *UPI | Binance UID | BEP20 | Polygon*\n\n"
    "📩 Use /price to check price list\n"
    "📤 Use /sell to submit your group for review\n"
    "💸 Use /withdraw to request payout\n"
    "💼 Use /balance to check your balance\n\n"
    "⚡ All actions are processed after admin approval."
)

# ========================
# 📊 /start & /price
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for year, amount in PRICES.items():
        text += f"📅 {year}: {amount}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================
# 🏷 SELL GROUP
# ========================
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Please send your *group link* to submit for review.")
    return 1

async def receive_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text
    user = update.message.from_user
    pending_groups[user.id] = {"link": link, "username": user.username, "name": user.first_name}

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{user.id}")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("✅ Your group link has been sent to admin for review.")
    msg = (
        f"🆕 *New Group Submission*\n"
        f"👤 User: @{user.username or user.first_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Link: {link}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

async def handle_group_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can review submissions.")
        return

    action, user_id = query.data.split(":")
    user_id = int(user_id)

    if user_id not in pending_groups:
        await query.edit_message_text("❌ This submission no longer exists.")
        return

    info = pending_groups.pop(user_id)

    if action == "approve_group":
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Your group has been *approved*! We will process your balance soon.",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"✅ Approved group from @{info['username']}")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your group has been *rejected* by the admin.",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"❌ Rejected group from @{info['username']}")

# ========================
# 💰 BALANCE
# ========================
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = user_balances.get(uid, 0)
    await update.message.reply_text(f"💰 Your current balance: *${bal}*", parse_mode="Markdown")

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        user_balances[user_id] = user_balances.get(user_id, 0) + amount
        await update.message.reply_text(f"✅ Added ${amount} to user {user_id}.")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💵 Your balance has been updated: *+${amount}* ✅",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("❌ Usage: /addbalance <user_id> <amount>")

# ========================
# 💸 WITHDRAW
# ========================
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(3)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="polygon")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💸 Select your *withdrawal method*:", reply_markup=reply_markup, parse_mode="Markdown")
    return WITHDRAW_METHOD

async def choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data
    context.user_data["method"] = method
    await query.edit_message_text(f"📤 Selected method: *{method.upper()}*\n\nPlease enter your address / UPI ID / UID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("💰 Enter the *amount* you want to withdraw:")
    return WITHDRAW_AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = update.message.text
    user = update.message.from_user
    method = context.user_data["method"]
    address = context.user_data["address"]

    pending_withdrawals[user.id] = {"method": method, "address": address, "amount": amount}

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm:{user.id}"),
            InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss:{user.id}")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💸 *New Withdrawal Request*\n👤 User: @{user.username or user.first_name}\n🆔 ID: {user.id}\n"
             f"💳 Method: {method}\n🏦 Address: {address}\n💰 Amount: {amount}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ Your withdrawal request has been sent to admin.")
    return ConversationHandler.END

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if str(query.from_user.id) != str(ADMIN_ID):
        await query.edit_message_text("❌ Only admin can confirm or dismiss withdrawals.")
        return

    action, user_id = query.data.split(":")
    user_id = int(user_id)
    if user_id not in pending_withdrawals:
        await query.edit_message_text("❌ This request no longer exists.")
        return

    info = pending_withdrawals.pop(user_id)
    if action == "confirm":
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* has been *approved*!",
            parse_mode="Markdown"
        )
        await query.edit_message_text("✅ Withdrawal Confirmed.")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your withdrawal request has been *rejected*.",
            parse_mode="Markdown"
        )
        await query.edit_message_text("❌ Withdrawal Dismissed.")

# ========================
# 🧰 ADMIN PANEL
# ========================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    keyboard = [
        [InlineKeyboardButton("📋 Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_pending_withdrawals")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛠 *Admin Panel*\nChoose an option:", reply_markup=reply_markup, parse_mode="Markdown")

async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can access this.")
        return

    if query.data == "admin_pending_groups":
        if not pending_groups:
            await query.edit_message_text("📋 No pending group submissions.")
            return
        text = "📋 *Pending Groups:*\n\n"
        for uid, info in pending_groups.items():
            text += f"👤 @{info['username']} ({uid})\n🔗 {info['link']}\n\n"
        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "admin_pending_withdrawals":
        if not pending_withdrawals:
            await query.edit_message_text("💸 No pending withdrawals.")
            return
        text = "💸 *Pending Withdrawals:*\n\n"
        for uid, info in pending_withdrawals.items():
            text += (
                f"👤 ID: {uid}\n"
                f"💳 {info['method'].upper()} | {info['address']}\n"
                f"💰 ${info['amount']}\n\n"
            )
        await query.edit_message_text(text, parse_mode="Markdown")

# ========================
# 🛠️ SET COMMANDS
# ========================
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("price", "Check group prices"),
        BotCommand("sell", "Sell your group"),
        BotCommand("withdraw", "Withdraw funds"),
        BotCommand("balance", "Check your balance"),
        BotCommand("admin", "Admin panel")
    ])

# ========================
# 🧰 MAIN
# ========================
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.post_init = set_commands

    # User Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("addbalance", add_balance))
    app.add_handler(CommandHandler("admin", admin))

    # Sell
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)]},
        fallbacks=[]
    )
    app.add_handler(sell_conv)
    app.add_handler(CallbackQueryHandler(handle_group_review, pattern="^(approve_group|reject_group):"))

    # Withdraw
    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(choose_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
        },
        fallbacks=[]
    )
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^(confirm|dismiss):"))

    # Admin Panel
    app.add_handler(CallbackQueryHandler(handle_admin_panel, pattern="^admin_"))

    print("🤖 Bot is running with full admin panel...")
    app.run_polling()

if __name__ == "__main__":
    main()
