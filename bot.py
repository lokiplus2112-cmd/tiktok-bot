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

# --- Web-сервер для Render ---
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
# Вставьте сюда ВАШ НОВЫЙ токен от BotFather
TOKEN = '8276557838:AAFp9IwYJchZUG9RavgNZU2dV4scYTzpCro'
bot = telebot.TeleBot(TOKEN)

# Лимиты Telegram API
MAX_VIDEO_SIZE = 48 * 1024 * 1024       # ~48 МБ (для плеера)
MAX_DOCUMENT_SIZE = 1950 * 1024 * 1024  # ~1.95 ГБ (как документ)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}
processed_messages = set()

# Путь к куки-файлу
COOKIES_FILE = os.path.join(os.path.dirname(__file__), 'cookies.txt')

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_info = types.KeyboardButton("💻 Как пользоваться на ПК?")
    btn_help = types.KeyboardButton("ℹ️ Помощь")
    markup.add(btn_info, btn_help)
    return markup

def try_send_from_telegram_preview(message):
    if message.message_id in processed_messages: 
        return True
    if hasattr(message, 'web_page') and message.web_page and hasattr(message.web_page, 'video') and message.web_page.video:
        try:
            bot.send_video(
                message.chat.id, 
                message.web_page.video.file_id, 
                reply_to_message_id=message.message_id, 
                caption="⚡ Отправлено мгновенно!"
            )
            processed_messages.add(message.message_id)
            return True
        except Exception: 
            pass
    return False

def download_file_by_url(url, filename, timeout=15):
    try:
        res = requests.get(url, headers=HEADERS, stream=True, timeout=timeout)
        res.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk: 
                    f.write(chunk)
        return os.path.exists(filename) and os.path.getsize(filename) > 5000
    except Exception: 
        if os.path.exists(filename):
            try: os.remove(filename)
            except Exception: pass
        return False

def check_and_send_video(message, filename, status_msg, caption):
    file_size = os.path.getsize(filename)
    size_mb = round(file_size / 1024 / 1024, 1)

    if file_size > MAX_DOCUMENT_SIZE:
        bot.edit_message_text(
            f"⚠️ Файл слишком большой ({size_mb} МБ). Лимит Telegram — 2 ГБ.", 
            message.chat.id, 
            status_msg.message_id
        )
        return

    bot.edit_message_text(f"📤 Отправляю в чат ({size_mb} МБ)...", message.chat.id, status_msg.message_id)
    
    with open(filename, 'rb') as media_file:
        if file_size <= MAX_VIDEO_SIZE:
            bot.send_video(
                message.chat.id, 
                media_file, 
                reply_to_message_id=message.message_id, 
                caption=caption, 
                timeout=300
            )
        else:
            bot.send_document(
                message.chat.id, 
                media_file, 
                reply_to_message_id=message.message_id, 
                caption=f"{caption}\n📁 *Отправлено документом без потери качества!*", 
                parse_mode="Markdown",
                timeout=600
            )

    bot.delete_message(message.chat.id, status_msg.message_id)
    processed_messages.add(message.message_id)

# --- ОБРАБОТЧИКИ КОМАНД ---
@bot.message_handler(commands=['start', 'help'])
def start_cmd(message):
    bot.reply_to(
        message, 
        "👋 **Привет! Я бот для скачивания медиа в максимальном качестве.**\n\n"
        "Присылай ссылку из:\n"
        "• **YouTube** (видео любой длины и Shorts)\n"
        "• **TikTok** (видео и фото-галереи)\n"
        "• **Instagram** (Reels, фото и карусели)\n\n"
        "✨ *Файлы большого размера отправляются документом без сжатия!*",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == "💻 Как пользоваться на ПК?")
def pc_info(message):
    bot.reply_to(
        message,
        "🖥 **Лайфхаки для работы с ПК:**\n\n"
        "1. **Быстрая вставка:** `Ctrl + C` в браузере -> `Ctrl + V` в чате с ботом -> `Enter`.\n"
        "2. **Быстрое сохранение:** Правый клик по файлу -> **«Сохранить как...»**.\n"
        "3. **Пересылка:** Просто пересылай сюда сообщения с ссылками из других чатов.",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda msg: msg.text == "ℹ️ Помощь")
def help_info(message):
    bot.reply_to(
        message,
        "📌 **Как отправить ссылку:**\n"
        "Скопируй ссылку из браузера или приложения и отправь в этот чат.",
        reply_markup=get_main_keyboard()
    )

# --- TikTok ---
@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    if try_send_from_telegram_preview(message): 
        return
    status_msg = bot.reply_to(message, "⏳ Обрабатываю TikTok...")
    try:
        api_url = f"https://www.tikwm.com/api/?url={message.text.strip()}&hd=1"
        response = requests.get(api_url, headers=HEADERS, timeout=10).json()
        if response.get('code') == 0:
            data = response['data']
            images = data.get('images')
            temp_dir = tempfile.gettempdir()
            
            if images and isinstance(images, list):
                bot.edit_message_text(f"📸 Скачиваю фото ({len(images)} ф.)...", message.chat.id, status_msg.message_id)
                media_group = []
                downloaded_files = []
                for idx, img_url in enumerate(images[:10]):
                    f_path = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}_{idx}.jpg")
                    if download_file_by_url(img_url, f_path, timeout=10):
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

            video_url = data.get('hdplay') or data.get('play')
            if video_url and not video_url.startswith('http'):
                video_url = 'https://www.tikwm.com' + video_url
            filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")
            if download_file_by_url(video_url, filename, timeout=15):
                check_and_send_video(message, filename, status_msg, "✅ TikTok видео!")
                if os.path.exists(filename): os.remove(filename)
            else: 
                bot.edit_message_text("❌ Ошибка сохранения файла.", message.chat.id, status_msg.message_id)
        else: 
            bot.edit_message_text("❌ Не удалось спарсить ссылку.", message.chat.id, status_msg.message_id)
    except Exception as e: 
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)

# --- YouTube ---
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    if try_send_from_telegram_preview(message): 
        return
    status_msg = bot.reply_to(message, "⏳ Обрабатываю YouTube видео...")
    filename = os.path.join(tempfile.gettempdir(), f"yt_{uuid.uuid4().hex}.mp4")
    url = message.text.strip()
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': filename,
        'quiet': True,
        'merge_output_format': 'mp4',
        'socket_timeout': 30,
        'nocheckcertificate': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'tv']
            }
        }
    }

    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    download_success = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(filename) and os.path.getsize(filename) > 5000:
            download_success = True
    except Exception as e:
        print(f"YT Error: {e}")

    if download_success and os.path.exists(filename):
        check_and_send_video(message, filename, status_msg, "✅ YouTube видео!")
        if os.path.exists(filename):
            os.remove(filename)
    else:
        bot.edit_message_text(
            "❌ YouTube заблокировал доступ. Проверьте наличие корректного cookies.txt в GitHub.", 
            message.chat.id, 
            status_msg.message_id
        )

# --- Запуск с защитой от вылетов (Conflict 409) ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    time.sleep(2)
    
    print("🚀 Бот запускается...")
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 409:
                print("⚠️ Конфликт 409: старая сессия еще завершается. Ждем 5 сек...")
                time.sleep(5)
            else:
                time.sleep(3)
        except Exception as e:
            print(f"⚠️ Ошибка polling: {e}")
            time.sleep(3)
