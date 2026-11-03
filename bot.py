
import os
import re
import html
import sqlite3
import logging
import threading
import telebot
from telebot import types

BOT_TOKEN = os.getenv("9291585542:AAEILt9kRz0opsjp2B1OAlIf30vCZMlaCSw", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "9047366482"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
DB_PATH = os.getenv("DATABASE_PATH", "shopbot.sqlite3")

if not BOT_TOKEN:9291585542:AAEILt9kRz0opsjp2B1OAlIf30vCZMlaCSw
    raise RuntimeError("Chua cau hinh BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            balance INTEGER DEFAULT 0 CHECK(balance >= 0),
            points INTEGER DEFAULT 0 CHECK(points >= 0)
        );

        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            admin_id INTEGER,
            type TEXT,
            amount INTEGER,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inventory(
            id INTEGER PRIMARY KEY CHECK(id=1),
            total INTEGER DEFAULT 0
        );

        INSERT OR IGNORE INTO inventory(id,total) VALUES(1,0);
        """)


def esc(value):
    return html.escape(str(value or ""))


def ensure_user(user):
    if not user:
        return
    with db() as conn:
        conn.execute("""
        INSERT INTO users(telegram_id,username,name)
        VALUES(?,?,?)
        ON CONFLICT(telegram_id) DO UPDATE SET
        username=excluded.username,name=excluded.name
        """, (user.id,user.username,user.first_name))


def get_user(uid):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (uid,)
        ).fetchone()


def admin(uid):
    return uid == ADMIN_ID


def money(value):
    return f"{value:,}".replace(",", ".") + "đ"


def user_menu():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("📦 Kho hàng",callback_data="stock"),
        types.InlineKeyboardButton("👤 Tài khoản",callback_data="account"),
        types.InlineKeyboardButton("⭐ Point",callback_data="points"),
        types.InlineKeyboardButton("📜 Lịch sử",callback_data="history"),
        types.InlineKeyboardButton("🛒 Mua hàng",callback_data="buy")
    )
    return m


def admin_menu():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("📊 Tổng quan",callback_data="stats"),
        types.InlineKeyboardButton("👥 Khách hàng",callback_data="users"),
        types.InlineKeyboardButton("📦 Quản lý kho",callback_data="stock_admin"),
        types.InlineKeyboardButton("🧾 Giao dịch",callback_data="transactions"),
        types.InlineKeyboardButton("❓ Hướng dẫn",callback_data="admin_help")
    )
    return m


def inventory():
    with db() as conn:
        row = conn.execute(
            "SELECT total FROM inventory WHERE id=1"
        ).fetchone()
    return row["total"]


@bot.message_handler(commands=["start","menu"])
def start(m):
    ensure_user(m.from_user)
    bot.send_message(
        m.chat.id,
        f"Xin chào <b>{esc(m.from_user.first_name)}</b>!\n"
        "Chào mừng đến SHOP VIP.",
        reply_markup=user_menu()
    )


@bot.message_handler(commands=["admin"])
def admin_panel(m):
    if not admin(m.from_user.id):
        return bot.reply_to(m,"Bạn không có quyền Admin.")
    bot.send_message(
        m.chat.id,"🛠 <b>BẢNG QUẢN TRỊ</b>",
        reply_markup=admin_menu()
    )


@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    ensure_user(c.from_user)
    key = c.data

    if key in ["stats","users","stock_admin","transactions","admin_help"]:
        if not admin(c.from_user.id):
            return bot.answer_callback_query(c.id,"Không có quyền!",show_alert=True)

    if key == "stock":
        text = f"📦 Tổng kho: <b>{inventory()}</b> sản phẩm"

    elif key == "account":
        u = get_user(c.from_user.id)
        text = (
            f"👤 ID: <code>{u['telegram_id']}</code>\n"
            f"💰 Số dư: {money(u['balance'])}\n"
            f"⭐ Point: {u['points']}"
        )

    elif key == "points":
        u = get_user(c.from_user.id)
        text = f"⭐ Point: <b>{u['points']}</b>"

    elif key == "history":
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id=? "
                "ORDER BY id DESC LIMIT 10",
                (c.from_user.id,)
            ).fetchall()
        text = "📜 <b>LỊCH SỬ</b>\n"
        for r in rows:
            text += (
                f"\n{esc(r['created_at'])} | "
                f"{esc(r['type'])} | {r['amount']:,}"
                f"\nLý do: {esc(r['reason'])}\n"
            )
        if not rows:
            text = "Chưa có giao dịch."

    elif key == "buy":
        contact = "@"+esc(ADMIN_USERNAME) if ADMIN_USERNAME else str(ADMIN_ID)
        text = f"🛒 Liên hệ Admin: {contact}"

    elif key == "stats":
        with db() as conn:
            n = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            balance = conn.execute("SELECT SUM(balance) n FROM users").fetchone()["n"] or 0
            points = conn.execute("SELECT SUM(points) n FROM users").fetchone()["n"] or 0
        text = (
            "📊 <b>TỔNG QUAN</b>\n\n"
            f"👥 Khách: {n}\n"
            f"💰 Tổng tiền: {money(balance)}\n"
            f"⭐ Tổng point: {points}\n"
            f"📦 Kho: {inventory()}"
        )

    elif key == "users":
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY telegram_id DESC LIMIT 10"
            ).fetchall()
        text = "👥 <b>KHÁCH HÀNG</b>\n"
        for u in rows:
            text += (
                f"\n{esc(u['name'])} | "
                f"<code>{u['telegram_id']}</code>\n"
                f"💰 {money(u['balance'])} | ⭐ {u['points']}\n"
            )

    elif key == "stock_admin":
        text = f"📦 Kho hiện tại: {inventory()}\nGửi file .txt/.csv để cập nhật."

    elif key == "transactions":
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY id DESC LIMIT 10"
            ).fetchall()
        text = "🧾 <b>GIAO DỊCH MỚI</b>\n"
        for r in rows:
            text += f"\n{r['user_id']} | {r['type']} | {r['amount']}"

    else:
        text = (
            "ADMIN COMMANDS:\n"
            "/CT ID 100 Ly do\n"
            "/TC ID 100 Ly do\n"
            "/Nt ID 100000 Ly do\n"
            "/TT ID 100000 Ly do"
        )

    markup = admin_menu() if admin(c.from_user.id) else user_menu()

    try:
        bot.edit_message_text(
            text,c.message.chat.id,c.message.message_id,
            reply_markup=markup,parse_mode="HTML"
        )
    except Exception:
        bot.send_message(c.message.chat.id,text,reply_markup=markup)

    bot.answer_callback_query(c.id)


def adjustment(m):
    if not admin(m.from_user.id):
        return bot.reply_to(m,"Không có quyền Admin.")

    match = re.match(
        r"^/(ct|tc|nt|tt)(?:@\w+)?\s+(.*)$",
        m.text or "",re.I
    )
    if not match:
        return

    command = match.group(1).lower()
    args = match.group(2).split()

    try:
        if m.reply_to_message:
            uid = m.reply_to_message.from_user.id
            ensure_user(m.reply_to_message.from_user)
            amount = int(args[0])
            reason = " ".join(args[1:]) or "Không có lý do"
        else:
            if len(args) < 2:
                raise ValueError("Thiếu ID hoặc số lượng")
            uid = int(args[0])
            amount = int(args[1])
            reason = " ".join(args[2:]) or "Không có lý do"

        if amount <= 0:
            raise ValueError("Số lượng phải lớn hơn 0")

        field,tx_type = {
            "ct":("points","POINT_ADD"),
            "tc":("points","POINT_SUB"),
            "nt":("balance","MONEY_ADD"),
            "tt":("balance","MONEY_SUB")
        }[command]

        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            u = conn.execute(
                f"SELECT {field} FROM users WHERE telegram_id=?",(uid,)
            ).fetchone()

            if not u:
                raise ValueError("Khách chưa nhắn /start với bot")

            if command in ["tc","tt"] and u[field] < amount:
                raise ValueError("Khách không đủ số dư")

            delta = -amount if command in ["tc","tt"] else amount

            conn.execute(
                f"UPDATE users SET {field}={field}+? WHERE telegram_id=?",
                (delta,uid)
            )

            conn.execute(
                "INSERT INTO transactions(user_id,admin_id,type,amount,reason) "
                "VALUES(?,?,?,?,?)",
                (uid,ADMIN_ID,tx_type,amount,reason)
            )

            conn.commit()

        bot.reply_to(m,"✅ Cập nhật thành công.")
        try:
            bot.send_message(
                uid,
                f"🔔 Admin vừa cập nhật {amount:,}\n"
                f"Lý do: {esc(reason)}"
            )
        except Exception:
            pass

    except Exception as e:
        bot.reply_to(m,f"❌ {esc(e)}")


@bot.message_handler(
    func=lambda m: bool(m.text) and
    re.match(r"^/(ct|tc|nt|tt)(?:@\w+)?\s",m.text,re.I)
)
def adjustment_handler(m):
    adjustment(m)


@bot.message_handler(content_types=["document"])
def upload(m):
    ensure_user(m.from_user)
    if not admin(m.from_user.id):
        return

    name = (m.document.file_name or "").lower()
    if not name.endswith((".txt",".csv")):
        return bot.reply_to(m,"Chỉ nhận file TXT hoặc CSV.")

    try:
        info = bot.get_file(m.document.file_id)
        data = bot.download_file(info.file_path).decode("utf-8-sig")
        count = sum(1 for line in data.splitlines() if line.strip())

        with db() as conn:
            conn.execute(
                "UPDATE inventory SET total=total+? WHERE id=1",
                (count,)
            )

        bot.reply_to(
            m,
            f"✅ Đã cộng {count} dòng.\n"
            f"📦 Tổng kho: {inventory()}"
        )
    except Exception as e:
        bot.reply_to(m,f"Lỗi: {esc(e)}")


@bot.message_handler(func=lambda m: bool(m.text), content_types=["text"])
def register_user(m):
    ensure_user(m.from_user)


if __name__ == "__main__":
    init_db()
    print("ShopBot is running...")
    bot.infinity_polling(skip_pending=True)
