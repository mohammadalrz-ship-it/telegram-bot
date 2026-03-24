"""
PUBG UC Store Bot — Premium Edition
• Premium Arabic UI / UX          • Real-store order confirmation flow
• Admin inline panel              • Persistent orders + ban system
• Anti-spam duplicate check       • Keep-alive HTTP + auto-restart
"""

import os, io, json, html, random, string, logging, threading
import qrcode
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes,
)

# ══════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════

BASE          = Path(__file__).parent
BALANCES_F    = BASE / "balances.json"
USERS_F       = BASE / "users.json"
ORDERS_F      = BASE / "orders.json"
BANNED_F      = BASE / "banned.json"

# ══════════════════════════════════════════════════════════════════════
#  CONVERSATION STATES
# ══════════════════════════════════════════════════════════════════════

(
    S_PUBG_ID,           # user: entering PUBG ID
    S_BAL_PROOF,         # user: sending payment proof (final step of balance flow)
    S_BROADCAST,         # admin: typing broadcast message
    S_ADM_BAL_AMOUNT,    # admin: entering amount for balance approval
    S_ADM_ADD_UID,       # admin: entering uid for manual add-balance
    S_ADM_ADD_AMOUNT,    # admin: entering amount for manual add-balance
    S_ADM_DEDUCT_UID,    # admin: entering uid for deduct
    S_ADM_DEDUCT_AMOUNT, # admin: entering amount for deduct
    S_ADM_BAN_UID,       # admin: entering uid to ban
    S_ADM_UNBAN_UID,     # admin: entering uid to unban
    S_CONFIRM_UC,        # user: confirming UC order before submission
    S_BAL_METHOD,        # user: choosing payment method (shamcash / syriatel)
    S_BAL_AMOUNT_SYP,    # user: entering amount (SYP or USD depending on pay_method)
    S_BAL_SYR_NUMBER,    # user: entering Syriatel destination number
    S_BAL_SHAM_TYPE,     # user: choosing ShamCash sub-type (USD or SYP)
) = range(1, 16)

# ══════════════════════════════════════════════════════════════════════
#  UC PACKAGES
# ══════════════════════════════════════════════════════════════════════

UC_PACKAGES = [
    (0,  "60 UC",    0.92),
    (1,  "325 UC",   4.40),
    (2,  "660 UC",   8.80),
    (3,  "1800 UC", 22.00),
    (4,  "3850 UC", 44.00),
    (5,  "8100 UC", 88.00),
]

# ── Payment constants ──────────────────────────────────────────────────
SYP_RATE         = 125                              # 1 USD = 125 SYP
SYRIATEL_NUMBERS = ["39182251", "81398181"]
SHAMCASH_ACCOUNT = "c1c8c0ec42173ec0399343eabf382b47"
SHAMCASH_OWNER   = "حسن عصام سعود"

def make_qr_bytes(data: str) -> io.BytesIO:
    buf = io.BytesIO()
    qrcode.make(data).save(buf, format="PNG")
    buf.seek(0)
    return buf

# ══════════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════════════

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💰 رصيدي"),       KeyboardButton("🎮 شحن شدات")],
        [KeyboardButton("➕ إضافة رصيد"),  KeyboardButton("📦 طلباتي")],
        [KeyboardButton("📞 الدعم")],
    ],
    resize_keyboard=True,
)

ADMIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💰 رصيدي"),       KeyboardButton("🎮 شحن شدات")],
        [KeyboardButton("➕ إضافة رصيد"),  KeyboardButton("📦 طلباتي")],
        [KeyboardButton("📞 الدعم"),       KeyboardButton("🔐 الإدارة")],
    ],
    resize_keyboard=True,
)

def get_menu(uid: int) -> ReplyKeyboardMarkup:
    try:
        return ADMIN_MENU if uid == adm_id() else MAIN_MENU
    except Exception:
        return MAIN_MENU

def kb_packages() -> InlineKeyboardMarkup:
    rows = []
    pkgs = UC_PACKAGES
    for i in range(0, len(pkgs), 2):
        row = []
        for idx, name, price in pkgs[i:i+2]:
            row.append(InlineKeyboardButton(
                f"🎮 {name}  ·  {price:.2f}$",
                callback_data=f"pkg_{idx}"
            ))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def kb_confirm_uc() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأكيد الطلب", callback_data="conf_yes"),
        InlineKeyboardButton("❌ إلغاء",        callback_data="conf_no"),
    ]])

def kb_bal_refresh() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 تحديث الرصيد", callback_data="bal_refresh"),
    ]])

def kb_admin_uc(oid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ قبول الشحن", callback_data=f"ua_{oid}"),
        InlineKeyboardButton("❌ رفض",        callback_data=f"ur_{oid}"),
    ]])

def kb_admin_bal(oid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ قبول وإضافة", callback_data=f"ba_{oid}"),
        InlineKeyboardButton("❌ رفض",          callback_data=f"br_{oid}"),
    ]])

def kb_pay_method() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 شام كاش",        callback_data="pay_sham"),
        InlineKeyboardButton("📱 سيرياتيل كاش",   callback_data="pay_syriatel"),
    ]])

def kb_sham_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💵 شام كاش دولار",  callback_data="pay_sham_usd"),
        InlineKeyboardButton("💰 شام كاش سوري",   callback_data="pay_sham_syp"),
    ]])

def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 طلبات الرصيد",    callback_data="adm_bal_reqs"),
         InlineKeyboardButton("🎮 طلبات الشدات",    callback_data="adm_uc_reqs")],
        [InlineKeyboardButton("📊 الإحصائيات",       callback_data="adm_stats"),
         InlineKeyboardButton("🔄 تحديث",            callback_data="adm_refresh")],
        [InlineKeyboardButton("➕ إضافة رصيد",       callback_data="adm_add"),
         InlineKeyboardButton("➖ خصم رصيد",         callback_data="adm_deduct")],
        [InlineKeyboardButton("🚫 حظر مستخدم",       callback_data="adm_ban"),
         InlineKeyboardButton("✅ فك الحظر",         callback_data="adm_unban")],
        [InlineKeyboardButton("📢 رسالة جماعية",     callback_data="adm_broadcast")],
    ])

# ══════════════════════════════════════════════════════════════════════
#  PERSISTENCE HELPERS
# ══════════════════════════════════════════════════════════════════════

def _load(path: Path, default=None):
    if default is None:
        default = {}
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default

def _save(path: Path, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Balances ──────────────────────────────────────────────────────────

def get_balance(uid: int) -> float:
    return round(_load(BALANCES_F).get(str(uid), 0.0), 2)

def change_balance(uid: int, delta: float) -> float:
    d = _load(BALANCES_F)
    k = str(uid)
    d[k] = round(d.get(k, 0.0) + delta, 2)
    _save(BALANCES_F, d)
    return d[k]

# ── Users ─────────────────────────────────────────────────────────────

def register_user(user) -> None:
    d = _load(USERS_F)
    d[str(user.id)] = {
        "name": user.first_name or "",
        "username": user.username,
    }
    _save(USERS_F, d)

def all_uids() -> list[int]:
    return [int(k) for k in _load(USERS_F).keys()]

# ── Orders ────────────────────────────────────────────────────────────

def _gen_oid() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=8))

def create_order(uid: int, otype: str, **kwargs) -> str:
    d = _load(ORDERS_F)
    oid = _gen_oid()
    while oid in d:
        oid = _gen_oid()
    d[oid] = {
        "type": otype,
        "uid": uid,
        "status": "pending",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        **kwargs,
    }
    _save(ORDERS_F, d)
    return oid

def get_order(oid: str) -> dict | None:
    return _load(ORDERS_F).get(oid)

def update_order(oid: str, **kwargs) -> None:
    d = _load(ORDERS_F)
    if oid in d:
        d[oid].update(kwargs)
        _save(ORDERS_F, d)

def user_orders(uid: int) -> list[tuple[str, dict]]:
    d = _load(ORDERS_F)
    return [(oid, o) for oid, o in d.items() if o["uid"] == uid]

def pending_orders(otype: str | None = None) -> list[tuple[str, dict]]:
    d = _load(ORDERS_F)
    return [
        (oid, o) for oid, o in d.items()
        if o["status"] == "pending" and (otype is None or o["type"] == otype)
    ]

def has_pending(uid: int, otype: str) -> bool:
    return any(True for _ in [
        o for _, o in pending_orders(otype) if o["uid"] == uid
    ])

# ── Bans ─────────────────────────────────────────────────────────────

def is_banned(uid: int) -> bool:
    return str(uid) in _load(BANNED_F)

def ban_user(uid: int) -> None:
    d = _load(BANNED_F)
    d[str(uid)] = True
    _save(BANNED_F, d)

def unban_user(uid: int) -> None:
    d = _load(BANNED_F)
    d.pop(str(uid), None)
    _save(BANNED_F, d)

# ══════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════

def adm_id() -> int:
    return int(os.environ["ADMIN_TELEGRAM_ID"])

def is_admin(update: Update) -> bool:
    return update.effective_user.id == adm_id()

def fmt_user(user) -> str:
    return f"@{user.username}" if user.username else f"#{user.id}"

def fmt_uid(uid: int) -> str:
    d = _load(USERS_F)
    info = d.get(str(uid), {})
    uname = info.get("username")
    return f"@{uname}" if uname else f"#{uid}"

STATUS_ICON = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
STATUS_TEXT = {"pending": "قيد الانتظار", "approved": "تم التنفيذ", "rejected": "مرفوض"}

# ══════════════════════════════════════════════════════════════════════
#  KEEP-ALIVE HTTP SERVER  (prevents Replit from sleeping)
# ══════════════════════════════════════════════════════════════════════

def _keep_alive() -> None:
    port = int(os.environ.get("BOT_PORT", os.environ.get("PORT", 8099)))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *_):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    logger.info(f"Keep-alive server listening on port {port}")
    server.serve_forever()

def start_keep_alive() -> None:
    t = threading.Thread(target=_keep_alive, daemon=True)
    t.start()

# ══════════════════════════════════════════════════════════════════════
#  BAN GUARD  (used at the top of every user-facing handler)
# ══════════════════════════════════════════════════════════════════════

async def _ban_check(update: Update) -> bool:
    """Returns True if user is banned (caller should return immediately)."""
    uid = update.effective_user.id
    if is_banned(uid):
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_text(
                "🚫 حسابك موقوف. للدعم: @Pixelm09",
                parse_mode="HTML",
            )
        return True
    return False

# ══════════════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _ban_check(update):
        return ConversationHandler.END
    context.user_data.clear()
    user = update.effective_user
    register_user(user)
    name = html.escape(user.first_name or "زائر")
    await update.message.reply_text(
        "🏪 <b>متجر شدات PUBG Mobile</b>\n"
        f"أهلاً <b>{name}</b>! اختر من القائمة:",
        parse_mode="HTML",
        reply_markup=get_menu(user.id),
    )
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  MAIN MENU
# ══════════════════════════════════════════════════════════════════════

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _ban_check(update):
        return ConversationHandler.END

    text = update.message.text
    user = update.effective_user
    register_user(user)
    menu = get_menu(user.id)

    # ── 🔐 الإدارة (admin only) ────────────────────────────────
    if text == "🔐 الإدارة":
        if not is_admin(update):
            await update.message.reply_text(
                "⛔ غير مسموح.",
                parse_mode="HTML",
                reply_markup=menu,
            )
            return ConversationHandler.END
        await _send_admin_panel(update.message, context)
        return ConversationHandler.END

    # ── 💰 رصيدي ──────────────────────────────────────────────
    if text == "💰 رصيدي":
        bal = get_balance(user.id)
        uid = user.id
        await update.message.reply_text(
            f"💰 رصيدك: <b>{bal:.2f}$</b>\n"
            f"ID: <code>{uid}</code>",
            parse_mode="HTML",
            reply_markup=kb_bal_refresh(),
        )

    # ── 🎮 شحن شدات ───────────────────────────────────────────
    elif text == "🎮 شحن شدات":
        await update.message.reply_text(
            "🎮 <b>شحن شدات</b>\n"
            "اختر الباقة:",
            parse_mode="HTML",
            reply_markup=kb_packages(),
        )

    # ── ➕ إضافة رصيد ──────────────────────────────────────────
    elif text == "➕ إضافة رصيد":
        if has_pending(user.id, "balance"):
            await update.message.reply_text(
                "⏳ لديك طلب قيد المراجعة، انتظر الرد أولاً.",
                parse_mode="HTML",
                reply_markup=menu,
            )
            return ConversationHandler.END

        await update.message.reply_text(
            f"➕ <b>شحن الرصيد</b>\n1$ = {SYP_RATE} ل.س — اختر طريقة الدفع:",
            parse_mode="HTML",
            reply_markup=kb_pay_method(),
        )
        return S_BAL_METHOD

    # ── 📦 طلباتي ─────────────────────────────────────────────
    elif text == "📦 طلباتي":
        orders = sorted(user_orders(user.id), key=lambda x: x[1]["created"], reverse=True)
        if not orders:
            await update.message.reply_text(
                "📭 لا توجد طلبات سابقة.",
                parse_mode="HTML",
                reply_markup=menu,
            )
        else:
            shown = orders[:5]
            header = (
                f"📦 <b>سجل طلباتي</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 عرض <b>{len(shown)}</b> من أصل <b>{len(orders)}</b> طلب\n"
            )
            cards = []
            for oid, o in shown:
                icon   = STATUS_ICON[o["status"]]
                stat   = STATUS_TEXT[o["status"]]
                if o["type"] == "uc":
                    type_line  = f"🎮 <b>شحن شدات</b>  ·  {o.get('package', '—')}  ·  {o.get('price', 0):.2f}$"
                    extra_line = f"🆔 PUBG ID: <code>{html.escape(str(o.get('pubg_id', '—')))}</code>"
                else:
                    added = o.get("amount_added")
                    type_line  = f"💵 <b>شحن رصيد</b>" + (f"  ·  +{added:.2f}$" if added else "")
                    extra_line = ""

                card = (
                    f"┌─────────────────────────\n"
                    f"│ {icon} <b>{stat}</b>\n"
                    f"│ 🔖 <code>{html.escape(oid)}</code>\n"
                    f"│ {type_line}\n"
                )
                if extra_line:
                    card += f"│ {extra_line}\n"
                card += f"│ 📅 {html.escape(o['created'])}\n└─────────────────────────"
                cards.append(card)

            await update.message.reply_text(
                header + "\n" + "\n\n".join(cards),
                parse_mode="HTML",
                reply_markup=menu,
            )

    # ── 📞 الدعم ──────────────────────────────────────────────
    elif text == "📞 الدعم":
        await update.message.reply_text(
            "📞 <b>الدعم الفني</b>\n"
            "@Pixelm09 — اذكر رقم طلبك عند التواصل",
            parse_mode="HTML",
            reply_markup=menu,
        )

    else:
        await update.message.reply_text(
            "👇 اختر من القائمة أدناه:",
            reply_markup=menu,
        )

    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  BALANCE REFRESH CALLBACK
