# src/ai_clients.py
import abc
from typing import Dict, List, Type # ВИПРАВЛЕННЯ: Додано Type
import asyncio
import os
import anthropic
import httpx
import logging # Додано logging
from groq import AsyncGroq, APIError as GroqAPIError

# Додаємо логування
logger = logging.getLogger(__name__)

# --- Імпорти Google Gemini ---
try:
    import google.generativeai as genai
    # ВИПРАВЛЕННЯ: Умовний імпорт помилки з fallback для Pylance
    try:
        from google.generativeai.errors import APIError as GeminiAPIError
    except ImportError:
        # Створюємо клас-заглушку, якщо модуль errors не знайдено
        class GeminiAPIError(Exception):
            pass
except ImportError:
    genai = None
    # Створюємо заглушку, якщо бібліотека Gemini недоступна
    class GeminiAPIError(Exception):
        pass


# Визначення моделей для зручності
MODELS_MAP = {
    # Groq: Використовуємо актуальну рекомендовану заміну Llama 3.1 8B Instant
    'Llama3 (Groq)': 'llama-3.1-8b-instant', 
    # Gemini: Швидка та надійна модель
    'Gemini': 'gemini-2.5-flash',
    'Claude': 'claude-3-haiku-20240307',
    'DeepSeek': 'deepseek-chat',
}

class BaseAI(abc.ABC):
    """Абстрактний базовий клас для всіх AI-клієнтів"""
    def __init__(self, model_name: str, api_key: str): # Додаємо api_key до конструктора для уніфікації
        self.model_name = MODELS_MAP.get(model_name, model_name) # Використовуємо ID моделі
        self.model_map_key = model_name
        self.api_key = api_key # Зберігаємо ключ тут

    @abc.abstractmethod
    async def validate_key(self) -> bool:
        """Асинхронно перевіряє, чи ключ робочий."""
        pass

    @abc.abstractmethod
    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерує відповідь на основі контексту дебатів."""
        pass

# --- КЛІЄНТИ ---

class GroqClient(BaseAI):
    def __init__(self, api_key: str):
        # Передаємо ключ у BaseAI
        super().__init__('Llama3 (Groq)', api_key=api_key) 
        self.client = AsyncGroq(api_key=self.api_key)
    
    async def validate_key(self) -> bool:
        """Перевірка ключа Groq."""
        try:
            # Спроба отримати список моделей як мінімальна перевірка
            await self.client.models.list() 
            return True
        except GroqAPIError:
            logger.error("Groq validation failed due to API Error.")
            return False
        except Exception:
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Groq (Llama 3.1)."""
        
        user_content = (
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись системних інструкцій, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
            return response.choices[0].message.content
        except GroqAPIError as e:
            # Повертаємо помилку, щоб її обробив бот
            logger.error(f"Groq generation failed: {e.code}")
            return f"Помилка генерації (GroqAPIError: {e.code}). Перевірте, чи модель {self.model_name} не застаріла."
        except Exception as e:
            logger.error(f"Groq generation failed (Unknown): {e}")
            return f"Помилка генерації (Невідома помилка Groq): {e}"


class GeminiClient(BaseAI):
    def __init__(self, api_key: str):
        # Передаємо ключ у BaseAI
        super().__init__('Gemini', api_key=api_key) 
    
    async def validate_key(self) -> bool:
        """Перевірка ключа Gemini."""
        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            # Використовуємо generate_content_async для асинхронності
            await model.generate_content_async("ping") 
            return True
        except GeminiAPIError: # Використовуємо GeminiAPIError
            logger.error("Gemini validation failed due to API Error.")
            return False
        except Exception:
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Gemini."""
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model_name)
        
        full_prompt = (
            f"СИСТЕМНІ ІНСТРУКЦІЇ:\n{system_prompt}\n\n"
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись інструкцій вище, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
            # Використовуємо generate_content_async для коректної роботи
            response = await model.generate_content_async(full_prompt) 
            return response.text
        except GeminiAPIError as e: # Використовуємо GeminiAPIError
            logger.error(f"Gemini generation failed (API Error): {e}")
            return f"Помилка генерації (Gemini API Error): {e}"
        except Exception as e:
            logger.error(f"Gemini generation failed (Unknown): {e}")
            return f"Помилка генерації (Gemini Error): {e}"


class ClaudeAI(BaseAI):
    """Обгортка для моделі Anthropic Claude."""
    def __init__(self, api_key: str):
        super().__init__("Claude", api_key=api_key)
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key) 

    async def validate_key(self) -> bool:
        """Перевірка ключа Claude."""
        try:
            # Використовуємо асинхронну версію
            await self.client.messages.create( 
                model=self.model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return True
        except anthropic.APIError: # Catch specific API Error
            logger.error("Claude validation failed due to API Error.")
            return False
        except Exception:
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Claude."""
        user_content = (
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись системних інструкцій, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
            # Використовуємо асинхронну версію
            message = await self.client.messages.create( 
                model=self.model_name,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )
            return message.content[0].text
        except anthropic.APIError as e:
            logger.error(f"Claude generation failed (API Error): {e}")
            return f"Помилка генерації (Claude API Error): {e.status_code}"
        except Exception as e:
            logger.error(f"Claude generation failed (Unknown): {e}")
            return f"Помилка генерації (Claude Error): {e}"


class DeepSeekAI(BaseAI):
    """Обгортка для моделі DeepSeek."""
    def __init__(self, api_key: str):
        super().__init__("DeepSeek", api_key=api_key)
        self.url = "https://api.deepseek.com/chat/completions"

    async def validate_key(self) -> bool:
        """Перевірка ключа DeepSeek."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 10
        }
        
        try:
            # httpx.AsyncClient для асинхронних запитів
            async with httpx.AsyncClient() as client: 
                response = await client.post(self.url, headers=headers, json=data, timeout=10.0)
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"DeepSeek validation failed: {e}")
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для DeepSeek."""
        user_content = (
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись системних інструкцій, дай відповідь. Будь лаконічним та переконливим."
        )
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.url, headers=headers, json=data, timeout=30.0)
                response.raise_for_status()
                response_json = response.json()
                return response_json['choices'][0]['message']['content']
        except httpx.HTTPStatusError as e:
            logger.error(f"DeepSeek generation failed (HTTP Error): {e.response.text}")
            return f"Помилка HTTP від DeepSeek: {e.response.text}"
        except Exception as e:
            logger.error(f"DeepSeek generation failed (Unknown): {e}")
            return f"Помилка генерації (DeepSeek Error): {e}"


# Словник для зручного вибору класів
AI_CLIENTS_MAP: Dict[str, Type[BaseAI]] = { 
    'groq': GroqClient,
    'gemini': GeminiClient,
    'claude': ClaudeAI,
    'deepseek': DeepSeekAI,
}

# ВИПРАВЛЕННЯ: Додавання змінних, які імпортує bot.py
MODEL_NAME_TO_ID = MODELS_MAP
AVAILABLE_SERVICES = list(AI_CLIENTS_MAP.keys())
AVAILABLE_MODELS = list(MODELS_MAP.keys())