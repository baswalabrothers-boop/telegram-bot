# final_advanced_marketplace_bot.py
import json
import logging
import re
import datetime
from pathlib import Path
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# =========================
# CONFIG - set these
# =========================
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282  # <- Replace with your numeric Telegram ID (single admin)

DATA_FILE = Path("data.json")

# Default prices (will be editable via admin)
DEFAULT_PRICES = {
    "2016-22": "11$",
    "2023": "6$",
    "2024 (1-3)": "5$",
    "2024 (4)": "4$",
    "2024 (5-6)": "1$"
}

# Invite link regex (relaxed)
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/)[A-Za-z0-9_-]+$",
    flags=re.IGNORECASE
)

# Conversation states
(
    SELL_LINK,
    WD_METHOD, WD_ADDRESS, WD_AMOUNT,
    ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER, ADMIN_BROADCAST,
    SETPRICE_KEY, SETPRICE_VALUE
) = range(20)

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# Persistence helpers
# =========================
def load_data():
    if not DATA_FILE.exists():
        base = {
            "users": {},                 # user_id -> {"balance": float, "groups": [], "sales": int, "joined": date, "withdraw_history": []}
            "pending_groups": {},        # user_id -> {"link":..., "time":...}
            "pending_withdrawals": {},   # user_id -> {"method":..., "address":..., "amount":..., "time":...}
            "banned": [],                # list of user_ids
            "prices": DEFAULT_PRICES.copy(),
            "stats": {                   # aggregate stats
                "total_credited": 0.0,
                "total_groups_sold": 0,
                "joins_by_date": {}     # "YYYY-MM-DD" -> count
            }
        }
        save_data(base)
        return base
    return json.loads(DATA_FILE.read_text(encoding="utf8"))

def save_data(d):
    DATA_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf8")

data = load_data()

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {
            "balance": 0.0,
            "groups": [],
            "sales": 0,
            "joined": datetime.date.today().isoformat(),
            "withdraw_history": []
        }
        # track join
        today = datetime.date.today().isoformat()
        data["stats"]["joins_by_date"].setdefault(today, 0)
        data["stats"]["joins_by_date"][today] += 1
        save_data(data)

def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"

# =========================
# Command menu for Telegram UI
# =========================
COMMANDS = [
    BotCommand("start", "Open the bot"),
    BotCommand("price", "Show group prices"),
    BotCommand("sell", "Sell your group"),
    BotCommand("withdraw", "Request payout"),
    BotCommand("balance", "Check your balance"),
    BotCommand("cancel", "Cancel current action"),
    BotCommand("admin", "Open admin panel (admin only)"),
    BotCommand("overview", "Admin overview (admin only)"),
]