# ══════════════════════════════════════════════════════════════════════

async def bal_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("🔄 تم التحديث")
    uid = query.from_user.id
    bal = get_balance(uid)
    try:
        await query.edit_message_text(
            "💰 <b>رصيدي</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 المستخدم:  <code>{uid}</code>\n"
            f"💵 الرصيد المتاح:  <b>{bal:.2f}$</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "لشحن رصيدك اضغط  ➕ إضافة رصيد",
            parse_mode="HTML",
            reply_markup=kb_bal_refresh(),
        )
    except Exception as e:
        logger.warning(f"bal_refresh edit failed for user {uid}: {e}")

# ══════════════════════════════════════════════════════════════════════
#  UC PURCHASE FLOW
# ══════════════════════════════════════════════════════════════════════

async def package_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if await _ban_check(update):
        return ConversationHandler.END

    idx  = int(query.data.split("_")[1])
    _, name, price = UC_PACKAGES[idx]
    uid  = query.from_user.id
    bal  = get_balance(uid)

    if has_pending(uid, "uc"):
        await query.message.reply_text(
            "⏳ <b>لديك طلب شحن شدات قيد المراجعة</b>\n\n"
            "طلبك السابق لا يزال تحت المعالجة.\n"
            "يرجى الانتظار حتى يتم الرد عليه.",
            parse_mode="HTML",
            reply_markup=get_menu(uid),
        )
        return ConversationHandler.END

    if bal < price:
        await query.message.reply_text(
            "❌ <b>رصيدك غير كافٍ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💳 سعر الباقة:      <b>{price:.2f}$</b>\n"
            f"💰 رصيدك الحالي:  <b>{bal:.2f}$</b>\n"
            f"📉 الفرق:               <b>{price - bal:.2f}$</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "اشحن رصيدك عبر  ➕ إضافة رصيد",
            parse_mode="HTML",
            reply_markup=get_menu(uid),
        )
        return ConversationHandler.END

    context.user_data["pkg_idx"]   = idx
    context.user_data["pkg_name"]  = name
    context.user_data["pkg_price"] = price

    await query.message.reply_text(
        f"🎮 <b>الباقة المختارة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>{html.escape(name)}</b>\n"
        f"💵 السعر:  <b>{price:.2f}$</b>\n"
        f"💰 رصيدك:  <b>{bal:.2f}$</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🆔 أدخل <b>ID حسابك في PUBG Mobile</b>:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_PUBG_ID


async def receive_pubg_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _ban_check(update):
        context.user_data.clear()
        return ConversationHandler.END

    pubg_id = update.message.text.strip()
    if not pubg_id.isdigit():
        await update.message.reply_text(
            "⚠️ <b>PUBG ID غير صحيح</b>\n\n"
            "يجب أن يكون PUBG ID أرقاماً فقط.\n"
            "تأكد من الـ ID وحاول مجدداً:",
            parse_mode="HTML",
        )
        return S_PUBG_ID

    user  = update.effective_user
    name  = context.user_data["pkg_name"]
    price = context.user_data["pkg_price"]
    bal   = get_balance(user.id)

    if bal < price:
        await update.message.reply_text(
            "❌ <b>رصيدك لم يعد كافياً</b>\n\n"
            "تغيّر رصيدك أثناء العملية.\n"
            "اشحن رصيدك أولاً عبر  ➕ إضافة رصيد",
            parse_mode="HTML",
            reply_markup=get_menu(user.id),
        )
        context.user_data.clear()
        return ConversationHandler.END

    remaining = round(bal - price, 2)

    context.user_data["pubg_id"] = pubg_id

    await update.message.reply_text(
        "🧾 <b>ملخص الطلب — تأكيد الشراء</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 الباقة:           <b>{html.escape(name)}</b>\n"
        f"💵 السعر:            <b>{price:.2f}$</b>\n"
        f"🎮 PUBG ID:       <code>{html.escape(pubg_id)}</code>\n\n"
        f"💰 رصيدك الحالي:   <b>{bal:.2f}$</b>\n"
        f"📉 الرصيد بعد الشراء: <b>{remaining:.2f}$</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⬇️ تأكد من صحة البيانات ثم اضغط <b>تأكيد الطلب</b>",
        parse_mode="HTML",
        reply_markup=kb_confirm_uc(),
    )
    return S_CONFIRM_UC


async def conf_uc_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("⏳ جاري تقديم الطلب...")

    if await _ban_check(update):
        context.user_data.clear()
        return ConversationHandler.END

    user  = query.from_user
    name  = context.user_data.get("pkg_name")
    price = context.user_data.get("pkg_price")
    pubg_id = context.user_data.get("pubg_id")

    if not all([name, price, pubg_id]):
        await query.message.reply_text(
            "⚠️ انتهت صلاحية الجلسة. ابدأ من جديد.",
            reply_markup=get_menu(user.id),
        )
        context.user_data.clear()
        return ConversationHandler.END

    bal = get_balance(user.id)
    if bal < price:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "❌ <b>رصيدك لم يعد كافياً</b>\n\n"
            "تغيّر رصيدك أثناء العملية.\n"
            "اشحن رصيدك أولاً عبر  ➕ إضافة رصيد",
            parse_mode="HTML",
            reply_markup=get_menu(user.id),
        )
        context.user_data.clear()
        return ConversationHandler.END

    if has_pending(user.id, "uc"):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⏳ <b>لديك طلب شحن قيد المراجعة</b>\n\n"
            "انتظر حتى يتم معالجة طلبك الحالي.",
            parse_mode="HTML",
            reply_markup=get_menu(user.id),
        )
        context.user_data.clear()
        return ConversationHandler.END

    oid = create_order(
        user.id, "uc",
        package=name, price=price, pubg_id=pubg_id,
        username=fmt_user(user),
    )

    try:
        await context.bot.send_message(
            chat_id=adm_id(),
            text=(
                "🛒 <b>طلب شحن شدات جديد</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔖 رقم الطلب:       <code>{html.escape(oid)}</code>\n"
                f"👤 المستخدم:         {html.escape(fmt_user(user))}\n"
                f"🆔 User ID:          <code>{user.id}</code>\n"
                f"🎮 PUBG ID:          <code>{html.escape(pubg_id)}</code>\n"
                f"📦 الباقة:            <b>{html.escape(name)}</b>\n"
                f"💰 السعر:             <b>{price:.2f}$</b>\n"
                f"💼 رصيد المستخدم:  <b>{bal:.2f}$</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            parse_mode="HTML",
            reply_markup=kb_admin_uc(oid),
        )
    except Exception as e:
        logger.error(f"Admin UC notify failed: {e}")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        "✅ <b>تم تقديم طلبك بنجاح!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔖 رقم الطلب:   <code>{html.escape(oid)}</code>\n"
        f"📦 الباقة:        <b>{html.escape(name)}</b>\n"
        f"🎮 PUBG ID:    <code>{html.escape(pubg_id)}</code>\n"
        f"💵 السعر:         <b>{price:.2f}$</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ طلبك قيد المراجعة — سيتم تنفيذه قريباً\n"
        "📲 ستصلك رسالة فور الموافقة",
        parse_mode="HTML",
        reply_markup=get_menu(user.id),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def conf_uc_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("تم الإلغاء")
    await query.edit_message_reply_markup(reply_markup=None)
    uid = query.from_user.id
    await query.message.reply_text(
        "❌ <b>تم إلغاء الطلب</b>\n\n"
        "لم يتم خصم أي رصيد.\n"
        "يمكنك اختيار باقة أخرى في أي وقت 🎮",
        parse_mode="HTML",
        reply_markup=get_menu(uid),
    )
    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  BALANCE TOP-UP FLOW  — payment method selection & SYP amount
# ══════════════════════════════════════════════════════════════════════

async def pay_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if await _ban_check(update):
        return ConversationHandler.END

    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "pay_sham":
        await query.message.reply_text(
            f"💳 شام كاش — 1$ = {SYP_RATE} ل.س:",
            parse_mode="HTML",
            reply_markup=kb_sham_type(),
        )
        return S_BAL_SHAM_TYPE
    else:
        context.user_data["pay_method"] = "syriatel"
        nums = "\n".join(f"<code>{n}</code>" for n in SYRIATEL_NUMBERS)
        await query.message.reply_text(
            f"📱 <b>سيرياتيل كاش</b> — {SYP_RATE} ل.س = 1$\n"
            f"الأرقام:\n{nums}\n"
            "أدخل المبلغ بالليرة السورية:",
            parse_mode="HTML",
        )
        return S_BAL_AMOUNT_SYP


async def sham_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if await _ban_check(update):
        return ConversationHandler.END

    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "pay_sham_usd":
        context.user_data["pay_method"] = "shamcash_usd"
        caption_usd = (
            "💵 <b>شام كاش دولار</b>\n"
            f"الحساب: <code>{html.escape(SHAMCASH_ACCOUNT)}</code>  ({html.escape(SHAMCASH_OWNER)})\n"
            f"1$ = {SYP_RATE} ل.س\n"
            "أدخل المبلغ بالدولار:"
        )
        await query.message.reply_photo(
            photo=make_qr_bytes(SHAMCASH_ACCOUNT),
            caption=caption_usd,
            parse_mode="HTML",
        )
    else:
        context.user_data["pay_method"] = "shamcash_syp"
        caption_syp = (
            "💰 <b>شام كاش سوري</b>\n"
            f"الحساب: <code>{html.escape(SHAMCASH_ACCOUNT)}</code>  ({html.escape(SHAMCASH_OWNER)})\n"
            f"{SYP_RATE} ل.س = 1$\n"
            "أدخل المبلغ بالليرة السورية:"
        )
        await query.message.reply_photo(
            photo=make_qr_bytes(SHAMCASH_ACCOUNT),
            caption=caption_syp,
            parse_mode="HTML",
        )

    return S_BAL_AMOUNT_SYP


async def receive_amount_syp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _ban_check(update):
        return ConversationHandler.END

    method = context.user_data.get("pay_method", "shamcash_syp")
    raw    = update.message.text.strip().replace(",", "").replace("،", "")

    if method == "shamcash_usd":
        try:
            amount_usd = float(raw)
            if amount_usd <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "⚠️ أرقام فقط — مثال: 10",
                parse_mode="HTML",
            )
            return S_BAL_AMOUNT_SYP
        context.user_data["amount_usd_calc"] = round(amount_usd, 2)
        context.user_data["amount_syp"]      = round(amount_usd * SYP_RATE, 2)
        await update.message.reply_text(
            "📸 أرسل صورة الإثبات أو رقم العملية:",
            parse_mode="HTML",
        )
        return S_BAL_PROOF

    try:
        amount_syp = float(raw)
        if amount_syp <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ أرقام فقط — مثال: 12000",
            parse_mode="HTML",
        )
        return S_BAL_AMOUNT_SYP

    amount_usd = round(amount_syp / SYP_RATE, 2)
    context.user_data["amount_syp"]      = amount_syp
    context.user_data["amount_usd_calc"] = amount_usd

    if method == "syriatel":
        nums = "\n".join(f"<code>{n}</code>" for n in SYRIATEL_NUMBERS)
        await update.message.reply_text(
            f"أدخل رقم سيرياتيل الذي حوّلت إليه:\n{nums}",
            parse_mode="HTML",
        )
        return S_BAL_SYR_NUMBER
    else:
        await update.message.reply_text(
            "📸 أرسل صورة الإثبات أو رقم العملية:",
            parse_mode="HTML",
        )
        return S_BAL_PROOF


