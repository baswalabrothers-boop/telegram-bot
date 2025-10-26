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
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")  # Replace with your BotFather token
ADMIN_ID = int(os.getenv("ADMIN_ID", "your_admin_id_here"))  # Your Telegram numeric ID
LINKS_CHANNEL_ID = int(os.getenv("LINKS_CHANNEL_ID", "-1003234042802"))  # Replace with your links channel ID
WITHDRAWALS_CHANNEL_ID = int(os.getenv("WITHDRAWALS_CHANNEL_ID", "-1003224533856"))  # Replace with your withdrawals channel ID

DATA_PATH = Path("data.json")

DEFAULT_PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$",
}

MAX_LINKS_PER_SUBMISSION = 10  # Maximum number of links allowed in one submission

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
                "users": {},  # user_id -> {"balance": float, "groups": [links], "sales": int, "custom_prices": {}, "withdraw_history": []}
                "pending_groups": {},  # user_id:link -> {"link":..., "time":..., "year":..., "seller_id":..., "status":..., "ownership_target_id":...}
                "pending_withdrawals": {},  # user_id -> {"method":..., "address":..., "amount":..., "time":..., "status":...}
                "sell_enabled": True,
                "global_prices": DEFAULT_PRICES
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

ADDRESS_VALIDATORS = {
    "upi": r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$",
    "binance": r"^\d+$",
    "bep20": r"^0x[a-fA-F0-9]{40}$",
    "polygon": r"^0x[a-fA-F0-9]{40}$"
}

def validate_address(method, address):
    regex = ADDRESS_VALIDATORS.get(method)
    if regex and not re.match(regex, address, re.IGNORECASE):
        return False
    return True

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

def get_today_date():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

# ========================
# Conversation states
# ========================
SELL_LINK, SELL_YEAR, SELL_COUNT = range(1, 4)
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 13)
ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER, ADMIN_BROADCAST = range(20, 25)

# ========================
# Commands menu
# ========================
COMMANDS = [
    BotCommand("start", "Open bot"),
    BotCommand("price", "Show prices"),
    BotCommand("sell", "Sell group"),
    BotCommand("withdraw", "Request withdrawal"),
    BotCommand("stats", "Show daily stats (admin only)"),
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
        kb.append(["🧑‍💻 Admin", "📊 Stats"])
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

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can view stats.")
        return
    today = get_today_date()
    sales_today = 0
    revenue_today = 0.0
    pending_groups = 0
    pending_withdrawals = 0
    for user_id, user in data["users"].items():
        for sale in user.get("withdraw_history", []):
            if sale["status"] == "Success" and sale["time"].startswith(today):
                sales_today += 1
                revenue_today += float(sale["amount"])
        pending_groups += len([g for k, g in data["pending_groups"].items() if g["seller_id"] == user_id and g["status"] == "pending"])
        if user_id in data["pending_withdrawals"]:
            pending_withdrawals += 1
    text = (
        f"📊 *Daily Stats ({today})*\n"
        f"✅ Sales completed: {sales_today}\n"
        f"💰 Revenue: ${revenue_today:.2f}\n"
        f"⏳ Pending groups/folders: {pending_groups}\n"
        f"💸 Pending withdrawals: {pending_withdrawals}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ------------------------
# SELL flow (Conversation)
# ------------------------
async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not data.get("sell_enabled", True):
        await update.message.reply_text("❌ Selling is currently disabled by admin.")
        return ConversationHandler.END
    context.user_data["in_sell"] = True
    await update.message.reply_text(
        f"📎 Send your *Telegram group or folder link(s)* (e.g., t.me/+ABC, t.me/addlist/XXX)\n"
        f"Maximum {MAX_LINKS_PER_SUBMISSION} links per submission.\n"
        "Type /cancel to stop.",
        parse_mode="Markdown"
    )
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END
    potential_links = [link.strip() for link in text.split() if link.strip()]
    valid_links = []
    invalid_links = []
    for link in potential_links:
        if INVITE_RE.match(link):
            valid_links.append(link)
        else:
            invalid_links.append(link)
    if not valid_links:
        await update.message.reply_text(
            f"❌ No valid links found. Please send valid links (e.g., t.me/+ABC) or /cancel.\n"
            f"Invalid links: {', '.join(invalid_links) if invalid_links else 'None'}"
        )
        return SELL_LINK
    if len(valid_links) > MAX_LINKS_PER_SUBMISSION:
        await update.message.reply_text(
            f"❌ Too many links. Maximum {MAX_LINKS_PER_SUBMISSION} allowed."
        )
        return SELL_LINK
    s_uid = str(uid)
    ensure_user(uid)
    existing_groups = data["users"][s_uid].get("groups", [])
    duplicates = [link for link in valid_links if link in existing_groups]
    if duplicates:
        await update.message.reply_text(
            f"❌ These links were already submitted:\n{', '.join(duplicates)}\nPlease send new links or /cancel."
        )
        return SELL_LINK
    context.user_data["sell_links"] = valid_links
    await update.message.reply_text(
        f"✅ Found {len(valid_links)} valid link(s):\n" +
        "\n".join(valid_links) +
        "\n\n📅 Please send the year range (e.g., `2016-22`, `2023`, `2024 (1-3)`):"
    )
    return SELL_YEAR

async def sell_receive_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    year = (update.message.text or "").strip()
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END
    global_prices = data.get("global_prices", DEFAULT_PRICES)
    if year not in global_prices and year not in data["users"][str(uid)].get("custom_prices", {}):
        await update.message.reply_text(
            f"❌ Invalid year range. Use: {', '.join(global_prices.keys())} or your custom ranges."
        )
        return SELL_YEAR
    context.user_data["sell_year"] = year
    links = context.user_data.get("sell_links", [])
    is_folder = any("addlist" in link for link in links)
    if is_folder:
        await update.message.reply_text(
            "📂 Some links are folders. Please estimate the number of groups in each folder (comma-separated if multiple, e.g., `5,3`):"
        )
        return SELL_COUNT
    for link in links:
        s_uid = str(uid)
        data["pending_groups"][f"{s_uid}:{link}"] = {
            "link": link,
            "year": year,
            "time": now(),
            "seller_id": s_uid,
            "status": "pending",
            "ownership_status": "none",
            "ownership_target_id": None,
            "seller_count": 1
        }
        if link not in data["users"][s_uid]["groups"]:
            data["users"][s_uid]["groups"].append(link)
    save_data(data)
    await forward_links_to_channel(update, context, links, year)
    context.user_data.pop("in_sell", None)
    context.user_data.pop("sell_links", None)
    context.user_data.pop("sell_year", None)
    await update.message.reply_text(
        f"✅ {len(links)} link(s) submitted to admin for review in the links channel."
    )
    return ConversationHandler.END

async def sell_receive_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    counts = (update.message.text or "").strip()
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END
    links = context.user_data.get("sell_links", [])
    year = context.user_data.get("sell_year", "")
    try:
        count_list = [int(c.strip()) for c in counts.split(",") if c.strip()]
        if len(count_list) != len([l for l in links if "addlist" in l]):
            await update.message.reply_text(
                "❌ Number of counts must match number of folder links."
            )
            return SELL_COUNT
        for i, link in enumerate(links):
            s_uid = str(uid)
            count = count_list.pop(0) if "addlist" in link else 1
            data["pending_groups"][f"{s_uid}:{link}"] = {
                "link": link,
                "year": year,
                "time": now(),
                "seller_id": s_uid,
                "status": "pending",
                "ownership_status": "none",
                "ownership_target_id": None,
                "seller_count": count
            }
            if link not in data["users"][s_uid]["groups"]:
                data["users"][s_uid]["groups"].append(link)
        save_data(data)
        await forward_links_to_channel(update, context, links, year, count_list)
        context.user_data.pop("in_sell", None)
        context.user_data.pop("sell_links", None)
        context.user_data.pop("sell_year", None)
        await update.message.reply_text(
            f"✅ {len(links)} link(s) submitted to admin for review in the links channel."
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid counts. Enter numbers separated by commas (e.g., `5,3`)."
        )
        return SELL_COUNT

async def forward_links_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, links, year, counts=None):
    uid = update.effective_user.id
    s_uid = str(uid)
    links_text = "\n".join([f"- {link} ({'Folder' if 'addlist' in link else 'Single'}, Est. groups: {counts.pop(0) if counts and 'addlist' in link else 1})" for link in links])
    message_text = (
        f"🆕 New submission\n"
        f"User: @{update.effective_user.username or update.effective_user.first_name} (ID: {uid})\n"
        f"Links:\n{links_text}\n"
        f"Year: {year}\n"
        f"Time: {now()}"
    )
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{s_uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{s_uid}"),
        ]
    ]
    try:
        await context.bot.send_message(
            LINKS_CHANNEL_ID,
            message_text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Failed to forward to links channel: {e}")
        await context.bot.send_message(
            ADMIN_ID,
            message_text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

# ------------------------
# WITHDRAW flow (Conversation)
# ------------------------
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    hist = data["users"][str(uid)].get("withdraw_history", [])[-5:]
    if hist:
        lines = [f"{h['time']}: ${h['amount']} via {h['method']} ({h['address']}) — {h['status']}" for h in hist]
        await update.message.reply_text("🧾 Recent withdrawals:\n" + "\n".join(lines))
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
    await q.edit_message_text(f"📤 Selected: *{method.upper()}*\nSend your address/ID:", parse_mode="Markdown")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = (update.message.text or "").strip()
    method = context.user_data.get("withdraw_method")
    if not validate_address(method, addr):
        await update.message.reply_text(f"❌ Invalid {method.upper()} address. Try again.")
        return WITHDRAW_ADDRESS
    context.user_data["withdraw_address"] = addr
    await update.message.reply_text("💰 Enter amount to withdraw:")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        amount = float((update.message.text or "").strip())
        if amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("❌ Invalid amount. Send a number.")
        return WITHDRAW_AMOUNT
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    if amount > bal:
        await update.message.reply_text(f"⚠️ Insufficient balance: ${bal:.2f}")
        return ConversationHandler.END
    time = now()
    withdrawal = {
        "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"],
        "amount": amount,
        "time": time,
        "status": "Pending"
    }
    data["pending_withdrawals"][str(uid)] = withdrawal
    data["users"][str(uid)]["withdraw_history"].append(withdrawal)
    save_data(data)
    confirm_text = (
        f"💸 *Withdrawal Request Submitted*\n"
        f"Amount: ${amount:.2f}\n"
        f"Method: {withdrawal['method'].upper()}\n"
        f"Address/ID: {withdrawal['address']}\n"
        f"Time: {withdrawal['time']}\n"
        f"Status: {withdrawal['status']}\n\n"
        f"Admin will review soon."
    )
    await update.message.reply_text(confirm_text, parse_mode="Markdown")
    message_text = (
        f"💸 *Withdrawal Request*\n"
        f"User: @{update.effective_user.username or update.effective_user.first_name} (ID: {uid})\n"
        f"Amount: ${amount:.2f}\n"
        f"Method: {withdrawal['method']}\n"
        f"Address: {withdrawal['address']}\n"
        f"Time: {withdrawal['time']}"
    )
    kb = [
        [
            InlineKeyboardButton("✅ Approve (Paid)", callback_data=f"approve_withdraw:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{uid}"),
        ]
    ]
    try:
        await context.bot.send_message(
            WITHDRAWALS_CHANNEL_ID,
            message_text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Failed to forward to withdrawals channel: {e}")
        await context.bot.send_message(
            ADMIN_ID,
            message_text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    return ConversationHandler.END

# ------------------------
# ADMIN callbacks
# ------------------------
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data_payload = q.data
    if data_payload.startswith("approve_group:") or data_payload.startswith("reject_group:"):
        action, s_uid = data_payload.split(":")
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "pending"}
        if not user_pending:
            await q.edit_message_text("⚠️ No pending submissions found.")
            return
        if action == "reject_group":
            links_text = "\n".join([info["link"] for info in user_pending.values()])
            for key in user_pending:
                data["pending_groups"].pop(key)
            save_data(data)
            await q.edit_message_text(f"❌ Rejected {len(user_pending)} submission(s).")
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"❌ Your submission(s) were rejected:\n{links_text}"
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of rejection.")
            return
        for key, info in user_pending.items():
            info["status"] = "approved_waiting_target"
            data["pending_groups"][key] = info
        save_data(data)
        links_text = "\n".join([info["link"] for info in user_pending.values()])
        await q.edit_message_text(
            f"✅ Approved {len(user_pending)} submission(s). Reply with the buyer @username or numeric ID."
        )
        context.user_data["awaiting_ownership_id"] = {"seller_id": s_uid}
        try:
            await context.bot.send_message(
                int(s_uid),
                f"✅ Your submission(s) approved:\n{links_text}\nAdmin will provide buyer ID soon."
            )
        except:
            logger.warning(f"Failed to notify user {s_uid} of approval.")
        return
    if data_payload.startswith("approve_withdraw:") or data_payload.startswith("reject_withdraw:"):
        action, s_uid = data_payload.split(":")
        if s_uid not in data["pending_withdrawals"]:
            await q.edit_message_text("⚠️ Withdrawal not found or already processed.")
            return
        wd = data["pending_withdrawals"][s_uid]
        hist = data["users"].get(s_uid, {}).get("withdraw_history", [])
        for rec in reversed(hist):
            if rec["status"] == "Pending" and rec["amount"] == wd["amount"] and rec["method"] == wd["method"]:
                rec["status"] = "Success" if action == "approve_withdraw" else "Rejected"
                break
        confirm_text = (
            f"💸 *Withdrawal Request Update*\n"
            f"Amount: ${wd['amount']:.2f}\n"
            f"Method: {wd['method'].upper()}\n"
            f"Address/ID: {wd['address']}\n"
            f"Time: {wd['time']}\n"
            f"Status: {'Success' if action == 'approve_withdraw' else 'Rejected'}"
        )
        if action == "approve_withdraw":
            data["users"][s_uid]["balance"] = max(0.0, data["users"][s_uid]["balance"] - wd["amount"])
            data["pending_withdrawals"].pop(s_uid)
            save_data(data)
            await q.edit_message_text(f"✅ Withdrawal marked as paid (Success).")
            try:
                await context.bot.send_message(int(s_uid), confirm_text, parse_mode="Markdown")
            except:
                logger.warning(f"Failed to notify user {s_uid} of withdrawal approval.")
        else:
            data["pending_withdrawals"].pop(s_uid)
            save_data(data)
            await q.edit_message_text(f"❌ Withdrawal rejected.")
            try:
                await context.bot.send_message(int(s_uid), confirm_text, parse_mode="Markdown")
            except:
                logger.warning(f"Failed to notify user {s_uid} of withdrawal rejection.")
        return
    if data_payload.startswith("submit_ownership:"):
        s_uid = data_payload.split(":")[1]
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "approved_waiting_target"}
        if not user_pending:
            await q.edit_message_text("⚠️ No pending submissions found.")
            return
        if str(q.from_user.id) != s_uid:
            await q.answer("❌ Only the seller can press this.")
            return
        for key, info in user_pending.items():
            info["ownership_status"] = "transferred"
            data["pending_groups"][key] = info
        save_data(data)
        links_text = "\n".join([info["link"] for info in user_pending.values()])
        kb = [
            [
                InlineKeyboardButton("✅ Verify Ownership", callback_data=f"verify_ownership:{s_uid}"),
                InlineKeyboardButton("❌ Ownership Failed", callback_data=f"reject_ownership:{s_uid}"),
            ]
        ]
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"👤 Seller submitted ownership transfer:\n{links_text}\nTarget: {list(user_pending.values())[0].get('ownership_target_id')}\nPlease verify.",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            logger.warning(f"Failed to notify admin for ownership verification.")
        await q.edit_message_text(f"✅ Ownership submitted for {len(user_pending)} link(s). Admin will verify.")
        return
    if data_payload.startswith("verify_ownership:") or data_payload.startswith("reject_ownership:"):
        action, s_uid = data_payload.split(":")
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "approved_waiting_target"}
        if not user_pending:
            await q.edit_message_text("⚠️ No pending ownership records.")
            return
        if action == "verify_ownership":
            custom_prices = data["users"][s_uid].get("custom_prices", {})
            global_prices = data.get("global_prices", DEFAULT_PRICES)
            total_credited = 0.0
            for key, info in user_pending.items():
                year = info.get("year")
                price_str = custom_prices.get(year, global_prices.get(year, "1$"))
                try:
                    price = float(price_str.replace("$", ""))
                except ValueError:
                    price = 1.0
                total_credited += price * info.get("seller_count", 1)
                data["users"][s_uid]["sales"] = data["users"][s_uid].get("sales", 0) + 1
                data["pending_groups"].pop(key)
            data["users"][s_uid]["balance"] += total_credited
            save_data(data)
            links_text = "\n".join([info["link"] for info in user_pending.values()])
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"✅ Ownership verified for {len(user_pending)} link(s):\n{links_text}\n${total_credited:.2f} credited."
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of ownership verification.")
            await q.edit_message_text(f"✅ Ownership verified. ${total_credited:.2f} credited to seller.")
        else:
            for key, info in user_pending.items():
                info["ownership_status"] = "failed"
                data["pending_groups"][key] = info
            save_data(data)
            links_text = "\n".join([info["link"] for info in user_pending.values()])
            try:
                await context.bot.send_message(
                    int(s_uid),
                    f"❌ Ownership verification failed for:\n{links_text}\nPlease re-transfer and submit again."
                )
            except:
                logger.warning(f"Failed to notify user {s_uid} of ownership failure.")
            await q.edit_message_text(f"❌ Ownership verification failed for {len(user_pending)} link(s).")
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
        [InlineKeyboardButton("🔍 Inspect User", callback_data="admin_inspect_user")],
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
    if key == "admin_pending_groups":
        if not data["pending_groups"]:
            await q.edit_message_text("📭 No pending groups/folders.")
            return ADMIN_PANEL
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
            links_text = "\n".join([f"- {info['link']} ({'Folder' if 'addlist' in info['link'] else 'Single'}, Est. groups: {info['seller_count']})" for info in infos])
            await context.bot.send_message(
                ADMIN_ID,
                f"👤 Seller ID: {seller_id}\nLinks:\n{links_text}\nSubmitted: {infos[0]['time']}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.edit_message_text("📋 Pending groups/folders sent to your chat.")
        return ADMIN_PANEL
    if key == "admin_pending_withdrawals":
        if not data["pending_withdrawals"]:
            await q.edit_message_text("📭 No pending withdrawals.")
            return ADMIN_PANEL
        for s_uid, w in data["pending_withdrawals"].items():
            kb = [
                [
                    InlineKeyboardButton("✅ Approve (Paid)", callback_data=f"approve_withdraw:{s_uid}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{s_uid}"),
                ],
            ]
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 Withdrawal: {s_uid}\nAmount: ${w['amount']:.2f}\nMethod: {w['method']}\nAddress: {w['address']}\nTime: {w['time']}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.edit_message_text("💸 Pending withdrawals sent to your chat.")
        return ADMIN_PANEL
    if key == "admin_add_balance":
        context.user_data["admin_mode"] = "add_balance"
        await q.edit_message_text("➕ Send user ID to add balance:")
        return ADMIN_ADD_USER
    if key == "admin_inspect_user":
        context.user_data["admin_mode"] = "inspect_user"
        await q.edit_message_text("🔍 Send user ID to inspect:")
        return ADMIN_INSPECT_USER
    if key == "admin_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await q.edit_message_text("📢 Send broadcast message:")
        return ADMIN_BROADCAST
    await q.edit_message_text("⚠️ Unknown action.")
    return ADMIN_PANEL

async def admin_add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid user ID.")
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
        await update.message.reply_text("❌ Invalid amount.")
        return ADMIN_ADD_AMOUNT
    uid = context.user_data.pop("target_user", None)
    if uid is None:
        await update.message.reply_text("❌ No target user set.")
        return ConversationHandler.END
    ensure_user(uid)
    data["users"][str(uid)]["balance"] += amt
    save_data(data)
    await update.message.reply_text(f"✅ Added ${amt:.2f} to {uid}. Balance: ${data['users'][str(uid)]['balance']:.2f}")
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
        f"🛒 Groups submitted: {len(u.get('groups', []))}\n"
        f"✅ Sales: {u.get('sales', 0)}\n"
        f"⏳ Pending groups: {', '.join(pending_g) if pending_g else 'None'}\n"
        f"⏳ Pending withdraw: {f'${pending_w['amount']:.2f} via {pending_w['method']}' if pending_w else 'None'}\n"
        f"📝 Withdraw history (last 5):\n"
    )
    for rec in u.get("withdraw_history", [])[-5:]:
        text += f"- {rec['time']}: ${rec['amount']:.2f} via {rec['method']} — {rec['status']}\n"
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
    for s_uid in data["users"]:
        try:
            await context.bot.send_message(int(s_uid), f"📢 Admin Broadcast:\n\n{text}")
            count += 1
        except:
            logger.warning(f"Failed to broadcast to {s_uid}.")
    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")
    return ADMIN_PANEL

# ------------------------
# Router for reply-keyboard and ownership ID
# ------------------------
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and context.user_data.get("awaiting_ownership_id"):
        info = context.user_data.pop("awaiting_ownership_id")
        target_id = (update.message.text or "").strip()
        seller_id = info.get("seller_id")
        user_pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id and v["status"] == "approved_waiting_target"}
        if not user_pending:
            await update.message.reply_text("⚠️ No pending submissions found.")
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
                f"📢 Transfer ownership for:\n{links_text}\nTo: {target_id}\n\n"
                "Press the button below after transferring.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Ownership Submitted", callback_data=f"submit_ownership:{seller_id}")]
                ])
            )
        except:
            logger.warning(f"Failed to notify seller {seller_id}.")
        await update.message.reply_text(f"✅ Buyer ID {target_id} set for {len(user_pending)} link(s).")
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
    elif txt == "📊 Stats" and uid == ADMIN_ID:
        await cmd_stats(update, context)
    else:
        await update.message.reply_text("⚠️ Use buttons or commands.")

# ========================
# App setup
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry), MessageHandler(filters.Regex("🛍 Sell$"), cmd_sell_entry)],
        states={
            SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)],
            SELL_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_year)],
            SELL_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_count)],
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("cancel", universal_cancel))
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
