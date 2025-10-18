    # advanced_marketplace_bot.py
import json
import logging
import re
import datetime
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand,
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
# CONFIG - set these
# ========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282  # <-- your Telegram numeric id

DATA_PATH = Path("data.json")

PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$",
}

# ========================
# Logging
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# Persistence helpers
# ========================
def load_data():
    if not DATA_PATH.exists():
        return {
            "users": {},               # user_id -> {"balance": float, "groups": [links], "sales": int}
            "pending_groups": {},      # user_id -> {"link":..., "time":...}
            "pending_withdrawals": {}, # user_id -> {"method":..., "address":..., "amount":..., "time":...}
        }
    return json.loads(DATA_PATH.read_text(encoding="utf8"))

def save_data(data):
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf8")

data = load_data()

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {"balance": 0.0, "groups": [], "sales": 0, "withdraw_history": []}
        save_data(data)

# ========================
# Regex / utilities
# ========================
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/)[A-Za-z0-9_-]+$",
    flags=re.IGNORECASE,
)

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

# ========================
# Conversation states
# ========================
SELL_LINK = 1
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 13)
ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER, ADMIN_BROADCAST = range(20, 25)

# ========================
# Commands menu (Telegram suggestions)
# ========================
COMMANDS = [
    BotCommand("start", "Open bot"),
    BotCommand("price", "Show prices"),
    BotCommand("sell", "Sell group"),
    BotCommand("withdraw", "Request withdrawal"),
    BotCommand("cancel", "Cancel current action"),
    BotCommand("admin", "Open admin panel (admin only)"),
]

# ========================
# Reply keyboard generator
# ========================
def get_keyboard(is_admin=False):
    kb = [
        ["🏠 Start", "💰 Prices"],
        ["🛍 Sell", "💸 Withdraw"],
        ["💵 Balance"]
    ]
    if is_admin:
        kb.append(["🧑‍💻 Admin"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# Handlers
# ========================
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands(COMMANDS)
    uid = update.effective_user.id
    ensure_user(uid)
    await update.message.reply_text(
        "👋 Welcome to Group Marketplace Bot!\nUse the keyboard or commands to operate.",
        reply_markup=get_keyboard(uid == ADMIN_ID),
    )

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for k, v in PRICES.items():
        text += f"📅 {k}: {v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"💰 Your balance: ${bal:.2f}")

# ------------------------
# SELL flow (Conversation)
# ------------------------
sell_timeouts = {}  # user_id -> handle

async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    context.user_data["in_sell"] = True
    await update.message.reply_text(
        "📎 Send your *Telegram group invite link* (examples: https://t.me/joinchat/AAA or https://t.me/+ABC or https://t.me/yourgroup)\n\n"
        "Type /cancel to stop. (Auto-cancels after 10 minutes.)",
        parse_mode="Markdown"
    )
    # schedule timeout using context.job_queue would be nicer, but we can rely on conversation_timeout param.
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    # If user had canceled earlier, ensure not processing
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END

    if not INVITE_RE.match(text):
        await update.message.reply_text("❌ Invalid Telegram invite link. Send correct link or /cancel to stop.")
        return SELL_LINK

    # valid
    s_uid = str(uid)
    data["pending_groups"][s_uid] = {"link": text, "time": now()}
    data["users"].setdefault(s_uid, {"balance": 0.0, "groups": [], "sales": 0, "withdraw_history": []})
    data["users"][s_uid]["groups"].append(text)
    save_data(data)
    context.user_data.pop("in_sell", None)

    # notify admin with approve/reject
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{uid}"),
        ]
    ]
    await context.bot.send_message(
        ADMIN_ID,
        f"🆕 New group submission\nUser: @{update.effective_user.username or update.effective_user.first_name} (ID: {uid})\nLink: {text}\nTime: {now()}",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    await update.message.reply_text("✅ Link submitted to admin for review. You will be notified on approval/rejection.")
    return ConversationHandler.END

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # clear any flags in user_data to avoid ghost behavior
    context.user_data.pop("in_sell", None)
    context.user_data.pop("withdraw_method", None)
    context.user_data.pop("withdraw_address", None)
    context.user_data.pop("admin_mode", None)
    context.user_data.pop("target_user", None)
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

# ------------------------
# WITHDRAW flow (Conversation)
# ------------------------
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    # show last 5 withdraws
    hist = data["users"][str(uid)].get("withdraw_history", [])[-5:]
    if hist:
        lines = [f"{h['time']}: {h['amount']}$ via {h['method']} — {h['status']}" for h in hist]
        await update.message.reply_text("🧾 Your recent withdraws:\n" + "\n".join(lines))
    keyboard = [
        [InlineKeyboardButton("🏦 UPI", callback_data="method_upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="method_polygon")],
    ]
    await update.message.reply_text("Select withdraw method:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    method = q.data.replace("method_", "")
    context.user_data["withdraw_method"] = method
    await q.edit_message_text(f"📤 Selected: *{method.upper()}*\nSend your address / UPI ID / UID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = (update.message.text or "").strip()
    context.user_data["withdraw_address"] = addr
    await update.message.reply_text("💰 Now enter the amount to withdraw (numbers only):")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        amount = float((update.message.text or "").strip())
        if amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("❌ Invalid amount. Send numeric value.")
        return WITHDRAW_AMOUNT

    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    if amount > bal:
        await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal:.2f}")
        return ConversationHandler.END

    # store pending withdrawal
    data["pending_withdrawals"][str(uid)] = {
        "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"],
        "amount": amount,
        "time": now(),
    }
    # add to user withdraw history as Pending
    rec = {"method": context.user_data["withdraw_method"], "address": context.user_data["withdraw_address"], "amount": amount, "status": "Pending", "time": now()}
    data["users"][str(uid)]["withdraw_history"].append(rec)
    save_data(data)

    # notify admin with inline approve/dismiss
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}"),
        ]
    ]
    await context.bot.send_message(ADMIN_ID, f"💸 Withdrawal request\nUser: {uid}\n{amount}$ via {rec['method']}\nAddress: {rec['address']}\nTime: {rec['time']}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

# ------------------------
# ADMIN callbacks: groups & withdraws & panel actions
# ------------------------
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data_payload = q.data
    # group approvals
    if data_payload.startswith("approve_group:") or data_payload.startswith("reject_group:"):
        action, uid_s = data_payload.split(":")
        s_uid = str(uid_s)
        if s_uid not in data["pending_groups"]:
            await q.edit_message_text("⚠️ This submission was processed already or not found.")
            return
        info = data["pending_groups"].pop(s_uid)
        save_data(data)
        if action == "approve_group":
            # increment sales
            data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"withdraw_history":[]})
            data["users"][s_uid]["sales"] = data["users"][s_uid].get("sales", 0) + 1
            save_data(data)
            try:
                await context.bot.send_message(int(s_uid), f"✅ Your group {info['link']} has been approved by admin.")
            except:
                pass
            await q.edit_message_text("✅ Group approved.")
        else:
            try:
                await context.bot.send_message(int(s_uid), f"❌ Your group {info['link']} was rejected by admin.")
            except:
                pass
            await q.edit_message_text("❌ Group rejected.")
        return

    # withdraw approvals
    if data_payload.startswith("approve_withdraw:") or data_payload.startswith("reject_withdraw:"):
        action, uid_s = data_payload.split(":")
        s_uid = str(uid_s)
        if s_uid not in data["pending_withdrawals"]:
            await q.edit_message_text("⚠️ This withdrawal was processed or not found.")
            return
        wd = data["pending_withdrawals"].pop(s_uid)
        # update user's withdraw_history last pending -> approved/rejected
        hist = data["users"].get(s_uid, {}).get("withdraw_history", [])
        for rec in reversed(hist):
            if rec["status"] == "Pending" and rec["amount"] == wd["amount"] and rec["method"] == wd["method"]:
                rec["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break
        # if approved, deduct balance
        if action == "approve_withdraw":
            data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"withdraw_history":[]})
            data["users"][s_uid]["balance"] = max(0.0, data["users"][s_uid]["balance"] - float(wd["amount"]))
            try:
                await context.bot.send_message(int(s_uid), f"✅ Your withdrawal of ${wd['amount']} has been approved and processed.")
            except:
                pass
            await q.edit_message_text("✅ Withdrawal approved and processed.")
        else:
            try:
                await context.bot.send_message(int(s_uid), f"❌ Your withdrawal of ${wd['amount']} has been rejected.")
            except:
                pass
            await q.edit_message_text("❌ Withdrawal rejected.")
        save_data(data)
        return

    # admin-panel helper callbacks (prefix admin_)
    if data_payload.startswith("admin_"):
        # delegate to admin panel callback handler below by editing message text (button clicks)
        # we simply send a small acknowledgement so panel logic (ConversationHandler) handles the rest
        await q.edit_message_text(f"Selected: {data_payload}")
        return

