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

# Group prices
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
sell_requests = {}      # {user_id: {"link": link}}
approved_sells = {}     # {user_id: [link1, link2]}
rejected_sells = {}     # {user_id: [link1, link2]}
users_list = set()      # track all users

# States
SELL_LINK, WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT, BROADCAST_MESSAGE, INSPECT_USER, ADMIN_ADD_BALANCE, ADMIN_SET_PRICE = range(8)

# ========================
# HELPERS
# ========================
def is_admin(user_id):
    return user_id == ADMIN_ID

def get_price_text():
    text = "📊 *Current Group Prices*\n\n"
    for year, amount in PRICES.items():
        text += f"📅 {year}: ${amount}\n"
    return text

def get_admin_stats_text():
    total_users = len(users_list)
    total_sells = sum(len(v) for v in approved_sells.values()) + sum(len(v) for v in rejected_sells.values()) + len(sell_requests)
    total_approved = sum(len(v) for v in approved_sells.values())
    total_rejected = sum(len(v) for v in rejected_sells.values())
    pending_sells = len(sell_requests)
    pending_withdraws = len(pending_withdrawals)
    msg = f"📊 *Admin Stats*\n\n"
    msg += f"👥 Total Users: {total_users}\n"
    msg += f"📝 Total Sells: {total_sells}\n"
    msg += f"✅ Approved Sells: {total_approved}\n"
    msg += f"❌ Rejected Sells: {total_rejected}\n"
    msg += f"⏳ Pending Sells: {pending_sells}\n"
    msg += f"💸 Pending Withdrawals: {pending_withdraws}\n"
    return msg

def get_user_history_text(user_id):
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
    return msg

# ========================
# USER COMMANDS
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users_list.add(user_id)
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
    sell_requests[user_id] = {"link": text}
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
# ADMIN PANEL
# ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Only admin can access this panel.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 View Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("💵 Set Prices", callback_data="admin_set_prices")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👤 Inspect User", callback_data="admin_inspect_user")]
    ]
    await update.message.reply_text("⚡ Admin Panel:", reply_markup=InlineKeyboardMarkup(keyboard))

# ========================
# CALLBACK HANDLER
# ========================
async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text("❌ Only admin can perform this action.")
        return

    data = query.data
    # Approve/Reject sells or withdraws
    if ":" in data:
        action, target_user = data.split(":")
        target_user = int(target_user)
        if action == "approve":
            info = sell_requests.pop(target_user, None)
            if info:
                approved_sells.setdefault(target_user, []).append(info["link"])
                await context.bot.send_message(chat_id=target_user, text="✅ Your group has been *approved*!", parse_mode="Markdown")
        elif action == "reject":
            info = sell_requests.pop(target_user, None)
            if info:
                rejected_sells.setdefault(target_user, []).append(info["link"])
                await context.bot.send_message(chat_id=target_user, text="❌ Your group has been *rejected*.", parse_mode="Markdown")
        elif action == "confirm_withdraw":
            info = pending_withdrawals.pop(target_user, None)
            if info:
                await context.bot.send_message(chat_id=target_user, text=f"✅ Withdrawal of ${info['amount']} via *{info['method'].upper()}* approved!", parse_mode="Markdown")
        elif action == "reject_withdraw":
            pending_withdrawals.pop(target_user, None)
            await context.bot.send_message(chat_id=target_user, text="❌ Withdrawal request rejected.", parse_mode="Markdown")
    else:
        # Admin panel options
        if data == "admin_stats":
            await query.edit_message_text(get_admin_stats_text(), parse_mode="Markdown")
        elif data == "admin_broadcast":
            await query.edit_message_text("📣 Send broadcast message (or /cancel):")
            return BROADCAST_MESSAGE
        elif data == "admin_inspect_user":
            await query.edit_message_text("👤 Send user ID to inspect:")
            return INSPECT_USER
        elif data == "admin_add_balance":
            await query.edit_message_text("💰 Send in format: <user_id> <amount>")
            return ADMIN_ADD_BALANCE
        elif data == "admin_set_prices":
            await query.edit_message_text("💵 Send in format: <year> <price>")
            return ADMIN_SET_PRICE

# ========================
# BROADCAST, INSPECT, ADMIN BALANCE & PRICE HANDLERS
# ========================
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    for uid in users_list:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📣 Broadcast:\n\n{msg}")
        except:
            pass
    await update.message.reply_text("✅ Broadcast sent to all users.")
    return ConversationHandler.END

async def inspect_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return INSPECT_USER
    await update.message.reply_text(get_user_history_text(uid), parse_mode="Markdown")
    return ConversationHandler.END

async def admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.strip().split()
        uid = int(args[0])
        amount = float(args[1])
        user_balances[uid] = user_balances.get(uid, 0) + amount
        await update.message.reply_text(f"✅ Added ${amount} to user {uid}.")
        await context.bot.send_message(uid, text=f"💰 Admin added ${amount} to your balance.")
    except:
        await update.message.reply_text("❌ Usage: <user_id> <amount>")
    return ConversationHandler.END

async def admin_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.strip().split()
        year = " ".join(args[:-1])
        price = float(args[-1])
        PRICES[year] = price
        await update.message.reply_text(f"✅ Price for {year} set to ${price}")
    except:
        await update.message.reply_text("❌ Usage: <year> <price>")
    return ConversationHandler.END

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

    # Broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message)],
        states={BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(broadcast_conv)

    # Inspect
    inspect_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, inspect_user)],
        states={INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, inspect_user)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(inspect_conv)

    # Admin Add Balance
    add_balance_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance)],
        states={ADMIN_ADD_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(add_balance_conv)

    # Admin Set Price
    set_price_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_price)],
        states={ADMIN_SET_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_price)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(set_price_conv)

    # Admin callbacks
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern=".*"))

    print("🤖 Advanced Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