# =========================
# Reply keyboard
# =========================
def main_kb(is_admin=False):
    kb = [
        ["🏠 Start", "💰 Prices"],
        ["🛍 Sell", "💸 Withdraw"],
        ["💵 Balance"]
    ]
    if is_admin:
        kb.append(["🧑‍💻 Admin"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# =========================
# Basic user commands
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands(COMMANDS)
    user = update.effective_user
    ensure_user(user.id)
    await update.message.reply_text(
        "👋 Welcome to Group Marketplace!\nUse the buttons or commands to operate.",
        reply_markup=main_kb(user.id == ADMIN_ID)
    )

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Current Group Prices*\n\n"
    for k, v in data["prices"].items():
        text += f"📅 {k}: {v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if uid in data["banned"]:
        await update.message.reply_text("🚫 You are banned.")
        return
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"💰 Your balance: ${bal:.2f}")

# =========================
# SELL conversation
# =========================
async def sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in data["banned"]:
        await update.message.reply_text("🚫 You are banned.")
        return ConversationHandler.END
    ensure_user(uid)
    context.user_data["in_sell"] = True
    await update.message.reply_text(
        "📎 Send your Telegram group invite link (examples: https://t.me/joinchat/AAAA or https://t.me/+AbCd)\n"
        "Type /cancel to stop. You have 10 minutes.",
        parse_mode="Markdown"
    )
    return SELL_LINK

async def sell_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.user_data.get("in_sell"):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if not INVITE_RE.match(text):
        await update.message.reply_text("❌ Invalid Telegram invite link. Send a valid link or /cancel.")
        return SELL_LINK
    # store pending group
    s_uid = str(uid)
    data["pending_groups"][s_uid] = {"link": text, "time": now_iso()}
    data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"joined":datetime.date.today().isoformat(),"withdraw_history":[]})
    data["users"][s_uid]["groups"].append(text)
    save_data(data)
    context.user_data.pop("in_sell", None)
    # notify admin with approve/reject
    kb = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{s_uid}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{s_uid}")]
    ]
    await context.bot.send_message(ADMIN_ID,
        f"🆕 New group submission\nUser: @{update.effective_user.username or update.effective_user.first_name} (ID:{uid})\nLink: {text}\nTime: {now_iso()}",
        reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Submitted to admin for review. You'll be notified after review.")
    return ConversationHandler.END

# =========================
# WITHDRAW conversation
# =========================
async def withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in data["banned"]:
        await update.message.reply_text("🚫 You are banned.")
        return ConversationHandler.END
    ensure_user(uid)
    # show last few withdraws
    last = data["users"][str(uid)]["withdraw_history"][-5:]
    if last:
        lines = [f"{r['time']}: {r['amount']}$ via {r['method']} — {r['status']}" for r in last]
        await update.message.reply_text("🧾 Recent withdrawals:\n" + "\n".join(lines))
    # show methods
    kb = [
        [InlineKeyboardButton("🏦 UPI", callback_data="method_upi")],
        [InlineKeyboardButton("🏦 Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("💵 BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("💰 Polygon USDT", callback_data="method_polygon")],
    ]
    await update.message.reply_text("Select withdrawal method:", reply_markup=InlineKeyboardMarkup(kb))
    return WD_METHOD

async def withdraw_choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    if user.id in data["banned"]:
        await q.edit_message_text("🚫 You are banned.")
        return ConversationHandler.END
    context.user_data["wd_method"] = q.data.replace("method_", "")
    await q.edit_message_text(f"📤 Selected: *{context.user_data['wd_method'].upper()}*\nSend your address / UPI / UID:", parse_mode="Markdown")
    return WD_ADDRESS

async def withdraw_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["wd_address"] = update.message.text.strip()
    await update.message.reply_text("💰 Enter the amount to withdraw:")
    return WD_AMOUNT

async def withdraw_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        amount = float((update.message.text or "").strip())
        if amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("❌ Invalid amount. Send numeric value.")
        return WD_AMOUNT
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    if amount > bal:
        await update.message.reply_text(f"⚠️ Insufficient balance. Your balance: ${bal:.2f}")
        return ConversationHandler.END
    # record pending withdraw
    s_uid = str(uid)
    data["pending_withdrawals"][s_uid] = {
        "method": context.user_data["wd_method"],
        "address": context.user_data["wd_address"],
        "amount": amount,
        "time": now_iso()
    }
    rec = {"method": context.user_data["wd_method"], "address": context.user_data["wd_address"], "amount": amount, "status": "Pending", "time": now_iso()}
    data["users"][s_uid]["withdraw_history"].append(rec)
    save_data(data)
    kb = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{s_uid}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{s_uid}")]
    ]
    await context.bot.send_message(ADMIN_ID,
        f"💸 Withdrawal request\nUser: {uid}\nAmount: {amount}$\nMethod: {rec['method']}\nAddress: {rec['address']}\nTime: {rec['time']}",
        reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Withdrawal request sent to admin.")
    return ConversationHandler.END

# =========================
# Universal cancel (works for all conv handlers)
# =========================
async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # clear user_data keys that may cause ghost behavior
    keys = ["in_sell", "wd_method", "wd_address", "admin_mode", "target_user", "setprice_key"]
    for k in keys:
        context.user_data.pop(k, None)
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

# =========================
# Admin approve/reject callbacks
# =========================
async def admin_approve_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    payload = q.data
    # Group approve/reject
    if payload.startswith("approve_group:") or payload.startswith("reject_group:"):
        action, s_uid = payload.split(":")
        if s_uid not in data["pending_groups"]:
            await q.edit_message_text("⚠️ Submission not found or already processed.")
            return
        info = data["pending_groups"].pop(s_uid)
        save_data(data)
        if action == "approve_group":
            # increment sold stats
            data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"joined":datetime.date.today().isoformat(),"withdraw_history":[]})
            data["users"][s_uid]["sales"] = data["users"][s_uid].get("sales",0) + 1
            data["stats"]["total_groups_sold"] = data["stats"].get("total_groups_sold", 0) + 1
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

    # Withdraw approve/reject
    if payload.startswith("approve_withdraw:") or payload.startswith("reject_withdraw:"):
        action, s_uid = payload.split(":")
        if s_uid not in data["pending_withdrawals"]:
            await q.edit_message_text("⚠️ Withdrawal not found or already processed.")
            return
        wd = data["pending_withdrawals"].pop(s_uid)
        # update history
        for rec in reversed(data["users"].get(s_uid, {}).get("withdraw_history", [])):
            if rec["status"] == "Pending" and rec["amount"] == wd["amount"] and rec["method"] == wd["method"]:
                rec["status"] = "Approved" if action == "approve_withdraw" else "Rejected"
                break
        if action == "approve_withdraw":
            # deduct balance
            data["users"].setdefault(s_uid, {"balance":0.0,"groups":[],"sales":0,"joined":datetime.date.today().isoformat(),"withdraw_history":[]})
            data["users"][s_uid]["balance"] = max(0.0, data["users"][s_uid]["balance"] - float(wd["amount"]))
            data["stats"]["total_credited"] = data["stats"].get("total_credited", 0.0) + float(wd["amount"])
            save_data(data)
            try:
                await context.bot.send_message(int(s_uid), f"✅ Your withdrawal of ${wd['amount']} has been approved and processed.")
            except:
                pass
            await q.edit_message_text("✅ Withdrawal approved and processed.")
        else:
            save_data(data)
            try:
                await context.bot.send_message(int(s_uid), f"❌ Your withdrawal of ${wd['amount']} has been rejected.")
            except:
                pass
            await q.edit_message_text("❌ Withdrawal rejected.")
        return

