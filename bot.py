 import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
import asyncio

# ========================
# CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282

# Prices (editable via admin)
PRICES = {
    "2016-22": 11,
    "2023": 6,
    "2024 (1-3)": 5,
    "2024 (4)": 4,
    "2024 (5-6)": 1
}

# Storage
user_balances = {}
pending_withdrawals = {}
sell_requests = {}   # {user_id: {"link": link, "year": year}}
approved_sells = {}  # {user_id: [link1, link2]}
rejected_sells = {}  # {user_id: [link1, link2]}

# ========================
# STATES
# ========================
SELL_LINK, WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(4)

# ========================
# HELPER FUNCTIONS
# ========================
def is_admin(user_id):
    return user_id == ADMIN_ID

def get_price_text():
    text = "📊 *Current Group Prices*\n\n"
    for year, amount in PRICES.items():
        text += f"📅 {year}: ${amount}\n"
    return text

# ========================
# USER COMMANDS
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("price", "View group prices"),
        BotCommand("sell", "Sell your group"),
        BotCommand("withdraw", "Withdraw balance")
    ]
    if is_admin(user_id):
        commands += [BotCommand("admin_panel", "Open admin panel")]
    await context.bot.set_my_commands(commands)
    await update.message.reply_text(
        "👋 Welcome to Telegram Group Marketplace Bot!\n\n"
        "📩 /price - check prices\n"
        "📤 /sell - submit your group\n"
        "💸 /withdraw - request payout\n"
        "⚡ Withdrawals processed after admin approval.",
        parse_mode="Markdown"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_price_text(), parse_mode="Markdown")

# ========================
# SELL FLOW
# ========================
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📎 Send your *group invite link* (or /cancel to stop):",
        parse_mode="Markdown"
    )
    return SELL_LINK

async def receive_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    if not text.startswith("https://t.me/"):
        await update.message.reply_text("❌ Invalid link! Send a valid Telegram group link or /cancel.")
        return SELL_LINK
    sell_requests[user_id] = {"link": text, "year": None}
    # Notify admin
    msg = f"🆕 *New Group Submission*\n👤 User: @{update.message.from_user.username or update.message.from_user.first_name}\n🆔 ID: {user_id}\n🔗 Link: {text}"
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve:{user_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject:{user_id}")]
    ]
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    await update.message.reply_text("✅ Your group link has been sent to admin for review.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation canceled.")
    return ConversationHandler.END

