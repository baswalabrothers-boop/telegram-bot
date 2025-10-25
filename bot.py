import json
import logging
import re
import datetime
import os
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "8075394934:AAHU9tRE9vemQIDzxRuX4UhxMUtw5mSlMy4")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5405985282")) # Your Telegram numeric ID

DATA_PATH = Path("data.json")

DEFAULT_PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$",
}

MAX_LINKS_PER_SUBMISSION = 10 # Maximum number of links allowed in one submission

# ========================
# Logging
# ========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# Persistence helpers
# ========================
def load_data():
    try:
        if not DATA_PATH.exists():
            return {
                "users": {}, # user_id -> {"balance": float, "groups": [links], "sales": int, "custom_prices": {}}
                "pending_groups": {}, # user_id:link -> {"link":..., "time":..., "year":...}
                "pending_withdrawals": {}, # user_id -> {"method":..., "address":..., "amount":..., "time":...}
                "sell_enabled": True, # Global sell toggle
                "global_prices": DEFAULT_PRICES # Global prices
            }
        return json.loads(DATA_PATH.read_text(encoding="utf8"))
    except json.JSONDecodeError:
        logger.error("Corrupted data.json. Initializing new data structure.")
        return {
            "users": {},
            "pending_groups": {},
            "pending_withdrawals": {},
            "sell_enabled": True,
            "global_prices": DEFAULT_PRICES
        }

def save_data(data_obj):
    try:
        DATA_PATH.write_text(json.dumps(data_obj, indent=2, ensure_ascii=False), encoding="utf8")
    except Exception as e:
        logger.error(f"Failed to save data.json: {e}")

data = load_data()

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {
            "balance": 0.0,
            "groups": [],
            "sales": 0,
            "withdraw_history": [],
            "custom_prices": {}
        }
        save_data(data)

# ========================
# Regex / utilities
# ========================
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/|t\.me/addlist/)[A-Za-z0-9_-]+$",
    flags=re.IGNORECASE,
)

# Basic address validation regex
ADDRESS_VALIDATORS = {
    "upi": r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$", # Example UPI format
    "binance": r"^\d+$", # Binance UID (numeric)
    "bep20": r"^0x[a-fA-F0-9]{40}$", # Ethereum/BEP20 address
    "polygon": r"^0x[a-fA-F0-9]{40}$" # Polygon address (same as BEP20 for simplicity)
}

def validate_address(method, address):
    regex = ADDRESS_VALIDATORS.get(method)
    if regex and not re.match(regex, address, re.IGNORECASE):
        return False
    return True

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