async def receive_syriatel_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _ban_check(update):
        return ConversationHandler.END

    number = update.message.text.strip()
    if number not in SYRIATEL_NUMBERS:
        nums = "\n".join(f"<code>{n}</code>" for n in SYRIATEL_NUMBERS)
        await update.message.reply_text(
            f"⚠️ اختر من الأرقام التالية:\n{nums}",
            parse_mode="HTML",
        )
        return S_BAL_SYR_NUMBER

    context.user_data["syr_number"] = number
    await update.message.reply_text(
        "📸 أرسل صورة الإثبات أو رقم العملية:",
        parse_mode="HTML",
    )
    return S_BAL_PROOF


async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _ban_check(update):
        return ConversationHandler.END

    user = update.effective_user

    if update.message.photo:
        proof_type    = "photo"
        proof_text    = ""
        proof_file_id = update.message.photo[-1].file_id
    else:
        proof_type    = "text"
        proof_text    = update.message.text.strip()
        proof_file_id = ""

    pay_method   = context.user_data.get("pay_method", "shamcash")
    amount_syp   = context.user_data.get("amount_syp")
    amount_usd   = context.user_data.get("amount_usd_calc")
    syr_number   = context.user_data.get("syr_number", "—")

    oid = create_order(
        user.id, "balance",
        proof_type=proof_type, proof_text=proof_text,
        proof_file_id=proof_file_id, username=fmt_user(user),
        pay_method=pay_method,
        amount_syp=amount_syp,
        amount_usd_calc=amount_usd,
        syr_number=syr_number,
    )

    pay_label = {
        "shamcash_usd": "💵 شام كاش دولار",
        "shamcash_syp": "💰 شام كاش سوري",
        "syriatel":     "📱 سيرياتيل كاش",
        "shamcash":     "💳 شام كاش",
    }.get(pay_method, "💳 شام كاش")

    proof_desc_html = (
        "📷 صورة إثبات التحويل"
        if proof_type == "photo"
        else f"🔢 رقم العملية: <code>{html.escape(proof_text)}</code>"
    )

    if pay_method == "shamcash_usd" and amount_usd is not None:
        syp_line = (
            f"💵 المبلغ المحول:  <b>{amount_usd:.2f}$</b>\n"
            f"💰 المكافئ بالليرة:  <b>{amount_syp:,.0f} ل.س</b>\n"
        )
    elif amount_syp is not None:
        syp_line = (
            f"💵 المبلغ المحول:  <b>{amount_syp:,.0f} ل.س</b>\n"
            f"📊 المكافئ بالدولار:  ~<b>{amount_usd:.2f}$</b>\n"
        )
    else:
        syp_line = ""
    syr_line = (
        f"📱 الرقم المحول إليه:  <code>{html.escape(syr_number)}</code>\n"
        if pay_method == "syriatel" and syr_number != "—" else ""
    )

    admin_text = (
        "💵 <b>طلب شحن رصيد جديد</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔖 رقم الطلب:  <code>{html.escape(oid)}</code>\n"
        f"👤 المستخدم:   {html.escape(fmt_user(user))}\n"
        f"🆔 User ID:    <code>{user.id}</code>\n"
        "─────────────────────────\n"
        f"💳 طريقة الدفع:  {pay_label}\n"
        f"{syp_line}"
        f"{syr_line}"
        "─────────────────────────\n"
        f"📋 الإثبات:  {proof_desc_html}"
    )

    try:
        if proof_type == "photo":
            await context.bot.send_photo(
                chat_id=adm_id(),
                photo=proof_file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=kb_admin_bal(oid),
            )
        else:
            await context.bot.send_message(
                chat_id=adm_id(),
                text=admin_text,
                parse_mode="HTML",
                reply_markup=kb_admin_bal(oid),
            )
    except Exception as e:
        logger.error(f"Admin balance notify failed: {e}")

    if pay_method == "shamcash_usd" and amount_usd is not None:
        syp_confirm = (
            f"\n💵 المبلغ المحول:  <b>{amount_usd:.2f}$</b>\n"
            f"💰 المكافئ:  <b>{amount_syp:,.0f} ل.س</b>"
        )
    elif amount_syp is not None:
        syp_confirm = (
            f"\n💵 المبلغ المحول:  <b>{amount_syp:,.0f} ل.س</b>\n"
            f"📊 المكافئ:  ~<b>{amount_usd:.2f}$</b>"
        )
    else:
        syp_confirm = ""

    await update.message.reply_text(
        "✅ <b>طلبك مُرسَل!</b>\n"
        f"<code>{html.escape(oid)}</code>{syp_confirm}\n"
        "ستصلك رسالة عند الإضافة.",
        parse_mode="HTML",
        reply_markup=get_menu(user.id),
    )
    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  ADMIN: UC APPROVE / REJECT  (global callbacks, no follow-up needed)
