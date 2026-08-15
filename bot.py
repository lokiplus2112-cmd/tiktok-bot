# YouTube (Скачивание с обходом блокировки ботов)
@bot.message_handler(func=lambda msg: msg.text and any(d in msg.text for d in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    if try_send_from_telegram_preview(message): 
        return
    status_msg = bot.reply_to(message, "⏳ Скачиваю YouTube видео...")
    filename = os.path.join(tempfile.gettempdir(), f"yt_{uuid.uuid4().hex}.mp4")
    url = message.text.strip()
    
    # 1. Сначала пробуем скачать через универсальный API (Cobalt) — обходит капчу YouTube
    try:
        instances = [
            "https://api.cobalt.tools/",
            "https://cobalt-api.kwiatekm.com/",
            "https://co.wuk.sh/"
        ]
        for inst in instances:
            res = requests.post(
                inst,
                json={"url": url, "videoQuality": "max"},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                download_url = data.get("url")
                if download_url and download_file_by_url(download_url, filename):
                    check_and_send_video(message, filename, status_msg, "✅ YouTube видео (без потери качества)!")
                    if os.path.exists(filename): os.remove(filename)
                    return
    except Exception:
        pass

    # 2. Если API не ответил, используем yt-dlp с настройками клиента iOS/Android (обход запроса входа)
    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': filename,
            'quiet': True,
            'merge_output_format': 'mp4',
            'socket_timeout': 30,
            # Маскируемся под мобильный клиент YouTube, чтобы не требовал Sign-in
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'mweb', 'android'],
                    'skip': ['webpage', 'configs']
                }
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        if os.path.exists(filename) and os.path.getsize(filename) > 5000:
            check_and_send_video(message, filename, status_msg, "✅ YouTube видео!")
            if os.path.exists(filename): 
                os.remove(filename)
        else:
            bot.edit_message_text("❌ Не удалось загрузить видео с YouTube.", message.chat.id, status_msg.message_id)
            
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка YouTube: {e}", message.chat.id, status_msg.message_id)
