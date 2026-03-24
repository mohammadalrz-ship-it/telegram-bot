import os
import json
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = os.environ.get("8388619491:AAGOgiY8h93-9W944R5FS81IgOJoyAaQirc")
ADMIN_ID = int(os.environ.get("7292420044", "0"))

BAL_FILE = "balances.json"
ORD_FILE = "orders.json"

def load(file):
    try:
        with open(file) as f:
            return json.load(f)
    except:
        return {}

def save(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

balances = load(BAL_FILE)
orders = load(ORD_FILE)

MENU = ReplyKeyboardMarkup([
    [KeyboardButton("💰 رصيدي"), KeyboardButton("➕ إضافة رصيد")],
    [KeyboardButton("🎮 شحن شدات"), KeyboardButton("📦 طلباتي")],
], resize_keyboard=True)

# ─── START ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    balances[uid] = balances.get(uid, 0)
    save(BAL_FILE, balances)

    await update.message.reply_text(
        "🎮 PIXEL STORE\n🔥 متجر شدات احترافي\n\nاختر 👇",
        reply_markup=MENU
    )

# ─── رصيد ───
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    await update.message.reply_text(f"💰 رصيدك: {balances.get(uid,0)}$")

# ─── إضافة رصيد ───
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 شام كاش\n\n"
        "الحساب:\n"
        "c1c8c0ec42173ec0399343eabf382b47\n\n"
        "📸 أرسل صورة التحويل"
    )
    context.user_data["proof"] = True

# ─── استقبال رسائل ───
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    text = update.message.text

    # ─── إثبات ───
    if context.user_data.get("proof"):
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            oid = str(len(orders)+1)

            orders[oid] = {"uid":uid,"type":"balance","status":"pending"}
            save(ORD_FILE, orders)

            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ قبول", callback_data=f"acc_{oid}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"rej_{oid}")
            ]])

            await context.bot.send_photo(
                ADMIN_ID,
                file_id,
                caption=f"طلب رصيد\nID:{uid}\nطلب:{oid}",
                reply_markup=btn
            )

            await update.message.reply_text("⏳ تم إرسال الطلب")
            context.user_data.clear()
            return

    # ─── شدات ───
    if text == "🎮 شحن شدات":
        await update.message.reply_text("✏️ اكتب PUBG ID")
        context.user_data["id"] = True

    elif context.user_data.get("id"):
        context.user_data["pubg"] = text
        await update.message.reply_text("💵 اختر:\n60 / 325 / 660")
        context.user_data["pkg"] = True
        context.user_data["id"] = False

    elif context.user_data.get("pkg"):
        prices = {"60":1,"325":5,"660":10}
        if text not in prices:
            await update.message.reply_text("❌ غلط")
            return

        price = prices[text]
        if balances.get(uid,0) < price:
            await update.message.reply_text("❌ ما في رصيد")
            return

        oid = str(len(orders)+1)
        orders[oid] = {
            "uid":uid,
            "type":"uc",
            "pkg":text,
            "pubg":context.user_data["pubg"],
            "price":price,
            "status":"pending"
        }
        save(ORD_FILE, orders)

        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تنفيذ", callback_data=f"done_{oid}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_{oid}")
        ]])

        await context.bot.send_message(
            ADMIN_ID,
            f"طلب شدات\nID:{uid}\nPUBG:{context.user_data['pubg']}\nباقة:{text}\nطلب:{oid}",
            reply_markup=btn
        )

        await update.message.reply_text("⏳ تم إرسال الطلب")
        context.user_data.clear()

    elif text == "💰 رصيدي":
        await balance(update, context)

    elif text == "➕ إضافة رصيد":
        await add_balance(update, context)

    elif text == "📦 طلباتي":
        user_orders = [f"{k}: {v['status']}" for k,v in orders.items() if v["uid"]==uid]
        await update.message.reply_text("\n".join(user_orders) if user_orders else "📭 لا يوجد")

# ─── أزرار الأدمن ───
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data
    oid = data.split("_")[1]
    order = orders.get(oid)

    if not order:
        return

    uid = order["uid"]

    if data.startswith("acc_"):
        balances[uid] += 10
        save(BAL_FILE, balances)
        order["status"] = "approved"
        save(ORD_FILE, orders)

        await context.bot.send_message(uid, "✅ تم إضافة الرصيد")

    elif data.startswith("done_"):
        balances[uid] -= order["price"]
        save(BAL_FILE, balances)
        order["status"] = "done"
        save(ORD_FILE, orders)

        await context.bot.send_message(uid, "🎮 تم تنفيذ طلبك")

    elif data.startswith("rej_"):
        order["status"] = "rejected"
        save(ORD_FILE, orders)

        await context.bot.send_message(uid, "❌ تم رفض الطلب")

    await q.edit_message_text("تم التنفيذ")

# ─── تشغيل ───
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle))
    app.add_handler(CallbackQueryHandler(buttons))

    app.run_polling()

if __name__ == "__main__":
    main()
