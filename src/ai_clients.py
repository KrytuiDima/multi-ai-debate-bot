# src/ai_clients.py
import abc
import asyncio
import google.generativeai as genai
from groq import AsyncGroq
import anthropic
import httpx

class BaseAI(abc.ABC):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self.api_key = api_key

    @abc.abstractmethod
    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        pass

class GroqClient(BaseAI):
    def __init__(self, api_key: str):
        super().__init__('Llama3 (Groq)', api_key)
        self.client = AsyncGroq(api_key=api_key)

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        try:
            user_content = f"Topic: {topic}\nHistory:\n{debate_history}\nTask: Answer concisely."
            resp = await self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"[Groq Error]: {e}"

class GeminiClient(BaseAI):
    def __init__(self, api_key: str):
        super().__init__('Gemini', api_key)
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp") 

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        try:
            full_prompt = f"{system_prompt}\n\nTOPIC: {topic}\nHISTORY:\n{debate_history}"
            resp = await self.model.generate_content_async(full_prompt)
            return resp.text
        except Exception as e:
            return f"[Gemini Error]: {e}"

class ClaudeClient(BaseAI):
    def __init__(self, api_key: str):
        super().__init__('Claude', api_key)
        self.client = anthropic.Anthropic(api_key=api_key)

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        try:
            user_content = f"Topic: {topic}\nHistory:\n{debate_history}"
            msg = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )
            return msg.content[0].text
        except Exception as e:
            return f"[Claude Error]: {e}"

class DeepSeekClient(BaseAI):
    def __init__(self, api_key: str):
        super().__init__('DeepSeek', api_key)
        self.url = "https://api.deepseek.com/chat/completions"

    async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Topic: {topic}\nHistory:\n{debate_history}"}
            ]
        }
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.url, headers=headers, json=data, timeout=30.0)
                resp.raise_for_status()
                return resp.json()['choices'][0]['message']['content']
            except Exception as e:
                return f"[DeepSeek Error]: {e}"

AI_CLIENT_CLASSES = {
    'gemini': GeminiClient,
    'groq': GroqClient,
    'claude': ClaudeClient,
    'deepseek': DeepSeekClient
}