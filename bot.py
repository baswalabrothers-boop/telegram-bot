import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
import os

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

# 💰 Fake balance storage (use database in real bot)
user_balances = {}
pending_withdrawals = {}

# ========================
# 📝 Welcome Message
# ========================
WELCOME_TEXT = (
    "👋 Welcome to the Official Telegram Group Marketplace Bot!\n\n"
    "🛒 Here you can *Sell or Buy Telegram Groups* of different years.\n"
    "💰 We support withdrawals via: *UPI | Binance UID | BEP20 | Polygon USDT*\n\n"
    "📩 Use /price to check price list\n"
    "📤 Use /sell to submit your group for sale\n"
    "💸 Use /withdraw to request payout\n\n"
    "⚡ All withdrawals are processed after admin approval."
)

# ========================
# 💰 Commands
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
    await update.message.reply_text("✅ Your group link has been sent to admin for review.")
    msg = f"🆕 *New Group Submission*\n👤 User: @{user.username or user.first_name}\n🆔 ID: {user.id}\n🔗 Link: {link}"
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
    return ConversationHandler.END

# ========================
# 💸 WITHDRAWAL FLOW
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
    data = query.data
    if not str(query.from_user.id) == str(ADMIN_ID):
        await query.edit_message_text("❌ Only admin can confirm or dismiss withdrawals.")
        return

    action, user_id = data.split(":")
    user_id = int(user_id)
    if user_id not in pending_withdrawals:
        await query.edit_message_text("❌ This request no longer exists.")
        return

    info = pending_withdrawals.pop(user_id)
    if action == "confirm":
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* has been *approved successfully*!",
            parse_mode="Markdown"
        )
        await query.edit_message_text("✅ Withdrawal Confirmed.")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your withdrawal request has been *declined*.",
            parse_mode="Markdown"
        )
        await query.edit_message_text("❌ Withdrawal Dismissed.")

# ========================
# 🪙 ADD BALANCE (ADMIN)
# ========================
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        user_balances[user_id] = user_balances.get(user_id, 0) + amount
        await update.message.reply_text(f"✅ Added ${amount} to user {user_id}.")
    except Exception:
        await update.message.reply_text("❌ Usage: /addbalance <user_id> <amount>")

# ========================
# 🧰 MAIN
# ========================
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Start & Price
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("addbalance", add_balance))

    # Sell
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)]},
        fallbacks=[]
    )
    app.add_handler(sell_conv)

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

    # Admin confirm/dismiss
    app.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^(confirm|dismiss):"))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
