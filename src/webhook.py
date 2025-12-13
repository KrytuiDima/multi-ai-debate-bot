# src/webhook.py (ФІНАЛЬНИЙ КОД)
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
import logging

# ПОВЕРТАЄМО ІМПОРТ З БОТА
from .bot import main_bot_setup, APPLICATION, TELEGRAM_BOT_TOKEN 

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/")
async def webhook_handler(request: Request):
    """Обробляє вхідні оновлення від Telegram."""

    try:
        json_data = await request.json()
    except Exception as e:
        logger.error(f"Помилка отримання JSON: {e}")
        return {"status": "error", "message": "Invalid JSON"}, 400

    # Ініціалізація Application
    application: Application = APPLICATION
    if application is None:
        application = main_bot_setup(TELEGRAM_BOT_TOKEN)

    try:
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        logger.info(f"Оновлення оброблено: {update.update_id}")

    except Exception as e:
        logger.error(f"Критична помилка обробки оновлення: {e}")
        return {"status": "error", "message": str(e)}, 200

    return {"status": "ok"}