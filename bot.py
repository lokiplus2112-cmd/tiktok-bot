import os
import uuid
import tempfile
import yt_dlp

# Укажите путь к файлу с куки
COOKIES_FILE = 'cookies.txt'

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
        # Маскировка под десктопный браузер
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'mweb'],
                'skip': ['hls', 'dash']
            }
        }
    }

    # Проверка наличия файла cookies.txt
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
