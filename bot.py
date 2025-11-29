import json
import logging
import re
import datetime
import os
from pathlib import Path
from collections import defaultdict
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
# CONFIG - MUST SET IN ENV
# ========================
BOT_TOKEN = os.getenv("8075394934:AAHU9tRE9vemQIDzxRuX4UhxMUtw5mSlMy4")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required!")

OWNER_ID = int(os.getenv("5405985282", "0"))
if OWNER_ID == 0:
    raise ValueError("Set OWNER_ID in environment!")

LINKS_CHANNEL = os.getenv("LINKS_CHANNEL", "-1003234042802")
WITHDRAW_CHANNEL = os.getenv("WITHDRAW_CHANNEL", "-1003224533856")
DATA_PATH = Path("data.json")

DEFAULT_PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$",
}
MAX_LINKS_PER_SUBMISSION = 10

# ========================
# Logging
# ========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================
# Data & Admin System
# ========================
def load_data():
    try:
        if not DATA_PATH.exists():
            return {
                "users": {},
                "pending_groups": {},
                "pending_withdrawals": {},
                "pending_requests": {},
                "sell_enabled": True,
                "global_prices": DEFAULT_PRICES,
                "admins": [OWNER_ID],
                "completed_sales": {}
            }
        return json.loads(DATA_PATH.read_text(encoding="utf8"))
    except Exception as e:
        logger.error(f"Corrupted data.json: {e}")
        return {
            "users": {}, "pending_groups": {}, "pending_withdrawals": {}, "pending_requests": {},
            "sell_enabled": True, "global_prices": DEFAULT_PRICES, "admins": [OWNER_ID], "completed_sales": {}
        }

def save_data(data_obj):
    try:
        DATA_PATH.write_text(json.dumps(data_obj, indent=2, ensure_ascii=False), encoding="utf8")
    except Exception as e:
        logger.error(f"Save failed: {e}")

data = load_data()
ADMIN_IDS = set(data.get("admins", [OWNER_ID]))
if OWNER_ID not in ADMIN_IDS:
    ADMIN_IDS.add(OWNER_ID)

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def save_admins():
    data["admins"] = list(ADMIN_IDS)
    save_data(data)

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {
            "balance": 0.0,
            "groups": [],
            "sales": 0,
            "withdraw_history": [],
            "custom_prices": {},
            "start_time": now(),
            "completed_sales": []
        }
        save_data(data)

# ========================
# Utils
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
    return regex and bool(re.match(regex, address, re.IGNORECASE))

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

def is_within_24_hours(timestamp: str) -> bool:
    try:
        dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return (datetime.datetime.utcnow() - dt).total_seconds() <= 86400
    except:
        return False

# ========================
# States
# ========================
SELL_TYPE, SELL_LINK, SELL_YEAR = range(1, 4)
WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 13)
ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER, ADMIN_BROADCAST = range(20, 25)

# ========================
# Keyboard & Commands
# ========================
COMMANDS = [
    BotCommand("start", "Open bot"),
    BotCommand("price", "Show prices"),
    BotCommand("sell", "Sell group"),
    BotCommand("withdraw", "Request withdrawal"),
    BotCommand("balance", "Check balance"),
    BotCommand("stats", "Bot stats (admin)"),
    BotCommand("admin", "Admin panel"),
    BotCommand("cancel", "Cancel"),
]

def get_keyboard(uid: int):
    if is_admin(uid):
        kb = [["Start", "Prices"], ["Sell", "Stats"], ["Admin"]]
    else:
        kb = [["Start", "Prices"], ["Sell", "Withdraw"], ["Balance"]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ========================
# Basic Commands
# ========================
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    await context.bot.set_my_commands(COMMANDS if is_admin(uid) else COMMANDS[:5])
    await update.message.reply_text(
        "Welcome to Group Marketplace Bot!\nUse buttons below.",
        reply_markup=get_keyboard(uid)
    )

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    text = "*Current Prices*\n\n"
    custom = data["users"][str(uid)].get("custom_prices", {})
    if custom:
        text += "*Your Custom Prices:*\n"
        for k, v in custom.items():
            text += f"• {k}: {v}\n"
        text += "\n"
    text += "*Global Prices:*\n"
    for k, v in data.get("global_prices", DEFAULT_PRICES).items():
        text += f"• {k}: {v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"Your balance: ${bal:.2f}")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    total_users = len(data["users"])
    new_24h = sum(1 for u in data["users"].values() if is_within_24_hours(u.get("start_time", "")))
    total_sold = sum(u.get("sales", 0) for u in data["users"].values())
    sold_24h = sum(
        s.get("count", 0) for u in data["users"].values()
        for s in u.get("completed_sales", [])
        if is_within_24_hours(s.get("time", ""))
    )
    await update.message.reply_text(
        f"*Bot Statistics*\n\n"
        f"Total Users: {total_users}\n"
        f"New (24h): {new_24h}\n"
        f"Groups Sold: {total_sold}\n"
        f"Sold (24h): {sold_24h}",
        parse_mode="Markdown"
    )

# ========================
# SELL FLOW
# ========================
async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not data.get("sell_enabled", True):
        await update.message.reply_text("Selling is temporarily disabled.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton("Single Group", callback_data="sell_type_single")],
        [InlineKeyboardButton("Folder", callback_data="sell_type_folder")],
    ]
    await update.message.reply_text("Choose type:", reply_markup=InlineKeyboardMarkup(kb))
    return SELL_TYPE

async def sell_choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["sell_type"] = q.data.split("_")[-1]
    await q.edit_message_text(
        "Send group/folder link(s)\n"
        f"• Max {MAX_LINKS_PER_SUBMISSION} per submission\n"
        "• Separate by space or new line\n"
        "Example: t.me/+ABC123"
    )
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    links = [l.strip() for l in re.split(r"\s+", text) if l.strip()]
    valid = [l for l in links if INVITE_RE.match(l)]
    invalid = [l for l in links if l not in valid]

    if not valid:
        await update.message.reply_text(f"No valid links.\nInvalid: {', '.join(invalid[:5])}")
        return SELL_LINK
    if len(valid) > MAX_LINKS_PER_SUBMISSION:
        await update.message.reply_text(f"Max {MAX_LINKS_PER_SUBMISSION} links allowed.")
        return SELL_LINK

    uid = update.effective_user.id
    s_uid = str(uid)
    existing = data["users"][s_uid].get("groups", [])
    dupes = [l for l in valid if l in existing]
    if dupes:
        await update.message.reply_text(f"Already submitted:\n" + "\n".join(dupes))
        return SELL_LINK

    context.user_data["sell_links"] = valid
    await update.message.reply_text(
        f"{len(valid)} link(s) accepted!\n\n"
        "Now send year range:\n"
        "Examples: `2023`, `2016-22`, `2024 (5-6)`",
        parse_mode="Markdown"
    )
    return SELL_YEAR
    async def sell_receive_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = update.message.text.strip()
    uid = update.effective_user.id
    s_uid = str(uid)
    links = context.user_data.get("sell_links", [])

    prices = {**data.get("global_prices", {}), **data["users"][s_uid].get("custom_prices", {})}
    if year not in prices:
        await update.message.reply_text(f"Invalid year.\nAvailable: {', '.join(prices.keys())}")
        return SELL_YEAR

    # Save pending groups
    for link in links:
        key = f"{s_uid}:{link}"
        data["pending_groups"][key] = {
            "link": link,
            "year": year,
            "time": now(),
            "seller_id": s_uid,
            "type": context.user_data["sell_type"],
            "status": "pending"
        }
        if link not in data["users"][s_uid]["groups"]:
            data["users"][s_uid]["groups"].append(link)
    save_data(data)

    # Notify admins
    kb = [[
        InlineKeyboardButton("Approve", callback_data=f"approve_group:{s_uid}"),
        InlineKeyboardButton("Reject", callback_data=f"reject_group:{s_uid}")
    ]]
    text = (
        f"New submission\n"
        f"User: {uid} (@{update.effective_user.username or 'NoUsername'})\n"
        f"Links ({len(links)}):\n" + "\n".join(links) + f"\nYear: {year}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, reply_markup=InlineKeyboardMarkup(kb))
        except:
            pass
    await context.bot.send_message(LINKS_CHANNEL, text)

    await update.message.reply_text("Submitted for review! You will be notified.")
    return ConversationHandler.END

# ========================
# WITHDRAW FLOW
# ========================
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.message.reply_text("Admins cannot withdraw.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton("UPI", callback_data="method_upi")],
        [InlineKeyboardButton("Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("Polygon USDT", callback_data="method_polygon")],
    ]
    await update.message.reply_text("Select withdrawal method:", reply_markup=InlineKeyboardMarkup(kb))
    return WITHDRAW_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["withdraw_method"] = q.data.replace("method_", "")
    await q.edit_message_text(f"Selected: {q.data.replace('method_', '').upper()}\nSend address/UID:")
    return WITHDRAW_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = update.message.text.strip()
    method = context.user_data["withdraw_method"]
    if not validate_address(method, addr):
        await update.message.reply_text("Invalid address. Try again.")
        return WITHDRAW_ADDRESS
    context.user_data["withdraw_address"] = addr
    await update.message.reply_text("Enter amount to withdraw:")
    return WITHDRAW_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("Invalid amount.")
        return WITHDRAW_AMOUNT

    uid = update.effective_user.id
    s_uid = str(uid)
    bal = data["users"][s_uid]["balance"]
    if amount > bal:
        await update.message.reply_text(f"Insufficient balance. You have ${bal:.2f}")
        return ConversationHandler.END

    data["pending_withdrawals"][s_uid] = {
        "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"],
        "amount": amount,
        "time": now()
    }
    data["users"][s_uid]["withdraw_history"].append({
        "amount": amount, "method": context.user_data["withdraw_method"],
        "address": context.user_data["withdraw_address"], "status": "Pending", "time": now()
    })
    save_data(data)

    kb = [[
        InlineKeyboardButton("Approve", callback_data=f"approve_withdraw:{uid}"),
        InlineKeyboardButton("Reject", callback_data=f"reject_withdraw:{uid}")
    ]]
    text = f"Withdrawal\nUser: {uid}\n${amount} via {context.user_data['withdraw_method']}\nAddress: {context.user_data['withdraw_address']}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, reply_markup=InlineKeyboardMarkup(kb))
        except:
            pass
    await context.bot.send_message(WITHDRAW_CHANNEL, text)

    await update.message.reply_text("Withdrawal request sent!")
    return ConversationHandler.END

# ========================
# ADMIN CALLBACKS (Groups & Withdrawals)
# ========================
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.edit_message_text("Not authorized.")
        return

    data_payload = q.data

    # === GROUP APPROVAL ===
    if data_payload.startswith(("approve_group:", "reject_group:")):
        action, seller_id = data_payload.split(":")
        s_uid = str(seller_id)
        pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "pending"}

        if action == "reject_group":
            for k in pending:
                data["pending_groups"].pop(k, None)
            save_data(data)
            await q.edit_message_text(f"{len(pending)} submission(s) rejected.")
            try:
                await context.bot.send_message(int(s_uid), f"Your {len(pending)} link(s) were rejected.")
            except:
                pass
            return

        # Approve → ask count if folder, then buyer
        for k, v in pending.items():
            v["status"] = "approved_waiting_count" if v["type"] == "folder" else "approved_waiting_target"
        save_data(data)

        links_text = "\n".join(info["link"] for info in pending.values())
        if any(v["type"] == "folder" for v in pending.values()):
            msg = await context.bot.send_message(q.from_user.id, f"Reply with total group count for user {s_uid}:\n{links_text}")
            data["pending_requests"][str(msg.message_id)] = {"type": "count", "seller_id": s_uid, "time": now()}
        else:
            for k, v in pending.items():
                v["approved_count"] = 1
                v["status"] = "approved_waiting_target"
            save_data(data)
            msg = await context.bot.send_message(q.from_user.id, f"Reply with buyer @username or ID for user {s_uid}:\n{links_text}")
            data["pending_requests"][str(msg.message_id)] = {"type": "buyer", "seller_id": s_uid, "time": now()}
        await q.edit_message_text(f"{len(pending)} submission(s) approved.")
        return

    # === OWNERSHIP SUBMITTED ===
    if data_payload.startswith("submit_ownership:"):
        s_uid = data_payload.split(":")[1]
        if q.from_user.id != int(s_uid):
            await q.answer("Only seller can press this.")
            return
        pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "approved_waiting_target"}
        for k, v in pending.items():
            v["ownership_status"] = "transferred"
        save_data(data)
        links = "\n".join(v["link"] for v in pending.values())
        kb = [
            [InlineKeyboardButton("Verified", callback_data=f"verify_ownership:{s_uid}")],
            [InlineKeyboardButton("Failed", callback_data=f"reject_ownership:{s_uid}")]
        ]
        await context.bot.send_message(q.from_user.id, "Ownership submitted. Awaiting verification.")
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, f"Ownership submitted by {s_uid}:\n{links}", reply_markup=InlineKeyboardMarkup(kb))
        return

    # === FINAL VERIFICATION ===
    if data_payload.startswith(("verify_ownership:", "reject_ownership:")):
        action, s_uid = data_payload.split(":")
        pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == s_uid and v["status"] == "approved_waiting_target"}
        if action == "verify_ownership":
            total_credited = 0.0
            total_groups = 0
            custom = data["users"][s_uid].get("custom_prices", {})
            global_p = data.get("global_prices", {})
            for info in pending.values():
                year = info["year"]
                count = info.get("approved_count", 1)
                price_str = custom.get(year, global_p.get(year, "1$"))
                price = float(price_str.replace("$", "").replace(",", ""))
                total_credited += price * count
                total_groups += count
            data["users"][s_uid]["balance"] += total_credited
            data["users"][s_uid]["sales"] += total_groups
            data["users"][s_uid]["completed_sales"].append({"count": total_groups, "amount": total_credited, "time": now()})
            for k in pending:
                data["pending_groups"].pop(k, None)
            save_data(data)
            await q.edit_message_text(f"Ownership verified! ${total_credited:.2f} credited.")
            await context.bot.send_message(int(s_uid), f"Ownership verified!\n{total_groups} groups → ${total_credited:.2f} added.")
        else:
            for k, v in pending.items():
                v["ownership_status"] = "failed"
            save_data(data)
            await q.edit_message_text("Ownership marked as failed.")
            await context.bot.send_message(int(s_uid), "Ownership verification FAILED. Please re-transfer.")
        return

    # === WITHDRAWAL ===
    if data_payload.startswith(("approve_withdraw:", "reject_withdraw:")):
        action, uid = data_payload.split(":")
        s_uid = str(uid)
        if s_uid not in data["pending_withdrawals"]:
            await q.edit_message_text("Not found.")
            return
        wd = data["pending_withdrawals"].pop(s_uid)
        for h in data["users"][s_uid]["withdraw_history"]:
            if h["status"] == "Pending" and h["amount"] == wd["amount"]:
                h["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break
        if action == "approve_withdraw":
            data["users"][s_uid]["balance"] -= wd["amount"]
        save_data(data)
        status = "approved" if action == "approve_withdraw" else "rejected"
        await q.edit_message_text(f"Withdrawal {status}.")
        await context.bot.send_message(int(s_uid), f"Your ${wd['amount']} withdrawal was {status}.")
        return

# ========================
# ADMIN PANEL & MULTI-ADMIN
# ========================
async def admin_panel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton("Pending Groups", callback_data="admin_pending_groups")],
        [InlineKeyboardButton("Pending Withdrawals", callback_data="admin_pending_withdrawals")],
        [InlineKeyboardButton("Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("Custom Prices", callback_data="admin_custom")],
        [InlineKeyboardButton("Inspect User", callback_data="admin_inspect_user")],
        [InlineKeyboardButton("Toggle Sell", callback_data="admin_toggle_sell")],
        [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("Admins Management", callback_data="admin_manage_admins")],
    ]
    await update.message.reply_text("Admin Panel", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_PANEL

# ========================
# ADMIN PANEL CALLBACKS (Full Multi-Admin System)
# ========================
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.edit_message_text("Not authorized.")
        return ADMIN_PANEL

    key = q.data

    # === Pending Groups List ===
    if key == "admin_pending_groups":
        pending = [v for v in data["pending_groups"].values() if v["status"] == "pending"]
        if not pending:
            await q.edit_message_text("No pending submissions.")
            return ADMIN_PANEL
        grouped = {}
        for info in pending:
            grouped.setdefault(info["seller_id"], []).append(info)
        for seller_id, items in grouped.items():
            links = "\n".join(f"• {i['link']} ({i['year']})" for i in items)
            kb = [[
                InlineKeyboardButton("Approve", callback_data=f"approve_group:{seller_id}"),
                InlineKeyboardButton("Reject", callback_data=f"reject_group:{seller_id}")
            ]]
            await context.bot.send_message(
                q.from_user.id,
                f"Pending from {seller_id}\n{links}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.edit_message_text("Check your DMs for pending submissions.")
        return ADMIN_PANEL

    # === Pending Withdrawals ===
    if key == "admin_pending_withdrawals":
        if not data["pending_withdrawals"]:
            await q.edit_message_text("No pending withdrawals.")
            return ADMIN_PANEL
        for uid, w in data["pending_withdrawals"].items():
            kb = [[
                InlineKeyboardButton("Approve", callback_data=f"approve_withdraw:{uid}"),
                InlineKeyboardButton("Reject", callback_data=f"reject_withdraw:{uid}")
            ]]
            await context.bot.send_message(
                q.from_user.id,
                f"{uid} → ${w['amount']} via {w['method']}\n{w['address']}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.edit_message_text("Check DMs for withdrawals.")
        return ADMIN_PANEL

    # === Add Balance ===
    if key == "admin_add_balance":
        context.user_data["admin_mode"] = "add_balance"
        await q.edit_message_text("Send user ID to add balance:")
        return ADMIN_ADD_USER

    # === Inspect User ===
    if key == "admin_inspect_user":
        context.user_data["admin_mode"] = "inspect"
        await q.edit_message_text("Send user ID to inspect:")
        return ADMIN_INSPECT_USER

    # === Toggle Sell ===
    if key == "admin_toggle_sell":
        data["sell_enabled"] = not data.get("sell_enabled", True)
        save_data(data)
        await q.edit_message_text(f"Selling: {'ON' if data['sell_enabled'] else 'OFF'}")
        return ADMIN_PANEL

    # === Broadcast ===
    if key == "admin_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await q.edit_message_text("Send broadcast message:")
        return ADMIN_BROADCAST

    # === Admins Management (Only Owner) ===
    if key == "admin_manage_admins":
        if q.from_user.id != OWNER_ID:
            await q.edit_message_text("Only the Owner can manage admins.")
            return ADMIN_PANEL
        kb = [
            [InlineKeyboardButton("Add Admin", callback_data="admin_add")],
            [InlineKeyboardButton("Remove Admin", callback_data="admin_remove")],
            [InlineKeyboardButton("List Admins", callback_data="admin_list")],
            [InlineKeyboardButton("Back", callback_data="admin_back")]
        ]
        await q.edit_message_text(
            f"Admins Management\nCurrent: {len(ADMIN_IDS)}\nOnly Owner can do this.",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return ADMIN_PANEL

    if key == "admin_add":
        if q.from_user.id != OWNER_ID:
            return ADMIN_PANEL
        context.user_data["awaiting_admin_id"] = True
        await q.edit_message_text("Send @username or numeric ID of new admin:")
        return ADMIN_PANEL

    if key == "admin_remove":
        if q.from_user.id != OWNER_ID:
            return ADMIN_PANEL
        if len(ADMIN_IDS) <= 1:
            await q.edit_message_text("Cannot remove last admin.")
            return ADMIN_PANEL
        kb = []
        for aid in ADMIN_IDS:
            if aid == OWNER_ID: continue
            kb.append([InlineKeyboardButton(f"Remove {aid}", callback_data=f"remove_admin:{aid}")])
        kb.append([InlineKeyboardButton("Back", callback_data="admin_manage_admins")])
        await q.edit_message_text("Select admin to remove:", reply_markup=InlineKeyboardMarkup(kb))
        return ADMIN_PANEL

    if key == "admin_list":
        text = "*Current Admins:*\n"
        for i, aid in enumerate(sorted(ADMIN_IDS), 1):
            text += f"{i}. <code>{aid}</code>{' (Owner)' if aid == OWNER_ID else ''}\n"
        await q.edit_message_text(text, parse_mode="Markdown")
        return ADMIN_PANEL

    if key.startswith("remove_admin:"):
        if q.from_user.id != OWNER_ID:
            return ADMIN_PANEL
        remove_id = int(key.split(":")[1])
        if remove_id == OWNER_ID:
            await q.edit_message_text("Cannot remove Owner.")
            return ADMIN_PANEL
        ADMIN_IDS.remove(remove_id)
        save_admins()
        await q.edit_message_text(f"Admin {remove_id} removed.")
        try:
            await context.bot.send_message(remove_id, "You have been removed from bot admins.")
        except:
            pass
        return ADMIN_PANEL

    if key == "admin_back":
        return await admin_panel_entry(update, context)

    # === Custom Prices Menu ===
    if key == "admin_custom":
        kb = [
            [InlineKeyboardButton("Set Custom Price", callback_data="custom_set")],
            [InlineKeyboardButton("Remove Custom Price", callback_data="custom_remove")],
            [InlineKeyboardButton("View User Prices", callback_data="custom_view")],
            [InlineKeyboardButton("Set Global Prices", callback_data="global_prices")]
        ]
        await q.edit_message_text("Custom Prices Menu:", reply_markup=InlineKeyboardMarkup(kb))
        return ADMIN_PANEL

    await q.edit_message_text("Unknown action.")
    return ADMIN_PANEL

# ========================
# Text Handlers for Admin Modes
# ========================
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    mode = context.user_data.get("admin_mode")
    text = update.message.text.strip()

    # === Add Balance ===
    if mode == "add_balance":
        try:
            uid = int(text)
            context.user_data["target_user"] = uid
            context.user_data["admin_mode"] = "add_amount"
            await update.message.reply_text(f"Send amount to add to {uid}:")
        except:
            await update.message.reply_text("Invalid ID.")
        return

    if mode == "add_amount":
        try:
            amt = float(text)
            uid = context.user_data.pop("target_user", None)
            ensure_user(uid)
            data["users"][str(uid)]["balance"] += amt
            save_data(data)
            await update.message.reply_text(f"Added ${amt} to {uid}\nNew balance: ${data['users'][str(uid)]['balance']:.2f}")
            try:
                await context.bot.send_message(uid, f"Admin added ${amt} to your balance!")
            except:
                pass
            context.user_data.pop("admin_mode", None)
        except:
            await update.message.reply_text("Invalid amount.")
        return

    # === Inspect User ===
    if mode == "inspect":
        try:
            uid = int(text)
            ensure_user(uid)
            u = data["users"][str(uid)]
            await update.message.reply_text(
                f"User: {uid}\n"
                f"Balance: ${u['balance']:.2f}\n"
                f"Sales: {u.get('sales', 0)}\n"
                f"Submitted: {len(u.get('groups', []))}\n"
                f"Custom Prices: {u.get('custom_prices', 'None')}"
            )
            context.user_data.pop("admin_mode", None)
        except:
            await update.message.reply_text("Invalid ID.")
        return

    # === Broadcast ===
    if mode == "broadcast":
        count = 0
        for uid in data["users"]:
            try:
                await context.bot.send_message(int(uid), f"Announcement:\n\n{text}")
                count += 1
            except:
                pass
        await update.message.reply_text(f"Broadcast sent to {count} users.")
        context.user_data.pop("admin_mode", None)
        return

    # === Add New Admin (from text) ===
    if context.user_data.get("awaiting_admin_id"):
        new_id = None
        if text.isdigit():
            new_id = int(text)
        else:
            try:
                chat = await context.bot.get_chat(text)
                new_id = chat.id
            except:
                await update.message.reply_text("User not found.")
                return
        if new_id in ADMIN_IDS:
            await update.message.reply_text("Already an admin.")
        else:
            ADMIN_IDS.add(new_id)
            save_admins()
            await update.message.reply_text(f"Added admin: {new_id}")
            try:
                await context.bot.send_message(new_id, "You are now an admin!")
            except:
                pass
        context.user_data.pop("awaiting_admin_id", None)
        return

# ========================
# Register Admin Panel Handlers
# ========================
# Add these in main():
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^(custom_|global_prices|remove_admin:)"))

# Update admin_conv states:
admin_conv = ConversationHandler(
    entry_points=[CommandHandler("admin", admin_panel_entry), MessageHandler(filters.Regex("^Admin$"), admin_panel_entry)],
    states={
        ADMIN_PANEL: [CallbackQueryHandler(admin_panel_callback)],
        ADMIN_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text)],
        ADMIN_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text)],
        ADMIN_INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text)],
        ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text)],
    },
    fallbacks=[CommandHandler("cancel", universal_cancel)],
    allow_reentry=True,
)

# ========================
# UNIVERSAL CANCEL
# ========================
async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ========================
# MAIN ROUTER (buttons + pending replies)
# ========================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message else ""
    uid = update.effective_user.id

    if text == "Start":
        await on_start(update, context)
    elif text == "Prices":
        await cmd_price(update, context)
    elif text == "Sell":
        return await cmd_sell_entry(update, context)
    elif text == "Withdraw":
        return await cmd_withdraw_entry(update, context)
    elif text == "Balance":
        await cmd_balance(update, context)
    elif text == "Stats" and is_admin(uid):
        await cmd_stats(update, context)
    elif text == "Admin" and is_admin(uid):
        return await admin_panel_entry(update, context)

# ========================
# APP SETUP
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry), MessageHandler(filters.Regex("^Sell$"), cmd_sell_entry)],
        states={
            SELL_TYPE: [CallbackQueryHandler(sell_choose_type, "^sell_type_")],
            SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)],
            SELL_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_year)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", cmd_withdraw_entry), MessageHandler(filters.Regex("^Withdraw$"), cmd_withdraw_entry)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_choose_method, "^method_")],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
    )

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel_entry), MessageHandler(filters.Regex("^Admin$"), admin_panel_entry)],
        states={ADMIN_PANEL: [CallbackQueryHandler(admin_panel_entry, "^admin_")]},
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        allow_reentry=True,
    )

    app.add_handler(sell_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(admin_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("stats", cmd_stats))

    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
