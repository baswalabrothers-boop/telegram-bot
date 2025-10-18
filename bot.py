# bot_advanced_with_validation.py
import logging
import re
import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

# ========================
# CONFIG - replace these
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282

# Prices (your provided values)
PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# ========================
# In-memory storage (swap with DB for production)
# ========================
user_balances = {}             # {user_id: float}
pending_groups = {}            # {user_id: {"link": str, "username":str, "submitted_at":str}}
approved_groups_count = {}     # {user_id: int}
submitted_groups_count = {}    # {user_id: int}
pending_withdrawals = {}       # {user_id: {"method":..., "address":..., "amount":...}}
withdraw_history = {}          # {user_id: [ {method, address, amount, status, timestamp}, ... ]}
all_users = set()
SELL_ENABLED = True            # toggle selling globally

# ========================
# Keyboards
# ========================
def get_main_keyboard(user_id):
    kb = [
        ["🏠 Start", "💰 Prices"],
        ["🛍 Sell", "💸 Withdraw"],
        ["💵 My Balance"]
    ]
    if user_id == ADMIN_ID:
        kb.append(["🧑‍💻 Admin Panel"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# States
# ========================
SELL_LINK = 1
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 13)
ADMIN_INSPECT_USER = 50
ADMIN_ADD_BALANCE_USER, ADMIN_ADD_BALANCE_AMOUNT = 51, 52

# ========================
# Logging
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# Helpers
# ========================
def is_valid_telegram_invite(link: str) -> bool:
    """
    Accepts common Telegram invite link formats:
    - https?://t.me/joinchat/<hash>
    - https?://t.me/+<hash>
    - https?://t.me/<group_name>
    - t.me/...
    - invite links like telegram.me/...
    """
    if not link or not isinstance(link, str):
        return False
    link = link.strip()
    # Basic patterns
    patterns = [
        r'^(https?://)?t\.me/joinchat/[A-Za-z0-9_-]+$',
        r'^(https?://)?t\.me/\+[A-Za-z0-9_-]+$',
        r'^(https?://)?t\.me/[A-Za-z0-9_]+$',
        r'^(https?://)?telegram\.me/joinchat/[A-Za-z0-9_-]+$',
        r'^(https?://)?telegram\.me/\+[A-Za-z0-9_-]+$',
        r'^(https?://)?telegram\.me/[A-Za-z0-9_]+$',
    ]
    for p in patterns:
        if re.match(p, link, flags=re.IGNORECASE):
            return True
    return False

def now_ts():
    return datetime.datetime.utcnow().isoformat() + "Z"

def ensure_user_stats(user_id):
    submitted_groups_count.setdefault(user_id, 0)
    approved_groups_count.setdefault(user_id, 0)
    withdraw_history.setdefault(user_id, [])

def add_withdraw_record(user_id, method, address, amount, status):
    rec = {"method": method, "address": address, "amount": float(amount), "status": status, "timestamp": now_ts()}
    withdraw_history.setdefault(user_id, []).append(rec)
    return rec

# ========================
# /start
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    all_users.add(user.id)
    kb = get_main_keyboard(user.id)
    await update.message.reply_text(
        "👋 Welcome to the Group Marketplace Bot!\nUse the buttons below to navigate.",
        reply_markup=kb
    )

# ========================
# Price
# ========================
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for y, p in PRICES.items():
        text += f"📅 {y}: {p}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================
# SELL flow with validation
# ========================
async def sell_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SELL_ENABLED:
        await update.message.reply_text("⚠️ Selling is currently *disabled* by admin. Try later.", parse_mode="Markdown")
        return ConversationHandler.END
    await update.message.reply_text("📎 Please send your *group invite link* for review (e.g. https://t.me/joinchat/xxxxx or https://t.me/+xxxxx or https://t.me/yourgroup):", parse_mode="Markdown")
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    if not is_valid_telegram_invite(text):
        # Invalid -> keep the conversation open and prompt again
        await update.message.reply_text(
            "❌ Invalid link. Please send a valid Telegram invite or group link.\nExamples:\n• https://t.me/joinchat/AAAAA\n• https://t.me/+AbCdEfGh\n• https://t.me/yourgroup\n\nSend a valid link or /cancel to stop."
        )
        return SELL_LINK

    # valid -> save
    pending_groups[user.id] = {"link": text, "username": user.username, "submitted_at": now_ts()}
    submitted_groups_count[user.id] = submitted_groups_count.get(user.id, 0) + 1
    ensure_user_stats(user.id)

    await update.message.reply_text("✅ Your group link has been submitted for admin review.")

    # notify admin with approve/reject buttons
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{user.id}")
        ]
    ]
    msg = (f"🆕 *New Group Submission*\n👤 @{user.username or user.first_name}\n"
           f"🆔 {user.id}\n🔗 {text}\n🕒 {pending_groups[user.id]['submitted_at']}")
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

# ========================
# Admin approves/rejects group
# ========================
async def admin_handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, uid_str = query.data.split(":")
        uid = int(uid_str)
    except Exception:
        await query.edit_message_text("❌ Invalid callback data.")
        return

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can perform this action.")
        return

    info = pending_groups.pop(uid, None)
    if not info:
        await query.edit_message_text("⚠️ This submission was already processed or doesn't exist.")
        return

    if action == "approve_group":
        # increment approved count
        approved_groups_count[uid] = approved_groups_count.get(uid, 0) + 1
        ensure_user_stats(uid)
        # notify user
        await context.bot.send_message(uid, f"✅ Your group link `{info['link']}` has been *approved* by admin. You will receive balance soon.", parse_mode="Markdown")
        await query.edit_message_text(f"✅ Approved group for user {uid}")
    else:
        await context.bot.send_message(uid, f"❌ Your group link `{info['link']}` was *rejected* by admin.", parse_mode="Markdown")
        await query.edit_message_text(f"❌ Rejected group for user {uid}")

# ========================
# Withdraw full process + history
# ========================
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # show last few history entries
    hist = withdraw_history.get(user.id, [])
    if hist:
        last = hist[-10:]
        lines = [f"{h['timestamp']}: {h['amount']}$ via {h['method']} — {h['status']}" for h in last]
        await update.message.reply_text("🧾 Your recent withdraw history:\n" + "\n".join(lines))
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="method_upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="method_polygon")]
    ]
    await update.message.reply_text("💸 Select withdraw method:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("method_", "")
    context.user_data["withdraw_method"] = method
    await query.edit_message_text(f"📤 Selected: *{method.upper()}*.\nPlease enter your address / UPI ID / UID:", parse_mode="Markdown")
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
    try:
        amount = float(amount_text)
        if amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("⚠️ Invalid amount. Send a valid numeric amount.")
        return WITHDRAW_AMOUNT

    bal = user_balances.get(user.id, 0.0)
    if amount > bal:
        await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal}")
        return ConversationHandler.END

    pending_withdrawals[user.id] = {"method": method, "address": address, "amount": amount, "timestamp": now_ts()}
    add_withdraw_record(user.id, method, address, amount, "pending")

    # send to admin with Approve/Dismiss buttons
    kb = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{user.id}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{user.id}")]
    ]
    msg = (f"💸 *New Withdrawal Request*\n👤 @{user.username or user.first_name}\n"
           f"🆔 {user.id}\n💳 {method}\n🏦 {address}\n💰 {amount}\n🕒 {pending_withdrawals[user.id]['timestamp']}")
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    await update.message.reply_text("✅ Your withdrawal request has been sent to admin for approval.")
    return ConversationHandler.END

async def admin_handle_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, uid_str = query.data.split(":")
        uid = int(uid_str)
    except Exception:
        await query.edit_message_text("❌ Invalid data.")
        return

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can do this.")
        return

    info = pending_withdrawals.pop(uid, None)
    if not info:
        await query.edit_message_text("⚠️ This withdrawal no longer exists.")
        return

    # update withdraw_history last matching record status
    hist = withdraw_history.get(uid, [])
    for rec in reversed(hist):
        if rec["status"] == "pending" and rec["amount"] == float(info["amount"]) and rec["method"] == info["method"]:
            rec["status"] = "approved" if action == "approve_withdraw" else "rejected"
            break

    if action == "approve_withdraw":
        # deduct balance
        user_balances[uid] = max(user_balances.get(uid, 0.0) - float(info["amount"]), 0.0)
        await context.bot.send_message(uid, f"✅ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* has been *approved* and processed.", parse_mode="Markdown")
        await query.edit_message_text("✅ Withdrawal approved and processed.")
    else:
        await context.bot.send_message(uid, f"❌ Your withdrawal of ${info['amount']} via *{info['method'].upper()}* has been *rejected*.", parse_mode="Markdown")
        await query.edit_message_text("❌ Withdrawal rejected.")

# ========================
# Admin Panel advanced features
# ========================
async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    kb = [
        [InlineKeyboardButton("👥 Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_pending_withdrawals")],
        [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("🔍 Inspect User", callback_data="admin_inspect_user")],
        [InlineKeyboardButton("📊 View Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("🪙 Toggle Sell On/Off", callback_data="admin_toggle_sell")]
    ]
    await update.message.reply_text("🧑‍💻 *Admin Panel* — choose an action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Only admin can use this.")
        return

    data = query.data
    if data == "admin_pending_groups":
        if not pending_groups:
            await query.edit_message_text("📭 No pending groups.")
            return
        # send a message per pending group with approve/reject inline buttons
        for uid, info in list(pending_groups.items()):
            kb = [
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}")]
            ]
            await context.bot.send_message(chat_id=ADMIN_ID,
                                           text=f"👤 {uid} ➝ {info['link']}\nSubmitted: {info.get('submitted_at')}",
                                           reply_markup=InlineKeyboardMarkup(kb))
        await query.edit_message_text("📋 Pending groups sent above.")
    elif data == "admin_pending_withdrawals":
        if not pending_withdrawals:
            await query.edit_message_text("📭 No pending withdrawals.")
            return
        for uid, info in list(pending_withdrawals.items()):
            kb = [
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}")]
            ]
            await context.bot.send_message(chat_id=ADMIN_ID,
                                           text=f"👤 {uid} ➝ {info['amount']}$ via {info['method']} ({info['address']})",
                                           reply_markup=InlineKeyboardMarkup(kb))
        await query.edit_message_text("💸 Pending withdrawals sent above.")
    elif data == "admin_add_balance":
        context.user_data["admin_action"] = "add_balance"
        await query.edit_message_text("➕ Send the *User ID* to add balance to:")
        return ADMIN_ADD_BALANCE_USER
    elif data == "admin_inspect_user":
        context.user_data["admin_action"] = "inspect_user"
        await query.edit_message_text("🔍 Send the *User ID* to inspect:")
        return ADMIN_INSPECT_USER
    elif data == "admin_stats":
        total_users = len(all_users)
        total_balance = sum(user_balances.values())
        await query.edit_message_text(f"📊 Total users: {total_users}\n💰 Total balance: ${total_balance}")
    elif data == "admin_toggle_sell":
        global SELL_ENABLED
        SELL_ENABLED = not SELL_ENABLED
        await query.edit_message_text(f"⚙️ Selling is now {'ENABLED' if SELL_ENABLED else 'DISABLED'}.")

async def admin_add_balance_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # expecting user id
    try:
        uid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("⚠️ Invalid user id. Send a numeric user id.")
        return ADMIN_ADD_BALANCE_USER
    context.user_data["target_user"] = uid
    await update.message.reply_text(f"Send amount to add to user {uid}:")
    return ADMIN_ADD_BALANCE_AMOUNT

async def admin_add_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("⚠️ Invalid amount. Send numeric value.")
        return ADMIN_ADD_BALANCE_AMOUNT
    uid = context.user_data.get("target_user")
    user_balances[uid] = user_balances.get(uid, 0.0) + amt
    await update.message.reply_text(f"✅ Added ${amt} to user {uid}. New balance: ${user_balances[uid]}")
    await context.bot.send_message(uid, f"💵 Your balance has been updated: +${amt}. New balance: ${user_balances[uid]}")
    # clear
    context.user_data.pop("target_user", None)
    return ConversationHandler.END

async def admin_inspect_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("⚠️ Invalid user id. Send a numeric user id.")
        return ADMIN_INSPECT_USER

    ensure_user_stats(uid)
    bal = user_balances.get(uid, 0.0)
    submitted = submitted_groups_count.get(uid, 0)
    approved = approved_groups_count.get(uid, 0)
    w_history = withdraw_history.get(uid, [])
    pending_w = pending_withdrawals.get(uid)
    pending_g = pending_groups.get(uid)
    text = (
        f"🔎 *User inspection*: {uid}\n"
        f"💰 Balance: ${bal}\n"
        f"📤 Submitted groups: {submitted}\n"
        f"✅ Approved groups: {approved}\n"
        f"📥 Pending group: {pending_g['link'] if pending_g else 'None'}\n"
        f"🕒 Withdrawals count: {len(w_history)}\n"
        f"⏳ Pending withdrawal: {pending_w['amount'] if pending_w else 'None'}\n\n"
        "📝 Recent withdrawal history:\n"
    )
    for rec in (w_history[-10:]):
        text += f"- {rec['timestamp']}: {rec['amount']}$ via {rec['method']} — {rec['status']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")
    return ConversationHandler.END

# ========================
# Handle the bottom keyboard actions and admin text flows
# ========================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    all_users.add(user.id)

    # If admin is in an add_balance/inspect flow, let ConversationHandlers handle those states.
    admin_action = context.user_data.get("admin_action")
    if admin_action == "add_balance" and user.id == ADMIN_ID:
        # This message will be processed by the admin_add_balance_user ConversationHandler
        return

    if text == "🏠 Start":
        await start(update, context)
    elif text == "💰 Prices":
        await price(update, context)
    elif text == "🛍 Sell":
        # enter sell conversation
        return await sell_start(update, context)
    elif text == "💸 Withdraw":
        return await withdraw_start(update, context)
    elif text == "💵 My Balance":
        await update.message.reply_text(f"💰 Your balance: ${user_balances.get(user.id, 0.0)}")
    elif text == "🧑‍💻 Admin Panel" and user.id == ADMIN_ID:
        await open_admin_panel(update, context)
    else:
        # if it's not a keyboard action and admin waiting for inspect/add flows, handle there
        # Admin-inspect and add-balance are handled through ConversationHandlers below
        await update.message.reply_text("⚠️ Unknown button or text. Use the menu buttons.")

# ========================
# App setup
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    # sell conversation
    sell_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛍 Sell$"), sell_start)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)]},
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(sell_conv)
    app.add_handler(CallbackQueryHandler(admin_handle_group_callback, pattern="^(approve_group|reject_group):"))

    # withdraw conversation
    withdraw_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw_start)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method)],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(admin_handle_withdraw_callback, pattern="^(approve_withdraw|reject_withdraw):"))

    # Admin-panel conversation & callbacks
    app.add_handler(MessageHandler(filters.Regex("^🧑‍💻 Admin Panel$"), open_admin_panel))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    # admin add-balance conversation (entry point triggered inside admin panel)
    admin_balance_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel_callback, pattern="^admin_add_balance$")],
        states={
            ADMIN_ADD_BALANCE_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_user)],
            ADMIN_ADD_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_amount)]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    app.add_handler(admin_balance_conv)

    # admin inspect user conv
    admin_inspect_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel_callback, pattern="^admin_inspect_user$")],
        states={
            ADMIN_INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inspect_user_handler)]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    app.add_handler(admin_inspect_conv)

    # handle button presses & general text for keyboard
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    print("🤖 Bot running with validation and advanced admin panel...")
    app.run_polling()

if __name__ == "__main__":
    main()
