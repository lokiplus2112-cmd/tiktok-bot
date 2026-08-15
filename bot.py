import os
import re
import uuid
import tempfile
import telebot
import yt_dlp

# Токен вашего бота
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
bot = telebot.TeleBot(TOKEN)

# Файл с куками в корне проекта
COOKIES_FILE = 'cookies.txt'

def try_send_from_telegram_preview(message):
    """Попытка переотправить видео напрямую из предпросмотра Telegram, если доступно."""
    return False

def check_and_send_video(message, filename, status_msg, caption_text):
    """Отправка видео пользователю с автоматическим сжатием при необходимости."""
    try:
        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        print(f"📦 Размер файла: {file_size_mb:.2f} MB")
        
        # Если файл больше 48 МБ, предупреждаем и сжимаем
        if file_size_mb > 48:
            bot.edit_message_text("⚠️ Файл слишком большой. Сжимаю видео...", message.chat.id, status_msg.message_id)
            compressed_filename = os.path.join(tempfile.gettempdir(), f"compressed_{uuid.uuid4().hex}.mp4")
            
            # Быстрое сжатие с уменьшением качества/разрешения через ffmpeg
            os.system(f'ffmpeg -y -i "{filename}" -vf "scale=-2:720" -crf 28 -preset faster "{compressed_filename}"')
            
            if os.path.exists(compressed_filename) and os.path.getsize(compressed_filename) > 0:
                os.remove(filename)
                filename = compressed_filename

        bot.edit_message_text("⬆️ Загружаю видео в Telegram...", message.chat.id, status_msg.message_id)
        
        with open(filename, 'rb') as video:
            bot.send_video(
                message.chat.id, 
                video, 
                caption=caption_text, 
                supports_streaming=True
            )
        bot.delete_message(message.chat.id, status_msg.message_id)
        
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        bot.edit_message_text("❌ Ошибка при отправке видео.", message.chat.id, status_msg.message_id)

# --- TikTok & Instagram ---
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['tiktok.com', 'instagram.com']))
def download_tiktok_instagram(message):
    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку...")
    filename = os.path.join(tempfile.gettempdir(), f"media_{uuid.uuid4().hex}.mp4")
    url = message.text.strip()

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': filename,
        'quiet': True,
        'merge_output_format': 'mp4',
        'socket_timeout': 30,
        'nocheckcertificate': True,
    }

    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    download_success = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(filename) and os.path.getsize(filename) > 5000:
            download_success = True
    except Exception as e:
        print(f"❌ Ошибка yt-dlp: {e}")

    if download_success and os.path.exists(filename):
        check_and_send_video(message, filename, status_msg, "✅ Ваше видео!")
        if os.path.exists(filename):
            os.remove(filename)
    else:
        bot.edit_message_text("❌ Не удалось скачать видео. Проверьте ссылку.", message.chat.id, status_msg.message_id)

# --- YouTube ---
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    if try_send_from_telegram_preview(message): 
        return
    
    status_msg = bot.reply_to(message, "⏳ Обрабатываю YouTube видео...")
    filename = os.path.join(tempfile.gettempdir(), f"yt_{uuid.uuid4().hex}.mp4")
    url = message.text.strip()
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': filename,
        'quiet': True,
        'merge_output_format': 'mp4',
        'socket_timeout': 30,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'mweb'],
                'skip': ['hls', 'dash']
            }
        }
    }

    # Проверка наличия и размера файла cookies.txt
    if os.path.exists(COOKIES_FILE):
        print(f"✅ Файл cookies.txt найден ({os.path.getsize(COOKIES_FILE)} байт)")
        ydl_opts['cookiefile'] = COOKIES_FILE
    else:
        print("⚠️ ВНИМАНИЕ: Файл cookies.txt НЕ НАЙДЕН в директории проекта!")

    download_success = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(filename) and os.path.getsize(filename) > 5000:
            download_success = True
    except Exception as e:
        print(f"❌ Ошибка yt-dlp: {e}")

    if download_success and os.path.exists(filename):
        check_and_send_video(message, filename, status_msg, "✅ YouTube видео!")
        if os.path.exists(filename):
            os.remove(filename)
    else:
        bot.edit_message_text(
            "❌ YouTube отклонил запрос. Перевыпустите cookies.txt из браузера и обновите его на GitHub.", 
            message.chat.id, 
            status_msg.message_id
        )

# --- Start Command ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Отправь мне ссылку на TikTok, Instagram Reels или YouTube Shorts/Video, и я скачаю его!")

if __name__ == '__main__':
    print("🤖 Бот запущен...")
    bot.infinity_polling()
