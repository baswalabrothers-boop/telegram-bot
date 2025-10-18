# advanced_marketplace_bot.py
import logging
import re
import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ========================
# CONFIG - set these
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282   # <-- your numeric Telegram ID (single admin). Replace.

# ========================
# PRICES (as you gave)
# ========================
PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# ========================
# Regex to validate invite links
# ========================
INVITE_REGEX = re.compile(
    r'^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+)[A-Za-z0-9_-]+$',
    flags=re.IGNORECASE
)

# ========================
# In-memory storage (replace with DB for persistence)
# ========================
user_balances = {}             # {user_id: float}
pending_groups = {}            # {user_id: {"link":..., "username":..., "submitted_at":...}}
submitted_groups_count = {}    # {user_id: int}
approved_groups_count = {}     # {user_id: int}
pending_withdrawals = {}       # {user_id: {"method":..., "address":..., "amount":..., "timestamp":...}}
withdraw_history = {}          # {user_id: [ {method, address, amount, status, timestamp}, ... ]}
all_users = set()
SELL_ENABLED = True

# ========================
# Conversation states
# ========================
(
    SELL_LINK,
    WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT,
    ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER,
    ADMIN_BROADCAST
) = range(10)

# ========================
# Logging
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# Reply keyboard (bottom buttons)
# ========================
def get_main_keyboard(user_id):
    keyboard = [
        ["🏠 Start", "💰 Prices"],
        ["🛍 Sell", "💸 Withdraw"],
        ["💵 Balance"]
    ]
    if user_id == ADMIN_ID:
        keyboard[-1].append("🧑‍💻 Admin")  # add Admin in last row for admin only
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========================
# Helpers
# ========================
def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"

def ensure_user(user_id):
    all_users.add(user_id)
    submitted_groups_count.setdefault(user_id, 0)
    approved_groups_count.setdefault(user_id, 0)
    withdraw_history.setdefault(user_id, [])
    user_balances.setdefault(user_id, 0.0)

def add_withdraw_record(user_id, method, address, amount, status):
    rec = {"method": method, "address": address, "amount": float(amount), "status": status, "timestamp": now_iso()}
    withdraw_history.setdefault(user_id, []).append(rec)
    return rec

# ========================
# START / PRICES / BALANCE
# ========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)
    await update.message.reply_text(
        "👋 Welcome to the Group Marketplace Bot!\nUse the buttons below to navigate.",
        reply_markup=get_main_keyboard(user.id)
    )

async def prices_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for year, price in PRICES.items():
        text += f"📅 {year}: {price}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    await update.message.reply_text(f"💰 Your current balance: ${user_balances.get(uid, 0.0):.2f}")

