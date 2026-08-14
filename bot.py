import os
import re
import tempfile
import uuid
import threading
import telebot
from telebot import apihelper
import requests
from flask import Flask
import yt_dlp

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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**!"
    )

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
            
            bot.edit_message_text("📤 Отправляю в чат...", message.chat.id, status_msg.message_id)
            
            with open(filename, 'rb') as video:
                bot.send_video(
                    message.chat.id, 
                    video, 
                    reply_to_message_id=message.message_id,
                    caption="✅ TikTok видео!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
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
            bot.edit_message_text("📤 Отправляю в чат...", message.chat.id, status_msg.message_id)
            with open(filename, 'rb') as video:
                bot.send_video(
                    message.chat.id, 
                    video, 
                    reply_to_message_id=message.message_id,
                    caption="✅ Instagram Reels!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
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

def download_youtube_via_proxy(video_id, filename):
    # Используем внешние медиа-сервера, которые не забанены в Google
    gateways = [
        f"https://invidious.nerdvpn.de/latest_version?id={video_id}&itag=22",
        f"https://inv.nadeko.net/latest_version?id={video_id}&itag=22",
        f"https://invidious.drgns.space/latest_version?id={video_id}&itag=22",
        f"https://inv.nadeko.net/latest_version?id={video_id}&itag=18"
    ]
    
    for stream_url in gateways:
        try:
            res = requests.get(stream_url, headers=HEADERS, stream=True, timeout=30, allow_redirects=True)
            if res.status_code == 200 and int(res.headers.get('Content-Length', 0)) > 50000:
                with open(filename, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if os.path.exists(filename) and os.path.getsize(filename) > 50000:
                    return True
        except Exception:
            continue
    return False

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Получаю видео из YouTube...")
    raw_url = message.text.strip()
    video_id = extract_youtube_id(raw_url)
    
    if not video_id:
        bot.edit_message_text("❌ Неверная ссылка на YouTube.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")
    
    try:
        bot.edit_message_text("⏳ Скачиваю YouTube Shorts...", message.chat.id, status_msg.message_id)

        # 1. Загрузка через шлюз напрямую
        download_success = download_youtube_via_proxy(video_id, filename)

        # 2. Резервный метод через Cobalt API
        if not download_success:
            try:
                payload = {"url": f"https://www.youtube.com/watch?v={video_id}"}
                headers = {"Accept": "application/json", "Content-Type": "application/json"}
                c_res = requests.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=10)
                if c_res.status_code == 200:
                    dl_link = c_res.json().get("url")
                    if dl_link:
                        v_res = requests.get(dl_link, headers=HEADERS, stream=True, timeout=60)
                        if v_res.status_code == 200:
                            with open(filename, 'wb') as f:
                                for chunk in v_res.iter_content(chunk_size=1024 * 1024):
                                    if chunk:
                                        f.write(chunk)
                            if os.path.exists(filename) and os.path.getsize(filename) > 50000:
                                download_success = True
            except Exception:
                pass

        if download_success:
            bot.edit_message_text("📤 Отправляю в чат...", message.chat.id, status_msg.message_id)
            with open(filename, 'rb') as video:
                bot.send_video(
                    message.chat.id, 
                    video, 
                    reply_to_message_id=message.message_id,
                    caption="✅ YouTube Shorts готово!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Не удалось скачать видео. Попробуйте еще раз через несколько секунд.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка скачивания: {e}", message.chat.id, status_msg.message_id)
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
