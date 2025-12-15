# src/ai_clients.py
import abc
from typing import Dict, List, Type # ВИПРАВЛЕННЯ: Додано Type
import asyncio
import os
import anthropic
import httpx
import logging # ВИПРАВЛЕННЯ: Додано logging
from groq import AsyncGroq, APIError as GroqAPIError

# Додаємо логування
logger = logging.getLogger(__name__)

# --- ВИПРАВЛЕННЯ: УМОВНИЙ ІМПОРТ GOOGLE GEMINI ТА ПОМИЛОК ---
try:
    # Намагаємося імпортувати основний SDK
    import google.generativeai as genai
    
    # Вирішення проблеми: Намагаємося імпортувати помилку, але якщо Pylance не знаходить, створюємо заглушку
    try:
        from google.generativeai.errors import APIError as GeminiAPIError # type: ignore
    except ImportError:
        # Це клас-заглушка, який Pylance знайде і це вирішить помилку "could not be resolved"
        class GeminiAPIError(Exception):
            pass
            
except ImportError:
    genai = None
    # Створюємо заглушку, якщо бібліотека Gemini недоступна
    class GeminiAPIError(Exception):
        pass
# --- КІНЕЦЬ ВИПРАВЛЕННЯ ІМПОРТІВ GEMINI ---


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
    def __init__(self, model_name: str, api_key: str): 
        # Використовуємо MODELS_MAP для отримання фактичного ID моделі
        self.model_name = MODELS_MAP.get(model_name, model_name) 
        self.model_map_key = model_name
        self.api_key = api_key 

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
        super().__init__('Llama3 (Groq)', api_key=api_key) 
        self.client = AsyncGroq(api_key=self.api_key)
    
    async def validate_key(self) -> bool:
        """Перевірка ключа Groq."""
        try:
            await self.client.models.list() 
            return True
        except GroqAPIError:
            logger.error("Groq validation failed due to API Error.")
            return False
        except Exception:
            logger.error("Groq validation failed due to unknown error.")
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
            logger.error(f"Groq generation failed: {e}")
            return f"Помилка генерації (GroqAPIError: {e.code}). Перевірте, чи модель {self.model_name} не застаріла."
        except Exception as e:
            logger.error(f"Groq generation failed (Unknown): {e}")
            return f"Помилка генерації (Невідома помилка Groq): {e}"


class GeminiClient(BaseAI):
    def __init__(self, api_key: str):
        super().__init__('Gemini', api_key=api_key) 
    
    async def validate_key(self) -> bool:
        """Перевірка ключа Gemini."""
        try:
            if not genai:
                raise ImportError("Google GenAI SDK is not installed.")
                
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            await model.generate_content_async("ping") 
            return True
        except GeminiAPIError as e: # ВИПРАВЛЕННЯ: Тепер Pylance знає про GeminiAPIError
            logger.error(f"Gemini validation failed (API Error): {e}")
            return False
        except Exception as e:
            logger.error(f"Gemini validation failed (Unknown): {e}")
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Gemini."""
        if not genai:
             return "Помилка: Gemini SDK не встановлено."
             
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model_name)
        
        full_prompt = (
            f"СИСТЕМНІ ІНСТРУКЦІЇ:\n{system_prompt}\n\n"
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись інструкцій вище, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
            response = await model.generate_content_async(full_prompt) 
            return response.text
        except GeminiAPIError as e: # ВИПРАВЛЕННЯ: Тепер Pylance знає про GeminiAPIError
            logger.error(f"Gemini generation failed (API Error): {e}")
            return f"Помилка генерації (Gemini API Error): {e}"
        except Exception as e:
            logger.error(f"Помилка генерації (Gemini Error): {e}")
            return f"Помилка генерації (Gemini Error): {e}"


class ClaudeAI(BaseAI):
    """Обгортка для моделі Anthropic Claude."""
    def __init__(self, api_key: str):
        super().__init__("Claude", api_key=api_key)
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key) 
        
    async def validate_key(self) -> bool:
        """Перевірка ключа Claude."""
        try:
            await self.client.messages.create( 
                model=self.model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return True
        except anthropic.APIError as e:
            logger.error(f"Claude validation failed (API Error): {e}")
            return False
        except Exception as e:
            logger.error(f"Claude validation failed (Unknown): {e}")
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Claude."""
        user_content = (
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись системних інструкцій, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
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