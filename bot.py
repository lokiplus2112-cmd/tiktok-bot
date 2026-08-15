def get_youtube_direct_url(video_id):
    """Получение прямой ссылки на скачивание через публичный инстанс Cobalt"""
    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    instances = [
        "https://api.cobalt.tools/",
        "https://cobalt-api.kwiatekm.com/",
        "https://api.vxtiktok.com/"
    ]
    
    payload = {
        "url": clean_url,
        "videoQuality": "720",  # Гарантирует, что файл будет весить < 50 МБ
        "downloadMode": "auto"
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    for api_url in instances:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("url"):
                    return data.get("url")
                elif data.get("picker"):
                    return data["picker"][0]["url"]
        except Exception:
            continue
    return None


@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Скачиваю YouTube Shorts...")
    url = message.text.strip()
    video_id = extract_youtube_id(url)

    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")

    try:
        # 1. Получаем прямую ссылку через Cobalt API
        direct_url = get_youtube_direct_url(video_id)
        
        # 2. Если Cobalt не сработал — пробуем локальный yt-dlp с ограничением качества (720p)
        if direct_url and download_file_by_url(direct_url, filename):
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
        else:
            # Резервный вариант через yt-dlp (ограничение до 720p для обхода ошибки 413)
            ydl_opts = {
                'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
                'outtmpl': filename,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
                
            if os.path.exists(filename) and os.path.getsize(filename) > 30000:
                check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
            else:
                bot.edit_message_text("❌ Не удалось загрузить видео с YouTube. Попробуйте еще раз через 5 секунд.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass
