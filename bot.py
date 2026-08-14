import os
import tempfile
import uuid
import threading
import telebot
from telebot import apihelper
import requests
from flask import Flask

# --- Веб-сервер для работы на бесплатном тарифе Render ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
# --------------------------------------------------------

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
        "👋 Привет! Отправь мне ссылку на видео из TikTok, и я скачаю его в оригинальном качестве!"
    )

@bot.message_handler(func=lambda msg: msg.text and 'tiktok.com' in msg.text)
def download_tiktok(message):
    status_msg = bot.reply_to(message, "⏳ Получаю оригинальное видео...")
    url = message.text.strip()
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"tt_{uuid.uuid4().hex}.mp4")
    
    try:
        api_url = "https://www.tikwm.com/api/"
        response = requests.post(api_url, data={'url': url}, headers=HEADERS, timeout=15).json()

        if response.get('code') == 0:
            video_url = response['data']['play']
            
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
                    caption="✅ Оригинальное видео готово!",
                    timeout=300
                )
            bot.delete_message(message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text(
                "❌ Не удалось найти видео по этой ссылке.", 
                message.chat.id, 
                status_msg.message_id
            )

    except Exception as e:
        bot.edit_message_text(
            f"❌ Ошибка: {e}", 
            message.chat.id, 
            status_msg.message_id
        )
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

if __name__ == '__main__':
    # Запуск веб-сервера в фоновом потоке
    threading.Thread(target=run_web).start()
    
    print("🚀 Бот запущен на Render!")
    bot.infinity_polling()
