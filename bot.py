# --- YOUTUBE SHORTS (С ПОДДЕРЖКОЙ COOKIES И УНИВЕРСАЛЬНЫМ ФОРМАТОМ) ---
def extract_youtube_id(url):
    match = re.search(r'(?:shorts/|v=|v%3D|be/)([\w-]{11})', url)
    return match.group(1) if match else None

@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Обрабатываю YouTube Shorts...")
    url = message.text.strip()
    video_id = extract_youtube_id(url)

    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")

    try:
        # Универсальный выбор форматов: сначала пытаемся взять <= 720p,
        # если нет — берем лучшее единое видео (best), чтобы не было ошибки "format not available"
        ydl_opts = {
            'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
            'outtmpl': filename,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'merge_output_format': 'mp4'  # Автоматически сшивает видео и аудио в mp4
        }

        # Проверяем и подключаем файл cookies.txt
        if os.path.exists('cookies.txt'):
            ydl_opts['cookiefile'] = 'cookies.txt'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        if os.path.exists(filename) and os.path.getsize(filename) > 30000:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
        else:
            bot.edit_message_text("❌ Не удалось загрузить видео с YouTube.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка скачивания YouTube: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass
