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
# CONFIG - USE ENVIRONMENT VARIABLES!
# ========================
BOT_TOKEN = os.getenv("8640257221:AAE0QEOy-QXh6feu4kxHPkALh5IBr9mHeRc")
if not BOT_TOKEN:
    raise ValueError("Set BOT_TOKEN in environment variables!")

OWNER_ID = int(os.getenv("OWNER_ID", "5405985282"))  # Only this ID can add new admins
LINKS_CHANNEL = os.getenv("LINKS_CHANNEL", "-1003234042802")
WITHDRAW_CHANNEL = os.getenv("WITHDRAW_CHANNEL", "-1003224533856")

DATA_PATH = Path("data.json")
MAX_LINKS_PER_SUBMISSION = 10

DEFAULT_PRICES = {
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
# Data Management
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
            }
        data = json.loads(DATA_PATH.read_text(encoding="utf8"))
        if "admins" not in data:
            data["admins"] = [OWNER_ID]
        if OWNER_ID not in data["admins"]:
            data["admins"].append(OWNER_ID)
        return data
    except Exception as e:
        logger.error(f"data.json corrupted: {e}")
        return {
            "users": {}, "pending_groups": {}, "pending_withdrawals": {}, "pending_requests": {},
            "sell_enabled": True, "global_prices": DEFAULT_PRICES, "admins": [OWNER_ID]
        }

def save_data(d):
    try:
        DATA_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf8")
    except Exception as e:
        logger.error(f"Save failed: {e}")

data = load_data()

def is_admin(uid: int) -> bool:
    return uid in data.get("admins", [])

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def ensure_user(uid: int):
    s = str(uid)
    if s not in data["users"]:
        data["users"][s] = {
            "balance": 0.0,
            "groups": [],
            "sales": 0,
            "withdraw_history": [],
            "custom_prices": {},
            {},
            "start_time": now(),
        }
        save_data(data)

def now():
    return datetime.datetime.utcnow().isoformat() + "Z"

# ========================
# Regex & Validators
# ========================
INVITE_RE = re.compile(
    r"^(https?://)?(t\.me/joinchat/|t\.me/\+|telegram\.me/joinchat/|telegram\.me/\+|t\.me/|t\.me/addlist/)[A-Za-z0-9_-]+$",
    re.IGNORECASE,
)

ADDRESS_VALIDATORS = {
    "upi": r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$",
    "binance": r"^\d+$",
    "bep20": r"^0x[a-fA-F0-9]{40}$",
    "polygon": r"^0x[a-fA-F0-9]{40}$",
}

def validate_address(method, address):
    regex = ADDRESS_VALIDATORS.get(method)
    if regex and not re.match(regex, address, re.IGNORECASE):
        return False
    return True

# ========================
# Keyboards
# ========================
def get_keyboard(uid: int):
    if is_admin(uid):
        return ReplyKeyboardMarkup([
            ["Home", "Prices"],
            ["Sell", "Stats"],
            ["Admin Panel"]
        ], resize_keyboard=True)
    else:
        return ReplyKeyboardMarkup([
            ["Home", "Prices"],
            ["Sell", "Withdraw"],
            ["Balance"]
        ], resize_keyboard=True)

# ========================
# Conversation States
# ========================
(
    SELL_TYPE, SELL_LINK, SELL_YEAR,
    WITHDRAW_METHOD, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT,
    ADMIN_PANEL, ADMIN_ADD_USER, ADMIN_ADD_AMOUNT, ADMIN_INSPECT_USER, ADMIN_BROADCAST,
    NEW_ADMIN_ID
) = range(13)

# ========================
# Commands List
# ========================
COMMANDS = [
    BotCommand("start", "Open bot"),
    BotCommand("price", "Show prices"),
    BotCommand("sell", "Sell group/folder"),
    BotCommand("withdraw", "Request withdrawal"),
    BotCommand("balance", "Check balance"),
    BotCommand("admin", "Admin panel"),
    BotCommand("newadmin", "Add new admin (owner only)"),
]

