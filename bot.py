import os, io, json, qrcode
from telegram import *
from telegram.ext import *

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

SYP_RATE = 125
SHAM_ACCOUNT = "c1c8c0ec42173ec0399343eabf382b47"
SHAM_NAME = "حسن عصام سعود"

# ===== DB =====
def load(name):
    try:
        return json.load(open(name))
    except:
        return {}

def save(name,data):
    json.dump(data,open(name,"w"))

balances = load("balances.json")
orders = load("orders.json")

# ===== QR =====
def make_qr():
    img = qrcode.make(SHAM_ACCOUNT)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

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
        "🔥 متجر شدات عالمي\nاختر 👇",
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
    await update.message.reply_text("💳 اختر الدفع:",reply_markup=kb)

# ===== الدفع =====
async def payment(update,context):
    q=update.callback_query
    await q.answer()

    if q.data=="usd":
        txt=f"💳 شام كاش دولار\n{SHAM_ACCOUNT}\n{SHAM_NAME}\n\n1$={SYP_RATE}\n\nاكتب المبلغ"
    else:
        txt=f"💳 شام كاش سوري\n{SHAM_ACCOUNT}\n{SHAM_NAME}\n\n{SYP_RATE}=1$\n\nاكتب المبلغ"

    await q.message.reply_photo(
        photo=make_qr(),
        caption=txt
    )

    context.user_data["wait_amount"]=True

# ===== handler =====
async def handle(update,context):
    uid=str(update.effective_user.id)
    text=update.message.text

    if text=="💰 رصيدي": return await balance(update,context)
    if text=="➕ إضافة رصيد": return await add_balance(update,context)

    if text=="🎮 شحن شدات":
        await update.message.reply_text("🆔 اكتب ID:")
        context.user_data["pubg"]=True
        return

    if text=="📊 لوحة الادمن" and int(uid)==ADMIN_ID:
        return await admin_panel(update,context)

    # مبلغ
    if context.user_data.get("wait_amount"):
        try:
            amount=float(text)
        except:
            return await update.message.reply_text("❌ رقم غلط")

        context.user_data["amount"]=amount
        context.user_data["wait_amount"]=False

        await update.message.reply_text("📸 ارسل رقم العملية او صورة")
        context.user_data["proof"]=True
        return

    # إثبات
    if context.user_data.get("proof"):
        oid=str(len(orders)+1)

        orders[oid]={
            "uid":uid,
            "amount":context.user_data["amount"],
            "type":"balance",
            "status":"pending"
        }
        save("orders.json",orders)

        await context.bot.send_message(
            ADMIN_ID,
            f"💰 طلب رصيد\nID:{uid}\nAmount:{orders[oid]['amount']}$\nOID:{oid}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ قبول",callback_data=f"ok_{oid}"),
                 InlineKeyboardButton("❌ رفض",callback_data=f"no_{oid}")]
            ])
        )

        await update.message.reply_text("✅ تم إرسال الطلب")
        context.user_data.clear()
        return

    # PUBG
    if context.user_data.get("pubg"):
        context.user_data["pubg_id"]=text
        await update.message.reply_text("اختر:\n1$=60 UC\n4$=325 UC")
        context.user_data["price"]=True
        return

    # شدات
    if context.user_data.get("price"):
        price=float(text)
        if balances.get(uid,0)<price:
            return await update.message.reply_text("❌ رصيدك غير كافي")

        oid=str(len(orders)+1)

        orders[oid]={
            "uid":uid,
            "price":price,
            "pubg":context.user_data["pubg_id"],
            "type":"uc",
            "status":"pending"
        }
        save("orders.json",orders)

        await context.bot.send_message(
            ADMIN_ID,
            f"🎮 طلب شدات\nID:{uid}\nPUBG:{context.user_data['pubg_id']}\nPrice:{price}$\nOID:{oid}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ قبول",callback_data=f"ucok_{oid}"),
                 InlineKeyboardButton("❌ رفض",callback_data=f"ucno_{oid}")]
            ])
        )

        await update.message.reply_text("✅ تم إرسال الطلب")
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
        o["status"]="approved"
        save("balances.json",balances)
        save("orders.json",orders)
        await context.bot.send_message(uid,"✅ تم تعبئة الرصيد")

    elif data.startswith("no_"):
        o["status"]="رفض"
        save("orders.json",orders)
        await context.bot.send_message(uid,"❌ تم رفض الطلب")

    elif data.startswith("ucok_"):
        balances[uid]-=o["price"]
        o["status"]="approved"
        save("balances.json",balances)
        save("orders.json",orders)
        await context.bot.send_message(uid,"✅ تم الشحن")

    elif data.startswith("ucno_"):
        o["status"]="رفض"
        save("orders.json",orders)
        await context.bot.send_message(uid,"❌ تم رفض الشحن")

# ===== لوحة الادمن =====
async def admin_panel(update,context):
    pending=[o for o in orders.values() if o["status"]=="pending"]

    txt="📊 الطلبات المعلقة:\n\n"
    for o in pending:
        txt+=f"{o['type']} - {o['uid']}\n"

    await update.message.reply_text(txt or "مافي طلبات")

# ===== تشغيل =====
def main():
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT,handle))
    app.add_handler(CallbackQueryHandler(payment,pattern="usd|syp"))
    app.add_handler(CallbackQueryHandler(admin))

    print("🔥 BOT RUNNING PRO")
    app.run_polling()

main()