# ========================
# SELL FLOW (validation, cancel, 10-min timeout)
# ========================
async def sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SELL_ENABLED:
        await update.message.reply_text("⚠️ Selling is currently disabled by admin. Try later.")
        return ConversationHandler.END
    user = update.effective_user
    ensure_user(user.id)
    # mark user in sell flow
    context.user_data['in_sell'] = True
    await update.message.reply_text(
        "📎 Send your Telegram *group invite link* to submit for review.\n\n"
        "If you change your mind type /cancel to stop.\n"
        "⏳ You have 10 minutes to send the link.",
        parse_mode="Markdown"
    )
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    # if user canceled via other flow, guard
    if not context.user_data.get('in_sell'):
        return ConversationHandler.END

    if not INVITE_REGEX.match(text):
        # Invalid link -> stay in SELL_LINK
        await update.message.reply_text(
            "❌ Invalid Telegram invite link. Examples of valid formats:\n"
            "- https://t.me/joinchat/AAAAA\n"
            "- https://t.me/+AbCdEfGh\n"
            "Send a valid link or /cancel to stop."
        )
        return SELL_LINK

    # valid link -> store and notify admin
    ensure_user(user.id)
    pending_groups[user.id] = {"link": text, "username": user.username or user.first_name, "submitted_at": now_iso()}
    submitted_groups_count[user.id] = submitted_groups_count.get(user.id, 0) + 1
    context.user_data.pop('in_sell', None)

    await update.message.reply_text("✅ Your group link has been submitted for admin review. You will be notified on approval/rejection.")

    # send admin message with Approve/Reject
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{user.id}")
        ]
    ]
    text_admin = (
        f"🆕 *New Group Submission*\n"
        f"👤 @{user.username or user.first_name} (ID: {user.id})\n"
        f"🔗 {text}\n"
        f"⏱ {pending_groups[user.id]['submitted_at']}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=text_admin, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

async def sell_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Cancel both via /cancel or user-triggered cancel
    context.user_data.pop('in_sell', None)
    await update.message.reply_text("❌ Sell process cancelled. You can start again anytime.")
    return ConversationHandler.END

# ========================
# WITHDRAW FLOW (method -> address -> amount) + history
# ========================
async def withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)
    # show last 10 withdraw history entries
    hist = withdraw_history.get(user.id, [])[-10:]
    if hist:
        lines = [f"{r['timestamp']}: {r['amount']}$ via {r['method']} — {r['status']}" for r in hist]
        await update.message.reply_text("🧾 Your recent withdraw history:\n" + "\n".join(lines))
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="method_upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="method_polygon")]
    ]
    await update.message.reply_text("💸 Select withdrawal method:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("method_", "")
    context.user_data["withdraw_method"] = method
    await query.edit_message_text(f"📤 Selected method: *{method.upper()}*\n\nPlease send your address / UPI ID / UID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_address"] = update.message.text.strip()
    await update.message.reply_text("💰 Enter the amount you want to withdraw (numbers only):")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    method = context.user_data.get("withdraw_method")
    address = context.user_data.get("withdraw_address")
    amount_text = update.message.text.strip()
    # validate amount
    try:
        amount = float(amount_text)
        if amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("⚠️ Invalid amount. Please send a numeric amount.")
        return WITHDRAW_AMOUNT

    # check balance
    ensure_user(user.id)
    bal = user_balances.get(user.id, 0.0)
    if amount > bal:
        await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal:.2f}")
        return ConversationHandler.END

    # store pending withdrawal & history
    pending_withdrawals[user.id] = {"method": method, "address": address, "amount": amount, "timestamp": now_iso()}
    add_withdraw_record(user.id, method, address, amount, "Pending")

    # notify admin with approve/dismiss
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{user.id}")
        ]
    ]
    admin_text = (
        f"💸 *New Withdrawal Request*\n👤 @{user.username or user.first_name} (ID: {user.id})\n"
        f"💳 {method}\n🏦 {address}\n💰 {amount}\n⏱ {pending_withdrawals[user.id]['timestamp']}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    await update.message.reply_text("✅ Your withdrawal request is sent to admin for approval.")
    return ConversationHandler.END

# ========================
# ADMIN CALLBACKS (approve/reject for groups & withdraws)
# ========================
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Approve/Reject group
    if data.startswith("approve_group:") or data.startswith("reject_group:"):
        action, uid_str = data.split(":")
        uid = int(uid_str)
        info = pending_groups.pop(uid, None)
        if not info:
            await query.edit_message_text("⚠️ Submission not found or already processed.")
            return
        if action == "approve_group":
            approved_groups_count[uid] = approved_groups_count.get(uid, 0) + 1
            await context.bot.send_message(uid, f"✅ Your group `{info['link']}` has been *approved* by admin.", parse_mode="Markdown")
            await query.edit_message_text("✅ Group approved.")
        else:
            await context.bot.send_message(uid, f"❌ Your group `{info['link']}` has been *rejected* by admin.", parse_mode="Markdown")
            await query.edit_message_text("❌ Group rejected.")
        return

    # Approve/Reject withdraw
    if data.startswith("approve_withdraw:") or data.startswith("reject_withdraw:"):
        action, uid_str = data.split(":")
        uid = int(uid_str)
        wd = pending_withdrawals.pop(uid, None)
        if not wd:
            await query.edit_message_text("⚠️ Withdrawal not found or processed.")
            return
        # update last pending record to approved/rejected
        hist = withdraw_history.get(uid, [])
        for rec in reversed(hist):
            if rec["status"] == "Pending" and rec["amount"] == float(wd["amount"]) and rec["method"] == wd["method"]:
                rec["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break

        if action == "approve_withdraw":
            # deduct balance and notify user
            user_balances[uid] = max(user_balances.get(uid, 0.0) - float(wd["amount"]), 0.0)
            await context.bot.send_message(uid, f"✅ Your withdrawal of ${wd['amount']} via *{wd['method'].upper()}* has been *approved* and processed.", parse_mode="Markdown")
            await query.edit_message_text("✅ Withdrawal approved and processed.")
        else:
            await context.bot.send_message(uid, f"❌ Your withdrawal of ${wd['amount']} via *{wd['method'].upper()}* has been *rejected*.", parse_mode="Markdown")
            await query.edit_message_text("❌ Withdrawal rejected.")
        return

# ========================
# ADMIN PANEL (Conversation) - full advanced panel
# ========================
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton("👥 Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_pending_withdrawals")],
        [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("🔍 Inspect User", callback_data="admin_inspect_user")],
        [InlineKeyboardButton("🪙 Toggle Sell On/Off", callback_data="admin_toggle_sell")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")]
    ]
    await update.message.reply_text("🧑‍💻 *Admin Panel* — choose an action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_PANEL

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can use this.")
        return ADMIN_PANEL

    data = query.data

    if data == "admin_pending_groups":
        if not pending_groups:
            await query.edit_message_text("📭 No pending groups.")
            return ADMIN_PANEL
        # send each pending as admin message with approve/reject
        for uid, info in list(pending_groups.items()):
            kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
                   InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}")]]
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 {uid} ➝ {info['link']}\nSubmitted: {info.get('submitted_at')}", reply_markup=InlineKeyboardMarkup(kb))
        await query.edit_message_text("📋 Pending groups sent above.")
        return ADMIN_PANEL

    if data == "admin_pending_withdrawals":
        if not pending_withdrawals:
            await query.edit_message_text("📭 No pending withdrawals.")
            return ADMIN_PANEL
        for uid, w in list(pending_withdrawals.items()):
            kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
                   InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}")]]
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 {uid} ➝ {w['amount']}$ via {w['method']} ({w['address']})", reply_markup=InlineKeyboardMarkup(kb))
        await query.edit_message_text("💸 Pending withdrawals sent above.")
        return ADMIN_PANEL

    if data == "admin_add_balance":
        context.user_data['admin_action'] = 'add_balance'
        await query.edit_message_text("➕ Send the user ID to add balance to:")
        return ADMIN_ADD_USER

    if data == "admin_inspect_user":
        context.user_data['admin_action'] = 'inspect_user'
        await query.edit_message_text("🔍 Send the user ID to inspect:")
        return ADMIN_INSPECT_USER

    if data == "admin_toggle_sell":
        global SELL_ENABLED
        SELL_ENABLED = not SELL_ENABLED
        await query.edit_message_text(f"⚙️ Sell is now {'ENABLED' if SELL_ENABLED else 'DISABLED'}.")
        return ADMIN_PANEL

    if data == "admin_broadcast":
        context.user_data['admin_action'] = 'broadcast'
        await query.edit_message_text("📢 Send the broadcast message to all users (text only):")
        return ADMIN_BROADCAST

    await query.edit_message_text("⚠️ Unknown action.")
    return ADMIN_PANEL

