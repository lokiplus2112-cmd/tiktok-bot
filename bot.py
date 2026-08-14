import os
import telebot
import yt_dlp

# ⚠️ Вставьте ваш токен от BotFather между кавычками ниже:
TOKEN = '8276557838:AAH_wSAdcAlJwMp8c2wp7y8k0lnhVLePxVA'

bot = telebot.TeleBot(TOKEN)

# Реакция на команду /start
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из TikTok, и я скачаю его для тебя."
    )

# Реакция на ссылку с tiktok.com
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    status_msg = bot.reply_to(message, "⏳ Скачиваю видео, подождите...")
    url = message.text.strip()
    file_path = f"video_{message.chat.id}.mp4"

    # Настройки для скачивания через yt-dlp
    ydl_opts = {
        'outtmpl': file_path,
        'format': 'best',
        'quiet': True,
    }

    try:
        # Скачиваем файл с TikTok
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Отправляем файл пользователю
        with open(file_path, 'rb') as video:
            bot.send_video(
                message.chat.id, 
                video, 
                reply_to_message_id=message.message_id,
                caption="✅ Ваше видео готово!"
            )

        # Удаляем временное сообщение "Скачиваю..."
        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(
            f"❌ Не удалось скачать видео.\nОшибка: {e}", 
            message.chat.id, 
            status_msg.message_id
        )

    finally:
        # Удаляем скачанный файл с компьютера, чтобы не засорять память
        if os.path.exists(file_path):
            os.remove(file_path)

# Запуск работы бота
if __name__ == '__main__':
    print("🚀 Бот успешно запущен!")
    bot.infinity_polling()