# ========================
# Conversation states
# ========================
SELL_LINK, SELL_YEAR = range(1, 3)
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
    uid = update.effective_user.id
    ensure_user(uid)

    text = "📊 *Current Group Prices*\n\n"
    user_custom = data["users"][str(uid)].get("custom_prices", {})

    if user_custom:
        text += "✨ *Your Custom Prices:*\n"
        for k, v in user_custom.items():
            text += f"📅 {k}: {v}\n"
        text += "\n"

    global_prices = data.get("global_prices", DEFAULT_PRICES)
    text += "🌍 *Standard Prices:*\n"
    for k, v in global_prices.items():
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
async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not data.get("sell_enabled", True):
        await update.message.reply_text("❌ Selling is currently disabled by admin.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("Single Group", callback_data="sell_type_single")],
        [InlineKeyboardButton("Folder Group", callback_data="sell_type_folder")],
    ]
    await update.message.reply_text(
        "🛍 Please choose the type of submission:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELL_LINK

async def sell_choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sell_type = q.data.replace("sell_type_", "")
    context.user_data["sell_type"] = sell_type
    context.user_data["in_sell"] = True
    msg = (
        "📎 Send your *Telegram group or folder link(s)* (examples: t.me/+ABC, t.me/yourgroup, t.me/addlist/XXX)\n"
        "You can send multiple links separated by spaces or newlines.\n"
        f"Maximum {MAX_LINKS_PER_SUBMISSION} links per submission.\n"
        "Type /cancel to stop. (Auto-cancels after 10 minutes.)\n"
    )
    if sell_type == "folder":
        msg += "\nNote: For folders, admin will count the number of groups inside."
    await q.edit_message_text(msg, parse_mode="Markdown")
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END

    # Split the message by whitespace or newlines to extract potential links
    potential_links = [link.strip() for link in text.split() if link.strip()]
    valid_links = []
    invalid_links = []

    # Validate each link
    for link in potential_links:
        if INVITE_RE.match(link):
            valid_links.append(link)
        else:
            invalid_links.append(link)

    if not valid_links:
        await update.message.reply_text(
            "❌ No valid Telegram group or folder links found. Please send valid links (e.g., t.me/+ABC, t.me/addlist/XXX) or /cancel to stop.\n"
            f"Invalid links: {', '.join(invalid_links) if invalid_links else 'None'}"
        )
        return SELL_LINK

    if len(valid_links) > MAX_LINKS_PER_SUBMISSION:
        await update.message.reply_text(
            f"❌ Too many links. Maximum {MAX_LINKS_PER_SUBMISSION} links allowed per submission."
        )
        return SELL_LINK

    # Check for duplicates
    s_uid = str(uid)
    ensure_user(uid)
    existing_groups = data["users"][s_uid].get("groups", [])
    duplicates = [link for link in valid_links if link in existing_groups]
    if duplicates:
        await update.message.reply_text(
            f"❌ The following links were already submitted:\n{', '.join(duplicates)}\nPlease send new links or /cancel."
        )
        return SELL_LINK

    # Store valid links in context for the next step
    context.user_data["sell_links"] = valid_links
    await update.message.reply_text(
        f"✅ Found {len(valid_links)} valid link(s):\n" +
        "\n".join(valid_links) +
        "\n\n📅 Please send the year range for these groups/folders (e.g., `2016-22`, `2023`, `2024 (1-3)`):"
    )
    return SELL_YEAR

async def sell_receive_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    year = (update.message.text or "").strip()
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END

    global_prices = data.get("global_prices", DEFAULT_PRICES)
    # Validate year against global or custom prices
    if year not in global_prices and year not in data["users"][str(uid)].get("custom_prices", {}):
        await update.message.reply_text(
            f"❌ Invalid year range. Please use one of: {', '.join(global_prices.keys())} or your custom price ranges."
        )
        return SELL_YEAR

    s_uid = str(uid)
    links = context.user_data.get("sell_links", [])
    if not links:
        await update.message.reply_text("❌ No links found. Please start over with /sell.")
        return ConversationHandler.END

    # Store each link as a pending group/folder
    for link in links:
        data["pending_groups"][f"{s_uid}:{link}"] = {
            "link": link,
            "year": year,
            "time": now(),
            "seller_id": s_uid,
            "ownership_status": "none",
            "ownership_target_id": None,
            "status": "pending"
        }
        data["users"].setdefault(s_uid, {"balance": 0.0, "groups": [], "sales": 0, "withdraw_history": [], "custom_prices": {}})
        if link not in data["users"][s_uid]["groups"]: # Prevent duplicates
            data["users"][s_uid]["groups"].append(link)
   
    save_data(data)
    context.user_data.pop("in_sell", None)
    context.user_data.pop("sell_links", None)

    # Notify admin with all links
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{s_uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{s_uid}"),
        ]
    ]
    links_text = "\n".join([f"- {link}" for link in links])
    await context.bot.send_message(
        ADMIN_ID,
        f"🆕 New submission ({context.user_data.get('sell_type', 'unknown')} type)\nUser: @{update.effective_user.username or update.effective_user.first_name} (ID: {uid})\nLinks:\n{links_text}\nYear: {year}\nTime: {now()}",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    context.user_data.pop("sell_type", None)
    await update.message.reply_text(f"✅ {len(links)} link(s) submitted to admin for review. You will be notified on approval/rejection.")
    return ConversationHandler.END

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("in_sell", None)
    context.user_data.pop("sell_links", None)
    context.user_data.pop("sell_type", None)
    context.user_data.pop("withdraw_method", None)
    context.user_data.pop("withdraw_address", None)
    context.user_data.pop("admin_mode", None)
    context.user_data.pop("target_user", None)
    context.user_data.pop("awaiting_ownership_id", None)
    context.user_data.pop("awaiting_group_count", None)
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

# ------------------------
# WITHDRAW flow (Conversation)
# ------------------------
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
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
    method = context.user_data.get("withdraw_method")
    if not validate_address(method, addr):
        await update.message.reply_text(f"❌ Invalid {method.upper()} address. Please provide a valid address.")
        return WITHDRAW_ADDRESS
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

    data["pending_withdrawals"][str(uid)] = {
        "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"],
        "amount": amount,
        "time": now(),
    }
    rec = {
        "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"],
        "amount": amount,
        "status": "Pending",
        "time": now()
    }
    data["users"][str(uid)]["withdraw_history"].append(rec)
    save_data(data)

    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}"),
        ]
    ]
    await context.bot.send_message(
        ADMIN_ID,
        f"💸 Withdrawal request\nUser: {uid}\n{amount}$ via {rec['method']}\nAddress: {rec['address']}\nTime: {rec['time']}",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

# ------------------------
# ADMIN callbacks: groups & withdraws & panel actions
# ------------------------
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data_payload = q.data

    # Group approvals
    if data_payload.startswith("approve_group:") or data_payload.startswith("reject_group:"):
        action, uid_s = data_payload.split(":")
        s_uid = str(uid_s)
        # Find all pending groups/folders for this user
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "pending"}
        if not user_pending:
            await q.edit_message_text("⚠️ No pending submissions found for this user.")
            return

        if action == "reject_group":
            rejected_links = [info["link"] for info in user_pending.values()]
            for key in list(user_pending.keys()):
                data["pending_groups"].pop(key, None)
            save_data(data)
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"❌ Your submission(s) were rejected by admin:\n" + "\n".join(rejected_links)
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of group rejection.")
            await q.edit_message_text(f"❌ {len(user_pending)} submission(s) rejected.")
            return

        # action == approve_group:
        for key, info in user_pending.items():
            info["status"] = "approved_waiting_count"
            info["seller_id"] = info.get("seller_id", s_uid)
            info["ownership_status"] = info.get("ownership_status", "none")
            info["ownership_target_id"] = info.get("ownership_target_id", None)
            data["pending_groups"][key] = info
        save_data(data)

        # Check if submission includes folders
        is_folder_submission = any('addlist/' in info["link"].lower() for info in user_pending.values())

        if is_folder_submission:
            await q.edit_message_text(
                f"✅ {len(user_pending)} link(s) approved. Since this includes folder(s), please send the total number of approved groups (counting folders' contents):"
            )
            context.user_data["awaiting_group_count"] = {"seller_id": s_uid}
        else:
            for key, info in user_pending.items():
                info["approved_count"] = 1
            save_data(data)
            links_text = "\n".join([info["link"] for info in user_pending.values()])
            await q.edit_message_text(
                f"✅ {len(user_pending)} submission(s) approved. Please send the Telegram @username or numeric ID of the buyer for these links:\n{links_text}"
            )
            context.user_data["awaiting_ownership_id"] = {"seller_id": s_uid}
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"✅ Your submission(s) were approved by admin:\n{links_text}\nAdmin will send buyer ID for transfer shortly."
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of group approval.")
        return

    # Withdraw approvals
    if data_payload.startswith("approve_withdraw:") or data_payload.startswith("reject_withdraw:"):
        action, uid_s = data_payload.split(":")
        s_uid = str(uid_s)
        if s_uid not in data["pending_withdrawals"]:
            await q.edit_message_text("⚠️ This withdrawal was processed or not found.")
            return
        wd = data["pending_withdrawals"].pop(s_uid)
        hist = data["users"].get(s_uid, {}).get("withdraw_history", [])
        for rec in reversed(hist):
            if rec["status"] == "Pending" and rec["amount"] == wd["amount"] and rec["method"] == wd["method"]:
                rec["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break
        if action == "approve_withdraw":
            data["users"].setdefault(s_uid, {"balance": 0.0, "groups": [], "sales": 0, "withdraw_history": [], "custom_prices": {}})
            data["users"][s_uid]["balance"] = max(0.0, data["users"][s_uid]["balance"] - float(wd["amount"]))
            try:
                await context.bot.send_message(int(s_uid), f"✅ Your withdrawal of ${wd['amount']} has been approved and processed.")
            except:
                logger.warning(f"Failed to notify user {s_uid} of withdrawal approval.")
            await q.edit_message_text("✅ Withdrawal approved and processed.")
        else:
            try:
                await context.bot.send_message(int(s_uid), f"❌ Your withdrawal of ${wd['amount']} has been rejected.")
            except:
                logger.warning(f"Failed to notify user {s_uid} of withdrawal rejection.")
            await q.edit_message_text("❌ Withdrawal rejected.")
        save_data(data)
        return

    # Seller pressed ownership-submitted button
    if data_payload.startswith("submit_ownership:"):
        action, s_uid = data_payload.split(":")
        s_uid = str(s_uid)
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "approved_waiting_target"}
        if not user_pending:
            await q.edit_message_text("⚠️ No pending submissions found for this user.")
            return
        if str(q.from_user.id) != str(s_uid):
            await q.answer("❌ Only the seller can press this.")
            return
        for key, info in user_pending.items():
            info["ownership_status"] = "transferred"
            data["pending_groups"][key] = info
        save_data(data)
        kb = [
            [
                InlineKeyboardButton("✅ Ownership Verified", callback_data=f"verify_ownership:{s_uid}"),
                InlineKeyboardButton("❌ Ownership Failed", callback_data=f"reject_ownership:{s_uid}"),
            ]
        ]
        links_text = "\n".join([info["link"] for info in user_pending.values()])
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"👤 Seller submitted ownership transfer for:\n{links_text}\nTarget: {list(user_pending.values())[0].get('ownership_target_id')}\nPlease verify.",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            logger.warning(f"Failed to notify admin of ownership submission for user {s_uid}.")
        await q.edit_message_text(f"✅ Ownership submitted for {len(user_pending)} link(s). Admin will verify shortly.")
        return

    # Ownership verification callbacks
    if data_payload.startswith("verify_ownership:") or data_payload.startswith("reject_ownership:"):
        action, s_uid = data_payload.split(":")
        s_uid = str(s_uid)
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "approved_waiting_target"}
        if not user_pending:
            await q.edit_message_text("⚠️ No pending ownership records found.")
            return
        if action == "verify_ownership":
            data["users"].setdefault(s_uid, {"balance": 0.0, "groups": [], "sales": 0, "withdraw_history": [], "custom_prices": {}})
            custom_prices = data["users"][s_uid].get("custom_prices", {})
            global_prices = data.get("global_prices", DEFAULT_PRICES)
            total_credited = 0.0
            # Get approved_count from the first entry (assuming same for all in submission)
            approved_count = list(user_pending.values())[0].get("approved_count", len(user_pending))
            year = list(user_pending.values())[0].get("year")
            price_str = custom_prices.get(year, global_prices.get(year, "1$"))
            try:
                price = float(price_str.replace("$", ""))
            except ValueError:
                price = 1.0
            total_credited = price * approved_count
            data["users"][s_uid]["sales"] = data["users"][s_uid].get("sales", 0) + approved_count
            for key in list(user_pending.keys()):
                data["pending_groups"].pop(key)
            data["users"][s_uid]["balance"] += total_credited
            save_data(data)
            links_text = "\n".join([info["link"] for info in user_pending.values()])
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"✅ Ownership verified for {len(user_pending)} link(s) ({approved_count} groups):\n{links_text}\n${total_credited:.2f} credited to your balance."
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of ownership verification.")
            await q.edit_message_text(f"✅ Ownership verified for {len(user_pending)} link(s) ({approved_count} groups). ${total_credited:.2f} credited to seller.")
        else:
            for key, info in user_pending.items():
                info["ownership_status"] = "failed"
                data["pending_groups"][key] = info
            save_data(data)
            links_text = "\n".join([info["link"] for info in user_pending.values()])
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"❌ Ownership verification FAILED for:\n{links_text}\nPlease re-transfer and press the Ownership Submitted button again."
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of ownership verification failure.")
            await q.edit_message_text(f"❌ Ownership verification marked as failed for {len(user_pending)} link(s) and seller notified.")
        return

