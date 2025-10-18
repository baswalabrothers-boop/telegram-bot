import logging, re, asyncio
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ========================
# 🔐 CONFIG
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282

PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# ========================
# 💾 In-memory Storage (DB recommended for production)
# ========================
user_balances = {}
pending_withdrawals = {}
withdrawal_history = {}
group_submissions = {}
user_stats = {}  # {user_id: {"sales": int}}

# ========================
# 📜 Command Menu
# ========================
COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("price", "Check group prices"),
    BotCommand("sell", "Sell your group"),
    BotCommand("withdraw", "Request withdrawal"),
    BotCommand("cancel", "Cancel current action"),
]

# ========================
# 🏁 START
# ========================
WELCOME_TEXT = (
    "👋 Welcome to *Group Marketplace Bot*!\n\n"
    "📊 Use the menu below to get started:\n"
    "• /price — Check group prices\n"
    "• /sell — Sell your group\n"
    "• /withdraw — Request payout\n\n"
    "💬 Withdrawals are processed manually by admin."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands(COMMANDS)
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

# ========================
# 📊 PRICE
# ========================
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for year, amount in PRICES.items():
        text += f"📅 {year}: {amount}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================
# 📎 SELL GROUP
# ========================
SELL_STATE = 1
sell_timeouts = {}

def is_valid_invite(link: str) -> bool:
    return bool(re.match(r"(https:\/\/t\.me\/\+|https:\/\/t\.me\/)[\w\d_]+", link))

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "📎 Please send your *group invite link*.\n\n"
        "❌ If you changed your mind, use /cancel to stop.",
        parse_mode="Markdown"
    )
    # Auto cancel after 10 minutes
    sell_timeouts[user_id] = asyncio.get_event_loop().call_later(
        600, lambda: asyncio.create_task(cancel_sell_timeout(context, user_id))
    )
    return SELL_STATE

async def receive_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user = update.message.from_user
    user_id = user.id

    if not is_valid_invite(link):
        await update.message.reply_text("❌ Invalid link. Please send a valid Telegram group invite link.")
        return SELL_STATE

    # Cancel timeout
    if user_id in sell_timeouts:
        sell_timeouts[user_id].cancel()
        del sell_timeouts[user_id]

    group_submissions[user_id] = {"link": link, "time": datetime.now()}
    msg = (
        f"🆕 *New Group Submission*\n👤 User: @{user.username or user.first_name}\n🆔 ID: {user.id}\n"
        f"🔗 Link: {link}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{user_id}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{user_id}")]
    ]
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    await update.message.reply_text("✅ Your group link has been sent to admin for review.")
    return ConversationHandler.END

async def cancel_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in sell_timeouts:
        sell_timeouts[user_id].cancel()
        del sell_timeouts[user_id]
    await update.message.reply_text("❌ Sell process cancelled.")
    return ConversationHandler.END

async def cancel_sell_timeout(context, user_id):
    try:
        await context.bot.send_message(chat_id=user_id, text="⏳ Sell process cancelled due to timeout (10 min).")
    except:
        pass

# ========================
# 🛡️ ADMIN APPROVE / REJECT
# ========================
async def handle_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, user_id = data.split(":")
    user_id = int(user_id)

    if action == "approve_group":
        await context.bot.send_message(user_id, "✅ Your group has been *approved*! Balance will be added after verification.", parse_mode="Markdown")
        await query.edit_message_text("✅ Group Approved.")
        # Count sale
        user_stats.setdefault(user_id, {"sales": 0})
        user_stats[user_id]["sales"] += 1
    elif action == "reject_group":
        await context.bot.send_message(user_id, "❌ Your group submission was *rejected* by admin.", parse_mode="Markdown")
        await query.edit_message_text("❌ Group Rejected.")

