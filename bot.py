
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)

# ---------------------- CONFIG ----------------------
BOT_TOKEN = "8353615250:AAEFKh2CYKd8fiG2estmGTE_bK1IHlFdH8s"
ADMIN_ID = 5405985282  # <-- Replace with your Telegram ID
INR_USD_RATE = 85    # Example conversion rate

# ---------------------- LOGGING ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------- DATA ----------------------
users = {}  # user_id: {"balance_inr":0,"balance_usd":0,"currency":"INR"}
group_requests = []  # {"user_id":..., "link":..., "request_id":...}
withdraw_requests = []  # {"user_id":..., "amount":..., "method":..., "currency":..., "request_id":...}
request_counter = 0  # unique ID for each request

# ---------------------- PRICE LIST ----------------------
PRICE_LIST_INR = {
    "2016–2022": "11$",
    "2023": "6$",
    "2024 (1–3)": "5$",
    "2024 (4)": "4$",
    "2024 (5–6)": "1$"
}

# ---------------------- START ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"balance_inr":0,"balance_usd":0,"currency":"INR"})
    keyboard = [
        [InlineKeyboardButton("INR", callback_data="currency_INR"),
         InlineKeyboardButton("USD", callback_data="currency_USD")]
    ]
    await update.message.reply_text(
        "👋 Welcome to Group Buyer Bot!\n"
        "💬 Sell your Telegram groups and withdraw funds.\n"
        "Select your preferred currency:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------- PROFILE ----------------------
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("ℹ️ No profile found. Send /start first.")
        return
    balance = user["balance_inr"] if user["currency"]=="INR" else user["balance_usd"]
    symbol = "₹" if user["currency"]=="INR" else "$"
    await update.message.reply_text(
        f"👤 Profile\n🆔 ID: {user_id}\n"
        f"💰 Balance: {symbol}{balance}\n"
        f"💱 Currency: {user['currency']}"
    )

# ---------------------- PRICE ----------------------
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "💵 Price List:\n\n"
    for year, amount in PRICE_LIST_INR.items():
        amount_usd = round(amount / INR_USD_RATE,2)
        msg += f"📅 {year}: ₹{amount} / ${amount_usd}\n"
    await update.message.reply_text(msg)

# ---------------------- CURRENCY CALLBACK ----------------------
async def currency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    currency = query.data.split("_")[1]
    users.setdefault(user_id, {"balance_inr":0,"balance_usd":0,"currency":"INR"})
    users[user_id]["currency"] = currency
    await query.edit_message_text(f"✅ Currency set to {currency}")

# ---------------------- SELL GROUP ----------------------
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 Send your Telegram group invite link.\n"
        "Admin will review and credit your balance manually."
    )

# ---------------------- HANDLE GROUP LINKS ----------------------
async def handle_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_counter
    text = update.message.text
    user_id = update.effective_user.id
    if "t.me/" in text:
        request_counter += 1
        request_id = request_counter
        group_requests.append({"user_id":user_id,"link":text,"request_id":request_id})
        await update.message.reply_text("✅ Group link submitted. Admin will review.")
    else:
        await update.message.reply_text("❌ Invalid link. Send a valid Telegram group invite link.")

# ---------------------- WITHDRAW ----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏦 Send your wallet address or payment method.\n"
        "Admin will review and process manually."
    )

async def handle_withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_counter
    user_id = update.effective_user.id
    text = update.message.text
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("ℹ️ Start with /start first.")
        return
    balance_inr = user["balance_inr"]
    balance_usd = user["balance_usd"]
    currency = user["currency"]
    amount = balance_inr if currency=="INR" else balance_usd
    if amount<=0:
        await update.message.reply_text("❌ You have no balance to withdraw.")
        return
    request_counter += 1
    request_id = request_counter
    withdraw_requests.append({
        "user_id":user_id,"amount":amount,"method":text,"currency":currency,"request_id":request_id
    })
    await update.message.reply_text("✅ Withdraw request submitted. Admin will review.")

# ---------------------- ADMIN PANEL ----------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not admin.")
        return

    if not group_requests and not withdraw_requests:
        await update.message.reply_text("ℹ️ No pending requests.")
        return

    msg_text = "📌 Admin Panel - Pending Requests:\n\n"

    for req in group_requests:
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_group_{req['request_id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_group_{req['request_id']}")
        ]])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 Group submission\nUser ID: {req['user_id']}\nLink: {req['link']}",
            reply_markup=buttons
        )

    for req in withdraw_requests:
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw_{req['request_id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw_{req['request_id']}")
        ]])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💸 Withdraw request\nUser ID: {req['user_id']}\nAmount: {req['currency']}{req['amount']}\nMethod: {req['method']}",
            reply_markup=buttons
        )

# ---------------------- CALLBACK HANDLER ----------------------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, type_req, req_id = data.split("_")
    req_id = int(req_id)

    if type_req=="group":
        req = next((r for r in group_requests if r["request_id"]==req_id), None)
        if not req: return
        user = users[req["user_id"]]
        if action=="approve":
            # For demo, assign ₹500 / equivalent USD
            amt_inr = 500
            amt_usd = round(amt_inr/INR_USD_RATE,2)
            user["balance_inr"] += amt_inr
            user["balance_usd"] += amt_usd
            await context.bot.send_message(req["user_id"], f"✅ Your group was approved. ₹{amt_inr} / ${amt_usd} added.")
            await query.edit_message_text(f"✅ Approved group from User {req['user_id']}\nLink: {req['link']}")
        else:
            await context.bot.send_message(req["user_id"], "❌ Your group was rejected by admin.")
            await query.edit_message_text(f"❌ Rejected group from User {req['user_id']}\nLink: {req['link']}")
        group_requests.remove(req)

    elif type_req=="withdraw":
        req = next((r for r in withdraw_requests if r["request_id"]==req_id), None)
        if not req: return
        if action=="approve":
            await context.bot.send_message(req["user_id"], f"✅ Withdraw request approved. Admin will pay {req['currency']}{req['amount']} manually.")
            await query.edit_message_text(f"✅ Approved withdraw for User {req['user_id']}\nAmount: {req['currency']}{req['amount']}\nMethod: {req['method']}")
        else:
            await context.bot.send_message(req["user_id"], f"❌ Withdraw request rejected by admin.")
            await query.edit_message_text(f"❌ Rejected withdraw for User {req['user_id']}\nAmount: {req['currency']}{req['amount']}\nMethod: {req['method']}")
        withdraw_requests.remove(req)

# ---------------------- MAIN ----------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("withdraw", withdraw))

    # Admin Panel
    app.add_handler(CommandHandler("admin_panel", admin_panel))

    # Callbacks
    app.add_handler(CallbackQueryHandler(currency_callback, pattern="currency_.*"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="(approve|reject)_(group|withdraw)_.*"))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_link))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_request))

    app.run_polling()

if __name__=="__main__":
    main()
