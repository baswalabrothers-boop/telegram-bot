import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# ========================
# CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282  # Replace with your numeric ID

# In-memory storage (use DB for production)
user_balances = {}
pending_groups = {}  # key: user_id, value: group_link
pending_withdrawals = {}  # key: user_id, value: dict with method, address, amount

# Logging
logging.basicConfig(level=logging.INFO)

# ========================
# STATES
# ========================
SELL_GROUP = 1
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(3)
ADMIN_ACTION, ADMIN_USER_ID, ADMIN_AMOUNT = range(3, 6)

# ========================
# BASIC COMMANDS
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Welcome to the Group Marketplace Bot!\n\n"
        "📌 Commands:\n"
        "/price - Show prices\n"
        "/sell - Sell your group\n"
        "/withdraw - Withdraw balance\n"
        "/balance - Check your balance\n"
        "/admin - Admin panel (Admins only)"
    )
    await update.message.reply_text(text)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📊 *Group Prices*\n"
        "• 2016–22 → $11\n"
        "• 2023 → $6\n"
        "• 2024 (1–3) → $5\n"
        "• 2024 (4) → $4\n"
        "• 2024 (5–6) → $1"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = user_balances.get(user_id, 0)
    await update.message.reply_text(f"💰 Your balance: ${bal}")

# ========================
# SELL FLOW
# ========================
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Please send your *group link* for review.")
    return SELL_GROUP

async def receive_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    link = update.message.text
    pending_groups[user.id] = link

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 *New Group Submission*\n👤 User: @{user.username or user.first_name}\n"
             f"🆔 {user.id}\n🔗 {link}",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ Your group has been sent for admin review.")
    return ConversationHandler.END

async def handle_group_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    admin_id = query.from_user.id

    if admin_id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can approve or reject groups.")
        return

    action, user_id = data.split("_")
    user_id = int(user_id)

    if user_id not in pending_groups:
        await query.edit_message_text("❌ This submission no longer exists.")
        return

    link = pending_groups.pop(user_id)

    if action == "approve":
        await context.bot.send_message(user_id, f"✅ Your group ({link}) has been *approved* by admin!")
        await query.edit_message_text(f"✅ Group approved. User {user_id} notified.")
    else:
        await context.bot.send_message(user_id, f"❌ Your group ({link}) has been *rejected* by admin.")
        await query.edit_message_text(f"❌ Group rejected. User {user_id} notified.")

# ========================
# WITHDRAW FLOW
# ========================
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="polygon")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💸 Select your withdrawal method:", reply_markup=reply_markup)
    return WITHDRAW_METHOD

async def choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['method'] = query.data
    await query.edit_message_text("📤 Enter your address / UPI / UID:")
    return WITHDRAW_ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("💰 Enter the amount you want to withdraw:")
    return WITHDRAW_AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    method = context.user_data['method']
    address = context.user_data['address']
    amount = update.message.text

    pending_withdrawals[user.id] = {"method": method, "address": address, "amount": amount}

    keyboard = [[
        InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{user.id}"),
        InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_{user.id}")
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💸 *New Withdrawal Request*\n👤 @{user.username or user.first_name}\n"
             f"🆔 {user.id}\n💳 {method}\n🏦 {address}\n💰 {amount}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

async def handle_withdraw_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can approve or dismiss withdrawals.")
        return

    action, user_id = data.split("_")
    user_id = int(user_id)
    if user_id not in pending_withdrawals:
        await query.edit_message_text("❌ This request no longer exists.")
        return

    info = pending_withdrawals.pop(user_id)
    if action == "confirm":
        await context.bot.send_message(user_id, f"✅ Your withdrawal of ${info['amount']} via {info['method']} has been approved.")
        await query.edit_message_text("✅ Withdrawal Confirmed.")
    else:
        await context.bot.send_message(user_id, "❌ Your withdrawal request has been rejected.")
        await query.edit_message_text("❌ Withdrawal Dismissed.")

# ========================
# ADMIN COMMANDS
# ========================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add Balance", callback_data="add_balance")],
        [InlineKeyboardButton("➖ Deduct Balance", callback_data="deduct_balance")],
        [InlineKeyboardButton("📋 Pending Withdrawals", callback_data="view_pending")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👑 Admin Panel", reply_markup=markup)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    context.user_data['admin_action'] = action

    if action in ["add_balance", "deduct_balance"]:
        await query.edit_message_text("Enter *User ID*:")
        return ADMIN_USER_ID
    elif action == "view_pending":
        if not pending_withdrawals:
            await query.edit_message_text("📭 No pending withdrawals.")
            return ConversationHandler.END
        text = "📋 *Pending Withdrawals:*\n"
        for uid, info in pending_withdrawals.items():
            text += f"👤 {uid} | ${info['amount']} via {info['method']}\n"
        await query.edit_message_text(text, parse_mode="Markdown")
        return ConversationHandler.END

async def admin_get_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['target_user'] = int(update.message.text)
        await update.message.reply_text("Enter amount:")
        return ADMIN_AMOUNT
    except ValueError:
        await update.message.reply_text("⚠️ Invalid User ID. Enter numeric ID.")
        return ADMIN_USER_ID

async def admin_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        user_id = context.user_data['target_user']
        action = context.user_data['admin_action']

        if action == "add_balance":
            user_balances[user_id] = user_balances.get(user_id, 0) + amount
            await update.message.reply_text(f"✅ Added ${amount} to user {user_id}.")
        else:
            user_balances[user_id] = max(user_balances.get(user_id, 0) - amount, 0)
            await update.message.reply_text(f"✅ Deducted ${amount} from user {user_id}.")
        await context.bot.send_message(user_id, f"💰 Your balance has been updated! Current balance: ${user_balances.get(user_id,0)}")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("⚠️ Invalid amount. Enter a number.")
        return ADMIN_AMOUNT

# ========================
# MAIN
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("admin", admin))

    # Sell flow
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={SELL_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)]},
        fallbacks=[]
    )
    app.add_handler(sell_conv)

    # Withdraw flow
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

    # Callback handlers
    app.add_handler(CallbackQueryHandler(handle_group_approval, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(handle_withdraw_approval, pattern="^(confirm|dismiss)_"))
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback)],
        states={
            ADMIN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_user)],
            ADMIN_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_amount)]
        },
        fallbacks=[]
    )
    app.add_handler(admin_conv)

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
