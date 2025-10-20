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
BOT_TOKEN = "8075394934:AAHU9tRE9vemQIDzxRuX4UhxMUtw5mSlMy4"
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
            "users": {},               # user_id -> {"balance": float, "groups": [links], "sales": int, "custom_prices": {}}
            "pending_groups": {},      # user_id -> {"link":..., "time":..., ...}
            "pending_withdrawals": {}, # user_id -> {"method":..., "address":..., "amount":..., "time":...}
        }
    return json.loads(DATA_PATH.read_text(encoding="utf8"))

def save_data(data_obj):
    DATA_PATH.write_text(json.dumps(data_obj, indent=2, ensure_ascii=False), encoding="utf8")

data = load_data()

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {
            "balance": 0.0,
            "groups": [],
            "sales": 0,
            "withdraw_history": [],
            "custom_prices": {}   # <-- added storage for per-user custom prices
        }
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
        ["ðŸ  Start", "ðŸ’° Prices"],
        ["ðŸ› Sell", "ðŸ’¸ Withdraw"],
        ["ðŸ’µ Balance"]
    ]
    if is_admin:
        kb.append(["ðŸ§‘â€ðŸ’» Admin"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# Handlers
# ========================
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands(COMMANDS)
    uid = update.effective_user.id
    ensure_user(uid)
    await update.message.reply_text(
        "ðŸ‘‹ Welcome to Group Marketplace Bot!\nUse the keyboard or commands to operate.",
        reply_markup=get_keyboard(uid == ADMIN_ID),
    )

# Price command: show per-user custom prices first (if any), then global
async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    text = "ðŸ“Š *Current Group Prices*\n\n"
    user_custom = data["users"][str(uid)].get("custom_prices", {})

    if user_custom:
        text += "âœ¨ *Your Custom Prices:*\n"
        for k, v in user_custom.items():
            text += f"ðŸ“… {k}: {v}\n"
        text += "\n"

    text += "ðŸŒ *Standard Prices:*\n"
    for k, v in PRICES.items():
        text += f"ðŸ“… {k}: {v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"ðŸ’° Your balance: ${bal:.2f}")

# ------------------------
# SELL flow (Conversation)
# ------------------------
sell_timeouts = {}  # user_id -> handle

async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    context.user_data["in_sell"] = True
    await update.message.reply_text(
        "ðŸ“Ž Send your *Telegram group invite link* (examples: https://t.me/joinchat/AAA or https://t.me/+ABC or https://t.me/yourgroup)\n\n"
        "Type /cancel to stop. (Auto-cancels after 10 minutes.)",
        parse_mode="Markdown"
    )
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END

    if not INVITE_RE.match(text):
        await update.message.reply_text("âŒ Invalid Telegram invite link. Send correct link or /cancel to stop.")
        return SELL_LINK

    s_uid = str(uid)
    # store pending group with ownership tracking fields
    data["pending_groups"][s_uid] = {
        "link": text,
        "time": now(),
        "seller_id": s_uid,
        "ownership_status": "none",        # none | requested | transferred | verified | failed
        "ownership_target_id": None,
        "status": "pending"               # used for admin workflow state
    }
    data["users"].setdefault(s_uid, {"balance": 0.0, "groups": [], "sales": 0, "withdraw_history": [], "custom_prices": {}})
    data["users"][s_uid]["groups"].append(text)
    save_data(data)
    context.user_data.pop("in_sell", None)

    kb = [
        [
            InlineKeyboardButton("âœ… Approve", callback_data=f"approve_group:{s_uid}"),
            InlineKeyboardButton("âŒ Reject", callback_data=f"reject_group:{s_uid}"),
        ]
    ]
    await context.bot.send_message(
        ADMIN_ID,
        f"ðŸ†• New group submission\nUser: @{update.effective_user.username or update.effective_user.first_name} (ID: {uid})\nLink: {text}\nTime: {now()}",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    await update.message.reply_text("âœ… Link submitted to admin for review. You will be notified on approval/rejection.")
    return ConversationHandler.END

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("in_sell", None)
    context.user_data.pop("withdraw_method", None)
    context.user_data.pop("withdraw_address", None)
    context.user_data.pop("admin_mode", None)
    context.user_data.pop("target_user", None)
    context.user_data.pop("awaiting_ownership_id", None)
    await update.message.reply_text("âŒ Operation cancelled.")
    return ConversationHandler.END

# ------------------------
# WITHDRAW flow (Conversation)
# ------------------------
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    hist = data["users"][str(uid)].get("withdraw_history", [])[-5:]
    if hist:
        lines = [f"{h['time']}: {h['amount']}$ via {h['method']} â€” {h['status']}" for h in hist]
        await update.message.reply_text("ðŸ§¾ Your recent withdraws:\n" + "\n".join(lines))
    keyboard = [
        [InlineKeyboardButton("ðŸ¦ UPI", callback_data="method_upi")],
        [InlineKeyboardButton("ðŸ¦ Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("ðŸ’µ BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("ðŸ’° Polygon USDT", callback_data="method_polygon")],
    ]
    await update.message.reply_text("Select withdraw method:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    method = q.data.replace("method_", "")
    context.user_data["withdraw_method"] = method
    await q.edit_message_text(f"ðŸ“¤ Selected: *{method.upper()}*\nSend your address / UPI ID / UID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = (update.message.text or "").strip()
    context.user_data["withdraw_address"] = addr
    await update.message.reply_text("ðŸ’° Now enter the amount to withdraw (numbers only):")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        amount = float((update.message.text or "").strip())
        if amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("âŒ Invalid amount. Send numeric value.")
        return WITHDRAW_AMOUNT

    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    if amount > bal:
        await update.message.reply_text(f"âš ï¸ Insufficient balance. Your balance: ${bal:.2f}")
        return ConversationHandler.END

    data["pending_withdrawals"][str(uid)] = {
        "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"],
        "amount": amount,
        "time": now(),
    }
    rec = {"method": context.user_data["withdraw_method"], "address": context.user_data["withdraw_address"], "amount": amount, "status": "Pending", "time": now()}
    data["users"][str(uid)]["withdraw_history"].append(rec)
    save_data(data)

    kb = [
        [
            InlineKeyboardButton("âœ… Approve", callback_data=f"approve_withdraw:{uid}"),
            InlineKeyboardButton("âŒ Reject", callback_data=f"reject_withdraw:{uid}"),
        ]
    ]
    await context.bot.send_message(ADMIN_ID, f"ðŸ’¸ Withdrawal request\nUser: {uid}\n{amount}$ via {rec['method']}\nAddress: {rec['address']}\nTime: {rec['time']}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("âœ… Withdrawal request sent to admin.")
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
            await q.edit_message_text("âš ï¸ This submission was processed already or not found.")
            return
        info = data["pending_groups"][s_uid]

        # If admin rejects immediately
        if action == "reject_group":
            try:
                await context.bot.send_message(int(s_uid), f"âŒ Your group {info['link']} was rejected by admin.")
            except:
                pass
            data["pending_groups"].pop(s_uid, None)
            save_data(data)
            await q.edit_message_text("âŒ Group rejected.")
            return

        # action == approve_group:
        info["status"] = "approved_waiting_target"
        info["seller_id"] = info.get("seller_id", s_uid)
        info["ownership_status"] = info.get("ownership_status", "none")
        info["ownership_target_id"] = info.get("ownership_target_id", None)
        save_data(data)

        await q.edit_message_text("âœ… Group approved. Please send the Telegram @username or numeric ID of the buyer to which the seller should transfer ownership.")
        context.user_data["awaiting_ownership_id"] = {"seller_id": s_uid}
        try:
            await context.bot.send_message(int(s_uid), f"âœ… Your group {info['link']} was approved by admin. Admin will send buyer ID for transfer shortly.")
        except:
            pass
        return

    # withdraw approvals
    if data_payload.startswith("approve_withdraw:") or data_payload.startswith("reject_withdraw:"):
        action, uid_s = data_payload.split(":")
        s_uid = str(uid_s)
        if s_uid not in data["pending_withdrawals"]:
            await q.edit_message_text("âš ï¸ This withdrawal was processed or not found.")
            return
        wd = data["pending_withdrawals"].pop(s_uid)
        hist = data["users"].get(s_uid, {}).get("withdraw_history", [])
        for rec in reversed(hist):
            if rec["status"] == "Pending" and rec["amount"] == wd["amount"] and rec["method"] == wd["method"]:
                rec["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break
        if action == "approve_withdraw":
            data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"withdraw_history":[],"custom_prices":{}})
            data["users"][s_uid]["balance"] = max(0.0, data["users"][s_uid]["balance"] - float(wd["amount"]))
            try:
                await context.bot.send_message(int(s_uid), f"âœ… Your withdrawal of ${wd['amount']} has been approved and processed.")
            except:
                pass
            await q.edit_message_text("âœ… Withdrawal approved and processed.")
        else:
            try:
                await context.bot.send_message(int(s_uid), f"âŒ Your withdrawal of ${wd['amount']} has been rejected.")
            except:
                pass
            await q.edit_message_text("âŒ Withdrawal rejected.")
        save_data(data)
        return

    # admin-panel helper callbacks (prefix admin_)
    if data_payload.startswith("admin_"):
        await q.edit_message_text(f"Selected: {data_payload}")
        return

    # ownership verification callbacks (admin verifying)
    if data_payload.startswith("verify_ownership:") or data_payload.startswith("reject_ownership:"):
        action, s_uid = data_payload.split(":")
        s_uid = str(s_uid)
        if s_uid not in data["pending_groups"]:
            await q.edit_message_text("âš ï¸ This ownership record was processed or not found.")
            return
        info = data["pending_groups"].pop(s_uid)
        if action == "verify_ownership":
            data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"withdraw_history":[],"custom_prices":{}})
            data["users"][s_uid]["sales"] = data["users"][s_uid].get("sales", 0) + 1
            info["ownership_status"] = "verified"
            # Add credit to seller balance (determine price â€” first check custom prices then global if needed)
            # NOTE: There's no year parsing in the provided code; if you want auto-credit based on year you must provide group-year logic.
            save_data(data)
            try:
                await context.bot.send_message(int(s_uid), f"âœ… Your group {info['link']} ownership has been VERIFIED by admin. Sale completed.")
            except:
                pass
            await q.edit_message_text("âœ… Ownership verified and sale completed.")
        else:
            info["ownership_status"] = "failed"
            data["pending_groups"][s_uid] = info
            save_data(data)
            try:
                await context.bot.send_message(int(s_uid), f"âŒ Ownership verification FAILED for {info['link']}. Please re-transfer and press the Ownership Submitted button again.")
            except:
                pass
            await q.edit_message_text("âŒ Ownership verification marked as failed and seller notified.")
        return

    # seller pressed ownership-submitted button (pattern: submit_ownership:{seller_uid})
    if data_payload.startswith("submit_ownership:"):
        action, s_uid = data_payload.split(":")
        s_uid = str(s_uid)
        if s_uid not in data["pending_groups"]:
            await q.edit_message_text("âš ï¸ This submission was processed already or not found.")
            return
        info = data["pending_groups"][s_uid]
        if str(q.from_user.id) != str(s_uid):
            await q.answer("âŒ Only the seller can press this.")
            return
        info["ownership_status"] = "transferred"
        save_data(data)
        kb = [
            [
                InlineKeyboardButton("âœ… Ownership Verified", callback_data=f"verify_ownership:{s_uid}"),
                InlineKeyboardButton("âŒ Ownership Failed", callback_data=f"reject_ownership:{s_uid}"),
            ]
        ]
        try:
            await context.bot.send_message(ADMIN_ID, f"ðŸ‘¤ Seller submitted ownership transfer for {info['link']}\nTarget: {info.get('ownership_target_id')}\nPlease verify.", reply_markup=InlineKeyboardMarkup(kb))
        except:
            pass
        await q.edit_message_text("âœ… Ownership submitted. Admin will verify shortly.")
        return

# ------------------------
# Admin panel (Conversation)
# ------------------------
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("âŒ You are not authorized.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton("ðŸ‘¥ Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("ðŸ’¸ Pending Withdrawals", callback_data="admin_pending_withdrawals")],
        [InlineKeyboardButton("âž• Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("ðŸ’° Custom", callback_data="admin_custom")],  # <-- New "Custom" menu
        [InlineKeyboardButton("ðŸ” Inspect User", callback_data="admin_inspect_user")],
        [InlineKeyboardButton("ðŸª™ Toggle Sell On/Off", callback_data="admin_toggle_sell")],
        [InlineKeyboardButton("ðŸ“¢ Broadcast", callback_data="admin_broadcast")],
    ]
    await update.message.reply_text("ðŸ§‘â€ðŸ’» *Admin Panel* â€” choose action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_PANEL

# extended admin panel callback to open custom price submenu
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.edit_message_text("âŒ Only admin.")
        return ADMIN_PANEL
    key = q.data

    if key == "admin_custom":
        kb = [
            [InlineKeyboardButton("âž• Set Price for User", callback_data="admin_custom_set")],
            [InlineKeyboardButton("ðŸ§¼ Remove Price for User", callback_data="admin_custom_remove")],
            [InlineKeyboardButton("ðŸ•µï¸ View Price for User", callback_data="admin_custom_view")],
        ]
        await q.edit_message_text("ðŸ’° Custom Price â€” choose:", reply_markup=InlineKeyboardMarkup(kb))
        return ADMIN_PANEL

    # handle pending groups
    if key == "admin_pending_groups":
        if not data["pending_groups"]:
            await q.edit_message_text("ðŸ“­ No pending groups.")
            return ADMIN_PANEL
        for s_uid, info in list(data["pending_groups"].items()):
            kb = [
                [InlineKeyboardButton("âœ… Approve", callback_data=f"approve_group:{s_uid}"),
                 InlineKeyboardButton("âŒ Reject", callback_data=f"reject_group:{s_uid}")],
            ]
            await context.bot.send_message(ADMIN_ID, f"ðŸ‘¤ {s_uid} âž {info['link']}\nSubmitted: {info['time']}", reply_markup=InlineKeyboardMarkup(kb))
        await q.edit_message_text("ðŸ“‹ Pending groups shown above.")
        return ADMIN_PANEL

    # handle pending withdrawals
    if key == "admin_pending_withdrawals":
        if not data["pending_withdrawals"]:
            await q.edit_message_text("ðŸ“­ No pending withdrawals.")
            return ADMIN_PANEL
        for s_uid, w in list(data["pending_withdrawals"].items()):
            kb = [
                [InlineKeyboardButton("âœ… Approve", callback_data=f"approve_withdraw:{s_uid}"),
                 InlineKeyboardButton("âŒ Reject", callback_data=f"reject_withdraw:{s_uid}")],
            ]
            await context.bot.send_message(ADMIN_ID, f"ðŸ‘¤ {s_uid} âž {w['amount']}$ via {w['method']} ({w['address']})", reply_markup=InlineKeyboardMarkup(kb))
        await q.edit_message_text("ðŸ’¸ Pending withdrawals shown above.")
        return ADMIN_PANEL

    # Add balance
    if key == "admin_add_balance":
        context.user_data["admin_mode"] = "add_balance"
        await q.edit_message_text("âž• Send user ID to add balance to:")
        return ADMIN_ADD_USER

    # Inspect user
    if key == "admin_inspect_user":
        context.user_data["admin_mode"] = "inspect_user"
        await q.edit_message_text("ðŸ” Send user ID to inspect:")
        return ADMIN_INSPECT_USER

    # Toggle Sell
    if key == "admin_toggle_sell":
        global SELL_ENABLED
        try:
            SELL_ENABLED = not SELL_ENABLED
        except NameError:
            SELL_ENABLED = False
            SELL_ENABLED = not SELL_ENABLED
        await q.edit_message_text(f"âš™ï¸ Selling is now {'ENABLED' if SELL_ENABLED else 'DISABLED'}.")
        return ADMIN_PANEL

    # Broadcast
    if key == "admin_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await q.edit_message_text("ðŸ“¢ Send broadcast text to send to all users:")
        return ADMIN_BROADCAST

    # Custom submenu actions
    if key == "admin_custom_set":
        # ask admin to send user id (we'll capture in button_router)
        context.user_data["admin_mode"] = "custom_set_user"
        await q.edit_message_text("ðŸ‘¤ Send the user ID (numeric) to set custom prices for:")
        return ADMIN_PANEL

    if key == "admin_custom_remove":
        context.user_data["admin_mode"] = "custom_remove_user"
        await q.edit_message_text("ðŸ‘¤ Send the user ID (numeric) to remove custom prices for:")
        return ADMIN_PANEL

    if key == "admin_custom_view":
        context.user_data["admin_mode"] = "custom_view_user"
        await q.edit_message_text("ðŸ‘¤ Send the user ID (numeric) to view current custom prices for:")
        return ADMIN_PANEL

    await q.edit_message_text("âš ï¸ Unknown admin action.")
    return ADMIN_PANEL

# Keep admin add user/amount/inspect/broadcast handlers (unchanged)
async def admin_add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("âŒ Invalid user ID. Send numeric ID.")
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
        await update.message.reply_text("âŒ Invalid amount.")
        return ADMIN_ADD_AMOUNT
    uid = context.user_data.pop("target_user", None)
    if uid is None:
        await update.message.reply_text("âŒ No target user set. Start again.")
        return ConversationHandler.END
    ensure_user(uid)
    data["users"][str(uid)]["balance"] = data["users"][str(uid)].get("balance", 0.0) + amt
    save_data(data)
    await update.message.reply_text(f"âœ… Added ${amt:.2f} to {uid}. New balance: ${data['users'][str(uid)]['balance']:.2f}")
    try:
        await context.bot.send_message(uid, f"ðŸ’µ Admin added ${amt:.2f} to your balance. New balance: ${data['users'][str(uid)]['balance']:.2f}")
    except:
        pass
    return ADMIN_PANEL

async def admin_inspect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("âŒ Invalid user ID.")
        return ADMIN_INSPECT_USER
    ensure_user(uid)
    u = data["users"][str(uid)]
    pending_g = data["pending_groups"].get(str(uid))
    pending_w = data["pending_withdrawals"].get(str(uid))
    text = (
        f"ðŸ”Ž User: {uid}\n"
        f"ðŸ’° Balance: ${u['balance']:.2f}\n"
        f"ðŸ›’ Total groups submitted: {len(u.get('groups',[]))}\n"
        f"âœ… Sales (approved): {u.get('sales',0)}\n"
        f"â³ Pending group: {pending_g['link'] if pending_g else 'None'}\n"
        f"â³ Pending withdraw: {pending_w['amount'] if pending_w else 'None'}\n"
        f"ðŸ“ Withdraw history (last 5):\n"
    )
    for rec in u.get("withdraw_history", [])[-5:]:
        text += f"- {rec['time']}: {rec['amount']}$ via {rec['method']} â€” {rec['status']}\n"
    # also show custom prices if present
    if u.get("custom_prices"):
        text += "\nðŸ’  Custom Prices:\n"
        for y, p in u["custom_prices"].items():
            text += f"- {y}: {p}\n"
    await update.message.reply_text(text)
    return ADMIN_PANEL

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text
    count = 0
    for s_uid in list(data["users"].keys()):
        try:
            context.bot.send_message(int(s_uid), f"ðŸ“¢ Broadcast from admin:\n\n{text}")
            count += 1
        except:
            pass
    await update.message.reply_text(f"âœ… Broadcast sent to {count} users.")
    return ADMIN_PANEL

# ------------------------
# Router for reply-keyboard (only when not in a conversation)
# and also handles admin custom-price text flow
# ------------------------
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # FIRST: handle admin replying with ownership target ID if we are awaiting it
    if update.effective_user.id == ADMIN_ID and context.user_data.get("awaiting_ownership_id"):
        info = context.user_data.pop("awaiting_ownership_id")
        target_id = (update.message.text or "").strip()
        seller_id = info.get("seller_id")
        if not seller_id or seller_id not in data["pending_groups"]:
            await update.message.reply_text("âš ï¸ Pending group not found or expired.")
            return

        pg = data["pending_groups"][seller_id]
        pg["ownership_status"] = "requested"
        pg["ownership_target_id"] = target_id
        save_data(data)

        try:
            await context.bot.send_message(
                int(seller_id),
                f"ðŸ“¢ Please transfer the group ownership to: {target_id}\n\n"
                "After you transfer ownership, press the button below to notify admin.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("âœ… Ownership Submitted", callback_data=f"submit_ownership:{seller_id}")]
                ])
            )
        except:
            pass

        await update.message.reply_text(f"âœ… Ownership target set to {target_id} and seller notified.")
        return

    # NEXT: handle admin custom-price flows (set/remove/view) captured through admin_mode
    if update.effective_user.id == ADMIN_ID and context.user_data.get("admin_mode"):
        mode = context.user_data.get("admin_mode")

        # SET custom price - step 1: admin has been asked to send user id
        if mode == "custom_set_user":
            target_uid = (update.message.text or "").strip()
            try:
                tid = int(target_uid)
            except:
                await update.message.reply_text("âŒ Invalid user ID. Send numeric ID.")
                return
            ensure_user(tid)
            context.user_data["target_user"] = str(tid)
            context.user_data["admin_mode"] = "custom_set_value"
            await update.message.reply_text("âœï¸ Send price like: `2016-22: 10$` or multiple separated by comma\nExample: `2016-22: 10$, 2023: 5$`")
            return

        # SET custom price - step 2: admin sends price values
        if mode == "custom_set_value":
            target_uid = context.user_data.get("target_user")
            txt = (update.message.text or "").strip()
            parts = [p.strip() for p in txt.split(",")]
            new_prices = {}
            for p in parts:
                if ":" in p:
                    yr, val = p.split(":", 1)
                    new_prices[yr.strip()] = val.strip()
            data["users"][target_uid]["custom_prices"] = new_prices
            save_data(data)
            await update.message.reply_text(f"âœ… Custom prices set for user {target_uid}: {new_prices}")
            context.user_data.pop("admin_mode", None)
            context.user_data.pop("target_user", None)
            return

        # REMOVE custom price - step 1: admin sends user id
        if mode == "custom_remove_user":
            target_uid = (update.message.text or "").strip()
            try:
                tid = int(target_uid)
            except:
                await update.message.reply_text("âŒ Invalid user ID. Send numeric ID.")
                return
            ensure_user(tid)
            if not data["users"][str(tid)].get("custom_prices"):
                await update.message.reply_text("âš ï¸ No custom prices found for this user.")
                context.user_data.pop("admin_mode", None)
                return
            context.user_data["target_user"] = str(tid)
            context.user_data["admin_mode"] = "custom_remove_action"
            years = "\n".join(data["users"][str(tid)]["custom_prices"].keys())
            await update.message.reply_text(
                f"ðŸ§¼ Custom prices for user {tid}:\n{years}\n\n"
                "Type specific year to remove (e.g. `2023`) or type `all` to remove all custom prices."
            )
            return

        # REMOVE custom price - step 2: admin sends action
        if mode == "custom_remove_action":
            target_uid = context.user_data.get("target_user")
            year = (update.message.text or "").strip()
            if year.lower() == "all":
                data["users"][target_uid]["custom_prices"] = {}
                save_data(data)
                await update.message.reply_text(f"âœ… All custom prices removed for user {target_uid}")
            else:
                if year in data["users"][target_uid]["custom_prices"]:
                    del data["users"][target_uid]["custom_prices"][year]
                    save_data(data)
                    await update.message.reply_text(f"âœ… Removed custom price for year {year} from user {target_uid}")
                else:
                    await update.message.reply_text(f"âš ï¸ No custom price found for year {year}.")
            context.user_data.pop("admin_mode", None)
            context.user_data.pop("target_user", None)
            return

        # VIEW custom price - admin sends user id
        if mode == "custom_view_user":
            target_uid = (update.message.text or "").strip()
            try:
                tid = int(target_uid)
            except:
                await update.message.reply_text("âŒ Invalid user ID. Send numeric ID.")
                return
            ensure_user(tid)
            user_prices = data["users"][str(tid)].get("custom_prices", {})
            if user_prices:
                text = "ðŸ•µï¸ *Custom Prices for this User:*\n"
                for k, v in user_prices.items():
                    text += f"ðŸ“… {k}: {v}\n"
                await update.message.reply_text(text, parse_mode="Markdown")
            else:
                await update.message.reply_text("âš ï¸ No custom prices set for this user.")
            context.user_data.pop("admin_mode", None)
            return

    # FALLBACK: original router logic for keyboard buttons
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id
    ensure_user(uid)
    if txt == "ðŸ  Start":
        await on_start(update, context)
    elif txt == "ðŸ’° Prices":
        await cmd_price(update, context)
    elif txt == "ðŸ› Sell":
        return await cmd_sell_entry(update, context)
    elif txt == "ðŸ’¸ Withdraw":
        return await cmd_withdraw_entry(update, context)
    elif txt == "ðŸ’µ Balance":
        await cmd_balance(update, context)
    elif txt == "ðŸ§‘â€ðŸ’» Admin" and uid == ADMIN_ID:
        return await admin_panel_entry(update, context)
    else:
        await update.message.reply_text("âš ï¸ Unknown option or use buttons/commands.")

# ========================
# App setup
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ConversationHandlers must be added before generic text handler so they get priority
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry), MessageHandler(filters.Regex("^ðŸ› Sell$"), cmd_sell_entry)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)]},
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", cmd_withdraw_entry), MessageHandler(filters.Regex("^ðŸ’¸ Withdraw$"), cmd_withdraw_entry)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method, pattern="^method_")],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel_entry), MessageHandler(filters.Regex("^ðŸ§‘â€ðŸ’» Admin$"), admin_panel_entry)],
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

    # Callbacks: approve/reject + ownership submit + ownership verify/reject
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(approve_group|reject_group|approve_withdraw|reject_withdraw|submit_ownership|verify_ownership|reject_ownership):"))
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
    main()
