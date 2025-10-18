import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_IDS = [5405985282]  # Replace with your Telegram ID

# Conversation states
SELL_LINK, WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT, ADMIN_ACTION = range(5)

# Regex for Telegram invite link
INVITE_REGEX = re.compile(r"(https?://)?(t\.me/joinchat/|t\.me/\+)[\w-]+")

# Prices
PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# Storage
pending_groups = {}        # user_id: link
user_balances = {}         # user_id: balance
withdraw_history = {}      # user_id: list of withdrawals
total_groups_sold = {}     # user_id: count
pending_withdrawals = {}   # user_id: withdrawal data

# ========================
# LOGGING
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# KEYBOARD
# ========================
def main_keyboard(is_admin=False):
    keyboard = [
        ["🏠 Start", "💰 Prices"],
        ["🛍 Sell", "💸 Withdraw"]
    ]
    if is_admin:
        keyboard.append(["🧑‍💻 Admin"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========================
# START
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id in ADMIN_IDS
    await update.message.reply_text(
        "👋 Welcome to the Telegram Group Marketplace Bot!\nUse the buttons below 👇",
        reply_markup=main_keyboard(is_admin)
    )

# ========================
# PRICES
# ========================
async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for year, price in PRICES.items():
        text += f"📅 {year}: {price}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================
# SELL FLOW
# ========================
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📎 Send your *group invite link* to proceed.\n❌ Or type /cancel to stop.\n⏳ You have 10 minutes.",
        parse_mode="Markdown"
    )
    return SELL_LINK

async def handle_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    link = update.message.text.strip()
    if INVITE_REGEX.match(link):
        pending_groups[user.id] = link
        for admin_id in ADMIN_IDS:
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{user.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{user.id}")
            ]])
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📢 *New Group Submission*\n👤 {user.mention_html()} (ID: {user.id})\n🔗 {link}",
                parse_mode="HTML",
                reply_markup=markup
            )
        await update.message.reply_text("✅ Your group link has been submitted for review.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("🚫 Invalid link. Please send a correct link or /cancel.")
        return SELL_LINK

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Process cancelled.")
    return ConversationHandler.END

# ========================
# WITHDRAW FLOW
# ========================
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    history = withdraw_history.get(user.id, [])
    hist_text = "🕓 *Your Withdraw History:*\n" + "\n".join(
        [f"{i+1}. {x['amount']}$ via {x['method']} — {x['status']}" for i, x in enumerate(history)]
    ) if history else "ℹ️ No withdrawal history found."
    await update.message.reply_text(hist_text, parse_mode="Markdown")

    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="polygon")]
    ]
    await update.message.reply_text("💸 Select your withdrawal method:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WITHDRAW_METHOD

async def choose_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["method"] = query.data
    await query.edit_message_text(f"📤 Selected: {query.data.upper()}\nSend your address / UPI / UID:")
    return WITHDRAW_ADDRESS

async def get_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("💰 Enter the amount:")
    return WITHDRAW_AMOUNT

async def get_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = {
        "method": context.user_data["method"],
        "address": context.user_data["address"],
        "amount": update.message.text
    }
    pending_withdrawals[user.id] = data
    for admin_id in ADMIN_IDS:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_wd:{user.id}"),
            InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_wd:{user.id}")
        ]])
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"💸 *New Withdrawal Request*\n👤 {user.mention_html()} (ID: {user.id})\n"
                 f"💳 Method: {data['method']}\n🏦 Address: {data['address']}\n💰 Amount: {data['amount']}",
            parse_mode="HTML",
            reply_markup=markup
        )
    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

# ========================
# ADMIN ACTIONS
# ========================
async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("approve_group:"):
        user_id = int(data.split(":")[1])
        total_groups_sold[user_id] = total_groups_sold.get(user_id, 0) + 1
        await context.bot.send_message(chat_id=user_id, text="✅ Your group is approved!")
        await query.edit_message_text("✅ Group approved.")
    elif data.startswith("reject_group:"):
        user_id = int(data.split(":")[1])
        await context.bot.send_message(chat_id=user_id, text="❌ Your group is rejected!")
        await query.edit_message_text("❌ Group rejected.")
    elif data.startswith("confirm_wd:"):
        user_id = int(data.split(":")[1])
        wd = pending_withdrawals.pop(user_id, None)
        if wd:
            withdraw_history.setdefault(user_id, []).append({**wd, "status": "Approved ✅"})
            await context.bot.send_message(chat_id=user_id, text=f"✅ Withdrawal of ${wd['amount']} approved!")
            await query.edit_message_text("✅ Withdrawal confirmed.")
    elif data.startswith("dismiss_wd:"):
        user_id = int(data.split(":")[1])
        wd = pending_withdrawals.pop(user_id, None)
        if wd:
            withdraw_history.setdefault(user_id, []).append({**wd, "status": "Rejected ❌"})
            await context.bot.send_message(chat_id=user_id, text=f"❌ Withdrawal of ${wd['amount']} rejected!")
            await query.edit_message_text("❌ Withdrawal dismissed.")

# ========================
# ADMIN PANEL
# ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Unauthorized.")
        return
    buttons = [
        [InlineKeyboardButton("➕ Add Balance", callback_data="add_balance")],
        [InlineKeyboardButton("🔍 Inspect User", callback_data="inspect_user")]
    ]
    await update.message.reply_text("👑 Admin Panel", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_panel_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "add_balance":
        await query.edit_message_text("✍️ Send: user_id amount\nExample: 123456 50")
        context.user_data["admin_action"] = "add_balance"
    elif query.data == "inspect_user":
        await query.edit_message_text("🔍 Send: user_id")
        context.user_data["admin_action"] = "inspect_user"

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    action = context.user_data.get("admin_action")
    if action == "add_balance":
        try:
            uid, amount = update.message.text.split()
            uid = int(uid)
            amount = float(amount)
            user_balances[uid] = user_balances.get(uid, 0) + amount
            await context.bot.send_message(chat_id=uid, text=f"💰 Admin added ${amount} to your balance.")
            await update.message.reply_text(f"✅ Added ${amount} to user {uid}.")
        except:
            await update.message.reply_text("❌ Invalid format.")
    elif action == "inspect_user":
        try:
            uid = int(update.message.text)
            bal = user_balances.get(uid, 0)
            sold = total_groups_sold.get(uid, 0)
            wd = withdraw_history.get(uid, [])
            await update.message.reply_text(
                f"📊 User ID: {uid}\n💰 Balance: ${bal}\n🪙 Groups Sold: {sold}\n📝 Withdrawals: {len(wd)}"
            )
        except:
            await update.message.reply_text("❌ Invalid user ID.")

# ========================
# MAIN
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Sell Conversation
    sell_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛍 Sell$"), sell)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_link)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=600
    )

    # Withdraw Conversation
    withdraw_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(choose_withdraw_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_withdraw_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_withdraw_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(sell_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(handle_admin_actions, pattern="^(approve_group|reject_group|confirm_wd|dismiss_wd):"))
    app.add_handler(MessageHandler(filters.Regex("^🧑‍💻 Admin$"), admin_panel))
    app.add_handler(CallbackQueryHandler(handle_admin_panel_buttons, pattern="^(add_balance|inspect_user)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))
    app.add_handler(MessageHandler(filters.Regex("^🏠 Start$"), start))
    app.add_handler(MessageHandler(filters.Regex("^💰 Prices$"), prices))

    app.run_polling()

if __name__ == "__main__":
    main()