# ══════════════════════════════════════════════════════════════════════

async def uc_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("✅ جاري الموافقة...")

    oid   = query.data[3:]   # strip "ua_"
    order = get_order(oid)
    if not order or order["status"] != "pending":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚠️ الطلب غير موجود أو تمت معالجته مسبقاً.",
        )
        return

    uid   = order["uid"]
    price = order["price"]
    bal   = get_balance(uid)

    if bal < price:
        update_order(oid, status="rejected")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"❌ رصيد المستخدم <code>{uid}</code> غير كافٍ "
            f"(<b>{bal:.2f}$</b> &lt; <b>{price:.2f}$</b>)\n"
            "تم رفض الطلب تلقائياً.",
            parse_mode="HTML",
        )
        try:
            await context.bot.send_message(
                uid,
                "❌ <b>تم رفض طلبك تلقائياً</b>\n\n"
                "رصيدك لم يعد كافياً لإتمام الشراء.\n"
                "للمساعدة تواصل معنا: @Pixelm09",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    new_bal = change_balance(uid, -price)
    update_order(oid, status="approved", approved_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

    try:
        await context.bot.send_message(
            uid,
            "🎉 <b>تم شحن حسابك بنجاح!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 الباقة:            <b>{html.escape(str(order['package']))}</b>\n"
            f"🎮 PUBG ID:       <code>{html.escape(str(order['pubg_id']))}</code>\n"
            f"🔖 رقم الطلب:     <code>{html.escape(oid)}</code>\n\n"
            f"💼 رصيدك المتبقي: <b>{new_bal:.2f}$</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🙏 شكراً لثقتك بنا!\n"
            "نتمنى لك تجربة ممتازة ⚡",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Could not notify user {uid}: {e}")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"✅ تم قبول الطلب <code>{html.escape(oid)}</code>\n"
        f"👤 المستخدم: <code>{uid}</code>\n"
        f"💰 خُصم: <b>{price:.2f}$</b>  |  رصيده الجديد: <b>{new_bal:.2f}$</b>",
        parse_mode="HTML",
    )


async def uc_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("❌ تم الرفض")

    oid   = query.data[3:]
    order = get_order(oid)
    if not order or order["status"] != "pending":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚠️ الطلب غير موجود أو تمت معالجته مسبقاً.",
        )
        return

    uid = order["uid"]
    update_order(oid, status="rejected", rejected_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

    try:
        await context.bot.send_message(
            uid,
            "❌ <b>تم رفض طلب الشحن</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔖 رقم الطلب:  <code>{html.escape(oid)}</code>\n\n"
            "💡 لم يتم خصم أي رصيد من حسابك.\n\n"
            "هل لديك استفسار؟ تواصل معنا:\n"
            "👤 @Pixelm09",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Could not notify user {uid}: {e}")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"❌ تم رفض الطلب <code>{html.escape(oid)}</code>\n"
        f"👤 المستخدم: <code>{uid}</code>",
        parse_mode="HTML",
    )

# ══════════════════════════════════════════════════════════════════════
#  ADMIN: BALANCE REJECT  (global callback)
# ══════════════════════════════════════════════════════════════════════

async def bal_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("❌ تم الرفض")

    oid   = query.data[3:]
    order = get_order(oid)
    if not order or order["status"] != "pending":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚠️ الطلب غير موجود أو تمت معالجته مسبقاً.",
        )
        return

    uid = order["uid"]
    update_order(oid, status="rejected", rejected_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

    try:
        await context.bot.send_message(
            uid,
            "❌ <b>تم رفض طلب شحن الرصيد</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔖 رقم الطلب:  <code>{html.escape(oid)}</code>\n\n"
            "الإثبات المُرسَل لم يتم قبوله.\n\n"
            "يمكنك المحاولة مجدداً أو التواصل مع الدعم:\n"
            "👤 @Pixelm09",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Could not notify user {uid}: {e}")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"❌ تم رفض طلب الرصيد <code>{html.escape(oid)}</code>\n"
        f"👤 المستخدم: <code>{uid}</code>",
        parse_mode="HTML",
    )

# ══════════════════════════════════════════════════════════════════════
#  ADMIN: BALANCE APPROVE (admin conv — entry point + amount step)
# ══════════════════════════════════════════════════════════════════════

async def bal_approve_init(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    oid   = query.data[3:]
    order = get_order(oid)
    if not order or order["status"] != "pending":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚠️ الطلب غير موجود أو تمت معالجته مسبقاً.",
        )
        return ConversationHandler.END

    context.user_data["bal_oid"] = oid
    context.user_data["bal_uid"] = order["uid"]
    await query.edit_message_reply_markup(reply_markup=None)

    amount_syp  = order.get("amount_syp")
    amount_usd  = order.get("amount_usd_calc")
    pay_method  = order.get("pay_method", "shamcash")
    syr_number  = order.get("syr_number", "—")
    pay_label   = {
        "shamcash_usd": "💵 شام كاش دولار",
        "shamcash_syp": "💰 شام كاش سوري",
        "syriatel":     "📱 سيرياتيل كاش",
        "shamcash":     "💳 شام كاش",
    }.get(pay_method, "💳 شام كاش")

    syp_info = ""
    if amount_syp is not None:
        if pay_method == "shamcash_usd":
            syp_info = (
                f"💵 المبلغ المحول:  <b>{amount_usd:.2f}$</b>\n"
                f"💰 المكافئ بالليرة:  <b>{amount_syp:,.0f} ل.س</b>\n"
            )
        else:
            syp_info = (
                f"💵 المبلغ المحول:  <b>{amount_syp:,.0f} ل.س</b>\n"
                f"📊 المكافئ المحسوب:  <b>{amount_usd:.2f}$</b>\n"
            )
        if pay_method == "syriatel" and syr_number != "—":
            syp_info += f"📱 الرقم المحول إليه:  <code>{html.escape(syr_number)}</code>\n"

    suggestion = (
        f"\n<i>(اقتراح: {amount_usd:.2f}$)</i>"
        if amount_usd is not None else "\n<i>مثال: 10</i>"
    )

    await query.message.reply_text(
        f"💰 قبول طلب <code>{html.escape(oid)}</code>\n"
        f"<code>{order['uid']}</code> · {pay_label}\n"
        f"{syp_info}"
        f"أدخل <b>المبلغ بالدولار</b>:{suggestion}",
        parse_mode="HTML",
    )
    return S_ADM_BAL_AMOUNT


async def bal_approve_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().replace("$", "").replace(" ", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ أرقام فقط — مثال: 10",
            parse_mode="HTML",
        )
        return S_ADM_BAL_AMOUNT

    oid = context.user_data.get("bal_oid")
    uid = context.user_data.get("bal_uid")
    if not oid or not uid:
        await update.message.reply_text("⚠️ حدث خطأ. حاول مرة أخرى.")
        return ConversationHandler.END

    new_bal = change_balance(uid, amount)
    update_order(
        oid, status="approved",
        amount_added=amount,
        approved_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    try:
        await context.bot.send_message(
            uid,
            "💰 <b>تمت إضافة الرصيد!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ المبلغ المضاف:    <b>+{amount:.2f}$</b>\n"
            f"💼 رصيدك الجديد:   <b>{new_bal:.2f}$</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "يمكنك الآن استخدام رصيدك لشراء شدات PUBG 🎮",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Could not notify user {uid}: {e}")

    await update.message.reply_text(
        f"✅ تمت إضافة <b>{amount:.2f}$</b> للمستخدم <code>{uid}</code>\n"
        f"💼 رصيده الجديد: <b>{new_bal:.2f}$</b>",
        parse_mode="HTML",
        reply_markup=ADMIN_MENU,
    )
    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  ADMIN PANEL  (shared helper + /admin command + 🔐 button)
# ══════════════════════════════════════════════════════════════════════

def _admin_panel_text() -> str:
    users_d  = _load(USERS_F)
    bals_d   = _load(BALANCES_F)
    orders_d = _load(ORDERS_F)
    pend_uc  = len(pending_orders("uc"))
    pend_bal = len(pending_orders("balance"))
    total_b  = sum(bals_d.values())

    all_orders = list(orders_d.values())
    revenue = sum(
        o.get("price", 0) for o in all_orders
        if o["type"] == "uc" and o["status"] == "approved"
    )
    approved_total = sum(1 for o in all_orders if o["status"] == "approved")

    alert = ""
    if pend_uc or pend_bal:
        alert = f"  🔴 <b>{pend_uc + pend_bal} طلب بانتظار مراجعتك</b>\n\n"

    return (
        "👑 <b>لوحة الإدارة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + alert +
        f"👥 المستخدمون:              <b>{len(users_d)}</b>\n"
        f"💰 إجمالي الأرصدة:          <b>{total_b:.2f}$</b>\n"
        f"📈 إجمالي الإيرادات:        <b>{revenue:.2f}$</b>\n"
        f"✅ طلبات مكتملة:             <b>{approved_total}</b>\n\n"
        f"⏳ شدات معلقة:   <b>{pend_uc}</b>  |  💵 رصيد معلق: <b>{pend_bal}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "اختر إجراءً 👇"
    )

async def _send_admin_panel(msg, context) -> None:
    await msg.reply_text(
        _admin_panel_text(),
        parse_mode="HTML",
        reply_markup=kb_admin_panel(),
    )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    await _send_admin_panel(update.message, context)

# ── Admin panel: refresh callback ─────────────────────────────────────

async def adm_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(update):
        await query.answer("⛔ غير مسموح")
        return
    await query.answer("🔄 تم التحديث")
    try:
        await query.edit_message_text(
            _admin_panel_text(),
            parse_mode="HTML",
            reply_markup=kb_admin_panel(),
        )
    except Exception:
        await query.message.reply_text(
            _admin_panel_text(),
            parse_mode="HTML",
            reply_markup=kb_admin_panel(),
        )

# ── Admin panel: stats callback ────────────────────────────────────────

async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(update):
        await query.answer("⛔ غير مسموح")
        return
    await query.answer()

    all_orders = list(_load(ORDERS_F).values())
    uc_orders  = [o for o in all_orders if o["type"] == "uc"]
    bal_orders = [o for o in all_orders if o["type"] == "balance"]
    approved   = sum(1 for o in all_orders if o["status"] == "approved")
    rejected   = sum(1 for o in all_orders if o["status"] == "rejected")
    pending    = sum(1 for o in all_orders if o["status"] == "pending")
    bals_d     = _load(BALANCES_F)
    total_spent = sum(
        o.get("price", 0) for o in uc_orders if o["status"] == "approved"
    )
    total_added = sum(
        o.get("amount_added", 0) for o in bal_orders if o["status"] == "approved"
    )

    await query.message.reply_text(
        "📊 <b>الإحصائيات الكاملة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 المستخدمون المسجلون:    <b>{len(_load(USERS_F))}</b>\n"
        f"💰 إجمالي الأرصدة الحالية: <b>{sum(bals_d.values()):.2f}$</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💹 <b>المبيعات والإيرادات</b>\n"
        f"  📈 إيرادات شحن الشدات:  <b>{total_spent:.2f}$</b>\n"
        f"  💵 رصيد محمّل:             <b>{total_added:.2f}$</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>الطلبات ({len(all_orders)} إجمالاً)</b>\n"
        f"  ✅ مكتمل:   <b>{approved}</b>\n"
        f"  ⏳ معلق:     <b>{pending}</b>\n"
        f"  ❌ مرفوض:  <b>{rejected}</b>\n\n"
        f"🎮 طلبات شدات:  <b>{len(uc_orders)}</b>  |  "
        f"💵 طلبات رصيد:  <b>{len(bal_orders)}</b>",
        parse_mode="HTML",
    )

# ── Admin panel: pending balance requests ──────────────────────────────

async def adm_bal_reqs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(update):
        await query.answer("⛔ غير مسموح")
        return
    await query.answer()

    reqs = pending_orders("balance")
    if not reqs:
        await query.message.reply_text(
            "✅ <b>لا توجد طلبات رصيد معلقة</b>\n\n"
            "قائمة الانتظار فارغة حالياً.",
            parse_mode="HTML",
        )
        return

    await query.message.reply_text(
        f"📥 <b>طلبات شحن الرصيد</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>{len(reqs)}</b> طلب بانتظار المراجعة",
        parse_mode="HTML",
    )
    for i, (oid, o) in enumerate(reqs, 1):
        proof_line = (
            "📷 صورة إثبات التحويل"
            if o.get("proof_type") == "photo"
            else f"🔢 <code>{html.escape(o.get('proof_text', '—'))}</code>"
        )
        text = (
            f"📌 <b>طلب {i} / {len(reqs)}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔖 رقم الطلب:  <code>{html.escape(oid)}</code>\n"
            f"👤 المستخدم:   {html.escape(str(o.get('username', '—')))}\n"
            f"🆔 User ID:    <code>{o['uid']}</code>\n"
            f"💳 الإثبات:    {proof_line}\n"
            f"📅 التاريخ:    {html.escape(o['created'])}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⬇️ اختر الإجراء:"
        )
        if o.get("proof_type") == "photo" and o.get("proof_file_id"):
            await query.message.reply_photo(
                photo=o["proof_file_id"],
                caption=text,
                parse_mode="HTML",
                reply_markup=kb_admin_bal(oid),
            )
        else:
            await query.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=kb_admin_bal(oid),
            )

# ── Admin panel: pending UC requests ──────────────────────────────────

async def adm_uc_reqs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(update):
        await query.answer("⛔ غير مسموح")
        return
    await query.answer()

    reqs = pending_orders("uc")
    if not reqs:
        await query.message.reply_text(
            "✅ <b>لا توجد طلبات شدات معلقة</b>\n\n"
            "قائمة الانتظار فارغة حالياً.",
            parse_mode="HTML",
        )
        return

    await query.message.reply_text(
        f"🎮 <b>طلبات شحن الشدات</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>{len(reqs)}</b> طلب بانتظار المراجعة",
        parse_mode="HTML",
    )
    for i, (oid, o) in enumerate(reqs, 1):
        text = (
            f"📌 <b>طلب {i} / {len(reqs)}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔖 رقم الطلب:  <code>{html.escape(oid)}</code>\n"
            f"👤 المستخدم:   {html.escape(str(o.get('username', '—')))}\n"
            f"🆔 User ID:    <code>{o['uid']}</code>\n"
            f"🎮 PUBG ID:    <code>{html.escape(str(o.get('pubg_id', '—')))}</code>\n"
            f"📦 الباقة:     <b>{html.escape(str(o.get('package', '—')))}</b>\n"
            f"💰 السعر:      <b>{o.get('price', 0):.2f}$</b>\n"
            f"📅 التاريخ:    {html.escape(o['created'])}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⬇️ اختر الإجراء:"
        )
        await query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=kb_admin_uc(oid),
        )

# ══════════════════════════════════════════════════════════════════════
#  ADMIN CONV: add balance, deduct, ban, unban, broadcast
# ══════════════════════════════════════════════════════════════════════

# ── Add balance ───────────────────────────────────────────────────────

async def adm_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "➕ <b>إضافة رصيد يدوي</b>\n\n"
        "أدخل <b>User ID</b> للمستخدم:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_ADM_ADD_UID


async def adm_add_uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "⚠️ أدخل User ID صحيح (أرقام فقط).",
        )
        return S_ADM_ADD_UID
    context.user_data["adm_uid"] = uid
    bal = get_balance(uid)
    await update.message.reply_text(
        f"👤 المستخدم: <code>{uid}</code>\n"
        f"💰 رصيده الحالي: <b>{bal:.2f}$</b>\n\n"
        "أدخل <b>المبلغ</b> بالدولار:",
        parse_mode="HTML",
    )
    return S_ADM_ADD_AMOUNT


