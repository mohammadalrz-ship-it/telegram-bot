import os, io, json, html, random, string, threading
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

import qrcode
from telegram import *
from telegram.ext import *

# =========================
# 🔥 KEEP ALIVE (UPTIME)
# =========================
def run_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

threading.Thread(target=run_server).start()

# =========================
# ⚙️ CONFIG
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID"))

SYP_RATE = 125
SHAM_ACCOUNT = "c1c8c0ec42173ec0399343eabf382b47"
OWNER = "حسن عصام سعود"

BASE = Path(__file__).parent
BAL_FILE = BASE / "bal.json"

# =========================
# 💾 DATABASE
# =========================
def load():
    if BAL_FILE.exists():
        return json.load(open(BAL_FILE))
    return {}

def save(data):
    json.dump(data, open(BAL_FILE, "w"))

def get_bal(uid):
    return load().get(str(uid), 0)

def add_bal(uid, amt):
    d = load()
    d[str(uid)] = d.get(str(uid), 0) + amt
    save(d)

# =========================
# 🔳 QR
# =========================
def qr(data):
    buf = io.BytesIO()
    qrcode.make(data).save(buf)
    buf.seek(0)
    return buf

# =========================
# 🏠 START
# =========================
async def start(update: Update, ctx):
    kb = [["💰 رصيدي","➕ شحن"],["🎮 شدات"]]
    await update.message.reply_text(
        "🔥 متجر Pixel UC\nاختر:",
        reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
    )

# =========================
# 💰 BALANCE
# =========================
async def balance(update: Update, ctx):
    bal = get_bal(update.effective_user.id)
    await update.message.reply_text(f"💰 رصيدك: {bal}$")

# =========================
# ➕ ADD BALANCE
# =========================
async def add(update: Update, ctx):
    await update.message.reply_photo(
        photo=qr(SHAM_ACCOUNT),
        caption=f"""💳 شام كاش
الحساب:
{SHAM_ACCOUNT}
({OWNER})

1$ = {SYP_RATE} ل.س

أرسل المبلغ:"""
    )
    return 1

async def amount(update: Update, ctx):
    try:
        usd = float(update.message.text)
    except:
        await update.message.reply_text("❌ رقم غلط")
        return 1

    ctx.user_data["usd"] = usd
    await update.message.reply_text("📸 أرسل إثبات")
    return 2

async def proof(update: Update, ctx):
    uid = update.effective_user.id
    usd = ctx.user_data["usd"]

    await ctx.bot.send_message(
        ADMIN_ID,
        f"💰 طلب رصيد\nID: {uid}\n{usd}$"
    )

    await update.message.reply_text("⏳ تم الإرسال")
    return ConversationHandler.END

# =========================
# 🎮 UC
# =========================
async def uc(update: Update, ctx):
    kb = [
        [InlineKeyboardButton("60 UC - 1$",callback_data="1")],
        [InlineKeyboardButton("325 UC - 5$",callback_data="5")]
    ]
    await update.message.reply_text(
        "🎮 اختر:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def uc_buy(update: Update, ctx):
    q = update.callback_query
    await q.answer()

    price = float(q.data)
    uid = q.from_user.id
    bal = get_bal(uid)

    if bal < price:
        await q.message.reply_text("❌ ما عندك رصيد")
        return

    ctx.user_data["price"] = price
    await q.message.reply_text("🎮 ابعت ID")
    return 3

async def pubg(update: Update, ctx):
    uid = update.effective_user.id
    price = ctx.user_data["price"]

    add_bal(uid, -price)

    await update.message.reply_text("✅ تم الطلب")

    await ctx.bot.send_message(
        ADMIN_ID,
        f"🎮 طلب شدات\nID: {uid}\n{price}$"
    )

    return ConversationHandler.END

# =========================
# 🚀 MAIN
# =========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("➕ شحن"), add),
            CallbackQueryHandler(uc_buy)
        ],
        states={
            1:[MessageHandler(filters.TEXT, amount)],
            2:[MessageHandler(filters.ALL, proof)],
            3:[MessageHandler(filters.TEXT, pubg)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("💰 رصيدي"), balance))
    app.add_handler(MessageHandler(filters.Regex("🎮 شدات"), uc))
    app.add_handler(conv)

    print("🔥 BOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()