# ========================
# Basic Commands
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    await context.bot.set_my_commands(COMMANDS)
    await update.message.reply_text(
        "Welcome to Group Marketplace Bot!\nUse the keyboard below.",
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
    for k, v in data["global_prices"].items():
        text += f"• {k}: {v}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    bal = data["users"][str(uid)]["balance"]
    await update.message.reply_text(f"Your balance: ${bal:.2f}")

# ========================
# /newadmin - Owner Only
# ========================
async def cmd_newadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only the bot owner can add new admins.")
        return ConversationHandler.END
    await update.message.reply_text("Send the numeric user ID to promote to admin:")
    return NEW_ADMIN_ID

async def newadmin_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    try:
        new_id = int(update.message.text.strip())
        if new_id in data["admins"]:
            await update.message.reply_text(f"{new_id} is already an admin.")
        else:
            data["admins"].append(new_id)
            save_data(data)
            await update.message.reply_text(f"Added {new_id} as admin!")
            try:
                await context.bot.send_message(new_id, "You have been promoted to ADMIN!")
            except:
                pass
    except ValueError:
        await update.message.reply_text("Invalid ID. Send numeric only.")
        return NEW_ADMIN_ID
    return ConversationHandler.END

# ========================
# SELL FLOW
# ========================
async def cmd_sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not data.get("sell_enabled", True):
        await update.message.reply_text("Selling is currently disabled.")
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Single Group", callback_data="sell_single")],
        [InlineKeyboardButton("Folder (Addlist)", callback_data="sell_folder")],
    ])
    await update.message.reply_text("Choose submission type:", reply_markup=keyboard)
    return SELL_TYPE

async def sell_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["sell_type"] = "folder" if "folder" in query.data else "single"
    await query.edit_message_text(
        f"Send your Telegram {'folder' if context.user_data['sell_type']=='folder' else 'group'} link(s)\n\n"
        "You can send up to 10 links at once.\n"
        "Example: t.me/+abc123 or t.me/addlist/xyz\n\n"
        "/cancel to stop"
    )
    return SELL_LINK

async def sell_receive_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    links = [l.strip() for l in re.split(r"[\s\n]+", text) if l.strip()]
    valid_links = [l for l in links if INVITE_RE.match(l)]
    invalid = [l for l in links if l not in valid_links]

    if not valid_links:
        await update.message.reply_text(f"No valid links found.\nInvalid examples: {', '.join(invalid[:5]) or '—'}")
        return SELL_LINK

    if len(valid_links) > MAX_LINKS_PER_SUBMISSION:
        await update.message.reply_text(f"Maximum {MAX_LINKS_PER_SUBMISSION} links allowed.")
        return SELL_LINK

    uid = update.effective_user.id
    existing = data["users"][str(uid)].get("groups", [])
    duplicates = [l for l in valid_links if l in existing]
    if duplicates:
        await update.message.reply_text(f"Already submitted:\n" + "\n".join(duplicates))
        return SELL_LINK

    context.user_data["sell_links"] = valid_links
    await update.message.reply_text(
        f"{len(valid_links)} valid link(s) received!\n\n"
        "Now send the year range:\n\n"
        "2016-22 | 2023 | 2024 (1-3) | 2024 (4) | 2024 (5-6)"
    )
    return SELL_YEAR

async def sell_receive_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = update.message.text.strip()
    uid = update.effective_user.id
    custom = data["users"][str(uid)].get("custom_prices", {})
    if year not in data["global_prices"] and year not in custom:
        await update.message.reply_text(f"Invalid year. Use one of:\n{', '.join(list(data['global_prices'].keys()) + list(custom.keys()))}")
        return SELL_YEAR

    links = context.user_data["sell_links"]
    s_uid = str(uid)

    for link in links:
        key = f"{s_uid}:{link}"
        data["pending_groups"][key] = {
            "link": link,
            "year": year,
            "type": context.user_data["sell_type"],
            "seller_id": s_uid,
            "time": now(),
            "status": "pending",
            "approved_count": 1,
        }
        if link not in data["users"][s_uid]["groups"]:
            data["users"][s_uid]["groups"].append(link)
    save_data(data)

    # Notify all admins
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Approve", callback_data=f"approve_group:{s_uid}"),
         InlineKeyboardButton("Reject", callback_data=f"reject_group:{s_uid}")],
    ])
    msg_text = (
        f"New {'Folder' if context.user_data['sell_type']=='folder' else 'Group'} Submission\n"
        f"User: {update.effective_user.full_name} (@{update.effective_user.username or 'no_username'})\n"
        f"ID: {uid}\nYear: {year}\nLinks:\n" + "\n".join(links)
    )
    for admin_id in data["admins"]:
        try:
            await context.bot.send_message(admin_id, msg_text, reply_markup=kb)
        except:
            pass
    await context.bot.send_message(LINKS_CHANNEL, msg_text)

    await update.message.reply_text(f"{len(links)} link(s) submitted successfully! Waiting for admin approval.")
    context.user_data.clear()
    return ConversationHandler.END

# ========================
# WITHDRAW FLOW
# ========================
async def cmd_withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await update.message.reply_text("Admins cannot withdraw.")
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("UPI", callback_data="method_upi")],
        [InlineKeyboardButton("Binance UID", callback_data="method_binance")],
        [InlineKeyboardButton("BEP20 USDT", callback_data="method_bep20")],
        [InlineKeyboardButton("Polygon USDT", callback_data="method_polygon")],
    ])
    await update.message.reply_text("Select withdrawal method:", reply_markup=keyboard)
    return WITHDRAW_METHOD

