import os
import re
import uuid
import tempfile
import threading
import time
import telebot
import requests
from flask import Flask
from werkzeug.serving import run_simple

# ==========================================
# 1. ВЕБ-СЕРВЕР ДЛЯ RENDER (Health Check)
# ==========================================
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

# ==========================================
# 2. НАСТРОЙКИ И КОНФИГУРАЦИЯ БОТА
# ==========================================
TOKEN = "8276557838:AAEYciE_o_-xzt5f0rb-3wtnEfGfAvw5p7Q"
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 48 * 1024 * 1024  # Лимит Telegram 48 МБ

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

def check_and_send_video(message, filename, status_msg, caption):
    """Проверка размера файла и отправка видео в Telegram"""
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

    bot.edit_message_text("📤 Отправляю видео в чат...", message.chat.id, status_msg.message_id)
    with open(filename, 'rb') as video:
        bot.send_video(
            message.chat.id, 
            video, 
            reply_to_message_id=message.message_id,
            caption=caption,
            timeout=300
        )
    bot.delete_message(message.chat.id, status_msg.message_id)

def send_photos_group(message, photo_urls, status_msg, caption="✅ Фотографии загружены!"):
    """Отправка списка изображений альбмом/группой в Telegram"""
    bot.edit_message_text("📤 Отправляю фотографии...", message.chat.id, status_msg.message_id)
    media_group = []
    
    # Telegram разрешает отправлять до 10 медиафайлов в одной группе
    for idx, img_url in enumerate(photo_urls[:10]):
        if idx == 0:
            media_group.append(telebot.types.InputMediaPhoto(media=img_url, caption=caption))
        else:
            media_group.append(telebot.types.InputMediaPhoto(media=img_url))
            
    try:
        bot.send_media_group(message.chat.id, media=media_group, reply_to_message_id=message.message_id)
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        print(f"❌ Ошибка отправки фото альбомом: {e}")
        bot.edit_message_text("❌ Ошибка при отправке фотографий.", message.chat.id, status_msg.message_id)

