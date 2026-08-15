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

MAX_FILE_SIZE = 48 * 1024 * 1024  # Ограничение Telegram в 48 МБ (запас от 50 МБ)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**!"
    )

def check_and_send_video(message, filename, status_msg, caption):
    """Проверка размера файла перед отправкой в Telegram"""
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

# --- TIKTOK ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    status_msg = bot.reply_to(message, "⏳ Получаю HD видео из TikTok...")
    url = message.text.strip()
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")
    
    try:
        api_url = "https://www.tikwm.com/api/"
        response = requests.post(api_url, data={'url': url, 'hd': 1}, headers=HEADERS, timeout=15).json()

        if response.get('code') == 0:
            data = response['data']
            video_url = data.get('hdplay') or data.get('play')
            
            if video_url and not video_url.startswith('http'):
                video_url = 'https://www.tikwm.com' + video_url

            bot.edit_message_text("⏳ Скачиваю файл...", message.chat.id, status_msg.message_id)
            
            res = requests.get(video_url, headers=HEADERS, stream=True, timeout=60)
            res.raise_for_status()
            with open(filename, 'wb') as f:
                for chunk in res.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            
            check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
        else:
            bot.edit_message_text("❌ Ошибка загрузки TikTok.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# --- INSTAGRAM ---
def get_instagram_direct_url(url):
    for mirror in ['ddinstagram.com', 'vxinstagram.com']:
        try:
            mirror_url = url.replace('instagram.com', mirror).replace('instagr.am', mirror)
            res = requests.get(mirror_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                match = re.search(r'property="og:video(?::secure_url)?"\s+content="([^"]+)"', res.text)
                if match:
                    return match.group(1).replace('&amp;', '&')
        except Exception:
            continue
    return None

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    status_msg = bot.reply_to(message, "⏳ Получаю видео из Instagram...")
    url = message.text.strip()
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"ig_{uuid.uuid4().hex}.mp4")
    
    try:
        video_url = get_instagram_direct_url(url)
        download_success = False

        if video_url:
            try:
                bot.edit_message_text("⏳ Скачиваю Instagram Reels...", message.chat.id, status_msg.message_id)
                res = requests.get(video_url, headers=HEADERS, stream=True, timeout=60)
                if res.status_code == 200:
                    with open(filename, 'wb') as f:
                        for chunk in res.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    if os.path.getsize(filename) > 10000:
                        download_success = True
            except Exception:
                download_success = False

        if download_success:
            check_and_send_video(message, filename, status_msg, "✅ Instagram Reels!")
        else:
            bot.edit_message_text("❌ Не удалось скачать видео с Instagram.", message.chat.id, status_msg.message_id)

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
    try:
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        # Использование формата 720p для оптиматизации размера под лимит 50 МБ
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
    except Exception:
        return False
    return False

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Получаю видео из YouTube...")
    raw_url = message.text.strip()
    video_id = extract_youtube_id(raw_url)
    
    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")
    
    try:
        bot.edit_message_text("⏳ Обрабатываю YouTube Shorts (720p)...", message.chat.id, status_msg.message_id)

        download_success = download_youtube_loader(video_id, filename)

        if download_success:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
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

if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    print("🚀 Бот запущен!")
    bot.infinity_polling()
