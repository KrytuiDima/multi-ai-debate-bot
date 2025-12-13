# src/ai_clients.py
import abc
from typing import Dict, List
import asyncio
import os
import anthropic
import httpx
import google.generativeai as genai
from groq import AsyncGroq, APIError as GroqAPIError

# Визначення моделей для зручності
MODELS_MAP = {
    # Groq: Використовуємо актуальну рекомендовану заміну Llama 3.1 8B Instant
    'Llama3 (Groq)': 'llama-3.1-8b-instant', 
    # Gemini: Швидка та надійна модель
    'Gemini': 'gemini-2.5-flash',
}

class BaseAI(abc.ABC):
    """Абстрактний базовий клас для всіх AI-клієнтів"""
    def __init__(self, api_key: str, model_name_map: str):
        self.api_key = api_key
        self.model_name = model_name_map 
        self.model_map_key = model_name_map

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
    async def validate_key(self) -> bool:
        """Перевірка ключа Groq."""
        try:
            client = AsyncGroq(api_key=self.api_key, timeout=5.0) 
            # Спроба отримати список моделей як мінімальна перевірка
            await client.models.list() 
            return True
        except GroqAPIError:
            return False
        except Exception:
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Groq (Llama 3.1)."""
        client = AsyncGroq(api_key=self.api_key)
        
        user_content = (
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись системних інструкцій, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
            response = await client.chat.completions.create(
                model=MODELS_MAP[self.model_map_key], 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
            return response.choices[0].message.content
        except GroqAPIError as e:
            # Повертаємо помилку, щоб її обробив бот
            return f"Помилка генерації (GroqAPIError: {e.code}). Перевірте, чи модель {MODELS_MAP[self.model_map_key]} не застаріла."
        except Exception as e:
            return f"Помилка генерації (Невідома помилка Groq): {e}"


class GeminiClient(BaseAI):
    async def validate_key(self) -> bool:
        """Перевірка ключа Gemini."""
        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(MODELS_MAP[self.model_map_key])
            await model.generate_content_async("ping")
            return True
        except Exception:
            return False

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        """Генерація відповіді для Gemini."""
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(MODELS_MAP[self.model_map_key])
        
        full_prompt = (
            f"СИСТЕМНІ ІНСТРУКЦІЇ:\n{system_prompt}\n\n"
            f"Тема дебатів: {topic}\n"
            f"Історія попередніх ходів:\n{debate_history}\n\n"
            f"Завдання: Дотримуючись інструкцій вище, дай відповідь. Будь лаконічним та переконливим."
        )
        
        try:
            response = await model.generate_content_async(full_prompt)
            return response.text
        except Exception as e:
            return f"Помилка генерації (Gemini Error): {e}"


class ClaudeAI(BaseAI):
    """Обгортка для моделі Anthropic Claude."""
    def __init__(self, api_key: str):
        super().__init__(api_key, "Claude")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_name = "claude-3-haiku-20240307"

    async def validate_key(self) -> bool:
        """Перевірка ключа Claude."""
        try:
            # Спроба відправити простий запит
            self.client.messages.create(
                model=self.model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return True
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
            message = self.client.messages.create(
                model=self.model_name,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )
            return message.content[0].text
        except Exception as e:
            return f"Помилка генерації (Claude Error): {e}"


class DeepSeekAI(BaseAI):
    """Обгортка для моделі DeepSeek."""
    def __init__(self, api_key: str):
        super().__init__(api_key, "DeepSeek")
        self.api_key = api_key
        self.url = "https://api.deepseek.com/chat/completions"
        self.model_name = "deepseek-chat"

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
        except Exception:
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
            return f"Помилка HTTP від DeepSeek: {e.response.text}"
        except Exception as e:
            return f"Помилка генерації (DeepSeek Error): {e}"


# Словник для зручного вибору класів
AI_CLIENTS: Dict[str, BaseAI] = {
    'Llama3 (Groq)': lambda api_key: GroqClient(api_key, 'Llama3 (Groq)'),
    'Gemini': lambda api_key: GeminiClient(api_key, 'Gemini'),
    'Claude': lambda api_key: ClaudeAI(api_key),
    'DeepSeek': lambda api_key: DeepSeekAI(api_key),
}