import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# 🧠 Basic Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"  # 🪙 Replace with your bot token
ADMIN_ID = 5405985282 # 👑 Replace with your Telegram user ID

# 🧾 Dummy price list (you can change these values)
PRICE_LIST = {
    "0-1 year": 50,
    "1-2 years": 100,
    "2+ years": 200
}

# 🧑 User data storage (temporary in memory)
USER_DATA = {}

# States for ConversationHandler
SELL = range(1)

# 🏁 /start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {"balance": 0, "groups": []}

    keyboard = [
        [InlineKeyboardButton("💵 Price", callback_data="price")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("🪙 Sell Group", callback_data="sell")],
        [InlineKeyboardButton("🏧 Withdraw", callback_data="withdraw")]
    ]
    await update.message.reply_text(
        "👋 Welcome to *Group Seller Bot*\n\nSell your Telegram groups and get paid fast 💰",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 💵 /price Command
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💰 *Group Price List:*\n\n"
    for k, v in PRICE_LIST.items():
        text += f"• {k}: ₹{v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# 👤 /profile Command
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = USER_DATA.get(user_id, {"balance": 0, "groups": []})
    groups = "\n".join(data["groups"]) if data["groups"] else "No groups sold yet"
    text = f"👤 *Your Profile*\n\n💰 Balance: ₹{data['balance']}\n📜 Groups sold:\n{groups}"
    await update.message.reply_text(text, parse_mode="Markdown")

# 🪙 /sell Command
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📩 Send me your *group invite link* to sell.")
    return SELL

# Receive group link & calculate price
async def receive_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text.strip()
    # 📌 For now, fixed price
    price = PRICE_LIST["0-1 year"]
    USER_DATA[user_id]["balance"] += price
    USER_DATA[user_id]["groups"].append(link)

    await update.message.reply_text(
        f"✅ Your group has been submitted.\n💰 You earned ₹{price}.\n🏦 Balance updated."
    )

    # 👑 Notify admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📢 New group submitted by {update.effective_user.username or user_id}\n🔗 {link}\n💰 ₹{price}"
    )
    return ConversationHandler.END

# 🏧 /withdraw Command
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    balance = USER_DATA.get(user_id, {"balance": 0})["balance"]

    if balance <= 0:
        await update.message.reply_text("🚫 You have no balance to withdraw.")
        return

    await update.message.reply_text("💸 Your withdrawal request has been sent to the admin.")

    # 👑 Notify admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💰 Withdrawal Request from @{user.username or user_id}\nAmount: ₹{balance}"
    )
    # Balance will be manually cleared after payment
    USER_DATA[user_id]["balance"] = 0

# 📌 Main Function
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    sell_handler = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={SELL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group)]},
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(sell_handler)
    app.add_handler(CommandHandler("withdraw", withdraw))

    app.run_polling()

if __name__ == "__main__":
    main()