async def admin_add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # expecting user id
    user = update.effective_user
    if user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Invalid ID. Send numeric user id.")
        return ADMIN_ADD_USER
    context.user_data['target_user'] = uid
    await update.message.reply_text(f"Now send the amount to add to user {uid}:")
    return ADMIN_ADD_AMOUNT

async def admin_add_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        amount = float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Invalid amount. Send numeric value.")
        return ADMIN_ADD_AMOUNT
    uid = context.user_data.pop('target_user', None)
    if uid is None:
        await update.message.reply_text("❌ No target user. Start over.")
        return ConversationHandler.END
    ensure_user(uid)
    user_balances[uid] = user_balances.get(uid, 0.0) + amount
    await update.message.reply_text(f"✅ Added ${amount:.2f} to user {uid}. New balance: ${user_balances[uid]:.2f}")
    try:
        await context.bot.send_message(chat_id=uid, text=f"💵 Your balance has been increased by ${amount:.2f}. New balance: ${user_balances[uid]:.2f}")
    except Exception:
        pass
    return ADMIN_PANEL

async def admin_inspect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Invalid user id.")
        return ADMIN_INSPECT_USER
    ensure_user(uid)
    bal = user_balances.get(uid, 0.0)
    submitted = submitted_groups_count.get(uid, 0)
    approved = approved_groups_count.get(uid, 0)
    hist = withdraw_history.get(uid, [])
    pending_g = pending_groups.get(uid)
    pending_w = pending_withdrawals.get(uid)
    text = (
        f"🔎 User: {uid}\n"
        f"💰 Balance: ${bal:.2f}\n"
        f"📤 Submitted groups: {submitted}\n"
        f"✅ Approved groups: {approved}\n"
        f"⏳ Pending group: {pending_g['link'] if pending_g else 'None'}\n"
        f"⏳ Pending withdraw: {pending_w['amount'] if pending_w else 'None'}\n"
        f"📝 Withdraw history ({len(hist)}):\n"
    )
    for r in hist[-10:]:
        text += f"- {r['timestamp']}: {r['amount']}$ via {r['method']} — {r['status']}\n"
    await update.message.reply_text(text)
    return ADMIN_PANEL

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text
    count = 0
    for uid in list(all_users):
        try:
            context.bot.send_message(uid, f"📢 Broadcast from admin:\n\n{text}")
            count += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")
    return ADMIN_PANEL

