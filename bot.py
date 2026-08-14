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

MAX_FILE_SIZE = 49 * 1024 * 1024  # Лимит Telegram Bot API — 49 МБ

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

# Кэш обработанных сообщений, чтобы не отправлять дубли
processed_messages = set()

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**!"
    )

def try_send_from_telegram_preview(message):
    """
    Проверяет предпросмотр Telegram и переотправляет видео мгновенно по file_id.
    """
    if message.message_id in processed_messages:
        return True

    if hasattr(message, 'web_page') and message.web_page:
        wp = message.web_page
        
        # 1. Проверяем наличие видео в предпросмотре
        if hasattr(wp, 'video') and wp.video:
            try:
                bot.send_video(
                    message.chat.id,
                    wp.video.file_id,
                    reply_to_message_id=message.message_id,
                    caption="⚡ Отправлено мгновенно из предпросмотра Telegram!"
                )
                processed_messages.add(message.message_id)
                return True
            except Exception:
                pass

        # 2. Проверяем документ
        if hasattr(wp, 'document') and wp.document:
            try:
                bot.send_document(
                    message.chat.id,
                    wp.document.file_id,
                    reply_to_message_id=message.message_id,
                    caption="⚡ Отправлено мгновенно из предпросмотра Telegram!"
                )
                processed_messages.add(message.message_id)
                return True
            except Exception:
                pass

    return False

# --- ОБРАБОТКА ОБНОВЛЕНИЯ ПРЕДПРОСМОТРА (Когда Telegram генерирует Link Preview спустя 1-3 сек) ---
@bot.edited_message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com', 'instagr.am']))
def handle_edited_preview(message):
    try_send_from_telegram_preview(message)

def check_and_send_video(message, filename, status_msg, caption):
    """Проверяет размер файла и отправляет видео"""
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
    """Извлечение прямого .mp4 из OpenGraph метатегов"""
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
    """Скачивание файла по ссылке"""
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

# --- YOUTUBE SHORTS ---
def extract_youtube_id(url):
    match = re.search(r'(?:shorts/|v=|v%3D|be/)([\w-]{11})', url)
    return match.group(1) if match else None

def download_youtube_loader(video_id, filename):
    """Загрузка YouTube через Loader API"""
    try:
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        init_api = f"https://loader.to/ajax/download.php?format=720&url={yt_url}"
        
        res = requests.get(init_api, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return False
            
        data = res.json()
        if not data.get('success'):
            return False
            
        task_id = data.get('id')
        
        for _ in range(10):
            time.sleep(2)
            prog_api = f"https://loader.to/ajax/progress.php?id={task_id}"
            p_res = requests.get(prog_api, headers=HEADERS, timeout=10)
            
            if p_res.status_code == 200:
                p_data = p_res.json()
                if p_data.get('success') and p_data.get('download_url'):
                    dl_url = p_data.get('download_url')
                    return download_file_by_url(dl_url, filename)
    except Exception:
        return False
    return False

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    # 1. Проверяем предпросмотр сразу
    if try_send_from_telegram_preview(message):
        return

    # 2. Ждем 3 секунды: если предпросмотр подгрузится, сработает handle_edited_preview
    time.sleep(3)
    if message.message_id in processed_messages:
        return

    # 3. Если предпросмотра не было, пробуем скачивание через сервис
    status_msg = bot.reply_to(message, "⏳ Обрабатываю YouTube Shorts...")
    url = message.text.strip()
    video_id = extract_youtube_id(url)

    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")

    try:
        success = download_youtube_loader(video_id, filename)
        
        if success:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
        else:
            bot.edit_message_text("❌ Не удалось загрузить видео с YouTube. Попробуйте еще раз через 5 секунд.", message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    print("🚀 Бот запущен!")
    bot.infinity_polling()
