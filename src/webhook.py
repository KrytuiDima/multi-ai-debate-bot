# src/webhook.py
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
import os
import asyncio
import logging

# ВАЖЛИВО: Імпортуємо ВСІ обробники та логіку з нашого bot.py
from bot import main_bot_setup, APPLICATION, TELEGRAM_BOT_TOKEN
# main_bot_setup – це функція, яка збирає всі CommandHandler, MessageHandler, тощо.

# Ініціалізуємо додаток FastAPI, який Vercel шукає
app = FastAPI()

# 1. Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 2. Обробник Webhook
@app.post("/")
async def webhook_handler(request: Request):
    """Обробляє вхідні оновлення від Telegram."""
    
    # 2.1. Отримання JSON-даних
    try:
        json_data = await request.json()
    except Exception as e:
        logger.error(f"Помилка отримання JSON: {e}")
        return {"status": "error", "message": "Invalid JSON"}, 400

    # 2.2. Налаштування Application (потрібно для Vercel)
    # Ми ініціалізуємо його при кожному запиті, щоб Vercel працював.
    application: Application = APPLICATION
    if application is None:
        application = main_bot_setup(TELEGRAM_BOT_TOKEN)

    # 2.3. Перетворюємо JSON в об'єкт Update і обробляємо його
    try:
        update = Update.de_json(json_data, application.bot)
        # Обробка оновлення
        await application.process_update(update)
        logger.info(f"Оновлення оброблено: {update.update_id}")
        
    except Exception as e:
        logger.error(f"Помилка обробки оновлення: {e}")
        # Повертаємо 200 OK, щоб Telegram не намагався надіслати повідомлення знову
        return {"status": "error", "message": str(e)}, 200

    return {"status": "ok"}


# 3. Функція для встановлення Webhook (запустити ОДИН раз)
async def set_webhook_url(webhook_url: str):
    """Встановлює Webhook URL для бота."""
    application: Application = APPLICATION
    if application is None:
        application = main_bot_setup(TELEGRAM_BOT_TOKEN)
        
    await application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook встановлено на: {webhook_url}")
    

# 4. Точка входу для Vercel (використовує FastAPI app)
# Ми не викликаємо тут uvicorn.run(), оскільки Vercel робить це сам.