async def adm_add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().replace("$", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ أدخل مبلغاً صحيحاً.")
        return S_ADM_ADD_AMOUNT

    uid     = context.user_data["adm_uid"]
    new_bal = change_balance(uid, amount)
    await update.message.reply_text(
        f"✅ تمت إضافة <b>{amount:.2f}$</b> للمستخدم <code>{uid}</code>\n"
        f"💼 رصيده الجديد: <b>{new_bal:.2f}$</b>",
        parse_mode="HTML",
        reply_markup=ADMIN_MENU,
    )
    try:
        await context.bot.send_message(
            uid,
            "💰 <b>تمت إضافة الرصيد!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ المبلغ المضاف:    <b>+{amount:.2f}$</b>\n"
            f"💼 رصيدك الجديد:   <b>{new_bal:.2f}$</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "يمكنك الآن استخدام رصيدك لشراء شدات PUBG 🎮",
            parse_mode="HTML",
        )
    except Exception:
        pass
    context.user_data.clear()
    return ConversationHandler.END

# ── Deduct balance ────────────────────────────────────────────────────

async def adm_deduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "➖ <b>خصم رصيد</b>\n\n"
        "أدخل <b>User ID</b> للمستخدم:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_ADM_DEDUCT_UID


async def adm_deduct_uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ أدخل User ID صحيح.")
        return S_ADM_DEDUCT_UID
    context.user_data["adm_uid"] = uid
    bal = get_balance(uid)
    await update.message.reply_text(
        f"👤 المستخدم: <code>{uid}</code>\n"
        f"💰 رصيده الحالي: <b>{bal:.2f}$</b>\n\n"
        "أدخل <b>المبلغ المراد خصمه</b>:",
        parse_mode="HTML",
    )
    return S_ADM_DEDUCT_AMOUNT


async def adm_deduct_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().replace("$", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ أدخل مبلغاً صحيحاً.")
        return S_ADM_DEDUCT_AMOUNT

    uid = context.user_data["adm_uid"]
    bal = get_balance(uid)
    if bal < amount:
        await update.message.reply_text(
            f"❌ رصيد المستخدم (<b>{bal:.2f}$</b>) أقل من المبلغ المطلوب (<b>{amount:.2f}$</b>).\n"
            "أدخل مبلغاً أصغر أو يساوي الرصيد:",
            parse_mode="HTML",
        )
        return S_ADM_DEDUCT_AMOUNT

    new_bal = change_balance(uid, -amount)
    await update.message.reply_text(
        f"✅ تم خصم <b>{amount:.2f}$</b> من المستخدم <code>{uid}</code>\n"
        f"💼 رصيده الجديد: <b>{new_bal:.2f}$</b>",
        parse_mode="HTML",
        reply_markup=ADMIN_MENU,
    )
    context.user_data.clear()
    return ConversationHandler.END

# ── Ban user ──────────────────────────────────────────────────────────

async def adm_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🚫 <b>حظر مستخدم</b>\n\n"
        "أدخل <b>User ID</b> للمستخدم المراد حظره:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_ADM_BAN_UID


async def adm_ban_uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ أدخل User ID صحيح.")
        return S_ADM_BAN_UID

    ban_user(uid)
    await update.message.reply_text(
        f"🚫 تم حظر المستخدم <code>{uid}</code> بنجاح.",
        parse_mode="HTML",
        reply_markup=ADMIN_MENU,
    )
    context.user_data.clear()
    return ConversationHandler.END

# ── Unban user ────────────────────────────────────────────────────────

async def adm_unban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "✅ <b>فك حظر مستخدم</b>\n\n"
        "أدخل <b>User ID</b> للمستخدم المراد فك حظره:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_ADM_UNBAN_UID


async def adm_unban_uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ أدخل User ID صحيح.")
        return S_ADM_UNBAN_UID

    unban_user(uid)
    await update.message.reply_text(
        f"✅ تم فك حظر المستخدم <code>{uid}</code> بنجاح.",
        parse_mode="HTML",
        reply_markup=ADMIN_MENU,
    )
    context.user_data.clear()
    return ConversationHandler.END

# ── Broadcast ─────────────────────────────────────────────────────────

async def adm_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    count = len(all_uids())
    await query.message.reply_text(
        "📢 <b>رسالة جماعية</b>\n\n"
        f"سيتم الإرسال لـ <b>{count}</b> مستخدم\n\n"
        "اكتب الرسالة الآن، أو /cancel للإلغاء:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_BROADCAST


async def broadcast_cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update):
        return ConversationHandler.END
    count = len(all_uids())
    await update.message.reply_text(
        "📢 <b>رسالة جماعية</b>\n\n"
        f"سيتم الإرسال لـ <b>{count}</b> مستخدم\n\n"
        "اكتب الرسالة الآن، أو /cancel للإلغاء:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return S_BROADCAST


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg   = update.message.text.strip()
    uids  = all_uids()
    sent  = failed = 0
    await update.message.reply_text(
        f"⏳ <b>جاري الإرسال...</b>\n\nإرسال لـ <b>{len(uids)}</b> مستخدم",
        parse_mode="HTML",
    )
    for uid in uids:
        try:
            await context.bot.send_message(
                uid,
                f"📢 <b>إعلان من المتجر</b>\n\n{html.escape(msg)}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"✅ <b>اكتمل الإرسال</b>\n\n"
        f"📤 نجح: <b>{sent}</b>  |  ❌ فشل: <b>{failed}</b>",
        parse_mode="HTML",
        reply_markup=ADMIN_MENU,
    )
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  CANCEL
# ══════════════════════════════════════════════════════════════════════

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    pkg = context.user_data.get("pkg_name")
    context.user_data.clear()
    if pkg:
        msg = f"❌ <b>تم إلغاء طلب {html.escape(pkg)}</b>\n\nلم يتم خصم أي رصيد."
    else:
        msg = "❌ <b>تم إلغاء العملية</b>"
    await update.message.reply_text(
        msg + "\n\nيمكنك البدء من جديد في أي وقت 👇",
        parse_mode="HTML",
        reply_markup=get_menu(uid),
    )
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════
#  ADMIN COMMANDS (slash)
# ══════════════════════════════════════════════════════════════════════

async def addbal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("الاستخدام: /addbal <uid> <amount>")
        return
    try:
        uid    = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ قيم غير صحيحة.")
        return
    new_bal = change_balance(uid, amount)
    await update.message.reply_text(
        f"✅ تمت إضافة <b>{amount:.2f}$</b> للمستخدم <code>{uid}</code>\n"
        f"💼 رصيده الجديد: <b>{new_bal:.2f}$</b>",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            uid,
            "💰 <b>تمت إضافة الرصيد!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ المبلغ المضاف:    <b>+{amount:.2f}$</b>\n"
            f"💼 رصيدك الجديد:   <b>{new_bal:.2f}$</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "يمكنك الآن استخدام رصيدك لشراء شدات PUBG 🎮",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("الاستخدام: /balance <uid>")
        return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ uid غير صحيح.")
        return
    bal = get_balance(uid)
    await update.message.reply_text(
        f"💰 رصيد المستخدم <code>{uid}</code>: <b>{bal:.2f}$</b>",
        parse_mode="HTML",
    )

# ══════════════════════════════════════════════════════════════════════
#  ERROR HANDLER
# ══════════════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import telegram.error as tg_err
    err = context.error
    if isinstance(err, tg_err.TimedOut):
        logger.warning("Transient TimedOut (auto-recovered): %s", err)
        return
    if isinstance(err, tg_err.Conflict):
        logger.error("Conflict — duplicate instance? (auto-recovered): %s", err)
        return
    if isinstance(err, tg_err.NetworkError):
        logger.warning("Transient NetworkError (auto-recovered): %s", err)
        return
    logger.error("Unhandled error", exc_info=context.error)


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set!")
    if not os.environ.get("ADMIN_TELEGRAM_ID"):
        raise RuntimeError("ADMIN_TELEGRAM_ID is not set!")

    # Start keep-alive HTTP server
    start_keep_alive()

    app = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(15)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(15)
        .get_updates_read_timeout(45)
        .build()
    )

    # ── Admin conversation (highest priority) ──────────────────────────
    admin_conv = ConversationHandler(
        entry_points=[
            # Balance approve (needs amount input)
            CallbackQueryHandler(bal_approve_init,     pattern=r"^ba_[A-Z0-9]{8}$"),
            # Panel flows
            CallbackQueryHandler(adm_add_start,        pattern=r"^adm_add$"),
            CallbackQueryHandler(adm_deduct_start,     pattern=r"^adm_deduct$"),
            CallbackQueryHandler(adm_ban_start,        pattern=r"^adm_ban$"),
            CallbackQueryHandler(adm_unban_start,      pattern=r"^adm_unban$"),
            CallbackQueryHandler(adm_broadcast_start,  pattern=r"^adm_broadcast$"),
            CommandHandler("broadcast", broadcast_cmd_start),
        ],
        states={
            S_ADM_BAL_AMOUNT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, bal_approve_amount)],
            S_ADM_ADD_UID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_uid)],
            S_ADM_ADD_AMOUNT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_amount)],
            S_ADM_DEDUCT_UID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_deduct_uid)],
            S_ADM_DEDUCT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_deduct_amount)],
            S_ADM_BAN_UID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_uid)],
            S_ADM_UNBAN_UID:     [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_unban_uid)],
            S_BROADCAST:         [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    # ── User conversation ──────────────────────────────────────────────
    user_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu),
            CallbackQueryHandler(package_selected, pattern=r"^pkg_\d+$"),
        ],
        states={
            S_PUBG_ID:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pubg_id)],
            S_BAL_METHOD: [
                CallbackQueryHandler(pay_method_selected, pattern=r"^pay_(sham|syriatel)$"),
            ],
            S_BAL_SHAM_TYPE: [
                CallbackQueryHandler(sham_type_selected, pattern=r"^pay_sham_(usd|syp)$"),
            ],
            S_BAL_AMOUNT_SYP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount_syp),
            ],
            S_BAL_SYR_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_syriatel_number),
            ],
            S_BAL_PROOF: [
                MessageHandler(
                    (filters.PHOTO | filters.TEXT) & ~filters.COMMAND,
                    receive_proof,
                )
            ],
            S_CONFIRM_UC: [
                CallbackQueryHandler(conf_uc_yes, pattern=r"^conf_yes$"),
                CallbackQueryHandler(conf_uc_no,  pattern=r"^conf_no$"),
            ],
        },
        fallbacks=[
            CommandHandler("start",  start),
            CommandHandler("cancel", cancel),
        ],
        per_message=False,
    )

    # Register in priority order
    app.add_handler(admin_conv)
    app.add_handler(user_conv)

    # Global callbacks (no follow-up state needed)
    app.add_handler(CallbackQueryHandler(uc_approve,   pattern=r"^ua_[A-Z0-9]{8}$"))
    app.add_handler(CallbackQueryHandler(uc_reject,    pattern=r"^ur_[A-Z0-9]{8}$"))
    app.add_handler(CallbackQueryHandler(bal_reject,   pattern=r"^br_[A-Z0-9]{8}$"))
    app.add_handler(CallbackQueryHandler(adm_stats,    pattern=r"^adm_stats$"))
    app.add_handler(CallbackQueryHandler(adm_bal_reqs, pattern=r"^adm_bal_reqs$"))
    app.add_handler(CallbackQueryHandler(adm_uc_reqs,  pattern=r"^adm_uc_reqs$"))
    app.add_handler(CallbackQueryHandler(adm_refresh,  pattern=r"^adm_refresh$"))
    app.add_handler(CallbackQueryHandler(bal_refresh,  pattern=r"^bal_refresh$"))

    # Admin slash commands
    app.add_handler(CommandHandler("admin",   admin_panel))
    app.add_handler(CommandHandler("addbal",  addbal_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
app.add_handler(CommandHandler("shamcash", shamcash))
    
    app.add_error_handler(error_handler)

    logger.info("Bot started. Keep-alive active.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        timeout=20,
    )


if __name__ == "__main__":
    main()
async def shamcash(update, context):
    import qrcode, io

    data = "39182251"  # رقم حسابك

    qr = qrcode.make(data)
    bio = io.BytesIO()
    bio.name = 'qr.png'
    qr.save(bio, 'PNG')
    bio.seek(0)

    await update.message.reply_photo(
        photo=bio,
        caption="💳 شام كاش\n39182251\n\nارسل رقم العملية"
    )
