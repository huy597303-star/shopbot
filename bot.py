import telebot
from telebot import types
import os

TOKEN = "9291585542:AAEILt9kRz0opsjp2B1OAlIf30vCZMlaCSw"
ADMIN_ID = 597303  # ID Telegram của bác
FILE_KHO = "clone.txt"

bot = telebot.TeleBot(TOKEN)

# Tạo file kho nếu chưa có
if not os.path.exists(FILE_KHO):
    open(FILE_KHO, 'w').close()

def dem_kho():
    try:
        with open(FILE_KHO, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip() != ""]
            return len(lines)
    except:
        return 0

@bot.message_handler(commands=['start', 'mua'])
def start(m):
    sl = dem_kho()
    text = f"🛒 SHOP CLONE TÙNG - VIP\n\n📦 Kho hiện có: {sl} acc\n\n👉 Gõ /kho để check số lượng\n👉 /lay <số lượng> để lấy clone\n\n💰 Giá: 1 acc = 10k"
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['kho', 'check'])
def check_kho(m):
    sl = dem_kho()
    bot.send_message(m.chat.id, f"📦 KHO HIỆN CÓ: {sl} ACC\n\nFile: {FILE_KHO}", parse_mode="Markdown")
    # Auto gửi file cho admin xem
    if m.from_user.id == ADMIN_ID or str(m.from_user.id) == str(ADMIN_ID):
        if sl > 0:
            bot.send_document(m.chat.id, open(FILE_KHO, 'rb'), caption=f"File gốc hiện có {sl} acc")

# ADMIN THÊM ACC - CÁCH 1: GỬI FILE .txt
@bot.message_handler(content_types=['document'])
def handle_file(m):
    if m.from_user.id != ADMIN_ID:
        bot.reply_to(m, "Bạn không phải admin!")
        return
    
    file_info = bot.get_file(m.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    
    # Lưu file tạm
    with open("tam.txt", "wb") as f:
        f.write(downloaded)
    
    # Đếm acc mới
    with open("tam.txt", "r", encoding='utf-8', errors='ignore') as f:
        new_acc = [l.strip() for l in f if l.strip() != ""]
    
    # Cộng dồn vào kho chính
    with open(FILE_KHO, "a", encoding="utf-8") as f:
        for acc in new_acc:
            f.write(acc + "\n")
    
    os.remove("tam.txt")
    tong = dem_kho()
    
    # BÁO CÁO VIP
    bot.send_message(m.chat.id, f"✅ ĐÃ THÊM THÀNH CÔNG\n\n➕ Thêm mới: {len(new_acc)} acc\n📦 Tổng kho hiện tại: {tong} acc", parse_mode="Markdown")
    # Auto upload lại file kho mới lên box chat
    bot.send_document(m.chat.id, open(FILE_KHO, 'rb'), caption=f"📤 File kho mới nhất - {tong} acc")

# ADMIN THÊM ACC - CÁCH 2: DÁN TRỰC TIẾP
@bot.message_handler(commands=['them'])
def them_acc(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        # Cú pháp: /them uid|pass|2fa
        data = m.text.replace("/them ", "").strip()
        if not data or data == "/them":
            bot.reply_to(m, "Dùng: /them uid|pass|2fa\nHoặc gửi file .txt")
            return
        
        with open(FILE_KHO, "a", encoding="utf-8") as f:
            f.write(data + "\n")
        
        tong = dem_kho()
        bot.reply_to(m, f"✅ Đã thêm 1 acc.\n📦 Tổng kho: {tong} acc", parse_mode="Markdown")
        bot.send_document(m.chat.id, open(FILE_KHO, 'rb'), caption=f"File kho update - {tong} acc")
    except Exception as e:
        bot.reply_to(m, f"Lỗi: {e}")

@bot.message_handler(commands=['lay'])
def lay_acc(m):
    try:
        parts = m.text.split()
        so_luong = int(parts[1]) if len(parts) > 1 else 1
        tong = dem_kho()
        
        if tong < so_luong:
            bot.reply_to(m, f"❌ Kho chỉ còn {tong} acc, không đủ {so_luong} acc!")
            return

        with open(FILE_KHO, "r", encoding="utf-8") as f:
            all_acc = f.readlines()
        
        lay = all_acc[:so_luong]
        con_lai = all_acc[so_luong:]

        with open(FILE_KHO, "w", encoding="utf-8") as f:
            f.writelines(con_lai)
        
        tong_moi = dem_kho()
        acc_text = "".join(lay)
        
        bot.send_message(m.chat.id, f"✅ Đã lấy {so_luong} acc. Gửi file bên dưới:\n📦 Kho còn lại: {tong_moi} acc")
        bot.send_document(m.chat.id, open(FILE_KHO, 'rb')) # Gửi file cho khách nếu muốn, hoặc chỉ gửi text
        
        # Gửi acc cho người mua
        bot.send_message(m.chat.id, f"`\n{acc_text}\n```", parse_mode="Markdown")

        # Báo cho admin
        bot.send_message(ADMIN_ID, f"🔔 Khách {m.from_user.id} vừa lấy {so_luong} acc. Kho còn {tong_moi}")

    except Exception as e:
        bot.reply_to(m, "Dùng: /lay 5 (lấy 5 acc)")

print("Bot VIP đang chạy...")
bot.infinity_polling()