# ========================
# 💰 BALANCE & WITHDRAW
# ========================
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(3)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="polygon")],
    ]
    await update.message.reply_text(
        "💸 Select your *withdrawal method*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return WITHDRAW_METHOD

async def choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["method"] = q.data
    await q.edit_message_text(f"📤 Method: *{q.data.upper()}*\nSend your address / UPI ID / UID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("💰 Enter the amount to withdraw:")
    return WITHDRAW_AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = update.message.text.strip()
    user_id = update.effective_user.id
    method = context.user_data["method"]
    address = context.user_data["address"]

    pending_withdrawals[user_id] = {"method": method, "address": address, "amount": amount}

    withdrawal_history.setdefault(user_id, []).append({
        "method": method, "address": address, "amount": amount, "time": datetime.now()
    })

    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_wd:{user_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_wd:{user_id}")]
    ]
    msg = (
        f"💸 *Withdrawal Request*\n🆔 {user_id}\n💳 {method}\n🏦 {address}\n💰 {amount}$"
    )
    await context.bot.send_message(ADMIN_ID, msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

async def handle_withdraw_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, user_id = q.data.split(":")
    user_id = int(user_id)

    if user_id not in pending_withdrawals:
        await q.edit_message_text("❌ Request expired.")
        return

    wd = pending_withdrawals.pop(user_id)
    if action == "confirm_wd":
        await context.bot.send_message(user_id, f"✅ Your withdrawal of {wd['amount']}$ has been approved!")
        await q.edit_message_text("✅ Withdrawal approved.")
    else:
        await context.bot.send_message(user_id, "❌ Your withdrawal request has been rejected.")
        await q.edit_message_text("❌ Withdrawal rejected.")

# ========================
# 🧑 ADMIN PANEL
# ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    keyboard = [
        [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("📊 Check User Stats", callback_data="admin_check_user")],
    ]
    await update.message.reply_text("🛡️ *Admin Panel*", parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "admin_add_balance":
        await q.edit_message_text("✍️ Send: `user_id amount` to add balance", parse_mode="Markdown")
        context.user_data["admin_mode"] = "add_balance"
    elif q.data == "admin_check_user":
        await q.edit_message_text("🔍 Send user ID to check stats")
        context.user_data["admin_mode"] = "check_user"

async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("admin_mode") == "add_balance":
        try:
            user_id, amt = update.message.text.split()
            user_id = int(user_id)
            amt = float(amt)
            user_balances[user_id] = user_balances.get(user_id, 0) + amt
            await context.bot.send_message(user_id, f"💰 Your balance has been increased by ${amt}.")
            await update.message.reply_text(f"✅ Added ${amt} to {user_id}")
        except:
            await update.message.reply_text("❌ Invalid format. Use: `user_id amount`")
    elif context.user_data.get("admin_mode") == "check_user":
        try:
            uid = int(update.message.text)
            bal = user_balances.get(uid, 0)
            sales = user_stats.get(uid, {}).get("sales", 0)
            wd = withdrawal_history.get(uid, [])
            wd_list = "\n".join([f"{w['amount']}$ {w['method']} at {w['time'].strftime('%d-%m %H:%M')}" for w in wd]) or "None"
            text = f"📊 User {uid}\n💰 Balance: ${bal}\n🛒 Sales: {sales}\n💸 Withdrawals:\n{wd_list}"
            await update.message.reply_text(text)
        except:
            await update.message.reply_text("❌ Invalid user ID.")

# ========================
# 🧰 MAIN
# ========================
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    # Sell conversation
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell)],
        states={SELL_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)]},
        fallbacks=[CommandHandler("cancel", cancel_sell)]
    )
    app.add_handler(sell_conv)

    # Withdraw conversation
    wd_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(choose_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel_sell)]
    )
    app.add_handler(wd_conv)

    # Admin stuff
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), admin_text_input))
    app.add_handler(CallbackQueryHandler(admin_actions, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(handle_group_admin, pattern="^(approve_group|reject_group):"))
    app.add_handler(CallbackQueryHandler(handle_withdraw_admin, pattern="^(confirm_wd|reject_wd):"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