# ------------------------
# Admin panel (Conversation)
# ------------------------
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton("👥 Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_pending_withdrawals")],
        [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("💰 Custom", callback_data="admin_custom")],
        [InlineKeyboardButton("🔍 Inspect User", callback_data="admin_inspect_user")],
        [InlineKeyboardButton("🪙 Toggle Sell On/Off", callback_data="admin_toggle_sell")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
    ]
    await update.message.reply_text("🧑‍💻 *Admin Panel* - choose action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_PANEL

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.edit_message_text("❌ Only admin.")
        return ADMIN_PANEL
    key = q.data
    if key == "admin_custom":
        kb = [
            [InlineKeyboardButton("➕ Set Price for User", callback_data="admin_custom_set")],
            [InlineKeyboardButton("🧼 Remove Price for User", callback_data="admin_custom_remove")],
            [InlineKeyboardButton("🕵️ View Price for User", callback_data="admin_custom_view")],
            [InlineKeyboardButton("🌍 Set Global Prices", callback_data="admin_global_prices_set")],
        ]
        await q.edit_message_text("💰 Custom Price — choose:", reply_markup=InlineKeyboardMarkup(kb))
        return ADMIN_PANEL
    if key == "admin_pending_groups":
        if not data["pending_groups"]:
            await q.edit_message_text("📭 No pending groups or folders.")
            return ADMIN_PANEL
        # Group pending submissions by seller_id
        grouped_pending = {}
        for key, info in data["pending_groups"].items():
            if info["status"] == "pending":
                seller_id = info["seller_id"]
                grouped_pending.setdefault(seller_id, []).append(info)
        for seller_id, infos in grouped_pending.items():
            kb = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{seller_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{seller_id}"),
                ],
            ]
            links_text = "\n".join([f"- {info['link']} (Year: {info.get('year', 'N/A')})" for info in infos])
            await context.bot.send_message(
                ADMIN_ID,
                f"👤 Seller ID: {seller_id}\nLinks:\n{links_text}\nSubmitted: {infos[0]['time']}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.edit_message_text("📋 Pending groups/folders shown above.")
        return ADMIN_PANEL
    if key == "admin_pending_withdrawals":
        if not data["pending_withdrawals"]:
            await q.edit_message_text("📭 No pending withdrawals.")
            return ADMIN_PANEL
        for s_uid, w in list(data["pending_withdrawals"].items()):
            kb = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{s_uid}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{s_uid}"),
                ],
            ]
            await context.bot.send_message(
                ADMIN_ID,
                f"👤 {s_uid} ➝ {w['amount']}$ via {w['method']} ({w['address']})",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.edit_message_text("💸 Pending withdrawals shown above.")
        return ADMIN_PANEL
    if key == "admin_add_balance":
        context.user_data["admin_mode"] = "add_balance"
        await q.edit_message_text("➕ Send user ID to add balance to:")
        return ADMIN_ADD_USER
    if key == "admin_inspect_user":
        context.user_data["admin_mode"] = "inspect_user"
        await q.edit_message_text("🔍️ Send user ID to inspect:")
        return ADMIN_INSPECT_USER
    if key == "admin_toggle_sell":
        data["sell_enabled"] = not data.get("sell_enabled", True)
        save_data(data)
        await q.edit_message_text(f"⚙️ Selling is now {'ENABLED' if data['sell_enabled'] else 'DISABLED'}.")
        return ADMIN_PANEL
    if key == "admin_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await q.edit_message_text("📢 Send broadcast text to send to all users:")
        return ADMIN_BROADCAST
    if key == "admin_custom_set":
        context.user_data["admin_mode"] = "custom_set_user"
        await q.edit_message_text("👤 Send the user ID (numeric) to set custom prices for:")
        return ADMIN_PANEL
    if key == "admin_custom_remove":
        context.user_data["admin_mode"] = "custom_remove_user"
        await q.edit_message_text("👤 Send the user ID (numeric) to remove custom prices for:")
        return ADMIN_PANEL
    if key == "admin_custom_view":
        context.user_data["admin_mode"] = "custom_view_user"
        await q.edit_message_text("👤 Send the user ID (numeric) to view current custom prices for:")
        return ADMIN_PANEL
    if key == "admin_global_prices_set":
        context.user_data["admin_mode"] = "global_prices_set_value"
        await q.edit_message_text(
            "✍️ Send global prices like: `2016-22: 10$` or multiple separated by comma\nExample: `2016-22: 10$, 2023: 5$`"
        )
        return ADMIN_PANEL
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
        if amt <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid amount. Send a positive number.")
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
        await context.bot.send_message(
            uid,
            f"💵 Admin added ${amt:.2f} to your balance. New balance: ${data['users'][str(uid)]['balance']:.2f}"
        )
    except:
        logger.warning(f"Failed to notify user {uid} of balance addition.")
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
    pending_g = [info["link"] for key, info in data["pending_groups"].items() if info["seller_id"] == str(uid)]
    pending_w = data["pending_withdrawals"].get(str(uid))
    text = (
        f"🔎 User: {uid}\n"
        f"💰 Balance: ${u['balance']:.2f}\n"
        f"🛒 Total groups submitted: {len(u.get('groups', []))}\n"
        f"✅ Sales (approved): {u.get('sales', 0)}\n"
        f"⏳ Pending groups/folders: {', '.join(pending_g) if pending_g else 'None'}\n"
        f"⏳ Pending withdraw: {pending_w['amount'] if pending_w else 'None'}\n"
        f"📝 Withdraw history (last 5):\n"
    )
    for rec in u.get("withdraw_history", [])[-5:]:
        text += f"- {rec['time']}: {rec['amount']}$ via {rec['method']} — {rec['status']}\n"
    if u.get("custom_prices"):
        text += "\n💠 Custom Prices:\n"
        for y, p in u["custom_prices"].items():
            text += f"- {y}: {p}\n"
    await update.message.reply_text(text)
    return ADMIN_PANEL

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Broadcast message cannot be empty.")
        return ADMIN_BROADCAST
    count = 0
    for s_uid in list(data["users"].keys()):
        try:
            await context.bot.send_message(int(s_uid), f"📢 Broadcast from admin:\n\n{text}")
            count += 1
        except:
            logger.warning(f"Failed to send broadcast to user {s_uid}.")
    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")
    return ADMIN_PANEL

# ------------------------
# Router for reply-keyboard (only when not in a conversation)
# and also handles admin custom-price text flow
# ------------------------
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and context.user_data.get("awaiting_group_count"):
        info = context.user_data.pop("awaiting_group_count")
        try:
            count = int((update.message.text or "").strip())
            if count <= 0:
                raise ValueError
        except:
            await update.message.reply_text("❌ Invalid count. Send positive integer.")
            context.user_data["awaiting_group_count"] = info  # Restore to ask again
            return
        seller_id = info["seller_id"]
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id and v["status"] == "approved_waiting_count"}
        if not user_pending:
            await update.message.reply_text("⚠️ Pending submission not found.")
            return
        for key, pg in user_pending.items():
            pg["approved_count"] = count
            pg["status"] = "approved_waiting_target"
            data["pending_groups"][key] = pg
        save_data(data)
        links_text = "\n".join([info["link"] for info in user_pending.values()])
        await update.message.reply_text(
            f"✅ Count set to {count}. Now send the Telegram @username or numeric ID of the buyer for these links:\n{links_text}"
        )
        context.user_data["awaiting_ownership_id"] = {"seller_id": seller_id}
        try:
            await context.bot.send_message(
                int(seller_id),
                f"✅ Your submission(s) were approved by admin ({count} groups):\n{links_text}\nAdmin will send buyer ID for transfer shortly."
            )
        except:
            logger.warning(f"Failed to notify user {seller_id} of group approval.")
        return

    if update.effective_user.id == ADMIN_ID and context.user_data.get("awaiting_ownership_id"):
        info = context.user_data.pop("awaiting_ownership_id")
        target_id = (update.message.text or "").strip()
        seller_id = info.get("seller_id")
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id and v["status"] == "approved_waiting_target"}
        if not user_pending:
            await update.message.reply_text("⚠️ Pending group/folder not found or expired.")
            return
        for key, pg in user_pending.items():
            pg["ownership_status"] = "requested"
            pg["ownership_target_id"] = target_id
            data["pending_groups"][key] = pg
        save_data(data)
        links_text = "\n".join([info["link"] for info in user_pending.values()])
        try:
            await context.bot.send_message(
                int(seller_id),
                f"📢 Please transfer the group/folder ownership for:\n{links_text}\nTo: {target_id}\n\n"
                "After you transfer ownership, press the button below to notify admin.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Ownership Submitted", callback_data=f"submit_ownership:{seller_id}")]
                ])
            )
        except:
            logger.warning(f"Failed to notify user {seller_id} of ownership target.")
        await update.message.reply_text(f"✅ Ownership target set to {target_id} for {len(user_pending)} link(s) and seller notified.")
        return

    if update.effective_user.id == ADMIN_ID and context.user_data.get("admin_mode"):
        mode = context.user_data.get("admin_mode")
        if mode == "custom_set_user":
            target_uid = (update.message.text or "").strip()
            try:
                tid = int(target_uid)
            except:
                await update.message.reply_text("❌ Invalid user ID. Send numeric ID.")
                return
            ensure_user(tid)
            context.user_data["target_user"] = str(tid)
            context.user_data["admin_mode"] = "custom_set_value"
            await update.message.reply_text(
                "✍️ Send price like: `2016-22: 10$` or multiple separated by comma\nExample: `2016-22: 10$, 2023: 5$`"
            )
            return
        if mode == "custom_set_value":
            target_uid = context.user_data.get("target_user")
            txt = (update.message.text or "").strip()
            parts = [p.strip() for p in txt.split(",")]
            new_prices = {}
            try:
                for p in parts:
                    if ":" in p:
                        yr, val = p.split(":", 1)
                        val = val.strip()
                        if not val.endswith("$"):
                            val += "$"
                        new_prices[yr.strip()] = val
                data["users"][target_uid]["custom_prices"] = new_prices
                save_data(data)
                await update.message.reply_text(f"✅ Custom prices set for user {target_uid}: {new_prices}")
                try:
                    await context.bot.send_message(
                        int(target_uid),
                        f"💰 Your custom group prices have been updated: {new_prices}"
                    )
                except:
                    logger.warning(f"Failed to notify user {target_uid} of custom price update.")
                context.user_data.pop("admin_mode", None)
                context.user_data.pop("target_user", None)
            except:
                await update.message.reply_text(
                    "❌ Invalid format. Use `year1:price1,year2:price2` (e.g., `2016-22:10$,2023:5$`)."
                )
                return
            return
        if mode == "custom_remove_user":
            target_uid = (update.message.text or "").strip()
            try:
                tid = int(target_uid)
            except:
                await update.message.reply_text("❌ Invalid user ID. Send numeric ID.")
                return
            ensure_user(tid)
            if not data["users"][str(tid)].get("custom_prices"):
                await update.message.reply_text("⚠️ No custom prices found for this user.")
                context.user_data.pop("admin_mode", None)
                return
            context.user_data["target_user"] = str(tid)
            context.user_data["admin_mode"] = "custom_remove_action"
            years = "\n".join(data["users"][str(tid)]["custom_prices"].keys())
            await update.message.reply_text(
                f"🧼 Custom prices for user {tid}:\n{years}\n\n"
                "Type specific year to remove (e.g., `2023`) or type `all` to remove all custom prices."
            )
            return
        if mode == "custom_remove_action":
            target_uid = context.user_data.get("target_user")
            year = (update.message.text or "").strip()
            if year.lower() == "all":
                data["users"][target_uid]["custom_prices"] = {}
                save_data(data)
                await update.message.reply_text(f"✅ All custom prices removed for user {target_uid}")
            else:
                if year in data["users"][target_uid]["custom_prices"]:
                    del data["users"][target_uid]["custom_prices"][year]
                    save_data(data)
                    await update.message.reply_text(f"✅ Removed custom price for year {year} from user {target_uid}")
                else:
                    await update.message.reply_text(f"⚠️ No custom price found for year {year}.")
            context.user_data.pop("admin_mode", None)
            context.user_data.pop("target_user", None)
            return
        if mode == "custom_view_user":
            target_uid = (update.message.text or "").strip()
            try:
                tid = int(target_uid)
            except:
                await update.message.reply_text("❌ Invalid user ID. Send numeric ID.")
                return
            ensure_user(tid)
            user_prices = data["users"][str(tid)].get("custom_prices", {})
            if user_prices:
                text = "🕵️ *Custom Prices for this User:*\n"
                for k, v in user_prices.items():
                    text += f"📅 {k}: {v}\n"
                await update.message.reply_text(text, parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ No custom prices set for this user.")
            context.user_data.pop("admin_mode", None)
            return
        if mode == "global_prices_set_value":
            txt = (update.message.text or "").strip()
            parts = [p.strip() for p in txt.split(",")]
            new_prices = {}
            try:
                for p in parts:
                    if ":" in p:
                        yr, val = p.split(":", 1)
                        val = val.strip()
                        if not val.endswith("$"):
                            val += "$"
                        new_prices[yr.strip()] = val
                data["global_prices"] = new_prices
                save_data(data)
                await update.message.reply_text(f"✅ Global prices updated: {new_prices}")
                context.user_data.pop("admin_mode", None)
            except:
                await update.message.reply_text(
                    "❌ Invalid format. Use `year1:price1,year2:price2` (e.g., `2016-22:10$,2023:5$`)."
                )
                return
            return
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id
    ensure_user(uid)
    if txt == "🏠 Start":
        await on_start(update, context)
    elif txt == "💰 Prices":
        await cmd_price(update, context)
    elif txt == "🛍 Sell":
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
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry), MessageHandler(filters.Regex("🛍 Sell$"), cmd_sell_entry)],
        states={
            SELL_LINK: [
                CallbackQueryHandler(sell_choose_type, pattern="^sell_type_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)
            ],
            SELL_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_year)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", cmd_withdraw_entry), MessageHandler(filters.Regex("💸 Withdraw$"), cmd_withdraw_entry)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method, pattern="^method_")],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel_entry), MessageHandler(filters.Regex("🧑‍💻 Admin$"), admin_panel_entry)],
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
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(approve_group|reject_group|approve_withdraw|reject_withdraw|submit_ownership|verify_ownership|reject_ownership):"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("cancel", universal_cancel))
    logger.info("Bot starting...")
    app.run_polling()
if __name__ == "__main__":
    main()
