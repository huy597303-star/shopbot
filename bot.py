import os, textwrap, zipfile

base = "/mnt/data/telegram-shop-bot"
os.makedirs(base, exist_ok=True)

files = {
"package.json": r'''
{
  "name": "telegram-group-ledger-bot",
  "version": "1.0.0",
  "description": "Telegram group bot for digital-goods inventory counts and user point/balance ledger",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js"
  },
  "engines": {
    "node": ">=20"
  },
  "dependencies": {
    "better-sqlite3": "^11.8.1",
    "dotenv": "^16.4.7",
    "telegraf": "^4.16.3"
  }
}
''',
".env.example": r'''
BOT_TOKEN=9291585542:AAEILt9kRz0opsjp2B1OAlIf30vCZMlaCSw
ADMIN_ID=9047366482
ADMIN_USERNAME=
DATABASE_PATH=./data/bot.sqlite
MAX_UPLOAD_MB=20
''',
".gitignore": r'''
node_modules/
.env
data/
*.sqlite
*.db
.DS_Store
''',
"render.yaml": r'''
services:
  - type: worker
    name: telegram-group-ledger-bot
    runtime: node
    plan: starter
    buildCommand: npm install
    startCommand: npm start
    disk:
      name: bot-data
      mountPath: /var/data
      sizeGB: 1
    envVars:
      - key: NODE_ENV
        value: production
      - key: DATABASE_PATH
        value: /var/data/bot.sqlite
      - key: BOT_TOKEN
        sync: false
      - key: ADMIN_ID
        value: "9047366482"
      - key: ADMIN_USERNAME
        sync: false
      - key: MAX_UPLOAD_MB
        value: "20"
''',
"src/index.js": r'''
require("dotenv").config();

const fs = require("fs");
const path = require("path");
const Database = require("better-sqlite3");
const { Telegraf, Markup } = require("telegraf");

const BOT_TOKEN = process.env.BOT_TOKEN;
const ADMIN_ID = String(process.env.ADMIN_ID || "9047366482");
const ADMIN_USERNAME = String(process.env.ADMIN_USERNAME || "").replace(/^@/, "");
const DATABASE_PATH = process.env.DATABASE_PATH || "./data/bot.sqlite";
const MAX_UPLOAD_MB = Number(process.env.MAX_UPLOAD_MB || 20);

if (!BOT_TOKEN) {
  console.error("Thiếu BOT_TOKEN. Hãy tạo file .env từ .env.example và điền token.");
  process.exit(1);
}

fs.mkdirSync(path.dirname(path.resolve(DATABASE_PATH)), { recursive: true });
const db = new Database(DATABASE_PATH);
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    telegram_id TEXT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
    points INTEGER NOT NULL DEFAULT 0 CHECK(points >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT NOT NULL,
    admin_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(telegram_id) REFERENCES users(telegram_id)
  );

  CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    item_count INTEGER NOT NULL DEFAULT 0,
    updated_by TEXT,
    updated_at TEXT
  );

  INSERT OR IGNORE INTO inventory(id, item_count) VALUES(1, 0);
`);

const bot = new Telegraf(BOT_TOKEN);

const menu = Markup.keyboard([
  ["📦 Check kho", "👤 Tài khoản"],
  ["🪙 Check point", "🛒 Mua hàng"],
  ["📜 Lịch sử"]
]).resize();

function isAdmin(ctx) {
  return String(ctx.from?.id || "") === ADMIN_ID;
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
  }[c]));
}

function ensureUser(ctx) {
  const from = ctx.from;
  if (!from) return;
  db.prepare(`
    INSERT INTO users(telegram_id, username, first_name)
    VALUES(?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
      username=excluded.username,
      first_name=excluded.first_name
  `).run(String(from.id), from.username || null, from.first_name || "");
}

function getUser(id) {
  return db.prepare("SELECT * FROM users WHERE telegram_id = ?").get(String(id));
}

function formatMoney(value) {
  return new Intl.NumberFormat("vi-VN").format(value) + "đ";
}

function targetFromCommand(ctx, args) {
  // Cách 1: reply tin nhắn của người nhận, ví dụ /CT 50 thưởng
  if (ctx.message.reply_to_message?.from) {
    return {
      id: String(ctx.message.reply_to_message.from.id),
      amount: Number(args[0]),
      reason: args.slice(1).join(" ").trim()
    };
  }
  // Cách 2: /CT <telegram_id> <số lượng> <lý do>
  return {
    id: String(args[0] || ""),
    amount: Number(args[1]),
    reason: args.slice(2).join(" ").trim()
  };
}

function recordAdjustment(ctx, type, targetId, amount, reason) {
  if (!/^\d+$/.test(targetId)) throw new Error("Telegram ID không hợp lệ.");
  if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error("Số lượng phải là số nguyên dương.");
  if (!reason) throw new Error("Bạn cần nhập lý do.");

  const target = getUser(targetId);
  if (!target) throw new Error("Chưa có dữ liệu user này. Hãy yêu cầu user nhắn /start cho bot trước.");

  const isPoint = type === "POINT_ADD" || type === "POINT_SUB";
  const column = isPoint ? "points" : "balance";
  const subtract = type === "POINT_SUB" || type === "MONEY_SUB";

  const transaction = db.transaction(() => {
    const current = getUser(targetId);
    if (subtract && current[column] < amount) {
      throw new Error(isPoint ? "User không đủ point để trừ." : "User không đủ số dư để trừ.");
    }
    const delta = subtract ? -amount : amount;
    db.prepare(`UPDATE users SET ${column} = ${column} + ? WHERE telegram_id = ?`)
      .run(delta, targetId);
    db.prepare(`
      INSERT INTO transactions(telegram_id, admin_id, type, amount, reason)
      VALUES(?, ?, ?, ?, ?)
    `).run(targetId, ADMIN_ID, type, amount, reason);
  });
  transaction();
}

function adminHelp() {
  return [
    "🛠 <b>LỆNH ADMIN</b>",
    "",
    "Có thể reply tin nhắn của user rồi dùng:",
    "<code>/CT 100 Lý do</code> — cộng point",
    "<code>/TC 50 Lý do</code> — trừ point",
    "<code>/Nt 100000 Lý do</code> — cộng tiền",
    "<code>/TT 20000 Lý do</code> — trừ tiền",
    "",
    "Hoặc dùng ID trực tiếp:",
    "<code>/CT 123456789 100 Lý do</code>",
    "<code>/TC 123456789 50 Lý do</code>",
    "<code>/Nt 123456789 100000 Lý do</code>",
    "<code>/TT 123456789 20000 Lý do</code>",
    "",
    "User cần nhắn /start với bot ít nhất một lần trước khi admin điều chỉnh."
  ].join("\n");
}

async function sendAccount(ctx, id) {
  const user = getUser(id);
  if (!user) return ctx.reply("Chưa có dữ liệu. Hãy gửi /start để đăng ký.");
  return ctx.reply(
    `👤 <b>TÀI KHOẢN</b>\nID: <code>${escapeHtml(user.telegram_id)}</code>\nTên: ${escapeHtml(user.first_name || "Chưa cập nhật")}\nUsername: ${user.username ? "@" + escapeHtml(user.username) : "Không có"}\nSố dư: <b>${formatMoney(user.balance)}</b>\nPoint: <b>${user.points}</b>`,
    { parse_mode: "HTML" }
  );
}

async function sendHistory(ctx, id) {
  const rows = db.prepare(`
    SELECT type, amount, reason, created_at
    FROM transactions
    WHERE telegram_id = ?
    ORDER BY id DESC
    LIMIT 20
  `).all(String(id));

  if (!rows.length) return ctx.reply("📜 Bạn chưa có giao dịch nào.");

  const labels = {
    POINT_ADD: "Cộng point", POINT_SUB: "Trừ point",
    MONEY_ADD: "Nạp tiền", MONEY_SUB: "Trừ tiền"
  };
  const lines = rows.map((r) => {
    const amount = r.type.startsWith("POINT") ? `${r.amount} point` : formatMoney(r.amount);
    return `• ${escapeHtml(r.created_at)} | ${labels[r.type]}: ${amount}\n  Lý do: ${escapeHtml(r.reason)}`;
  });
  return ctx.reply("📜 <b>LỊCH SỬ GIAO DỊCH (20 gần nhất)</b>\n\n" + lines.join("\n\n"), { parse_mode: "HTML" });
}

async function showStock(ctx) {
  const row = db.prepare("SELECT item_count, updated_at FROM inventory WHERE id=1").get();
  return ctx.reply(`📦 <b>KHO HIỆN TẠI</b>\nSố lượng: <b>${row.item_count}</b>\nCập nhật: ${row.updated_at || "Chưa có"}`, { parse_mode: "HTML" });
}

bot.start((ctx) => {
  ensureUser(ctx);
  ctx.reply(
    "Chào mừng! Chọn chức năng bên dưới.\nBot chỉ quản lý số lượng hàng hóa, số dư và point; không lưu hoặc phân phối thông tin đăng nhập.",
    menu
  );
});

bot.command("help", (ctx) => {
  ensureUser(ctx);
  ctx.reply("Lệnh: /start, /kho, /taikhoan, /point, /lichsu, /mua\nAdmin: /adminhelp");
});

bot.command("adminhelp", (ctx) => {
  if (!isAdmin(ctx)) return ctx.reply("Bạn không có quyền dùng lệnh này.");
  return ctx.reply(adminHelp(), { parse_mode: "HTML" });
});

bot.command("kho", async (ctx) => { ensureUser(ctx); return showStock(ctx); });
bot.command("taikhoan", async (ctx) => { ensureUser(ctx); return sendAccount(ctx, ctx.from.id); });
bot.command("point", async (ctx) => {
  ensureUser(ctx);
  const user = getUser(ctx.from.id);
  return ctx.reply(`🪙 Point hiện tại của bạn: <b>${user.points}</b>`, { parse_mode: "HTML" });
});
bot.command("lichsu", async (ctx) => { ensureUser(ctx); return sendHistory(ctx, ctx.from.id); });
bot.command("mua", async (ctx) => {
  ensureUser(ctx);
  const contact = ADMIN_USERNAME ? `@${ADMIN_USERNAME}` : `Telegram ID: ${ADMIN_ID}`;
  return ctx.reply(`🛒 Để hỏi mua hàng, vui lòng liên hệ admin: ${contact}`);
});

const adminCommands = [
  { command: "CT", type: "POINT_ADD", label: "Cộng point" },
  { command: "TC", type: "POINT_SUB", label: "Trừ point" },
  { command: "Nt", type: "MONEY_ADD", label: "Nạp tiền" },
  { command: "TT", type: "MONEY_SUB", label: "Trừ tiền" }
];

for (const item of adminCommands) {
  bot.command(item.command, (ctx) => {
    if (!isAdmin(ctx)) return ctx.reply("⛔ Bạn không có quyền dùng lệnh admin.");
    try {
      const raw = (ctx.message.text || "").trim().split(/\s+/).slice(1);
      const parsed = targetFromCommand(ctx, raw);
      recordAdjustment(ctx, item.type, parsed.id, parsed.amount, parsed.reason);
      const target = getUser(parsed.id);
      return ctx.reply(
        `✅ Đã ${item.label.toLowerCase()} thành công.\nUser: ${escapeHtml(target.first_name || parsed.id)} (<code>${parsed.id}</code>)\nSố lượng: <b>${parsed.amount}</b>\nLý do: ${escapeHtml(parsed.reason)}`,
        { parse_mode: "HTML" }
      );
    } catch (err) {
      return ctx.reply(`❌ ${escapeHtml(err.message)}\n\nDùng /adminhelp để xem cú pháp.`, { parse_mode: "HTML" });
    }
  });
}

bot.on("document", async (ctx) => {
  ensureUser(ctx);
  if (!isAdmin(ctx)) return ctx.reply("⛔ Chỉ admin được cập nhật kho.");
  const doc = ctx.message.document;
  const maxBytes = MAX_UPLOAD_MB * 1024 * 1024;
  if (doc.file_size && doc.file_size > maxBytes) {
    return ctx.reply(`File quá lớn. Giới hạn hiện tại: ${MAX_UPLOAD_MB} MB.`);
  }
  try {
    const link = await ctx.telegram.getFileLink(doc.file_id);
    const response = await fetch(link.href);
    if (!response.ok) throw new Error("Không tải được file từ Telegram.");
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > maxBytes) throw new Error("File vượt giới hạn dung lượng.");

    // Chỉ đếm dòng không rỗng trong bộ nhớ. Không lưu file, không gửi nội dung file vào chat/log.
    const content = buffer.toString("utf8").replace(/^\uFEFF/, "");
    const count = content.split(/\r?\n/).filter((line) => line.trim().length > 0).length;

    db.prepare(`
      UPDATE inventory SET item_count=?, updated_by=?, updated_at=datetime('now')
      WHERE id=1
    `).run(count, String(ctx.from.id));

    return ctx.reply(`✅ Đã cập nhật số lượng kho: <b>${count}</b> dòng có dữ liệu.\nFile không được lưu trên máy chủ và nội dung không được gửi vào nhóm.`, { parse_mode: "HTML" });
  } catch (err) {
    console.error("Inventory count failed:", err.message);
    return ctx.reply("❌ Không thể đếm file. Hãy gửi file văn bản UTF-8 và thử lại.");
  }
});

bot.hears("📦 Check kho", (ctx) => showStock(ctx));
bot.hears("👤 Tài khoản", (ctx) => { ensureUser(ctx); return sendAccount(ctx, ctx.from.id); });
bot.hears("🪙 Check point", (ctx) => {
  ensureUser(ctx);
  const user = getUser(ctx.from.id);
  return ctx.reply(`🪙 Point của bạn: <b>${user.points}</b>`, { parse_mode: "HTML" });
});
bot.hears("🛒 Mua hàng", (ctx) => {
  ensureUser(ctx);
  const contact = ADMIN_USERNAME ? `@${ADMIN_USERNAME}` : `Telegram ID: ${ADMIN_ID}`;
  return ctx.reply(`Liên hệ admin để mua hàng: ${contact}`);
});
bot.hears("📜 Lịch sử", (ctx) => { ensureUser(ctx); return sendHistory(ctx, ctx.from.id); });

bot.catch((err, ctx) => {
  console.error("Bot error:", err.message);
  if (ctx?.reply) ctx.reply("Có lỗi xảy ra. Vui lòng thử lại sau.").catch(() => {});
});

(async () => {
  await bot.launch();
  console.log("Telegram bot is running.");
})();

process.once("SIGINT", () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));
''',
"README.md": r'''
# Telegram Group Ledger Bot

Bot Telegram bằng Node.js dùng trong nhóm để:
- Hiển thị kho theo **số lượng dòng có dữ liệu** trong file văn bản do admin gửi.
- Hiển thị ID, tên, số dư và point của người dùng.
- Cho người dùng xem point và 20 giao dịch gần nhất.
- Chuyển người mua sang liên hệ admin.
- Admin cộng/trừ point và cộng/trừ số dư bằng lệnh riêng.
- Ghi lịch sử giao dịch kèm thời gian, admin và lý do.

**Phạm vi an toàn:** Bot chỉ đếm số lượng hàng hóa/dịch vụ số hợp pháp. Bot không lưu, hiển thị, bán hoặc phân phối mật khẩu, cookie, token hay thông tin đăng nhập tài khoản. File kho chỉ được tải vào bộ nhớ để đếm dòng, không ghi xuống ổ đĩa.

## 1. Chuẩn bị
- Node.js 20 trở lên
- Tài khoản Telegram
- Tạo bot bằng `@BotFather`, lấy token
- Tạo nhóm Telegram và thêm bot vào nhóm

## 2. Chạy trên Windows CMD
Mở CMD trong thư mục dự án:

```cmd
npm install
copy .env.example .env
notepad .env
```

Điền `BOT_TOKEN` trong `.env`. `ADMIN_ID` đã đặt sẵn là `9047366482`.

Chạy bot:

```cmd
npm start
```

Giữ cửa sổ CMD mở để bot hoạt động.

## 3. Cấu hình Telegram
1. Mở `@BotFather`, dùng `/mybots`, chọn bot và lấy token.
2. Thêm bot vào nhóm Telegram.
3. Nếu muốn bot đọc file tài liệu và tin nhắn lệnh trong nhóm, vào `@BotFather` → `/setprivacy` → chọn bot → `Disable`.
4. Khởi động lại bot sau khi đổi Privacy Mode.
5. Gửi `/start` cho bot (nên gửi trong nhóm và nhắn riêng cho bot ít nhất một lần).
6. Admin gửi `/adminhelp` để xem cú pháp.

Không chia sẻ token bot cho bất kỳ ai. Nếu token bị lộ, tạo token mới bằng BotFather.

## 4. Cách dùng trong nhóm

### Người dùng
- `/start` — đăng ký và hiện menu
- `/kho` — xem số lượng trong kho
- `/taikhoan` — xem ID, tên, số dư, point
- `/point` — xem point
- `/lichsu` — xem 20 giao dịch gần nhất
- `/mua` — xem cách liên hệ admin

### Admin
Có 2 cách chỉ định người nhận.

**Cách A — reply tin nhắn của người nhận:**
Reply tin nhắn của user rồi gửi:
```text
/CT 100 Thưởng khách hàng
/TC 20 Điều chỉnh point
/Nt 100000 Khách nạp tiền
/TT 20000 Hoàn tiền
```

**Cách B — ghi Telegram ID:**
```text
/CT 123456789 100 Thưởng khách hàng
/TC 123456789 20 Điều chỉnh point
/Nt 123456789 100000 Khách nạp tiền
/TT 123456789 20000 Hoàn tiền
```

User phải nhắn `/start` cho bot trước để được tạo hồ sơ. Bot không cho trừ point hoặc số dư xuống dưới 0.

### Cập nhật kho
Admin gửi file văn bản `.txt` hoặc `.csv` vào nhóm. Bot đếm số dòng không rỗng và chỉ trả về con số. Mỗi dòng được tính là một mục hàng hóa. Bot không lưu file và không gửi nội dung file vào nhóm.

## 5. Deploy GitHub + Render

### Đưa code lên GitHub
1. Tạo repository mới trên GitHub.
2. Mở CMD trong thư mục dự án.
3. Chạy:

```cmd
git init
git add .
git commit -m "Initial Telegram bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Thay URL bằng repository của bạn. Không đưa file `.env` lên GitHub.

### Deploy trên Render
1. Đăng nhập Render và chọn **New → Blueprint**.
2. Kết nối GitHub, chọn repository vừa tạo.
3. Render đọc cấu hình từ `render.yaml`.
4. Trong phần Environment, nhập:
   - `BOT_TOKEN`: token lấy từ BotFather
   - `ADMIN_USERNAME`: username admin, không cần dấu `@` (có thể để trống)
5. Tạo dịch vụ. Chọn gói Worker phù hợp; Background Worker và Persistent Disk có thể cần gói trả phí theo chính sách Render hiện hành.
6. Xem Logs, khi thấy `Telegram bot is running.` là bot đã khởi động.

`render.yaml` gắn Persistent Disk tại `/var/data` và SQLite lưu ở `/var/data/bot.sqlite`. Không bỏ Persistent Disk nếu muốn dữ liệu còn sau khi deploy/restart.

## 6. Lưu ý vận hành
- SQLite phù hợp bot nhỏ, một tiến trình bot.
- Sao lưu file `/var/data/bot.sqlite` định kỳ.
- Không chạy cùng một token bot ở nhiều tiến trình polling đồng thời.
- Không gửi token, file dữ liệu hoặc bản sao database lên GitHub.
- Đây là bản nền tảng: chưa có cổng thanh toán tự động, hóa đơn, phân quyền nhiều admin hoặc bảng quản trị web.
'''
}

for rel, content in files.items():
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(textwrap.dedent(content).lstrip())

zip_path = "/mnt/data/telegram-shop-bot.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, names in os.walk(base):
        for name in names:
            full = os.path.join(root, name)
            arc = os.path.relpath(full, base)
            z.write(full, os.path.join("telegram-shop-bot", arc))

print("Created:", zip_path)
print("Files:", ", ".join(sorted([os.path.relpath(os.path.join(r,n), base) for r,_,ns in os.walk(base) for n in ns])))