# --- TIKTOK (ВИДЕО + ФОТО КАРУСЕЛЬ) ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку TikTok...")
    url = message.text.strip()
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")
    
    try:
        api_url = "https://www.tikwm.com/api/"
        response = requests.post(api_url, data={'url': url, 'hd': 1}, headers=HEADERS, timeout=15).json()

        if response.get('code') == 0:
            data = response['data']
            
            # Проверяем, являются ли данные каруселью фотографий
            images = data.get('images')
            if images and isinstance(images, list):
                send_photos_group(message, images, status_msg, "✅ Фотогалерея из TikTok!")
                return

            # Если это видео
            video_url = data.get('hdplay') or data.get('play')
            if video_url and not video_url.startswith('http'):
                video_url = 'https://www.tikwm.com' + video_url

            bot.edit_message_text("⏳ Скачиваю видео...", message.chat.id, status_msg.message_id)
            
            res = requests.get(video_url, headers=HEADERS, stream=True, timeout=60)
            res.raise_for_status()
            with open(filename, 'wb') as f:
                for chunk in res.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            
            check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
        else:
            bot.edit_message_text("❌ Ошибка загрузки TikTok. Проверьте ссылку.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- INSTAGRAM (REELS + ФОТО / АЛЬБОМЫ) ---
def get_instagram_media(url):
    """Парсинг видео и фото из зеркала Instagram"""
    video_urls = []
    image_urls = []
    
    for mirror in ['ddinstagram.com', 'vxinstagram.com']:
        try:
            mirror_url = url.replace('instagram.com', mirror).replace('instagr.am', mirror)
            res = requests.get(mirror_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                # Поиск видео
                v_matches = re.findall(r'property="og:video(?::secure_url)?"\s+content="([^"]+)"', res.text)
                for v in v_matches:
                    clean_v = v.replace('&amp;', '&')
                    if clean_v not in video_urls:
                        video_urls.append(clean_v)
                
                # Поиск фото (если видео не найдены)
                if not video_urls:
                    i_matches = re.findall(r'property="og:image"\s+content="([^"]+)"', res.text)
                    for img in i_matches:
                        clean_img = img.replace('&amp;', '&')
                        if clean_img not in image_urls:
                            image_urls.append(clean_img)
                            
                if video_urls or image_urls:
                    break
        except Exception:
            continue
            
    return video_urls, image_urls

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    status_msg = bot.reply_to(message, "⏳ Получаю медиа из Instagram...")
    url = message.text.strip()
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.mp4")
    
    try:
        video_urls, image_urls = get_instagram_media(url)
        
        # 1. Если нашли видео (Reels / Post Video)
        if video_urls:
            bot.edit_message_text("⏳ Скачиваю Instagram видео...", message.chat.id, status_msg.message_id)
            res = requests.get(video_urls[0], headers=HEADERS, stream=True, timeout=60)
            if res.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if os.path.getsize(filename) > 10000:
                    check_and_send_video(message, filename, status_msg, "✅ Instagram Reels!")
                    return

        # 2. Если нашли фото / альбомы
        if image_urls:
            send_photos_group(message, image_urls, status_msg, "✅ Фото из Instagram!")
            return

        bot.edit_message_text("❌ Не удалось скачать медиа из Instagram. Возможно, профиль приватный.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- YOUTUBE SHORTS / VIDEO ---
def extract_youtube_id(url):
    match = re.search(r'(?:shorts/|v=|v%3D|be/)([\w-]{11})', url)
    return match.group(1) if match else None

def download_youtube_loader(video_id, filename):
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
        
        for _ in range(15):
            time.sleep(2)
            prog_api = f"https://loader.to/ajax/progress.php?id={task_id}"
            p_res = requests.get(prog_api, headers=HEADERS, timeout=10)
            
            if p_res.status_code == 200:
                p_data = p_res.json()
                if p_data.get('success') and p_data.get('download_url'):
                    dl_url = p_data.get('download_url')
                    
                    video_res = requests.get(dl_url, headers=HEADERS, stream=True, timeout=90)
                    if video_res.status_code == 200:
                        with open(filename, 'wb') as f:
                            for chunk in video_res.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f.write(chunk)
                        return os.path.exists(filename) and os.path.getsize(filename) > 30000
    except Exception as e:
        print(f"❌ Ошибка Loader.to: {e}")
        return False
    return False

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Получаю видео из YouTube...")
    raw_url = message.text.strip()
    video_id = extract_youtube_id(raw_url)
    
    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")
    
    try:
        bot.edit_message_text("⏳ Обрабатываю YouTube видео (720p)...", message.chat.id, status_msg.message_id)

        download_success = download_youtube_loader(video_id, filename)

        if download_success:
            check_and_send_video(message, filename, status_msg, "✅ YouTube видео готово!")
        else:
            bot.edit_message_text("❌ Сервер обработки перегружен. Попробуйте еще раз через полминуты.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- КОМАНДЫ ---
@bot.message_handler(commands=['start', 'help'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 **Привет! Я универсальный бот-загрузчик.**\n\n"
        "Отправь мне ссылку из:\n"
        "• **TikTok** (видео и фото-слайдшоу)\n"
        "• **Instagram** (Reels, видео и фото)\n"
        "• **YouTube** (Shorts и обычные видео)",
        parse_mode="Markdown"
    )

# ==========================================
# 3. ЗАПУСК БОТА
# ==========================================
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    time.sleep(2)
    
    print("🚀 Бот успешно запущен!")
    
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 409:
                print("⚠️ Конфликт 409: переподключение...")
                time.sleep(5)
            else:
                time.sleep(3)
        except Exception as e:
            print(f"⚠️ Ошибка polling: {e}")
            time.sleep(3)
