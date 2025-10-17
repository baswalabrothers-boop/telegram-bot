import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# 🧠 Replace with your Bot Token
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
YOUR_TELEGRAM_ID = 5405985282  # <-- Replace with your Telegram ID

# 💰 In-memory storage
users = {}  # {user_id: {"balance": amount}}
withdraw_requests = []  # list of {"user_id":, "amount":, "method":}

# 📊 Price list (for reference)
PRICE_LIST = {
    "2016–22": 11,
    "2023": 6,
    "2024 (1–3)": 5,
    "2024 (4)": 4,
    "2024 (5–6)": 1
}

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- COMMANDS ----------------

# /start - Welcome message
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"balance": 0})
    await update.message.reply_text(
        "👋 Welcome to *Professional Group Buyer Bot*!\n\n"
        "💬 Sell your Telegram groups and withdraw your earnings securely.\n\n"
        "📌 Important:\n"
        "- Prices are in USD.\n"
        "- Withdrawals accepted via *UPI, Binance ID, BEP20*, or *Polygon USDT*.\n\n"
        "Commands:\n"
        "/profile - View your profile\n"
        "/price - View price list\n"
        "/sell - Submit your Telegram group link\n"
        "/withdraw - Request withdrawal of your balance\n\n"
        "Please follow the instructions carefully to avoid delays."
        , parse_mode="Markdown"
    )

# /profile - View balance
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = users.get(user_id, {}).get("balance", 0)
    await update.message.reply_text(
        f"👤 Profile\n🆔 ID: {user_id}\n💰 Balance: ${balance}"
    )

# /price - Show price list
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "💵 *Price List (per group in USD)*\n\n"
    for year, price in PRICE_LIST.items():
        msg += f"📅 {year}: ${price}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# /sell - Instructions to send group link
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 Please send your Telegram group *invite link* here.\n"
        "Admin will verify the group and credit the balance manually."
        , parse_mode="Markdown"
    )

# /withdraw - Request withdrawal
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = users.get(user_id, {}).get("balance", 0)
    if balance <= 0:
        await update.message.reply_text("❌ You have no balance to withdraw.")
        return
    await update.message.reply_text(
        "🏦 Send your withdrawal address (one of the following):\n"
        "- UPI ID\n"
        "- Binance ID\n"
        "- BEP20 Wallet\n"
        "- Polygon USDT\n"
        "Admin will process it after approval."
    )

# /admin - View pending withdraw requests
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

# /addbalance - Admin manually adds balance
async def addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id != YOUR_TELEGRAM_ID:
        await update.message.reply_text("❌ You are not admin.")
        return
    try:
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
            return
        user_id = int(args[0])
        amount = float(args[1])
        users.setdefault(user_id, {"balance": 0})
        users[user_id]["balance"] += amount
        await update.message.reply_text(f"✅ Added ${amount} to user {user_id}'s balance.")
        # Optionally notify the user
        await context.bot.send_message(chat_id=user_id, text=f"💰 Your balance has been updated by ${amount} by admin.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ---------------- MESSAGE HANDLER ----------------
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    users.setdefault(user_id, {"balance": 0})

    # Group link submission
    if "t.me/" in text:
        if user_id == YOUR_TELEGRAM_ID:
            await update.message.reply_text("❌ Admin cannot submit group links.")
            return
        # Forward group link to admin
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=f"📩 New group link submitted by user {user_id}:\n{text}"
        )
        await update.message.reply_text(
            "✅ Your group link has been submitted to admin.\n"
            "Admin will verify and credit your balance manually."
        )

    # Withdraw request
    elif ("@" in text) or ("binance" in text.lower()) or len(text) > 5:
        balance = users[user_id]["balance"]
        if balance <= 0:
            await update.message.reply_text("❌ You have no balance to withdraw.")
            return
        withdraw_requests.append({"user_id": user_id, "amount": balance, "method": text})
        await update.message.reply_text(
            f"✅ Withdraw request submitted for ${balance}\n💬 Admin will process it soon."
        )
        # Notify admin
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=f"💸 Withdraw request from user {user_id}:\nAmount: ${balance}\nMethod: {text}"
        )

    # Invalid message
    else:
        await update.message.reply_text(
            "❌ Invalid message. Send a valid Telegram group link or a proper withdrawal address (UPI, Binance, BEP20, Polygon USDT)."
        )

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("addbalance", addbalance))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    # Run
    app.run_polling()

if __name__ == "__main__":
    main()
