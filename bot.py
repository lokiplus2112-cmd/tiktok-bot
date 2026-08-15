import os
import re
import uuid
import tempfile
import threading
import time
import telebot
import requests
import yt_dlp
from flask import Flask
from werkzeug.serving import run_simple

# ==========================================
# 1. ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы прошёл health check)
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
# 2. НАСТРОЙКИ БОТА
# ==========================================
TOKEN = "8276557838:AAEYciE_o_-xzt5f0rb-3wtnEfGfAvw5p7Q"
bot = telebot.TeleBot(TOKEN)

def try_send_from_telegram_preview(message):
    return False

def check_and_send_video(message, filename, status_msg, caption_text):
    """Отправка видео пользователю с автоматическим сжатием при необходимости."""
    try:
        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        print(f"📦 Размер файла: {file_size_mb:.2f} MB")
        
        # Если файл больше 48 МБ, сжимаем через ffmpeg (для бесплатного лимита Telegram)
        if file_size_mb > 48:
            bot.edit_message_text("⚠️ Файл слишком большой. Сжимаю видео...", message.chat.id, status_msg.message_id)
            compressed_filename = os.path.join(tempfile.gettempdir(), f"compressed_{uuid.uuid4().hex}.mp4")
            
            os.system(f'ffmpeg -y -i "{filename}" -vf "scale=-2:720" -crf 28 -preset faster "{compressed_filename}"')
            
            if os.path.exists(compressed_filename) and os.path.getsize(compressed_filename) > 0:
                os.remove(filename)
                filename = compressed_filename

        bot.edit_message_text("⬆️ Загружаю видео в Telegram...", message.chat.id, status_msg.message_id)
        
        with open(filename, 'rb') as video:
            bot.send_video(
                message.chat.id, 
                video, 
                caption=caption_text, 
                supports_streaming=True,
                timeout=300
            )
        bot.delete_message(message.chat.id, status_msg.message_id)
        
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        bot.edit_message_text("❌ Ошибка при отправке видео в Telegram.", message.chat.id, status_msg.message_id)

# --- Обработчик TikTok & Instagram ---
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['tiktok.com', 'instagram.com']))
def download_tiktok_instagram(message):
    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку...")
    filename = os.path.join(tempfile.gettempdir(), f"media_{uuid.uuid4().hex}.mp4")
    url = message.text.strip()

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': filename,
        'quiet': True,
        'merge_output_format': 'mp4',
        'socket_timeout': 30,
        'nocheckcertificate': True,
    }

    download_success = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(filename) and os.path.getsize(filename) > 5000:
            download_success = True
    except Exception as e:
        print(f"❌ Ошибка yt-dlp: {e}")

    if download_success and os.path.exists(filename):
        check_and_send_video(message, filename, status_msg, "✅ Ваше видео!")
        if os.path.exists(filename):
            os.remove(filename)
    else:
        bot.edit_message_text("❌ Не удалось скачать видео. Проверьте ссылку.", message.chat.id, status_msg.message_id)

# --- Обработчик YouTube БЕЗ КУК (через Cobalt API) ---
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    if try_send_from_telegram_preview(message): 
        return
    
    status_msg = bot.reply_to(message, "⏳ Обрабатываю YouTube видео...")
    url = message.text.strip()
    filename = os.path.join(tempfile.gettempdir(), f"yt_{uuid.uuid4().hex}.mp4")

    # Обращаемся к публичному API Cobalt
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "vQuality": "720"
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=15)
        data = response.json()

        # Проверяем ответ от API
        if data.get("status") in ["tunnel", "redirect"]:
            video_url = data.get("url")
            
            # Скачиваем сгенерированный видеопоток
            res = requests.get(video_url, stream=True, timeout=60)
            res.raise_for_status()
            
            with open(filename, 'wb') as f:
                for chunk in res.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

            if os.path.exists(filename) and os.path.getsize(filename) > 5000:
                check_and_send_video(message, filename, status_msg, "✅ YouTube видео!")
                if os.path.exists(filename):
                    os.remove(filename)
            else:
                bot.edit_message_text("❌ Не удалось сохранить видеофайл.", message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Не удалось получить доступ к видео. Попробуйте другую ссылку.", message.chat.id, status_msg.message_id)

    except Exception as e:
        print(f"❌ Ошибка YouTube API: {e}")
        bot.edit_message_text("❌ Сервис загрузки YouTube временно недоступен. Попробуйте позже.", message.chat.id, status_msg.message_id)

# --- Команда /start ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 **Привет! Я бот для скачивания видео.**\n\n"
        "Отправь мне ссылку из:\n"
        "• **TikTok**\n"
        "• **Instagram Reels**\n"
        "• **YouTube** (видео и Shorts)",
        parse_mode="Markdown"
    )

# ==========================================
# 3. ЗАПУСК БОТА С АВТОПЕРЕЗАПУСКОМ (409 Conflict Fix)
# ==========================================
if __name__ == '__main__':
    # Запуск Flask в отдельном потоке (для Render)
    threading.Thread(target=run_web, daemon=True).start()
    time.sleep(2)
    
    print("🚀 Бот успешно запущен и готовит порт...")
    
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 409:
                print("⚠️ Конфликт 409: старая сессия ещё закрывается. Переподключение через 5 сек...")
                time.sleep(5)
            else:
                time.sleep(3)
        except Exception as e:
            print(f"⚠️ Ошибка polling: {e}")
            time.sleep(3)