# =========================
# Admin panel conversation & actions
# =========================
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
        [InlineKeyboardButton("📊 Overview", callback_data="admin_overview")],
        [InlineKeyboardButton("🪙 Set Price", callback_data="admin_set_price")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban_user")],
        [InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user")],
    ]
    await update.message.reply_text("🧑‍💻 *Admin Panel* — choose an action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_PANEL

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.edit_message_text("❌ Only admin can use this.")
        return ADMIN_PANEL
    key = q.data

    # Pending groups
    if key == "admin_pending_groups":
        if not data["pending_groups"]:
            await q.edit_message_text("📭 No pending groups.")
            return ADMIN_PANEL
        for s_uid, info in list(data["pending_groups"].items()):
            kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_group:{s_uid}"),
                   InlineKeyboardButton("❌ Reject", callback_data=f"reject_group:{s_uid}")]]
            await context.bot.send_message(ADMIN_ID, f"👤 {s_uid} ➝ {info['link']}\nSubmitted: {info['time']}", reply_markup=InlineKeyboardMarkup(kb))
        await q.edit_message_text("📋 Pending groups listed above.")
        return ADMIN_PANEL

    # Pending withdrawals
    if key == "admin_pending_withdrawals":
        if not data["pending_withdrawals"]:
            await q.edit_message_text("📭 No pending withdrawals.")
            return ADMIN_PANEL
        for s_uid, w in list(data["pending_withdrawals"].items()):
            kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw:{s_uid}"),
                   InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{s_uid}")]]
            await context.bot.send_message(ADMIN_ID, f"👤 {s_uid} ➝ {w['amount']}$ via {w['method']} ({w['address']})", reply_markup=InlineKeyboardMarkup(kb))
        await q.edit_message_text("💸 Pending withdrawals listed above.")
        return ADMIN_PANEL

    # Add balance -> start flow
    if key == "admin_add_balance":
        context.user_data["admin_mode"] = "add_balance"
        await q.edit_message_text("➕ Send user ID to add balance to:")
        return ADMIN_ADD_USER

    # Inspect user
    if key == "admin_inspect_user":
        context.user_data["admin_mode"] = "inspect_user"
        await q.edit_message_text("🔍 Send user ID to inspect:")
        return ADMIN_INSPECT_USER

    # Overview
    if key == "admin_overview":
        # build overview
        total_users = len(data["users"])
        today = datetime.date.today().isoformat()
        new_today = data["stats"].get("joins_by_date", {}).get(today, 0)
        total_groups_sold = data["stats"].get("total_groups_sold", 0)
        # groups sold today (count by scanning users' groups with today's date in submitted groups time is not stored for approved groups; we approximate by scans if needed)
        # we'll count pending groups time vs today as a simple today-sold approximation: sum of users' sales that have joined today is not exact; keep simple overall numbers
        pending_withdraw_total = sum(w["amount"] for w in data["pending_withdrawals"].values()) if data.get("pending_withdrawals") else 0.0
        total_credited = data["stats"].get("total_credited", 0.0)
        banned_count = len(data.get("banned", []))
        text = (
            f"📊 *BOT OVERVIEW* — {today}\n\n"
            f"👥 Total users: {total_users}\n"
            f"🆕 New users today: {new_today}\n\n"
            f"📦 Total groups sold: {total_groups_sold}\n"
            f"💰 Total credited (paid out): ${total_credited:.2f}\n"
            f"💸 Pending withdrawals total: ${pending_withdraw_total:.2f}\n"
            f"🚫 Banned users: {banned_count}\n"
        )
        await q.edit_message_text(text, parse_mode="Markdown")
        return ADMIN_PANEL

    # Set price (start)
    if key == "admin_set_price":
        context.user_data["admin_mode"] = "set_price"
        await q.edit_message_text("🪙 Send the price key you want to set (example exactly as shown):\n" + "\n".join(data["prices"].keys()))
        return SETPRICE_KEY

    # Broadcast
    if key == "admin_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await q.edit_message_text("📢 Send the broadcast text (text only):")
        return ADMIN_BROADCAST

    # Ban user
    if key == "admin_ban_user":
        context.user_data["admin_mode"] = "ban_user"
        await q.edit_message_text("🚫 Send the user ID to ban:")
        return ADMIN_INSPECT_USER

    # Unban user
    if key == "admin_unban_user":
        context.user_data["admin_mode"] = "unban_user"
        await q.edit_message_text("✅ Send the user ID to unban:")
        return ADMIN_INSPECT_USER

    await q.edit_message_text("⚠️ Unknown admin action.")
    return ADMIN_PANEL

