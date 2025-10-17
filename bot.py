import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# 🧠 Replace with your Bot Token
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
YOUR_TELEGRAM_ID = 5405985282 # <-- Replace with your Telegram ID

# 💰 Simple in-memory storage (restart clears data)
users = {}
withdraw_requests = []

# 📊 Price list by year (USD)
PRICE_LIST = {
    "2016–22": 11,
    "2023": 6,
    "2024 (1–3)": 5,
    "2024 (4)": 4,
    "2024 (5–6)": 1
}

# 🧰 Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🟢 Start Command with professional welcome
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"balance": 0})
    await update.message.reply_text(
        "👋 Welcome to *Professional Group Buyer Bot*!\n\n"
        "💬 We help you sell your Telegram groups and withdraw your earnings securely.\n\n"
        "📌 Important:\n"
        "- Prices are listed in USD.\n"
        "- Withdrawals are accepted via *UPI, Binance ID, BEP20*, or *Polygon USDT*.\n\n"
        "Commands:\n"
        "/profile - View your profile\n"
        "/price - View price list per group\n"
        "/sell - Submit your Telegram group link\n"
        "/withdraw - Request withdrawal of your balance\n\n"
        "Please follow the instructions carefully to avoid delays."
    , parse_mode="Markdown")

# 👤 Profile Command
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id, {"balance": 0})
    await update.message.reply_text(
        f"👤 *Profile*\n"
        f"🆔 ID: {user_id}\n"
        f"💰 Balance: ${user['balance']}"
    , parse_mode="Markdown")

# 💰 Price Command
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "💵 *Price List (per group in USD)*\n\n"
    for year, price in PRICE_LIST.items():
        msg += f"📅 {year}: ${price}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# 📨 Sell Command
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 Please send your Telegram group *invite link* here.\n"
        "Our team will check the group year and credit your balance accordingly."
    , parse_mode="Markdown")

# 🏧 Withdraw Command
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = users.get(user_id, {}).get("balance", 0)
    if balance <= 0:
        await update.message.reply_text("❌ You have no balance to withdraw.")
        return
    await update.message.reply_text(
        "🏦 Please send your withdrawal address in one of the following formats:\n"
        "- UPI ID\n"
        "- Binance ID\n"
        "- BEP20 Wallet Address\n"
        "- Polygon USDT Address\n\n"
        "After admin approval, the requested amount will be sent."
    )

# 👑 Admin Command to view withdraws
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id != YOUR_TELEGRAM_ID:
        await update.message.reply_text("❌ You are not admin.")
        return
    if not withdraw_requests:
        await update.message.reply_text("ℹ️ No withdraw requests pending.")
        return
    msg = "📜 *Pending Withdraw Requests:*\n\n"
    for req in withdraw_requests:
        msg += f"🆔 {req['user_id']} - ${req['amount']} - {req['method']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ✨ Combined message handler
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    users.setdefault(user_id, {"balance": 0})

    # Handle group link
    if "t.me/" in text:
        credit = 5  # demo credit in USD
        users[user_id]["balance"] += credit
        await update.message.reply_text(
            f"✅ Group received!\n💰 Temporary ${credit} added to your balance (demo).\n"
            "Admin will verify and adjust the final amount."
        )
        logger.info(f"User {user_id} submitted a group. Credit ${credit}.")

    # Handle withdraw request
    elif ("@" in text) or ("binance" in text.lower()) or len(text) > 5:
        balance = users[user_id]["balance"]
        if balance <= 0:
            await update.message.reply_text("❌ You have no balance to withdraw.")
            return
        withdraw_requests.append({"user_id": user_id, "amount": balance, "method": text})
        users[user_id]["balance"] = 0
        await update.message.reply_text(
            f"✅ Withdraw request submitted for ${balance}\n💬 Admin will pay you soon."
        )
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=f"💸 New withdraw request\n🧑 User ID: {user_id}\n💰 Amount: ${balance}\n💳 Method: {text}"
        )
        logger.info(f"User {user_id} requested withdraw of ${balance}.")

    # Invalid message
    else:
        await update.message.reply_text(
            "❌ Invalid message. Send a valid Telegram group link or a proper withdrawal address (UPI, Binance ID, BEP20, Polygon USDT)."
        )

# 🤖 Main function
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    app.run_polling()

if __name__ == "__main__":
    main()
