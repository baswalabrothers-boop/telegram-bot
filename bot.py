import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# 🧠 Replace with your Bot Token
BOT_TOKEN = "YOUR_BOT_TOKEN"

# 💰 Simple in-memory storage (restart clears data)
users = {}
withdraw_requests = []

# 📊 Price list by year
PRICE_LIST = {
    "2016–2022": "11$",
    "2023": "6$",
    "2024 (1–3)": "5$",
    "2024 (4)": "4$",
    "2024 (5–6)": "1$"
}

# 🧰 Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🟢 Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"balance": 0})
    await update.message.reply_text(
        "👋 Welcome to Group Buyer Bot\n\n"
        "💬 You can sell your Telegram groups and withdraw your balance here.\n\n"
        "Commands:\n"
        "/profile - View your profile\n"
        "/price - View price list\n"
        "/sell - Sell your group\n"
        "/withdraw - Withdraw your balance"
    )

# 👤 Profile Command
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id, {"balance": 0})
    await update.message.reply_text(
        f"👤 Profile\n"
        f"🆔 ID: {user_id}\n"
        f"💰 Balance: ₹{user['balance']}"
    )

# 💰 Price Command
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "💵 *Price List (per group)*\n\n"
    for year, price in PRICE_LIST.items():
        msg += f"📅 {year}: {price}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# 📨 Sell Command
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 Please send your group **invite link** here.\n"
        "Our team will check the group year and add balance accordingly."
    )

# 📎 When user sends link
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if "t.me/" in text:
        # You can add verification of group year here later
        users[user_id]["balance"] += 500  # sample credit
        await update.message.reply_text(
            "✅ Group received!\n"
            "💰 Temporary ₹500 added to your balance (demo).\n"
            "Admin will verify and adjust final amount."
        )
    else:
        await update.message.reply_text("❌ Invalid link. Please send a valid Telegram group invite link.")

# 🏧 Withdraw Command
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if users[user_id]["balance"] <= 0:
        await update.message.reply_text("❌ You have no balance to withdraw.")
        return
    await update.message.reply_text(
        "🏦 Please send your payment method (e.g. UPI ID or Wallet Address).\n"
        "After admin approves, amount will be sent."
    )

# 💬 Capture withdraw request
async def handle_withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if "@" in text or "upi" in text or len(text) > 5:
        amount = users[user_id]["balance"]
        withdraw_requests.append({"user_id": user_id, "amount": amount, "method": text})
        users[user_id]["balance"] = 0
        await update.message.reply_text(
            f"✅ Withdraw request submitted for ₹{amount}\n"
            "💬 Admin will pay you soon."
        )
        # 👑 Notify admin
        admin_id = YOUR_TELEGRAM_ID  # <-- Replace with your Telegram ID
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"💸 New withdraw request\n🧑 User ID: {user_id}\n💰 Amount: ₹{amount}\n💳 Method: {text}"
        )

# 👑 Admin view withdrawals
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
        msg += f"🆔 {req['user_id']} - ₹{req['amount']} - {req['method']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# 🤖 Main
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_request))
    app.run_polling()

if __name__ == "__main__":
    main()
