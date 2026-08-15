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

# --- Настройка Web-сервера ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/healthz')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    # Werkzeug - стандартный сервер, не конфликтует с потоками
    run_simple('0.0.0.0', port, app, threaded=True)

# --- Инициализация бота ---
TOKEN = '8276557838:AAH_wSAdcAlJwMp8c2wp7y8k0lnhVLePxVA'
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 48 * 1024 * 1024
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
processed_messages = set()

# --- Вспомогательные функции ---
def try_send_from_telegram_preview(message):
    if message.message_id in processed_messages: return True
    if hasattr(message, 'web_page') and message.web_page and hasattr(message.web_page, 'video') and message.web_page.video:
        try:
            bot.send_video(message.chat.id, message.web_page.video.file_id, reply_to_message_id=message.message_id, caption="⚡ Отправлено из превью!")
            processed_messages.add(message.message_id)
            return True
        except: pass
    return False

def download_file_by_url(url, filename):
    try:
        res = requests.get(url, headers=HEADERS, stream=True, timeout=30)
        res.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk: f.write(chunk)
        return os.path.exists(filename) and os.path.getsize(filename) > 5000
    except: return False

def check_and_send_video(message, filename, status_msg, caption):
    file_size = os.path.getsize(filename)
    if file_size > MAX_FILE_SIZE:
        bot.edit_message_text(f"⚠️ Файл слишком большой ({round(file_size/1024/1024, 1)} МБ).", message.chat.id, status_msg.message_id)
        return
    bot.edit_message_text("📤 Отправляю...", message.chat.id, status_msg.message_id)
    with open(filename, 'rb') as video:
        bot.send_video(message.chat.id, video, reply_to_message_id=message.message_id, caption=caption, timeout=300)
    bot.delete_message(message.chat.id, status_msg.message_id)
    processed_messages.add(message.message_id)

# --- Обработчики ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "👋 Привет! Присылай ссылку на TikTok, Instagram или YouTube Shorts.")

@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    if try_send_from_telegram_preview(message): return
    status_msg = bot.reply_to(message, "⏳ Обрабатываю TikTok...")
    try:
        api_url = f"https://www.tikwm.com/api/?url={message.text.strip()}&hd=1"
        response = requests.get(api_url, headers=HEADERS, timeout=15).json()
        if response.get('code') == 0:
            data = response['data']
            video_url = data.get('hdplay') or data.get('play')
            filename = os.path.join(tempfile.gettempdir(), f"tt_{uuid.uuid4().hex}.mp4")
            if download_file_by_url(video_url, filename):
                check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
                os.remove(filename)
            else: bot.edit_message_text("❌ Ошибка загрузки.", message.chat.id, status_msg.message_id)
        else: bot.edit_message_text("❌ Ошибка API.", message.chat.id, status_msg.message_id)
    except Exception as e: bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['instagram.com', 'instagr.am']))
def download_instagram(message):
    if try_send_from_telegram_preview(message): return
    status_msg = bot.reply_to(message, "⏳ Получаю контент Instagram...")
    try:
        cobalt_url = "https://api.cobalt.tools/"
        res = requests.post(cobalt_url, json={"url": message.text.strip()}, headers={"Accept": "application/json"}, timeout=10).json()
        media_url = res.get("url")
        if not media_url: 
            bot.edit_message_text("❌ Не удалось получить контент.", message.chat.id, status_msg.message_id)
            return
        filename = os.path.join(tempfile.gettempdir(), f"ig_{uuid.uuid4().hex}.mp4")
        if download_file_by_url(media_url, filename):
            check_and_send_video(message, filename, status_msg, "✅ Instagram контент!")
            os.remove(filename)
    except Exception as e: bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    if try_send_from_telegram_preview(message): return
    status_msg = bot.reply_to(message, "⏳ Скачиваю YouTube...")
    filename = os.path.join(tempfile.gettempdir(), f"yt_{uuid.uuid4().hex}.mp4")
    try:
        with yt_dlp.YoutubeDL({'format': 'best', 'outtmpl': filename, 'quiet': True}) as ydl:
            ydl.download([message.text.strip()])
        check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts!")
        os.remove(filename)
    except Exception as e: bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

# --- Запуск ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    time.sleep(2)
    try:
        bot.remove_webhook()
    except: pass
    
    print("🚀 Бот запущен!")
    bot.infinity_polling(skip_pending=True)
