# src/webhook.py (Тільки для тестування!)
from fastapi import FastAPI, Request
import logging

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ми відключаємо усі імпорти з .bot, щоб уникнути помилок!
# from .bot import main_bot_setup, APPLICATION, TELEGRAM_BOT_TOKEN 


@app.post("/")
async def webhook_handler(request: Request):
    """Обробляє вхідні оновлення від Telegram."""
    # Тимчасово не обробляємо дані, просто підтверджуємо успіх
    try:
        await request.json()
    except:
        pass  # Не падаємо, якщо немає JSON

    # Тут повинен бути код ініціалізації бота, але ми його пропускаємо.
    logger.info("TEST: Webhook received, returning OK.")
    
    return {"status": "ok"}