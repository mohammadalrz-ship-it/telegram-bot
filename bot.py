import os, io, json, qrcode
from telegram import *
from telegram.ext import *

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

SYP_RATE = 125
SHAM_ACCOUNT = "c1c8c0ec42173ec0399343eabf382b47"
SHAM_NAME = "حسن عصام سعود"

# ===== ملفات =====
def load(f):
    try: return json.load(open(f))
    except: return {}

def save(f,d):
    json.dump(d,open(f,"w"))

balances = load("balances.json")
orders = load("orders.json")

# ===== QR =====
def qr(data):
    buf = io.BytesIO()
    qrcode.make(data).save(buf)
    buf.seek(0)
    return buf

# ===== MENU =====
def menu(uid):
    if uid == ADMIN_ID:
        return ReplyKeyboardMarkup([
            ["💰 رصيدي","➕ إضافة رصيد"],
            ["🎮 شحن شدات","📊 لوحة الادمن"]
        ],resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["💰 رصيدي","➕ إضافة رصيد"],
        ["🎮 شحن شدات"]
    ],resize_keyboard=True)

# ===== START =====
async def start(update,context):
    await update.message.reply_text(
        "🔥 متجر شدات احترافي\nاختر من القائمة 👇",
        reply_markup=menu(update.effective_user.id)
    )

# ===== الرصيد =====
async def balance(update,context):
    uid=str(update.effective_user.id)
    await update.message.reply_text(f"💰 رصيدك: {balances.get(uid,0)}$")

# ===== إضافة رصيد =====
async def add_balance(update,context):
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 شام دولار",callback_data="usd")],
        [InlineKeyboardButton("💰 شام سوري",callback_data="syp")]
    ])
    await update.message.reply_text("💳 اختر طريقة الدفع:",reply_markup=kb)

# ===== الدفع =====
async def pay(update,context):
    q=update.callback_query
    await q.answer()

    if q.data=="usd":
        context.user_data["type"]="usd"
        txt=f"💳 شام دولار\n{SHAM_ACCOUNT}\n{SHAM_NAME}\n\n1$={SYP_RATE}\n\n💬 اكتب المبلغ"
    else:
        context.user_data["type"]="syp"
        txt=f"💳 شام سوري\n{SHAM_ACCOUNT}\n{SHAM_NAME}\n\n{SYP_RATE}=1$\n\n💬 اكتب المبلغ"

    await q.message.reply_photo(photo=qr(SHAM_ACCOUNT),caption=txt)
    context.user_data["wait_amount"]=True

# ===== باقات =====
def packages():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("60 UC - 1$",callback_data="uc_1")],
        [InlineKeyboardButton("325 UC - 4$",callback_data="uc_4")],
        [InlineKeyboardButton("660 UC - 8$",callback_data="uc_8")]
    ])

# ===== handler =====
async def handle(update,context):
    uid=str(update.effective_user.id)
    text=update.message.text

    if text=="💰 رصيدي": return await balance(update,context)
    if text=="➕ إضافة رصيد": return await add_balance(update,context)

    if text=="🎮 شحن شدات":
        await update.message.reply_text("🆔 اكتب ID:")
        context.user_data["wait_pubg"]=True
        return

    if text=="📊 لوحة الادمن" and int(uid)==ADMIN_ID:
        return await admin_panel(update,context)

    # مبلغ
    if context.user_data.get("wait_amount"):
        context.user_data["amount"]=float(text)
        context.user_data["wait_amount"]=False
        await update.message.reply_text("📸 ارسل اثبات")
        context.user_data["proof"]=True
        return

    # إثبات
    if context.user_data.get("proof"):
        oid=str(len(orders)+1)
        orders[oid]={"uid":uid,"amount":context.user_data["amount"],"type":"bal"}
        save("orders.json",orders)

        await context.bot.send_message(
            ADMIN_ID,
            f"💰 طلب رصيد\nID:{uid}\n{orders[oid]['amount']}$\nOID:{oid}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅",callback_data=f"ok_{oid}"),
                 InlineKeyboardButton("❌",callback_data=f"no_{oid}")]
            ])
        )

        await update.message.reply_text("✅ تم الطلب")
        context.user_data.clear()
        return

    # PUBG
    if context.user_data.get("wait_pubg"):
        context.user_data["pubg"]=text
        await update.message.reply_text("اختر الباقة:",reply_markup=packages())
        context.user_data["wait_uc"]=True
        return

# ===== اختيار باقة =====
async def uc_select(update,context):
    q=update.callback_query
    await q.answer()

    uid=str(q.from_user.id)
    price=float(q.data.split("_")[1])

    if balances.get(uid,0)<price:
        return await q.message.reply_text("❌ رصيدك غير كافي")

    oid=str(len(orders)+1)
    orders[oid]={
        "uid":uid,
        "price":price,
        "pubg":context.user_data["pubg"],
        "type":"uc"
    }
    save("orders.json",orders)

    await context.bot.send_message(
        ADMIN_ID,
        f"🎮 طلب شدات\nID:{uid}\nPUBG:{context.user_data['pubg']}\n{price}$\nOID:{oid}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅",callback_data=f"ucok_{oid}"),
             InlineKeyboardButton("❌",callback_data=f"ucno_{oid}")]
        ])
    )

    await q.message.reply_text("✅ تم الطلب")
    context.user_data.clear()

# ===== ادمن =====
async def admin(update,context):
    q=update.callback_query
    await q.answer()

    data=q.data
    oid=data.split("_")[1]
    o=orders.get(oid)
    if not o:return

    uid=o["uid"]

    if data.startswith("ok_"):
        balances[uid]=balances.get(uid,0)+o["amount"]
        save("balances.json",balances)
        await context.bot.send_message(uid,"✅ تم التعبئة")

    elif data.startswith("no_"):
        await context.bot.send_message(uid,"❌ مرفوض")

    elif data.startswith("ucok_"):
        balances[uid]-=o["price"]
        save("balances.json",balances)
        await context.bot.send_message(uid,"✅ تم الشحن")

    elif data.startswith("ucno_"):
        await context.bot.send_message(uid,"❌ مرفوض")

# ===== لوحة الادمن =====
async def admin_panel(update,context):
    await update.message.reply_text(
        f"📊 الطلبات: {len(orders)}"
    )

# ===== تشغيل =====
def main():
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT,handle))
    app.add_handler(CallbackQueryHandler(pay,pattern="usd|syp"))
    app.add_handler(CallbackQueryHandler(admin))
    app.add_handler(CallbackQueryHandler(uc_select,pattern="uc_"))

    print("🔥 SUPER BOT RUNNING")
    app.run_polling()

main()
