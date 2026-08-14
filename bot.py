import os
import re
import tempfile
import uuid
import threading
import telebot
from telebot import apihelper
import requests
from flask import Flask

# --- Веб-сервер для бесплатного тарифа Render ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
# ------------------------------------------------

apihelper.CONNECT_TIMEOUT = 300
apihelper.READ_TIMEOUT = 300
apihelper.CUSTOM_REQUEST_TIMEOUT = 300

TOKEN = '8276557838:AAH_wSAdcAlJwMp8c2wp7y8k0lnhVLePxVA'
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 48 * 1024 * 1024  # Лимит Telegram в 48 МБ

# User-Agent Telegram бота, чтобы сайты отдавали OpenGraph метатеги
HEADERS = {
    'User-Agent': 'TelegramBot (like TwitterBot)'
}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**!"
    )

def parse_og_video_url(url, mirrors):
    """Считывает прямую ссылку на .mp4 из OpenGraph тегов, используемых Telegram"""
    for mirror in mirrors:
        try:
            target_url = url
            if 'instagram.com' in url or 'instagr.am' in url:
                target_url = re.sub(r'https?://(www\.)?instagr(\.am|am\.com)', f'https://{mirror}', url)
            elif 'tiktok.com' in url:
                target_url = re.sub(r'https?://(www\.|vm\.|vt\.)?tiktok\.com', f'https://{mirror}', url)
            elif 'youtube.com' in url or 'youtu.be' in url:
                target_url = re.sub(r'https?://(www\.)?(youtube\.com|youtu\.be)', f'https://{mirror}', url)

            res = requests.get(target_url, headers=HEADERS, timeout=10, allow_redirects=True)
            if res.status_code == 200:
                # Поиск og:video или og:video:secure_url в коде страницы
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

def download_and_send(message, video_url, status_msg, caption):
    """Скачивание файла по прямой ссылке и отправка пользователю"""
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"vid_{uuid.uuid4().hex}.mp4")

    try:
        bot.edit_message_text("⏳ Загружаю видеофайл...", message.chat.id, status_msg.message_id)
        
        res = requests.get(video_url, headers=HEADERS, stream=True, timeout=90)
        res.raise_for_status()

        with open(filename, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        file_size = os.path.getsize(filename)
        if file_size > MAX_FILE_SIZE:
            size_mb = round(file_size / (1024 * 1024), 1)
            bot.edit_message_text(f"⚠️ Видео слишком большое ({size_mb} МБ). Лимит Telegram — 50 МБ.", message.chat.id, status_msg.message_id)
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

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка при отправке: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- TIKTOK ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    status_msg = bot.reply_to(message, "⏳ Извлекаю видео из TikTok...")
    url = message.text.strip()

    # 1. Парсинг через OpenGraph зеркала (vxtiktok / fxtiktok)
    direct_url = parse_og_video_url(url, ['vxtiktok.com', 'fxtiktok.com'])

    # 2. Резерв через TikWM API
    if not direct_url:
        try:
            res = requests.post("https://www.tikwm.com/api/", data={'url': url, 'hd': 1}, headers=HEADERS, timeout=10).json()
            if res.get('code') == 0:
                data = res['data']
                direct_url = data.get('hdplay') or data.get('play')
                if direct_url and not direct_url.startswith('http'):
                    direct_url = 'https://www.tikwm.com' + direct_url
        except Exception:
            pass

    if direct_url:
        download_and_send(message, direct_url, status_msg, "✅ TikTok видео!")
    else:
        bot.edit_message_text("❌ Не удалось получить ссылку на видео TikTok.", message.chat.id, status_msg.message_id)

# --- INSTAGRAM ---
@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    status_msg = bot.reply_to(message, "⏳ Извлекаю Instagram Reels...")
    url = message.text.strip()

    # Парсинг через OpenGraph зеркала (ddinstagram / vxinstagram)
    direct_url = parse_og_video_url(url, ['ddinstagram.com', 'vxinstagram.com'])

    if direct_url:
        download_and_send(message, direct_url, status_msg, "✅ Instagram Reels!")
    else:
        bot.edit_message_text("❌ Не удалось извлечь Reels с Instagram.", message.chat.id, status_msg.message_id)

# --- YOUTUBE SHORTS ---
@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Извлекаю YouTube Shorts...")
    url = message.text.strip()

    # Парсинг через OpenGraph зеркала YouTube (fxyoutube / ddyoutube)
    direct_url = parse_og_video_url(url, ['fxyoutube.com', 'ddyoutube.com'])

    # Резервный метод через Cobalt API
    if not direct_url:
        try:
            payload = {"url": url, "videoQuality": "720"}
            c_res = requests.post("https://api.cobalt.tools/", json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=10)
            if c_res.status_code == 200:
                direct_url = c_res.json().get("url")
        except Exception:
            pass

    if direct_url:
        download_and_send(message, direct_url, status_msg, "✅ YouTube Shorts готово!")
    else:
        bot.edit_message_text("❌ Не удалось скачать YouTube Shorts. Попробуйте еще раз.", message.chat.id, status_msg.message_id)

if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    print("🚀 Бот запущен!")
    bot.infinity_polling()
