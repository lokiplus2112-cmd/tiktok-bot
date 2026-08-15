import os
import re
import time
import tempfile
import uuid
import threading
import telebot
from telebot import apihelper
import requests
from flask import Flask
import yt_dlp

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
TOKEN = '8276557838:AAH_wSAdcAlJwMp8c2wp7y8k0lnhVLePxVA'
bot = telebot.TeleBot(TOKEN)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is live!", 200

@app.route('/healthz')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
# -----------------------------

apihelper.CONNECT_TIMEOUT = 300
apihelper.READ_TIMEOUT = 300
apihelper.CUSTOM_REQUEST_TIMEOUT = 300

MAX_FILE_SIZE = 49 * 1024 * 1024  # Лимит Telegram API — 49 МБ

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

processed_messages = set()

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**!"
    )

def try_send_from_telegram_preview(message):
    if message.message_id in processed_messages:
        return True

    if hasattr(message, 'web_page') and message.web_page:
        wp = message.web_page
        if hasattr(wp, 'video') and wp.video:
            try:
                bot.send_video(
                    message.chat.id,
                    wp.video.file_id,
                    reply_to_message_id=message.message_id,
                    caption="⚡ Отправлено из предпросмотра Telegram!"
                )
                processed_messages.add(message.message_id)
                return True
            except Exception:
                pass
    return False

def check_and_send_video(message, filename, status_msg, caption):
    file_size = os.path.getsize(filename)
    if file_size > MAX_FILE_SIZE:
        size_mb = round(file_size / (1024 * 1024), 1)
        bot.edit_message_text(
            f"⚠️ Видео слишком большое ({size_mb} МБ). Лимит Telegram Bot API — 50 МБ.", 
            message.chat.id, 
            status_msg.message_id
        )
        return

    bot.edit_message_text("📤 Отправляю в чат...", message.chat.id, status_msg.message_id)
    with open(filename, 'rb') as video:
        bot.send_video(
            message.chat.id, 
            video, 
            reply_to_message_id=message.message_id,
            caption=caption,
            timeout=300
        )
    bot.delete_message(message.chat.id, status_msg.message_id)
    processed_messages.add(message.message_id)

def parse_og_video_url(url, mirrors):
    for mirror in mirrors:
        try:
            target_url = url
            if 'instagram.com' in url or 'instagr.am' in url:
                target_url = re.sub(r'https?://(www\.)?instagr(\.am|am\.com)', f'https://{mirror}', url)
            elif 'tiktok.com' in url:
                target_url = re.sub(r'https?://(www\.|vm\.|vt\.)?tiktok\.com', f'https://{mirror}', url)

            res = requests.get(target_url, headers=HEADERS, timeout=10, allow_redirects=True)
            if res.status_code == 200:
                match = re.search(r'property=["\']og:video(?::secure_url)?["\']\s+content=["\']([^"\']+)["\']', res.text, re.IGNORECASE)
                if not match:
                    match = re.search(r'content=["\']([^"\']+\.mp4[^"\']*)["\']', res.text, re.IGNORECASE)
                
                if match:
                    direct_url = match.group(1).replace('&amp;', '&')
                    if direct_url.startswith('http'):
                        return direct_url
        except Exception:
            continue
    return None

def download_file_by_url(video_url, filename):
    res = requests.get(video_url, headers=HEADERS, stream=True, timeout=90)
    res.raise_for_status()
    with open(filename, 'wb') as f:
        for chunk in res.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return os.path.exists(filename) and os.path.getsize(filename) > 30000

# --- TIKTOK ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    if try_send_from_telegram_preview(message):
        return

    status_msg = bot.reply_to(message, "⏳ Скачиваю видео из TikTok...")
    url = message.text.strip()
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")

    try:
        direct_url = parse_og_video_url(url, ['vxtiktok.com', 'fxtiktok.com'])

        if not direct_url:
            res = requests.post("https://www.tikwm.com/api/", data={'url': url, 'hd': 1}, headers=HEADERS, timeout=10).json()
            if res.get('code') == 0:
                data = res['data']
                direct_url = data.get('hdplay') or data.get('play')
                if direct_url and not direct_url.startswith('http'):
                    direct_url = 'https://www.tikwm.com' + direct_url

        if direct_url and download_file_by_url(direct_url, filename):
            check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
        else:
            bot.edit_message_text("❌ Не удалось получить видео TikTok.", message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- INSTAGRAM ---
@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    if try_send_from_telegram_preview(message):
        return

    status_msg = bot.reply_to(message, "⏳ Скачиваю Instagram Reels...")
    url = message.text.strip()
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.mp4")

    try:
        direct_url = parse_og_video_url(url, ['ddinstagram.com', 'vxinstagram.com'])

        if direct_url and download_file_by_url(direct_url, filename):
            check_and_send_video(message, filename, status_msg, "✅ Instagram Reels!")
        else:
            bot.edit_message_text("❌ Не удалось извлечь Reels с Instagram.", message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- YOUTUBE SHORTS (СИСТЕМА БЫСТРОЙ ЗАГРУЗКИ) ---
def extract_youtube_id(url):
    match = re.search(r'(?:shorts/|v=|v%3D|be/)([\w-]{11})', url)
    return match.group(1) if match else None

def get_youtube_cobalt_url(video_id):
    """Быстрое получение прямой ссылки через зеркала Cobalt API"""
    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    instances = [
        "https://api.cobalt.tools/",
        "https://cobalt-api.kwiatekm.com/"
    ]
    
    payload = {
        "url": clean_url,
        "videoQuality": "720",
        "downloadMode": "auto"
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    for api_url in instances:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if data.get("url"):
                    return data.get("url")
                elif data.get("picker"):
                    return data["picker"][0]["url"]
        except Exception:
            continue
    return None

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Обрабатываю YouTube Shorts...")
    url = message.text.strip()
    video_id = extract_youtube_id(url)

    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")

    try:
        # Способ 1: Использование быстрых Cobalt API сервисов
        direct_url = get_youtube_cobalt_url(video_id)
        if direct_url and download_file_by_url(direct_url, filename):
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
            return

        # Способ 2 (Резервный): yt-dlp без жестких требований
        ydl_opts = {
            'format': 'b/best',
            'outtmpl': filename,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30
        }

        if os.path.exists('cookies.txt'):
            ydl_opts['cookiefile'] = 'cookies.txt'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        if os.path.exists(filename) and os.path.getsize(filename) > 30000:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
        else:
            bot.edit_message_text("❌ Не удалось загрузить видео с YouTube.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка скачивания YouTube: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- ЗАПУСК ---
if __name__ == '__main__':
    server_thread = threading.Thread(target=run_web, daemon=True)
    server_thread.start()
    
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass

    print("🚀 Бот и веб-сервер запущены!")
    bot.infinity_polling(skip_pending=True)
