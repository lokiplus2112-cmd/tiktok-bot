import os
import re
import time
import tempfile
import uuid
import threading
import telebot
from telebot import apihelper, types
import requests
from flask import Flask
from werkzeug.serving import run_simple
import yt_dlp

# --- Web-сервер для поддержки активности Render ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/healthz')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    run_simple('0.0.0.0', port, app, threaded=True)

# --- Инициализация бота ---
TOKEN = '8276557838:AAH_wSAdcAlJwMp8c2wp7y8k0lnhVLePxVA'
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 48 * 1024 * 1024
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
}
processed_messages = set()

# --- Вспомогательные функции ---
def try_send_from_telegram_preview(message):
    if message.message_id in processed_messages: 
        return True
    if hasattr(message, 'web_page') and message.web_page and hasattr(message.web_page, 'video') and message.web_page.video:
        try:
            bot.send_video(
                message.chat.id, 
                message.web_page.video.file_id, 
                reply_to_message_id=message.message_id, 
                caption="⚡ Отправлено мгновенно из предпросмотра!"
            )
            processed_messages.add(message.message_id)
            return True
        except Exception: 
            pass
    return False

def download_file_by_url(url, filename):
    try:
        res = requests.get(url, headers=HEADERS, stream=True, timeout=30)
        res.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk: 
                    f.write(chunk)
        return os.path.exists(filename) and os.path.getsize(filename) > 5000
    except Exception: 
        return False

