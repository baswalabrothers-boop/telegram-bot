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

# In-memory storage
user_balances = {}
pending_groups = {}  # key: user_id, value: group_link

# Logging
logging.basicConfig(level=logging.INFO)

# ========================
# SELL FLOW
# ========================
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Please send your *group link* for review.")
    return 1

async def receive_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    link = update.message.text
    user_id = user.id
    pending_groups[user_id] = link

    # Send message to admin with Approve / Reject buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 *New Group Submission*\n👤 User: @{user.username or user.first_name}\n"
             f"🆔 {user_id}\n🔗 {link}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ Your group has been sent for admin review.")
    return ConversationHandler.END

# ========================
# APPROVE / REJECT HANDLER
# ========================
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
    else:  # reject
        await context.bot.send_message(user_id, f"❌ Your group ({link}) has been *rejected* by admin.")
        await query.edit_message_text(f"❌ Group rejected. User {user_id} notified.")

# ========================
# ADD BALANCE
# ========================
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        user_balances[user_id] = user_balances.get(user_id, 0) + amount
        await update.message.reply_text(f"✅ Added ${amount} to user {user_id}.")
        await context.bot.send_message(user_id, f"💰 Your balance has been updated! +${amount}")
    except Exception:
        await update.message.reply_text("❌ Usage: /addbalance <user_id> <amount>")

# ========================
# BALANCE CHECK
# ========================
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = user_balances.get(user_id, 0)
    await update.message.reply_text(f"💰 Your balance: ${bal}")

# ========================
# MAIN
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Sell conversation
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)]},
        fallbacks=[]
    )
    app.add_handler(sell_conv)

    # Balance & Addbalance
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("addbalance", add_balance))

    # Approve / Reject callback
    app.add_handler(CallbackQueryHandler(handle_group_approval, pattern="^(approve|reject)_"))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

