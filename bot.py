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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 Привет! Отправь мне ссылку на видео из **TikTok**, **Instagram (Reels)** или **YouTube (Shorts)**, и я скачаю его!"
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
                    caption="✅ TikTok видео в формате HD!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Не удалось найти TikTok видео.", message.chat.id, status_msg.message_id)

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
                if not match:
                    match = re.search(r'content="([^"]+\.mp4[^"]*)"', res.text)
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

        if not download_success:
            bot.edit_message_text("⏳ Скачиваю видео (резервный канал)...", message.chat.id, status_msg.message_id)
            ydl_opts = {
                'format': 'b[ext=mp4]/b',
                'outtmpl': filename,
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                download_success = True

        if download_success:
            bot.edit_message_text("📤 Отправляю в чат...", message.chat.id, status_msg.message_id)
            with open(filename, 'rb') as video:
                bot.send_video(
                    message.chat.id, 
                    video, 
                    reply_to_message_id=message.message_id,
                    caption="✅ Видео из Instagram готово!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Не удалось скачать видео с Instagram.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка при скачивании: {e}", message.chat.id, status_msg.message_id)
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

def download_youtube_piped(video_id, filename):
    instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.yt",
        "https://pipedapi.mha.fi",
        "https://piped-api.garudalinux.org",
        "https://pipedapi.adminforge.de"
    ]
    for instance in instances:
        try:
            res = requests.get(f"{instance}/streams/{video_id}", headers=HEADERS, timeout=8)
            if res.status_code == 200:
                data = res.json()
                video_streams = data.get("videoStreams", [])
                stream_url = None
                
                # Поиск прямого mp4 видео со звуком
                for s in video_streams:
                    if s.get("videoOnly") is False and "video/mp4" in s.get("mimeType", ""):
                        stream_url = s.get("url")
                        break
                
                # Если со звуком в одном потоке нет, ищем любой видеопоток mp4
                if not stream_url:
                    for s in video_streams:
                        if "video/mp4" in s.get("mimeType", ""):
                            stream_url = s.get("url")
                            break

                if stream_url:
                    v_res = requests.get(stream_url, headers=HEADERS, stream=True, timeout=60)
                    if v_res.status_code == 200:
                        with open(filename, 'wb') as f:
                            for chunk in v_res.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f.write(chunk)
                        if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                            return True
        except Exception:
            continue
    return False

def download_youtube_cobalt(url, filename):
    clean_url = f"https://www.youtube.com/watch?v={extract_youtube_id(url)}" if extract_youtube_id(url) else url
    instances = [
        "https://api.cobalt.tools",
        "https://cobalt.stream",
        "https://co.wuk.sh"
    ]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    data = {"url": clean_url}
    for api_endpoint in instances:
        try:
            res = requests.post(f"{api_endpoint}/", json=data, headers=headers, timeout=8)
            if res.status_code == 200:
                res_data = res.json()
                video_link = res_data.get("url")
                if video_link:
                    v_res = requests.get(video_link, headers=HEADERS, stream=True, timeout=60)
                    if v_res.status_code == 200:
                        with open(filename, 'wb') as f:
                            for chunk in v_res.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f.write(chunk)
                        if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                            return True
        except Exception:
            continue
    return False

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Получаю видео из YouTube...")
    url = message.text.strip()
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")
    
    try:
        download_success = False
        video_id = extract_youtube_id(url)

        bot.edit_message_text("⏳ Скачиваю YouTube Shorts...", message.chat.id, status_msg.message_id)

        # 1. Попытка через Piped API (наиболее надежно)
        if video_id:
            download_success = download_youtube_piped(video_id, filename)

        # 2. Попытка через Cobalt API
        if not download_success:
            download_success = download_youtube_cobalt(url, filename)

        # 3. Резерв через yt-dlp
        if not download_success:
            clean_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': filename,
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios', 'web']
                    }
                }
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clean_url])
                if os.path.exists(filename) and os.path.getsize(filename) > 10000:
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
                    caption="✅ YouTube Shorts готово!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Не удалось скачать видео с YouTube. Попробуйте еще раз.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка при скачивании: {e}", message.chat.id, status_msg.message_id)
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