def check_and_send_video(message, filename, status_msg, caption):
    file_size = os.path.getsize(filename)
    if file_size > MAX_FILE_SIZE:
        bot.edit_message_text(
            f"⚠️ Файл слишком большой ({round(file_size/1024/1024, 1)} МБ).", 
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

# --- УНИВЕРСАЛЬНЫЙ ПОИСК МЕДИА ДЛЯ INSTAGRAM ---
def get_instagram_media_urls(url):
    urls = []

    # 1. Запрос через инстансы Cobalt
    instances = [
        "https://api.cobalt.tools/",
        "https://cobalt-api.kwiatekm.com/",
        "https://co.wuk.sh/"
    ]
    for inst in instances:
        try:
            res = requests.post(
                inst, 
                json={"url": url, "downloadMode": "auto"}, 
                headers={"Accept": "application/json", "Content-Type": "application/json"}, 
                timeout=7
            )
            if res.status_code == 200:
                data = res.json()
                if data.get("url"):
                    return [data.get("url")]
                elif data.get("picker"):
                    return [item["url"] for item in data["picker"]]
        except Exception:
            continue

    # 2. Запрос через зеркала Insta (ddinstagram / vxinstagram)
    for mirror in ['ddinstagram.com', 'vxinstagram.com', 'kkinstagram.com']:
        try:
            m_url = url.replace('instagram.com', mirror).replace('instagr.am', mirror)
            res = requests.get(m_url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                # Видео
                match_vid = re.search(r'property="og:video(?::secure_url)?"\s+content="([^"]+)"', res.text)
                if match_vid:
                    urls.append(match_vid.group(1).replace('&amp;', '&'))
                    break
                # Картинка
                match_img = re.search(r'property="og:image"\s+content="([^"]+)"', res.text)
                if match_img:
                    urls.append(match_img.group(1).replace('&amp;', '&'))
                    break
        except Exception:
            continue

    return urls

# --- ОБРАБОТЧИКИ ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "👋 Привет! Присылай ссылку на TikTok, Instagram или YouTube Shorts.")

# TikTok
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    if try_send_from_telegram_preview(message): 
        return
    status_msg = bot.reply_to(message, "⏳ Обрабатываю TikTok...")
    try:
        api_url = f"https://www.tikwm.com/api/?url={message.text.strip()}&hd=1"
        response = requests.get(api_url, headers=HEADERS, timeout=15).json()
        if response.get('code') == 0:
            data = response['data']
            images = data.get('images')
            temp_dir = tempfile.gettempdir()
            
            # Галерея
            if images and isinstance(images, list):
                bot.edit_message_text(f"📸 Скачиваю фото-галерею ({len(images)} ф.)...", message.chat.id, status_msg.message_id)
                media_group = []
                downloaded_files = []
                for idx, img_url in enumerate(images[:10]):
                    f_path = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}_{idx}.jpg")
                    if download_file_by_url(img_url, f_path):
                        downloaded_files.append(f_path)
                        caption = "✅ TikTok слайд-шоу!" if idx == 0 else ""
                        media_group.append(types.InputMediaPhoto(open(f_path, 'rb'), caption=caption))
                if media_group:
                    bot.send_media_group(message.chat.id, media_group, reply_to_message_id=message.message_id)
                    bot.delete_message(message.chat.id, status_msg.message_id)
                    processed_messages.add(message.message_id)
                for f in downloaded_files:
                    try: os.remove(f)
                    except Exception: pass
                return

            # Видео
            video_url = data.get('hdplay') or data.get('play')
            if video_url and not video_url.startswith('http'):
                video_url = 'https://www.tikwm.com' + video_url
            filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")
            if download_file_by_url(video_url, filename):
                check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
                if os.path.exists(filename): os.remove(filename)
            else: 
                bot.edit_message_text("❌ Ошибка сохранения файла.", message.chat.id, status_msg.message_id)
        else: 
            bot.edit_message_text("❌ Не удалось спарсить ссылку.", message.chat.id, status_msg.message_id)
    except Exception as e: 
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

# Instagram
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    if try_send_from_telegram_preview(message): 
        return
    status_msg = bot.reply_to(message, "⏳ Получаю контент из Instagram...")
    temp_dir = tempfile.gettempdir()
    
    try:
        media_urls = get_instagram_media_urls(message.text.strip())
        
        if not media_urls:
            bot.edit_message_text(
                "❌ Не удалось получить контент. Аккаунт может быть закрытым (Private) или ссылка недействительна.", 
                message.chat.id, 
                status_msg.message_id
            )
            return

        # Карусель / Альбом
        if len(media_urls) > 1:
            bot.edit_message_text(f"📸 Загружаю карусель ({len(media_urls)} ф.)...", message.chat.id, status_msg.message_id)
            media_group = []
            downloaded_files = []

            for idx, item_url in enumerate(media_urls[:10]):
                is_video = ".mp4" in item_url.lower() or "video" in item_url.lower()
                ext = ".mp4" if is_video else ".jpg"
                f_path = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}_{idx}{ext}")
                
                if download_file_by_url(item_url, f_path):
                    downloaded_files.append(f_path)
                    caption = "✅ Instagram Альбом!" if idx == 0 else ""
                    if is_video:
                        media_group.append(types.InputMediaVideo(open(f_path, 'rb'), caption=caption))
                    else:
                        media_group.append(types.InputMediaPhoto(open(f_path, 'rb'), caption=caption))

            if media_group:
                bot.send_media_group(message.chat.id, media_group, reply_to_message_id=message.message_id)
                bot.delete_message(message.chat.id, status_msg.message_id)
                processed_messages.add(message.message_id)

            for f_path in downloaded_files:
                try: os.remove(f_path)
                except Exception: pass
            return

        # Одиночный файл (фото или видео)
        single_url = media_urls[0]
        is_video = ".mp4" in single_url.lower() or "video" in single_url.lower() or "/v/" in single_url.lower()
        
        if is_video:
            filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.mp4")
            if download_file_by_url(single_url, filename):
                check_and_send_video(message, filename, status_msg, "✅ Instagram Reels!")
                if os.path.exists(filename): os.remove(filename)
            else:
                bot.edit_message_text("❌ Ошибка скачивания видео.", message.chat.id, status_msg.message_id)
        else:
            filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.jpg")
            if download_file_by_url(single_url, filename):
                with open(filename, 'rb') as photo:
                    bot.send_photo(message.chat.id, photo, reply_to_message_id=message.message_id, caption="🖼 Instagram Фото!")
                bot.delete_message(message.chat.id, status_msg.message_id)
                processed_messages.add(message.message_id)
                if os.path.exists(filename): os.remove(filename)
            else:
                bot.edit_message_text("❌ Ошибка скачивания фото.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

# YouTube Shorts
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    if try_send_from_telegram_preview(message): 
        return
    status_msg = bot.reply_to(message, "⏳ Скачиваю YouTube Shorts...")
    filename = os.path.join(tempfile.gettempdir(), f"yt_{uuid.uuid4().hex}.mp4")
    try:
        ydl_opts = {
            'format': 'b/best',
            'outtmpl': filename,
            'quiet': True,
            'socket_timeout': 10
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([message.text.strip()])
        if os.path.exists(filename) and os.path.getsize(filename) > 5000:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts!")
            if os.path.exists(filename): os.remove(filename)
        else:
            bot.edit_message_text("❌ Не удалось загрузить видео с YouTube.", message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка YouTube: {e}", message.chat.id, status_msg.message_id)

# --- Запуск ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    time.sleep(2)
    try:
        bot.remove_webhook()
    except Exception:
        pass
    
    print("🚀 Бот успешно запущен!")
    bot.infinity_polling(skip_pending=True)
