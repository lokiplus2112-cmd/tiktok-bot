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

MAX_FILE_SIZE = 48 * 1024 * 1024  # Лимит Telegram — 48 МБ

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**!"
    )

def try_send_from_telegram_preview(message):
    """
    Пытается мгновенно переотправить видео из предпросмотра (Link Preview),
    которое Telegram уже закешировал на своих серверах.
    """
    if hasattr(message, 'web_page') and message.web_page:
        wp = message.web_page
        
        # 1. Проверяем наличие видео в объекте Link Preview
        if hasattr(wp, 'video') and wp.video:
            try:
                bot.send_video(
                    message.chat.id,
                    wp.video.file_id,
                    reply_to_message_id=message.message_id,
                    caption="⚡ Скопировано напрямую из предпросмотра Telegram!"
                )
                return True
            except Exception:
                pass

        # 2. Проверяем наличие документа/анимации (в редких случаях для Shorts/Reels)
        if hasattr(wp, 'document') and wp.document and wp.document.mime_type and 'video' in wp.document.mime_type:
            try:
                bot.send_document(
                    message.chat.id,
                    wp.document.file_id,
                    reply_to_message_id=message.message_id,
                    caption="⚡ Скопировано напрямую из предпросмотра Telegram!"
                )
                return True
            except Exception:
                pass

    return False

def download_and_send(message, video_url, status_msg, caption):
    """Загрузка файла по ссылке и отправка в чат (Резервный вариант)"""
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"vid_{uuid.uuid4().hex}.mp4")

    try:
        bot.edit_message_text("⏳ Скачиваю видеофайл...", message.chat.id, status_msg.message_id)
        
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

def parse_og_video_url(url, mirrors):
    """Считывание прямой ссылки из OpenGraph метатегов"""
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

# --- TIKTOK ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    # 1. Попытка забрать видео мгновенно из Link Preview Telegram
    if try_send_from_telegram_preview(message):
        return

    # 2. Если предпросмотра нет, скачиваем резервным путем
    status_msg = bot.reply_to(message, "⏳ Извлекаю видео из TikTok...")
    url = message.text.strip()

    direct_url = parse_og_video_url(url, ['vxtiktok.com', 'fxtiktok.com'])

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
        bot.edit_message_text("❌ Не удалось получить видео TikTok.", message.chat.id, status_msg.message_id)

# --- INSTAGRAM ---
@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    # 1. Попытка забрать видео мгновенно из Link Preview Telegram
    if try_send_from_telegram_preview(message):
        return

    # 2. Резервный путь
    status_msg = bot.reply_to(message, "⏳ Извлекаю Instagram Reels...")
    url = message.text.strip()

    direct_url = parse_og_video_url(url, ['ddinstagram.com', 'vxinstagram.com'])

    if direct_url:
        download_and_send(message, direct_url, status_msg, "✅ Instagram Reels!")
    else:
        bot.edit_message_text("❌ Не удалось извлечь Reels с Instagram.", message.chat.id, status_msg.message_id)

# --- YOUTUBE SHORTS ---
def extract_youtube_id(url):
    match = re.search(r'(?:shorts/|v=|v%3D|be/)([\w-]{11})', url)
    return match.group(1) if match else None

def get_youtube_stream_link(video_id):
    clean_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        c_res = requests.post(
            "https://api.cobalt.tools/",
            json={"url": clean_url, "videoQuality": "720"},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=8
        )
        if c_res.status_code == 200:
            c_data = c_res.json()
            if c_data.get("url"):
                return c_data.get("url")
    except Exception:
        pass

    piped_instances = ["https://pipedapi.kavin.rocks", "https://api.piped.yt", "https://pipedapi.mha.fi"]
    for instance in piped_instances:
        try:
            p_res = requests.get(f"{instance}/streams/{video_id}", timeout=6)
            if p_res.status_code == 200:
                data = p_res.json()
                for stream in data.get("videoStreams", []):
                    if stream.get("videoOnly") is False and "video/mp4" in stream.get("mimeType", ""):
                        return stream.get("url")
        except Exception:
            continue

    invidious_gateways = [
        f"https://inv.nadeko.net/latest_version?id={video_id}&itag=18",
        f"https://invidious.nerdvpn.de/latest_version?id={video_id}&itag=18"
    ]
    for gw in invidious_gateways:
        try:
            h_res = requests.head(gw, timeout=5, allow_redirects=True)
            if h_res.status_code == 200:
                return gw
        except Exception:
            continue

    return None

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    # 1. Попытка забрать видео мгновенно из Link Preview Telegram
    if try_send_from_telegram_preview(message):
        return

    # 2. Резервный путь
    status_msg = bot.reply_to(message, "⏳ Извлекаю YouTube Shorts...")
    url = message.text.strip()
    video_id = extract_youtube_id(url)

    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    direct_url = get_youtube_stream_link(video_id)

    if direct_url:
        download_and_send(message, direct_url, status_msg, "✅ YouTube Shorts готово!")
    else:
        bot.edit_message_text("❌ Серверы YouTube временно недоступны. Попробуйте еще раз через полминуты.", message.chat.id, status_msg.message_id)

if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    print("🚀 Бот запущен!")
    bot.infinity_polling()
