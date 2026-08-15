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
import yt_dlp

# --- Профессиональный веб-сервер (WSGI Gunicorn) для Render ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/healthz')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    from gunicorn.app.base import BaseApplication

    class StandaloneApplication(BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    options = {
        'bind': f'0.0.0.0:{port}',
        'workers': 1,
        'loglevel': 'warning'
    }
    StandaloneApplication(app, options).run()
# ---------------------------------------------------------------

apihelper.CONNECT_TIMEOUT = 300
apihelper.READ_TIMEOUT = 300
apihelper.CUSTOM_REQUEST_TIMEOUT = 300

TOKEN = '8276557838:AAH_wSAdcAlJwMp8c2wp7y8k0lnhVLePxVA'
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 48 * 1024 * 1024  # Ограничение Telegram в 48 МБ

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

processed_messages = set()

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео или фото-пост из **TikTok**, **Instagram** или **YouTube Shorts**!"
    )

def try_send_from_telegram_preview(message):
    """Мгновенная пересылка, если Telegram уже сгенерировал превью"""
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
                    caption="⚡ Отправлено мгновенно из предпросмотра!"
                )
                processed_messages.add(message.message_id)
                return True
            except Exception:
                pass
    return False

def check_and_send_video(message, filename, status_msg, caption):
    """Проверка размера и отправка одиночного видео"""
    file_size = os.path.getsize(filename)
    
    if file_size > MAX_FILE_SIZE:
        size_mb = round(file_size / (1024 * 1024), 1)
        bot.edit_message_text(
            f"⚠️ Видео слишком большое ({size_mb} МБ).\n"
            f"Telegram запрещает ботам отправлять файлы больше 50 МБ.", 
            message.chat.id, 
            status_msg.message_id
        )
        return

    bot.edit_message_text("📤 Отправляю файл в чат...", message.chat.id, status_msg.message_id)
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

def download_file_by_url(url, filename):
    res = requests.get(url, headers=HEADERS, stream=True, timeout=30)
    res.raise_for_status()
    with open(filename, 'wb') as f:
        for chunk in res.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return os.path.exists(filename) and os.path.getsize(filename) > 5000

