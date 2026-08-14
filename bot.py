@bot.message_handler(func=lambda msg: msg.text and any(domain in msg.text for domain in ['youtube.com', 'youtu.be']))
def download_youtube(message):
    status_msg = bot.reply_to(message, "⏳ Жду генерации предпросмотра Telegram...")

    # Цикл ожидания до 5 секунд: проверяем, появился ли предпросмотр
    for _ in range(10):
        time.sleep(0.5)
        try:
            # Обновляем данные сообщения, чтобы проверить появление web_page
            updated_msg = bot.get_message(message.chat.id, message.message_id)
            if updated_msg and try_send_from_telegram_preview(updated_msg):
                bot.delete_message(message.chat.id, status_msg.message_id)
                return
        except Exception:
            pass

    # Если за 5 секунд Telegram так и не отдал видео-предпросмотр,
    # переходим к скачиванию через внешние сервисы
    bot.edit_message_text("⏳ Предпросмотр не найден, скачиваю с YouTube...", message.chat.id, status_msg.message_id)
    url = message.text.strip()
    video_id = extract_youtube_id(url)

    if not video_id:
        bot.edit_message_text("❌ Некорректная ссылка на YouTube Shorts.", message.chat.id, status_msg.message_id)
        return

    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"yt_{uuid.uuid4().hex}.mp4")

    try:
        success = download_youtube_loader(video_id, filename)
        if success:
            check_and_send_video(message, filename, status_msg, "✅ YouTube Shorts готово!")
        else:
            bot.edit_message_text("❌ Ошибка загрузки с YouTube. Попробуйте еще раз через несколько секунд.", message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass
