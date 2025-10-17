# bot_full_ready.py
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
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
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"           # <- replace
ADMIN_ID = 5405985282                  # <- replace with your numeric Telegram ID

# Prices you specified
PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# ========================
# STORAGE (in-memory)
# Replace with a DB for production
# ========================
user_balances = {}             # {user_id: float}
pending_groups = {}            # {user_id: {"link": str, "username": str, "name": str}}
pending_withdrawals = {}       # {user_id: {"method":..., "address":..., "amount":..., "status":"pending"}}
withdraw_history = {}          # {user_id: [ {"amount":..., "method":..., "address":..., "status":..., "timestamp":...}, ... ]}

# ========================
# Keyboards
# ========================
user_keyboard = [
    ["🏠 Start", "💰 Prices"],
    ["🛍 Sell", "💸 Withdraw"],
    ["💵 Balance"]
]
admin_keyboard = [
    ["🏠 Start", "💰 Prices"],
    ["🛍 Sell", "💸 Withdraw"],
    ["💵 Balance", "🧑‍💻 Admin"]
]

# We'll create ReplyKeyboardMarkups dynamically per user in /start
# ========================
# Conversation states
# ========================
SELL_STATE = 1
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(3)

# ========================
# Logging
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# Helpers
# ========================
def format_prices():
    out = "📊 *Current Group Prices*\n\n"
    for yr, amt in PRICES.items():
        out += f"📅 {yr}: {amt}\n"
    return out

def add_withdraw_history(user_id, method, address, amount, status):
    import datetime
    rec = {
        "method": method,
        "address": address,
        "amount": amount,
        "status": status,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }
    withdraw_history.setdefault(user_id, []).append(rec)
    return rec

# ========================
# /start handler — sends keyboard (admin sees Admin button)
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id == ADMIN_ID:
        kb = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
    else:
        kb = ReplyKeyboardMarkup(user_keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Welcome to the Group Marketplace Bot!\nUse the buttons below to navigate.",
        reply_markup=kb
    )

# ========================
# Price
# ========================
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_prices(), parse_mode="Markdown")

# ========================
# SELL FLOW
# ========================
async def sell_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Please send your group invite link to submit for review.")
    return SELL_STATE

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    link = update.message.text.strip()
    pending_groups[user.id] = {"link": link, "username": user.username, "name": user.first_name}
    # Notify user
    await update.message.reply_text("✅ Your group link has been sent to admin for review.")
    # Send admin message with inline buttons
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{user.id}")
        ],
    ]
    msg = (
        f"🆕 *New Group Submission*\n"
        f"👤 User: @{user.username or user.first_name}\n"
        f"🆔 {user.id}\n"
        f"🔗 {link}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

async def admin_handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # e.g. "approve_group:12345"
    try:
        action, uid_str = data.split(":")
        user_id = int(uid_str)
    except Exception:
        await query.edit_message_text("❌ Invalid data.")
        return

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can use this.")
        return

    if user_id not in pending_groups:
        await query.edit_message_text("❌ This submission no longer exists.")
        return

    info = pending_groups.pop(user_id)

    if action == "approve_group":
        # notify seller
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your group link `{info['link']}` has been *approved* by admin. You will receive balance shortly.",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"✅ Approved group from @{info.get('username') or info.get('name')}")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Your group link `{info['link']}` has been *rejected* by admin.",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"❌ Rejected group from @{info.get('username') or info.get('name')}")

# ========================
# WITHDRAW FLOW (includes history display)
# ========================
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    hist = withdraw_history.get(user.id, [])
    if hist:
        # Show last 10 entries succinctly
        lines = []
        for r in hist[-10:]:
            lines.append(f"{r['timestamp']}: {r['amount']}$ via {r['method']} — {r['status']}")
        await update.message.reply_text("🧾 Your recent withdraw history:\n" + "\n".join(lines))
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="polygon")],
    ]
    await update.message.reply_text("💸 Select withdrawal method:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["withdraw_method"] = query.data
    await query.edit_message_text("📤 Enter your address / UPI ID / UID:")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_address"] = update.message.text.strip()
    await update.message.reply_text("💰 Enter the amount you want to withdraw (numbers only):")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    method = context.user_data.get("withdraw_method")
    address = context.user_data.get("withdraw_address")
    amount_text = update.message.text.strip()

    # Basic validation
    try:
        amount = float(amount_text)
    except ValueError:
        await update.message.reply_text("⚠️ Invalid amount. Please send a numeric value.")
        return WITHDRAW_AMOUNT

    # Ensure user has balance
    bal = user_balances.get(user.id, 0)
    if amount > bal:
        await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal}")
        return ConversationHandler.END

    # Save pending withdrawal
    pending_withdrawals[user.id] = {"method": method, "address": address, "amount": amount}
    add_withdraw_history(user.id, method, address, amount, "pending")

    # Notify admin with inline confirm/dismiss buttons
    kb = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_withdraw:{user.id}"),
            InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_withdraw:{user.id}")
        ]
    ]
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(f"💸 *New Withdrawal Request*\n👤 @{user.username or user.first_name}\n"
              f"🆔 {user.id}\n💳 {method}\n🏦 {address}\n💰 {amount}"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

    await update.message.reply_text("✅ Your withdrawal request has been sent to admin for approval.")
    return ConversationHandler.END

async def admin_handle_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # e.g. confirm_withdraw:12345
    try:
        action, uid_str = data.split(":")
        user_id = int(uid_str)
    except Exception:
        await query.edit_message_text("❌ Invalid data.")
        return

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can use this.")
        return

    if user_id not in pending_withdrawals:
        await query.edit_message_text("❌ This withdrawal no longer exists.")
        return

    info = pending_withdrawals.pop(user_id)
    # find last pending record in history and set status
    history = withdraw_history.get(user_id, [])
    # update latest 'pending' to approved/rejected
    for rec in reversed(history):
        if rec["status"] == "pending" and rec["amount"] == info["amount"] and rec["method"] == info["method"]:
            rec["status"] = "approved" if action == "confirm_withdraw" else "rejected"
            break

    if action == "confirm_withdraw":
        # Deduct user's balance and notify user
        user_balances[user_id] = max(user_balances.get(user_id, 0) - float(info["amount"]), 0.0)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* has been *approved* and processed.",
            parse_mode="Markdown"
        )
        await query.edit_message_text("✅ Withdrawal Confirmed and processed.")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* has been *rejected*.",
            parse_mode="Markdown"
        )
        await query.edit_message_text("❌ Withdrawal Dismissed.")

# ========================
# ADMIN PANEL (inline). Only accessible to admin.
# Admin can list pending groups, pending withdrawals, add balance by sending "user_id amount"
# ========================
async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only admin should call; start button triggers this path for admin
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    kb = [
        [InlineKeyboardButton("📋 Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_pending_withdrawals")],
        [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("📊 View All Balances", callback_data="admin_view_balances")],
    ]
    await update.message.reply_text("🛠 *Admin Panel* — choose an action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can use this.")
        return

    data = query.data
    if data == "admin_pending_groups":
        if not pending_groups:
            await query.edit_message_text("📋 No pending group submissions.")
            return
        # Build a message listing pending groups with approve/reject buttons under each
        for uid, info in list(pending_groups.items()):
            kb = [
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}")]
            ]
            await context.bot.send_message(chat_id=ADMIN_ID,
                                           text=f"👤 @{info.get('username') or info.get('name')} (ID: {uid})\n🔗 {info.get('link')}",
                                           reply_markup=InlineKeyboardMarkup(kb))
        await query.edit_message_text("📋 Sent pending groups as messages above.")
    elif data == "admin_pending_withdrawals":
        if not pending_withdrawals:
            await query.edit_message_text("💸 No pending withdrawals.")
            return
        for uid, info in list(pending_withdrawals.items()):
            kb = [
                [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_withdraw:{uid}"),
                 InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_withdraw:{uid}")]
            ]
            await context.bot.send_message(chat_id=ADMIN_ID,
                                           text=(f"👤 ID: {uid}\n💳 {info['method'].upper()} | {info['address']}\n"
                                                 f"💰 {info['amount']}"),
                                           reply_markup=InlineKeyboardMarkup(kb))
        await query.edit_message_text("💸 Sent pending withdrawals as messages above.")
    elif data == "admin_add_balance":
        # set a flag for admin to send "user_id amount" next
        context.user_data["awaiting_add_balance"] = True
        await query.edit_message_text("➕ Send user ID and amount separated by space like:\n`123456789 5.0`")
    elif data == "admin_view_balances":
        if not user_balances:
            await query.edit_message_text("📊 No balances yet.")
            return
        text = "📊 All balances:\n\n"
        for uid, bal in user_balances.items():
            text += f"{uid}: ${bal}\n"
        await query.edit_message_text(text)

# Handle admin sending "user_id amount" when flagged
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return  # only admin uses this text route for admin actions

    if context.user_data.get("awaiting_add_balance"):
        text = update.message.text.strip()
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("⚠️ Invalid format. Send: `123456789 5.0`")
            return
        try:
            uid = int(parts[0])
            amt = float(parts[1])
        except Exception:
            await update.message.reply_text("⚠️ Invalid numbers. Example: `123456789 5.0`")
            return

        user_balances[uid] = user_balances.get(uid, 0.0) + amt
        # notify admin & user
        await update.message.reply_text(f"✅ Added ${amt} to user {uid}. New balance: ${user_balances[uid]}")
        await context.bot.send_message(chat_id=uid, text=f"💵 Your balance has been updated: +${amt}. New balance: ${user_balances[uid]}")
        # clear flag
        context.user_data["awaiting_add_balance"] = False

# ========================
# Routing from ReplyKeyboard buttons
# ========================
async def handle_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Map bottom keyboard labels to actions
    if text == "🏠 Start":
        await start(update, context)
    elif text == "💰 Prices":
        await price(update, context)
    elif text == "🛍 Sell":
        # start sell conversation
        return await sell_start(update, context)
    elif text == "💸 Withdraw":
        return await withdraw_start(update, context)
    elif text == "💵 Balance":
        await update.message.reply_text(f"💰 Your current balance: ${user_balances.get(update.effective_user.id, 0.0)}")
    elif text == "🧑‍💻 Admin":
        await open_admin_panel(update, context)
    else:
        # allow other text (e.g., admin numeric entry) to be handled by admin_text_handler
        await admin_text_handler(update, context)

# ========================
# Application setup
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Basic commands (so commands also appear in Telegram's command list)
    app.post_init = lambda bot_app: bot_app.bot.set_my_commands([
        # these are shown in the command suggestions bar (not the persistent keyboard)
        # keep them for convenience
        ("start", "Open the bot"),
        ("price", "Show prices"),
        ("withdraw", "Withdraw / view history"),
        ("balance", "View your balance"),
    ])

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    # Sell conversation (entry from button route)
    sell_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛍 Sell$"), sell_start)],
        states={SELL_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)]},
        fallbacks=[]
    )
    app.add_handler(sell_conv)
    app.add_handler(CallbackQueryHandler(admin_handle_group_callback, pattern="^(approve_group|reject_group):"))

    # Withdraw conversation
    withdraw_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw_start)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[]
    )
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(admin_handle_withdraw_callback, pattern="^(confirm_withdraw|dismiss_withdraw):"))

    # Admin panel callbacks
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))  # safe duplicate

    # Admin add-balance via plain text handler
    # This will be handled through admin_text_handler when awaited flag is set.
    # We also need a generic message handler for keyboard button taps and admin replies:
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_text))

    print("🤖 Bot running with admin panel, bottom keyboard, sell and withdraw flows...")
    app.run_polling()

if __name__ == "__main__":
    main()
