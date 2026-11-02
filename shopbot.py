import telebot
bot = telebot.TeleBot("9291585542:AAEILt9kRz0opsjp2B1OAlIf30vCZMlaCSw") # lấy từ BotFather
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "Shop clone Tùng - Gõ /mua để xem hàng")

bot.infinity_polling()