async def admin_add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    mode = context.user_data.get("admin_mode")
    if mode == "add_balance":
        try:
            uid = int(update.message.text.strip())
        except:
            await update.message.reply_text("❌ Invalid user id.")
            return ADMIN_ADD_USER
        context.user_data["target_user"] = uid
        await update.message.reply_text(f"Send amount to add to user {uid}:")
        return ADMIN_ADD_AMOUNT
    elif mode in ("inspect_user", "ban_user", "unban_user"):
        # reuse this handler for inspect/ban/unban flows
        try:
            uid = int(update.message.text.strip())
        except:
            await update.message.reply_text("❌ Invalid user id.")
            return ADMIN_INSPECT_USER
        if mode == "inspect_user":
            ensure_user(uid)
            u = data["users"][str(uid)]
            pending_g = data["pending_groups"].get(str(uid))
            pending_w = data["pending_withdrawals"].get(str(uid))
            text = (
                f"🔎 User {uid}\n"
                f"💰 Balance: ${u['balance']:.2f}\n"
                f"🛒 Groups submitted: {len(u.get('groups',[]))}\n"
                f"✅ Sales: {u.get('sales',0)}\n"
                f"⏳ Pending group: {pending_g['link'] if pending_g else 'None'}\n"
                f"⏳ Pending withdraw: {pending_w['amount'] if pending_w else 'None'}\n"
                f"📝 Last withdraws:\n"
            )
            for r in u.get("withdraw_history", [])[-5:]:
                text += f"- {r['time']}: {r['amount']}$ via {r['method']} — {r['status']}\n"
            await update.message.reply_text(text)
            return ADMIN_PANEL
        elif mode == "ban_user":
            data.setdefault("banned", [])
            if str(uid) not in data["banned"]:
                data["banned"].append(str(uid))
                save_data(data)
            await update.message.reply_text(f"🚫 Banned user {uid}.")
            try:
                await context.bot.send_message(uid, "🚫 You have been banned by admin.")
            except:
                pass
            return ADMIN_PANEL
        else:  # unban
            if str(uid) in data.get("banned", []):
                data["banned"].remove(str(uid))
                save_data(data)
            await update.message.reply_text(f"✅ Unbanned user {uid}.")
            try:
                await context.bot.send_message(uid, "✅ You have been unbanned by admin.")
            except:
                pass
            return ADMIN_PANEL
    else:
        await update.message.reply_text("⚠️ Admin mode not set. Start again from Admin Panel.")
        return ConversationHandler.END

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
        await update.message.reply_text("❌ No target user. Start again.")
        return ConversationHandler.END
    ensure_user(uid)
    data["users"][str(uid)]["balance"] = data["users"][str(uid)].get("balance", 0.0) + amt
    save_data(data)
    await update.message.reply_text(f"✅ Added ${amt:.2f} to user {uid}. New balance: ${data['users'][str(uid)]['balance']:.2f}")
    try:
        await context.bot.send_message(uid, f"💵 Admin added ${amt:.2f} to your balance. New balance: ${data['users'][str(uid)]['balance']:.2f}")
    except:
        pass
    return ADMIN_PANEL