async def withdraw_method_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    method = q.data.replace("method_", "")
    context.user_data["wd_method"] = method
    await q.edit_message_text(f"Send your {method.upper()} address/ID:")
    return WITHDRAW_ADDRESS

async def withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = update.message.text.strip()
    method = context.user_data["wd_method"]
    if not validate_address(method, addr):
        await update.message.reply_text(f"Invalid {method.upper()} format.")
        return WITHDRAW_ADDRESS
    context.user_data["wd_address"] = addr
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("Send valid amount.")
        return WITHDRAW_AMOUNT

    uid = update.effective_user.id
    bal = data["users"][str(uid)]["balance"]
    if amount > bal:
        await update.message.reply_text(f"Insufficient balance: ${bal:.2f}")
        return ConversationHandler.END

    data["pending_withdrawals"][str(uid)] = {
        "method": context.user_data["wd_method"],
        "address": context.user_data["wd_address"],
        "amount": amount,
        "time": now(),
    }
    data["users"][str(uid)]["withdraw_history"].append({
        "method": context.user_data["wd_method"],
        "address": context.user_data["wd_address"],
        "amount": amount,
        "status": "Pending",
        "time": now()
    })
    save_data(data)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Approve", callback_data=f"approve_wd:{uid}"),
         InlineKeyboardButton("Reject", callback_data=f"reject_wd:{uid}")],
    ])
    msg = f"Withdrawal Request\nUser ID: {uid}\nAmount: ${amount}\nMethod: {context.user_data['wd_method']}\nAddress: {context.user_data['wd_address']}"
    for admin_id in data["admins"]:
        await context.bot.send_message(admin_id, msg, reply_markup=kb)
    await context.bot.send_message(WITHDRAW_CHANNEL, msg)
    await update.message.reply_text("Withdrawal request sent!")
    return ConversationHandler.END

# ========================
# ADMIN CALLBACKS (ALL FIXED)
# ========================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.edit_message_text("Only admins.")
        return

    payload = q.data

    # Group Approve/Reject
    if payload.startswith(("approve_group:", "reject_group:")):
        action = payload.split(":")[0].split("_")[0]
        seller_id = payload.split(":")[1]
        pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id and v["status"] == "pending"}

        if not pending:
            await q.edit_message_text("No pending submissions.")
            return

        if action == "reject":
            links = [v["link"] for v in pending.values()]
            for k in list(pending.keys()):
                data["pending_groups"].pop(k)
            save_data(data)
            try:
                await context.bot.send_message(int(seller_id), "Your submission was rejected:\n" + "\n".join(links))
            except:
                pass
            await q.edit_message_text("Rejected.")
            return

        # APPROVE
        has_folder = any(v["type"] == "folder" for v in pending.values())
        for k, v in pending.items():
            v["status"] = "waiting_count" if has_folder else "waiting_buyer"
            v["approved_count"] = v.get("approved_count", 1)
            data["pending_groups"][k] = v
        save_data(data)

        links_text = "\n".join(v["link"] for v in pending.values())
        if has_folder:
            msg = await context.bot.send_message(q.from_user.id, f"Reply with total group count in folder(s):\n{links_text}")
            data["pending_requests"][str(msg.message_id)] = {"type": "count", "seller": seller_id}
        else:
            msg = await context.bot.send_message(q.from_user.id, f"Reply with buyer @username or ID:\n{links_text}")
            data["pending_requests"][str(msg.message_id)] = {"type": "buyer", "seller": seller_id}
        await q.edit_message_text(f"Approved. {'Waiting for count...' if has_folder else 'Waiting for buyer...'}")
        return

    # Withdraw Approve/Reject
    if payload.startswith(("approve_wd:", "reject_wd:")):
        action, uid = payload.split(":")
        uid = uid.strip()
        wd = data["pending_withdrawals"].pop(uid, None)
        if not wd:
            await q.edit_message_text("Already processed.")
            return
        status = "Approved" if "approve" in action else "Rejected"
        for h in data["users"][uid]["withdraw_history"]:
            if h["status"] == "Pending" and h["amount"] == wd["amount"]:
                h["status"] = status
                break
        if "approve" in action:
            data["users"][uid]["balance"] -= wd["amount"]
            await context.bot.send_message(int(uid), f"Your ${wd['amount']} withdrawal was APPROVED!")
        else:
            await context.bot.send_message(int(uid), f"Your ${wd['amount']} withdrawal was rejected.")
        save_data(data)
        await q.edit_message_text(f"Withdrawal {status.lower()}.")
        return

    # Ownership Done Button
    if payload.startswith("ownership_done:"):
        seller_id = payload.split(":")[1]
        pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id and v["status"] == "waiting_ownership"}
        if not pending:
            await q.answer("No pending ownership.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Verified", callback_data=f"verify_own:{seller_id}"),
             InlineKeyboardButton("Failed", callback_data=f"fail_own:{seller_id}")],
        ])
        links = "\n".join(v["link"] for v in pending.values())
        await context.bot.send_message(q.from_user.id, f"Seller claims transfer done:\n{links}\nVerify?", reply_markup=kb)
        await q.edit_message_text("Ownership submitted. Waiting for verification...")
        return

    # Final Ownership Verification
    if payload.startswith(("verify_own:", "fail_own:")):
        seller_id = payload.split(":")[1]
        pending = [v for v in data["pending_groups"].values() if v["seller_id"] == seller_id and v["status"] == "waiting_ownership"]
        if not pending:
            await q.edit_message_text("No pending.")
            return

        if payload.startswith("verify_own:"):
            total_groups = sum(v.get("approved_count", 1) for v in pending)
            year = pending[0]["year"]
            custom = data["users"][seller_id].get("custom_prices", {})
            price_str = custom.get(year, data["global_prices"].get(year, "1$"))
            price = float(price_str.replace("$", ""))
            credit = total_groups * price
            data["users"][seller_id]["balance"] += credit
            data["users"][seller_id]["sales"] += total_groups
            links = "\n".join(v["link"] for v in pending)
            for k in [k for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id]:
                data["pending_groups"].pop(k)
            save_data(data)
            await context.bot.send_message(int(seller_id), f"Ownership VERIFIED!\n{total_groups} groups → ${credit:.2f} added!")
            await q.edit_message_text(f"Verified – ${credit:.2f} credited.")
        else:
            await q.edit_message_text("Ownership failed.")
            await context.bot.send_message(int(seller_id), "Ownership FAILED. Transfer again and press button.")