# ========================
# WITHDRAW FLOW
# ========================
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="polygon")]
    ]
    await update.message.reply_text(
        "💸 Select your *withdrawal method*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return WITHDRAW_METHOD

async def choose_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["withdraw_method"] = query.data
    await query.edit_message_text(f"📤 Selected method: *{query.data.upper()}*\nEnter your address / UPI ID / UID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def get_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_address"] = update.message.text
    await update.message.reply_text("💰 Enter the *amount* you want to withdraw:")
    return WITHDRAW_AMOUNT

async def get_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    method = context.user_data["withdraw_method"]
    address = context.user_data["withdraw_address"]
    amount = update.message.text.strip()
    if not amount.isdigit():
        await update.message.reply_text("❌ Invalid amount. Enter numeric value.")
        return WITHDRAW_AMOUNT
    pending_withdrawals[user_id] = {"method": method, "address": address, "amount": amount}
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_withdraw:{user_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{user_id}")]
    ]
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💸 *New Withdrawal Request*\n👤 User: @{update.message.from_user.username or update.message.from_user.first_name}\n🆔 ID: {user_id}\n💳 Method: {method}\n🏦 Address: {address}\n💰 Amount: {amount}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ Your withdrawal request has been sent to admin.")
    return ConversationHandler.END

# ========================
# ADMIN CALLBACKS
# ========================
async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Only admin can perform this action.")
        return
    parts = query.data.split(':')
    action = parts[0]
    target_user = int(parts[1])

    if action == "approve":
        info = sell_requests.pop(target_user, None)
        if info:
            approved_sells.setdefault(target_user, []).append(info["link"])
            await context.bot.send_message(chat_id=target_user, text="✅ Your group has been *approved* by admin!", parse_mode="Markdown")
    elif action == "reject":
        info = sell_requests.pop(target_user, None)
        if info:
            rejected_sells.setdefault(target_user, []).append(info["link"])
            await context.bot.send_message(chat_id=target_user, text="❌ Your group has been *rejected* by admin.", parse_mode="Markdown")
    elif action == "confirm_withdraw":
        info = pending_withdrawals.pop(target_user, None)
        if info:
            await context.bot.send_message(chat_id=target_user, text=f"✅ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* approved!", parse_mode="Markdown")
    elif action == "reject_withdraw":
        pending_withdrawals.pop(target_user, None)
        await context.bot.send_message(chat_id=target_user, text="❌ Your withdrawal request has been *rejected*.", parse_mode="Markdown")

# ========================
# ADMIN PANEL
# ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not admin")
        return
    keyboard = [
        [InlineKeyboardButton("💰 Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("📊 View Users Summary", callback_data="admin_user_summary")],
        [InlineKeyboardButton("⚡ Set Prices", callback_data="admin_set_prices")],
        [InlineKeyboardButton("📈 Full Stats", callback_data="admin_full_stats")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")]
    ]
    await update.message.reply_text("⚙️ Admin Panel:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Not authorized")
        return
    action = query.data
    if action == "admin_add_balance":
        await query.edit_message_text("Usage: /addbalance <user_id> <amount>")
    elif action == "admin_user_summary":
        msg = f"👥 Total Users: {len(user_balances)}\n💰 Pending Withdrawals: {len(pending_withdrawals)}\n📝 Total Sell Requests: {len(sell_requests)}"
        await query.edit_message_text(msg)
    elif action == "admin_set_prices":
        await query.edit_message_text("Usage: /setprice <year> <amount>")
    elif action == "admin_full_stats":
        await admin_full_stats(update, context)
    elif action == "admin_broadcast":
        await query.edit_message_text("Usage: /broadcast <message_text>")

# ========================
# ADMIN COMMANDS
# ========================
async def addbalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not admin")
        return
    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        user_balances[user_id] = user_balances.get(user_id, 0) + amount
        await update.message.reply_text(f"✅ Added ${amount} to user {user_id}.")
    except:
        await update.message.reply_text("❌ Usage: /addbalance <user_id> <amount>")

async def setprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not admin")
        return
    try:
        year = context.args[0]
        amount = float(context.args[1])
        PRICES[year] = amount
        await update.message.reply_text(f"✅ Price for {year} set to ${amount}.")
    except:
        await update.message.reply_text("❌ Usage: /setprice <year> <amount>")

async def admin_full_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = len(user_balances)
    total_sell_requests = len(sell_requests)
    total_pending_withdrawals = len(pending_withdrawals)
    total_balance = sum(user_balances.values())

    sold_per_year = {year: 0 for year in PRICES.keys()}
    for links in approved_sells.values():
        for link in links:
            for year in PRICES.keys():
                if year in link:
                    sold_per_year[year] += 1

    msg = f"📊 *Admin Full Stats*\n\n"
    msg += f"👥 Total Users: {total_users}\n"
    msg += f"💰 Pending Withdrawals: {total_pending_withdrawals}\n"
    msg += f"📝 Sell Requests: {total_sell_requests}\n"
    msg += f"💵 Total Balances: ${total_balance}\n\n"
    msg += "📅 *Groups Sold per Year:*\n"
    for year, count in sold_per_year.items():
        msg += f"{year}: {count}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def user_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not admin.")
        return
    try:
        user_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Usage: /user_history <user_id>")
        return

    balance = user_balances.get(user_id, 0)
    pending_sells = 1 if user_id in sell_requests else 0
    approved = len(approved_sells.get(user_id, []))
    rejected = len(rejected_sells.get(user_id, []))
    pending_withdraw = 1 if user_id in pending_withdrawals else 0

    msg = f"📊 *User History for ID {user_id}*\n\n"
    msg += f"💰 Balance: ${balance}\n"
    msg += f"📝 Pending Sells: {pending_sells}\n"
    msg += f"✅ Approved Sells: {approved}\n"
    msg += f"❌ Rejected Sells: {rejected}\n"
    msg += f"💸 Pending Withdrawals: {pending_withdraw}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not admin")
        return
    msg = " ".join(context.args)
    for user_id in user_balances.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text=msg)
        except:
            pass
    await update.message.reply_text("✅ Broadcast sent.")

# ========================
# MAIN
# ========================
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("admin_panel", admin_panel))
    app.add_handler(CommandHandler("addbalance", addbalance_command))
    app.add_handler(CommandHandler("setprice", setprice_command))
    app.add_handler(CommandHandler("user_history", user_history))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Sell Flow
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=600
    )
    app.add_handler(sell_conv)

    # Withdraw Flow
    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(choose_withdraw_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_withdraw_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_withdraw_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(withdraw_conv)

    # Admin Callbacks
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^(approve|reject|confirm_withdraw|reject_withdraw):"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