# --- TIKTOK (ВИДЕО + СЛАЙД-ШОУ/ГАЛЕРЕИ) ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    if try_send_from_telegram_preview(message):
        return

    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку TikTok...")
    url = message.text.strip()
    temp_dir = tempfile.gettempdir()
    
    try:
        api_url = "https://www.tikwm.com/api/"
        response = requests.post(api_url, data={'url': url, 'hd': 1}, headers=HEADERS, timeout=15).json()

        if response.get('code') == 0:
            data = response['data']
            images = data.get('images')
            
            # Если это слайд-шоу с картинками
            if images and isinstance(images, list):
                bot.edit_message_text(f"📸 Загружаю фото-галерею ({len(images)} фото)...", message.chat.id, status_msg.message_id)
                
                media_group = []
                downloaded_files = []

                for idx, img_url in enumerate(images[:10]):
                    img_path = os.path.join(temp_dir, f"tt_img_{uuid.uuid4().hex}_{idx}.jpg")
                    if download_file_by_url(img_url, img_path):
                        downloaded_files.append(img_path)
                        caption = "✅ TikTok галерея!" if idx == 0 else ""
                        media_group.append(types.InputMediaPhoto(open(img_path, 'rb'), caption=caption))

                if media_group:
                    bot.send_media_group(message.chat.id, media_group, reply_to_message_id=message.message_id)
                    bot.delete_message(message.chat.id, status_msg.message_id)
                    processed_messages.add(message.message_id)

                for f_path in downloaded_files:
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass
                return

            # Если обычное видео
            video_url = data.get('hdplay') or data.get('play')
            if video_url and not video_url.startswith('http'):
                video_url = 'https://www.tikwm.com' + video_url

            filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")
            
            if download_file_by_url(video_url, filename):
                check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
                if os.path.exists(filename):
                    os.remove(filename)
            else:
                bot.edit_message_text("❌ Ошибка при сохранении файла.", message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Ошибка загрузки TikTok.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

# --- INSTAGRAM (REELS, ФОТО И КАРУСЕЛИ) ---
def get_instagram_media_urls(url):
    try:
        cobalt_url = "https://api.cobalt.tools/"
        payload = {"url": url, "downloadMode": "auto"}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        
        res = requests.post(cobalt_url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if data.get("url"):
                return [data.get("url")]
            elif data.get("picker"):
                return [item["url"] for item in data["picker"]]
    except Exception:
        pass

    for mirror in ['ddinstagram.com', 'vxinstagram.com']:
        try:
            mirror_url = url.replace('instagram.com', mirror).replace('instagr.am', mirror)
            res = requests.get(mirror_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                match = re.search(r'property="og:video(?::secure_url)?"\s+content="([^"]+)"', res.text)
                if match:
                    return [match.group(1).replace('&amp;', '&')]
                img_match = re.search(r'property="og:image"\s+content="([^"]+)"', res.text)
                if img_match:
                    return [img_match.group(1).replace('&amp;', '&')]
        except Exception:
            continue
            
    return []

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    if try_send_from_telegram_preview(message):
        return

    status_msg = bot.reply_to(message, "⏳ Получаю контент из Instagram...")
    url = message.text.strip()
    temp_dir = tempfile.gettempdir()
    
    try:
        media_urls = get_instagram_media_urls(url)

        if not media_urls:
            bot.edit_message_text("❌ Не удалось получить контент. Пост закрыт или Instagram заблокировал запрос.", message.chat.id, status_msg.message_id)
            return

        # Карусель (несколько файлов)
        if len(media_urls) > 1:
            bot.edit_message_text(f"📸 Загружаю альбом ({len(media_urls)} элементов)...", message.chat.id, status_msg.message_id)
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
                try:
                    os.remove(f_path)
                except Exception:
                    pass
            return

        # Один файл (видео или картинка)
        single_url = media_urls[0]
        bot.edit_message_text("⏳ Скачиваю файл...", message.chat.id, status_msg.message_id)
        is_video = ".mp4" in single_url.lower() or "video" in single_url.lower()
        
        if is_video:
            filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.mp4")
            if download_file_by_url(single_url, filename):
                check_and_send_video(message, filename, status_msg, "✅ Instagram Reels!")
                if os.path.exists(filename):
                    os.remove(filename)
            else:
                bot.edit_message_text("❌ Ошибка при сохранении видео.", message.chat.id, status_msg.message_id)
        else:
            filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.jpg")
            if download_file_by_url(single_url, filename):
                with open(filename, 'rb') as photo:
                    bot.send_photo(message.chat.id, photo, reply_to_message_id=message.message_id, caption="🖼 Instagram Фото!")
                bot.delete_message(message.chat.id, status_msg.message_id)
                processed_messages.add(message.message_id)
                if os.path.exists(filename):
                    os.remove(filename)
            else:
                bot.edit_message_text("❌ Ошибка при сохранении фото.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

# --- YOUTUBE SHORTS ---
def extract_youtube_id(url):
    match = re.search(r'(?:shorts/|v=|v%3D|be/)([\w-]{11})', url)
    return match.group(1) if match else None

def get_youtube_fallback_url(video_id):
    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    instances = [
        "https://api.cobalt.tools/",
        "https://cobalt-api.kwiatekm.com/",
        "https://co.wuk.sh/"
    ]
    payload = {"url": clean_url, "videoQuality": "720", "downloadMode": "auto"}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    for api_url in instances:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=6)
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
    if try_send_from_telegram_preview(message):
        return

    status_msg = bot.reply_to(message, "⏳ Скачиваю YouTube Shorts...")
    raw_url = message.text.strip()
    video_id = extract_youtube_id(raw_url)
    
    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")
    
    ydl_opts = {
        'format': 'b/best',
        'outtmpl': filename,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 10,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb'],
            }
        }
    }

    try:
        download_success = False
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            if os.path.exists(filename) and os.path.getsize(filename) > 30000:
                download_success = True
        except Exception:
            download_success = False

        if not download_success:
            direct_url = get_youtube_fallback_url(video_id)
            if direct_url:
                download_success = download_file_by_url(direct_url, filename)

        if download_success:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
        else:
            bot.edit_message_text("❌ Не удалось получить видеопоток с YouTube.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка YouTube: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- ЗАПУСК ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    
    time.sleep(3)
    try:
        bot.remove_webhook()
    except Exception:
        pass

    print("🚀 Бот запущен!")
    
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            time.sleep(5)