# ========================
# Button-only handlers (bottom keyboard) — map button text to functions
# ========================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user = update.effective_user
    ensure_user(user.id)

    # Prevent keyboard text from interfering with active conversation: ConversationHandler has priority.
    # This handler only receives messages when no active ConversationHandler for user is running.
    if text == "🏠 Start":
        await start_cmd(update, context)
    elif text == "💰 Prices":
        await prices_cmd(update, context)
    elif text == "🛍 Sell":
        # start sell conversation by returning the entry; this must be routed to sell_conv entry point
        return await sell_entry(update, context)
    elif text == "💸 Withdraw":
        return await withdraw_entry(update, context)
    elif text == "💵 Balance":
        await balance_cmd(update, context)
    elif text == "🧑‍💻 Admin" and user.id == ADMIN_ID:
        # open admin panel conversation entry
        return await admin_panel_entry(update, context)
    else:
        await update.message.reply_text("⚠️ Unknown option. Use the keyboard buttons.")

# ========================
# Universal cancel (for conversation fallbacks)
# ========================
async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # clear any conversation flags in user_data
    context.user_data.pop('in_sell', None)
    context.user_data.pop('withdraw_method', None)
    context.user_data.pop('withdraw_address', None)
    context.user_data.pop('admin_action', None)
    context.user_data.pop('target_user', None)
    await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END

# ========================
# Application setup
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Sell ConversationHandler
    sell_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sell", sell_entry),
            MessageHandler(filters.Regex("^🛍 Sell$"), sell_entry)
        ],
        states={
            SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)],
        },
        fallbacks=[CommandHandler("cancel", sell_cancel)],
        conversation_timeout=600
    )

    # Withdraw ConversationHandler
    withdraw_conv = ConversationHandler(
        entry_points=[
            CommandHandler("withdraw", withdraw_entry),
            MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw_entry)
        ],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method, pattern="^method_")],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600
    )

    # Admin ConversationHandler (panel + sub-actions)
    admin_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧑‍💻 Admin$"), admin_panel_entry), CommandHandler("admin", admin_panel_entry)],
        states={
            ADMIN_PANEL: [CallbackQueryHandler(admin_panel_callback, pattern="^admin_")],
            ADMIN_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_handler)],
            ADMIN_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_amount_handler)],
            ADMIN_INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inspect_handler)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_handler)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
        allow_reentry=True
    )

    # Register handlers (order important - ConversationHandlers first)
    app.add_handler(sell_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(admin_conv)

    # Admin callbacks for approve/reject and withdraw confirm/dismiss
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(approve_group|reject_group|approve_withdraw|reject_withdraw):"))

    # Button router (only catches keyboard presses and plain text outside conversations)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))

    # Basic commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("price", prices_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("cancel", universal_cancel))

    print("🤖 Advanced Marketplace Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