# ========================
# REPLY HANDLER (Count & Buyer)
# ========================
async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message or not is_admin(msg.from_user.id):
        return

    req_id = str(msg.reply_to_message.message_id)
    req = data["pending_requests"].get(req_id)
    if not req:
        return

    seller_id = req["seller"]
    pending = {k: v for k, v in data["pending_groups"].items() if v["seller_id"] == seller_id}

    if req["type"] == "count":
        try:
            count = int(msg.text.strip())
            if count < 1:
                raise ValueError
        except:
            await msg.reply_text("Send valid number.")
            return
        for v in pending.values():
            v["approved_count"] = count
            v["status"] = "waiting_buyer"
        save_data(data)
        await msg.reply_text(f"Count set to {count}. Now reply with buyer @username or ID.")
        new_msg = await context.bot.send_message(msg.from_user.id, "Reply with buyer @username or numeric ID:")
        data["pending_requests"][str(new_msg.message_id)] = {"type": "buyer", "seller": seller_id}
        data["pending_requests"].pop(req_id, None)
        save_data(data)

    elif req["type"] == "buyer":
        buyer_id = msg.text.strip().lstrip("@")
        for v in pending.values():
            v["buyer_id"] = buyer_id
            v["status"] = "waiting_ownership"
        save_data(data)
        links = "\n".join(v["link"] for v in pending.values())
        await context.bot.send_message(int(seller_id),
            f"Transfer ownership to: @{buyer_id}\n\nLinks:\n{links}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Ownership Transferred", callback_data=f"ownership_done:{seller_id}")
            ]])
        )
        await msg.reply_text(f"Buyer set to @{buyer_id}")
        data["pending_requests"].pop(req_id, None)
        save_data(data)

# ========================
# MAIN
# ========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    sell_conv = ConversationHandler(
        entry_points=[CommandHandler("sell", cmd_sell_entry), MessageHandler(filters.Regex("^Sell$"), cmd_sell_entry)],
        states={
            SELL_TYPE: [CallbackQueryHandler(sell_type_cb, pattern="^sell_")],
            SELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_links)],
            SELL_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_year)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: (c.user_data.clear(), ConversationHandler.END)[1])],
        conversation_timeout=600,
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", cmd_withdraw_entry), MessageHandler(filters.Regex("^Withdraw$"), cmd_withdraw_entry)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_method_cb, pattern="^method_")],
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_address)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: (c.user_data.clear(), ConversationHandler.END)[1])],
    )

    newadmin_conv = ConversationHandler(
        entry_points=[CommandHandler("newadmin", cmd_newadmin)],
        states={NEW_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, newadmin_receive_id)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(sell_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(newadmin_conv)
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    logger.info("Bot started successfully!")
    app.run_polling()

if __name__ == "__main__":
    main()