async def admin_inspect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This receives when admin_mode is set for inspect/ban/unban in admin_panel_callback
    return await admin_add_user_handler(update, context)

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text
    count = 0
    for s_uid in list(data["users"].keys()):
        try:
            context.bot.send_message(int(s_uid), f"📢 Broadcast:\n\n{text}")
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")
    return ADMIN_PANEL

# Set price handlers
async def admin_setprice_key_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    key = update.message.text.strip()
    if key not in data["prices"]:
        await update.message.reply_text("❌ Invalid price key. Send one of:\n" + "\n".join(data["prices"].keys()))
        return SETPRICE_KEY
    context.user_data["setprice_key"] = key
    await update.message.reply_text(f"Send new value for {key} (for example: 7$):")
    return SETPRICE_VALUE

async def admin_setprice_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    val = update.message.text.strip()
    key = context.user_data.pop("setprice_key", None)
    if not key:
        await update.message.reply_text("❌ No key set. Start again.")
        return ConversationHandler.END
    data["prices"][key] = val
    save_data(data)
    await update.message.reply_text(f"✅ Price updated: {key} -> {val}")
    return ADMIN_PANEL

# =========================
# Button router (reply keyboard)
# =========================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id
    ensure_user(uid)
    if uid in data.get("banned", []):
        await update.message.reply_text("🚫 You are banned.")
        return
    if txt == "🏠 Start":
        await cmd_start(update, context)
    elif txt == "💰 Prices":
        await cmd_price(update, context)
    elif txt == "🛍 Sell":
        return await sell_entry(update, context)
    elif txt == "💸 Withdraw":
        return await withdraw_entry(update, context)
    elif txt == "💵 Balance":
        await cmd_balance(update, context)
    elif txt == "🧑‍💻 Admin" and uid == ADMIN_ID:
        return await admin_panel_entry(update, context)
    else:
        await update.message.reply_text("⚠️ Unknown option. Use the keyboard buttons or commands.")

# =========================
# Register and run
# =========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation handlers (sell, withdraw, admin) added first to have priority
    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", sell_entry), MessageHandler(filters.Regex("^🛍 Sell$"), sell_entry)],
        states={SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_link)]},
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw_entry), MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw_entry)],
        states={
            WD_METHOD: [CallbackQueryHandler(withdraw_choose_method, pattern="^method_")],
            WD_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_address)],
            WD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_get_amount)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600
    )

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel_entry), MessageHandler(filters.Regex("^🧑‍💻 Admin$"), admin_panel_entry)],
        states={
            ADMIN_PANEL: [CallbackQueryHandler(admin_panel_callback, pattern="^admin_")],
            ADMIN_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_handler)],
            ADMIN_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_amount_handler)],
            ADMIN_INSPECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inspect_handler)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_handler)],
            SETPRICE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_setprice_key_handler)],
            SETPRICE_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_setprice_value_handler)],
        },
        fallbacks=[CommandHandler("cancel", universal_cancel)],
        conversation_timeout=600,
        allow_reentry=True
    )

    app.add_handler(sell_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(admin_conv)

    # Callbacks for approve/reject
    app.add_handler(CallbackQueryHandler(admin_approve_reject_callback, pattern="^(approve_group|reject_group|approve_withdraw|reject_withdraw):"))

    # Admin panel callback prefixless (we used admin_ in admin_panel_callback)
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))

    # Generic button router (only fires when not in a ConversationHandler for the user)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))

    # Basic commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("overview", lambda u, c: admin_panel_entry(u, c) if u.effective_user.id == ADMIN_ID else None))
    app.add_handler(CommandHandler("cancel", universal_cancel))
    # ensure set commands appear in Telegram UI
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