# ------------------------
# Admin panel (Conversation)
# ------------------------
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # can be triggered via /admin command or "🧑‍💻 Admin" keyboard button
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
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
    ]
    await update.message.reply_text("🧑‍💻 *Admin Panel* — choose action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_PANEL

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.edit_message_text("❌ Only admin.")
        return ADMIN_PANEL
    key = q.data

    # Pending groups
    if key == "admin_pending_groups":
        if not data["pending_groups"]:
            await q.edit_message_text("📭 No pending groups.")
            return ADMIN_PANEL
        for s_uid, info in list(data["pending_groups"].items()):
            kb = [
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{s_uid}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{s_uid}")],
            ]
            await context.bot.send_message(ADMIN_ID, f"👤 {s_uid} ➝ {info['link']}\nSubmitted: {info['time']}", reply_markup=InlineKeyboardMarkup(kb))
        await q.edit_message_text("📋 Pending groups shown above.")
        return ADMIN_PANEL

    # Pending withdrawals
    if key == "admin_pending_withdrawals":
        if not data["pending_withdrawals"]:
            await q.edit_message_text("📭 No pending withdrawals.")
            return ADMIN_PANEL
        for s_uid, w in list(data["pending_withdrawals"].items()):
            kb = [
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{s_uid}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{s_uid}")],
            ]
            await context.bot.send_message(ADMIN_ID, f"👤 {s_uid} ➝ {w['amount']}$ via {w['method']} ({w['address']})", reply_markup=InlineKeyboardMarkup(kb))
        await q.edit_message_text("💸 Pending withdrawals shown above.")
        return ADMIN_PANEL

    # Add balance (start flow)
    if key == "admin_add_balance":
        context.user_data["admin_mode"] = "add_balance"
        await q.edit_message_text("➕ Send user ID to add balance to:")
        return ADMIN_ADD_USER

    # Inspect user
    if key == "admin_inspect_user":
        context.user_data["admin_mode"] = "inspect_user"
        await q.edit_message_text("🔍 Send user ID to inspect:")
        return ADMIN_INSPECT_USER

    # Toggle Sell
    if key == "admin_toggle_sell":
        global SELL_ENABLED
        SELL_ENABLED = not SELL_ENABLED
        await q.edit_message_text(f"⚙️ Selling is now {'ENABLED' if SELL_ENABLED else 'DISABLED'}.")
        return ADMIN_PANEL

    # Broadcast
    if key == "admin_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await q.edit_message_text("📢 Send broadcast text to send to all users:")
        return ADMIN_BROADCAST

    await q.edit_message_text("⚠️ Unknown admin action.")
    return ADMIN_PANEL

async def admin_add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid user ID. Send numeric ID.")
        return ADMIN_ADD_USER
    context.user_data["target_user"] = uid
    await update.message.reply_text(f"Send amount to add to user {uid}:")
    return ADMIN_ADD_AMOUNT

async def admin_add_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        amt = float(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid amount.")
        return ADMIN_ADD_AMOUNT
    uid = context.user_data.pop("target_user", None)
    if uid is None:
        await update.message.reply_text("❌ No target user set. Start again.")
        return ConversationHandler.END
    ensure_user(uid)
    data["users"][str(uid)]["balance"] = data["users"][str(uid)].get("balance", 0.0) + amt
    save_data(data)
    await update.message.reply_text(f"✅ Added ${amt:.2f} to {uid}. New balance: ${data['users'][str(uid)]['balance']:.2f}")
    try:
        await context.bot.send_message(uid, f"💵 Admin added ${amt:.2f} to your balance. New balance: ${data['users'][str(uid)]['balance']:.2f}")
    except:
        pass
    return ADMIN_PANEL

async def admin_inspect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return ADMIN_INSPECT_USER
    ensure_user(uid)
    u = data["users"][str(uid)]
    pending_g = data["pending_groups"].get(str(uid))
    pending_w = data["pending_withdrawals"].get(str(uid))
    text = (
        f"🔎 User: {uid}\n"
        f"💰 Balance: ${u['balance']:.2f}\n"
        f"🛒 Total groups submitted: {len(u.get('groups',[]))}\n"
        f"✅ Sales (approved): {u.get('sales',0)}\n"
        f"⏳ Pending group: {pending_g['link'] if pending_g else 'None'}\n"
        f"⏳ Pending withdraw: {pending_w['amount'] if pending_w else 'None'}\n"
        f"📝 Withdraw history (last 5):\n"
    )
    for rec in u.get("withdraw_history", [])[-5:]:
        text += f"- {rec['time']}: {rec['amount']}$ via {rec['method']} — {rec['status']}\n"
    await update.message.reply_text(text)
    return ADMIN_PANEL

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text
    count = 0
    for s_uid in list(data["users"].keys()):
        try:
            context.bot.send_message(int(s_uid), f"📢 Broadcast from admin:\n\n{text}")
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")
    return ADMIN_PANEL

# ------------------------
# Router for reply-keyboard (only when not in a conversation)
# ------------------------
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id
    ensure_user(uid)
    # If user is inside a conversation, this handler won't get the message (ConversationHandler takes precedence).
    if txt == "🏠 Start":
        await on_start(update, context)
    elif txt == "💰 Prices":
        await cmd_price(update, context)
    elif txt == "🛍 Sell":
        # start sell conversation - return as entry
        return await cmd_sell_entry(update, context)
    elif txt == "💸 Withdraw":
        return await cmd_withdraw_entry(update, context)
    elif txt == "💵 Balance":
        await cmd_balance(update, context)
    elif txt == "🧑‍💻 Admin" and uid == ADMIN_ID:
        return await admin_panel_entry(update, context)
    else:
        await update.message.reply_text("⚠️ Unknown option or use buttons/commands.")

# ========================
# App setup
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ConversationHandlers must be added before generic text handler so they get priority
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry), MessageHandler(filters.Regex("^🛍 Sell$"), cmd_sell_entry)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)]},
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", cmd_withdraw_entry), MessageHandler(filters.Regex("^💸 Withdraw$"), cmd_withdraw_entry)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method, pattern="^method_")],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel_entry), MessageHandler(filters.Regex("^🧑‍💻 Admin$"), admin_panel_entry)],
        states={
            ADMIN_PANEL: [CallbackQueryHandler(admin_panel_callback, pattern="^admin_")],
            ADMIN_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_handler)],
            ADMIN_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_amount_handler)],
            ADMIN_INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inspect_handler)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_handler)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
        allow_reentry=True,
    )

    app.add_handler(sell_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(admin_conv)

    # Callbacks: approve/reject
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(approve_group|reject_group|approve_withdraw|reject_withdraw):"))
    # Admin panel buttons (these are admin_ prefixed callbacks)
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))

    # Generic router for keyboard buttons (fires only when user is not inside a conversation)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))

    # Basic commands
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("cancel", universal_cancel))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
