# bot.py
from telegram.ext import Updater, CommandHandler

TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"

def start(update, context):
    update.message.reply_text("✅ Bot is running 24/7!")

updater = Updater(TOKEN)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", start))

updater.start_polling()
updater.idle()
