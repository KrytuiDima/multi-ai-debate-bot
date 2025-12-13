# src/debate_manager.py
import asyncio
from typing import Dict, List, Tuple
from enum import Enum
import abc

# Імпортуємо DB_MANAGER та BaseAI, щоб вони були доступні
from database import DB_MANAGER
# Припускаємо, що BaseAI імпортовано з ai_clients (якщо запускатиметься окремо)
class BaseAI(abc.ABC): 
    pass 

class DebateStatus(Enum):
    THINKING = "⏳ Думає..."
    FINISHED = "✅ Готово"

class DebateSession:
    """Керує всіма раундами, історією та промптингом для дебатів."""
    
    def __init__(self, topic: str, clients_map: Dict[str, BaseAI], key_ids_map: Dict[str, int], max_rounds: int = 3): 
        self.topic = topic
        # {alias_name: client_object}
        self.clients: Dict[str, BaseAI] = clients_map
        # {alias_name: key_id}
        self.key_ids: Dict[str, int] = key_ids_map
        # Історія тепер зберігає повні результати раунду: List[Dict[AI_Name, Response_Text]]
        self.history: List[Dict[str, str]] = [] 
        self.round = 0
        self.is_running = False
        self.MAX_ROUNDS = max_rounds 

    def get_system_prompt(self, model_name: str) -> str:
        """
        Генерує динамічний системний промпт для конкретної моделі на поточному раунді.
        """
        clients_list = list(self.clients.keys())
        opponent_name = next(name for name in clients_list if name != model_name)
        
        # Визначаємо, хто є "ЗА" (перший клієнт) і "ПРОТИ" (другий клієнт)
        # Перший клієнт завжди "ЗА", другий завжди "ПРОТИ"
        is_pro = model_name == clients_list[0]
        side = "ЗА" if is_pro else "ПРОТИ"
        
        prompt = (
            f"Ти - інтелектуальна модель **{model_name}**, яка бере участь у дебатах. "
            f"Твій опонент: **{opponent_name}**. "
            f"Тема: **{self.topic}**. "
            f"Твоя позиція: **{side}**.\n\n"
            "Твоя мета - переконати читача у правильності своєї позиції, використовуючи логічні аргументи, факти та чітку структуру. "
            "Кожен твій хід повинен:\n"
            "1. Відповідати на аргументи, висунуті опонентом у попередньому раунді (якщо це не перший раунд).\n"
            "2. Розвивати твою основну тезу.\n"
            "3. Бути лаконічним і мати максимум 3-4 абзаци.\n"
            f"Зараз **Раунд {self.round + 1}** з {self.MAX_ROUNDS}. Будь переконливим!"
        )
        return prompt

    def get_full_history(self) -> str:
        """Форматує повну історію дебатів для передачі у промпт."""
        history_text = ""
        for i, round_data in enumerate(self.history):
            history_text += f"\n--- РАУНД {i+1} ---\n"
            for name, response in round_data.items():
                history_text += f"{name}: {response}\n"
        return history_text.strip()

    async def run_next_round(self) -> Tuple[str, str]:
        """Виконує наступний раунд дебатів, генерує відповіді та зменшує ліміти."""
        
        if self.round >= self.MAX_ROUNDS:
            raise ValueError("Дебати завершено. Немає більше раундів.")

        self.is_running = True
        
        # Визначаємо, хто ходить першим
        client_names = list(self.clients.keys())
        ai1_name, ai2_name = client_names[0], client_names[1]
        
        # Перевірка лімітів перед запуском
        remaining1 = DB_MANAGER.get_remaining_calls(self.key_ids[ai1_name])
        remaining2 = DB_MANAGER.get_remaining_calls(self.key_ids[ai2_name])
        
        if remaining1 is None or remaining1 < 1:
            raise Exception(f"Ліміт запитів вичерпано для {ai1_name} ({remaining1} залишилося).")
        if remaining2 is None or remaining2 < 1:
            raise Exception(f"Ліміт запитів вичерпано для {ai2_name} ({remaining2} залишилося).")
        
        # Історія для поточного промпту
        debate_history = self.get_full_history()

        # 1. Створення завдань для обох моделей
        task1 = self.clients[ai1_name].generate_response(
            system_prompt=self.get_system_prompt(ai1_name),
            debate_history=debate_history,
            topic=self.topic
        )
        
        task2 = self.clients[ai2_name].generate_response(
            system_prompt=self.get_system_prompt(ai2_name),
            debate_history=debate_history,
            topic=self.topic
        )
        
        # 2. Очікування результатів
        response1, response2 = await asyncio.gather(task1, task2)
        
        # 3. Зменшення лімітів ПІСЛЯ успішного отримання відповідей
        # Якщо будь-яка з цих операцій не вдасться, це викличе помилку, і поточний раунд не буде збережено.
        
        # Примітка: Якщо в response1/response2 є помилка (повернена стрінгом), 
        # ми також повинні зупинити процес і не зменшувати ліміти,
        # але на практиці, якщо генерація була запущена, ліміт має зменшитись.
        # Для простоти, зменшуємо ліміти одразу після отримання відповіді.
        
        # Спроба декременту
        decrement_success1 = DB_MANAGER.decrement_calls(self.key_ids[ai1_name])
        decrement_success2 = DB_MANAGER.decrement_calls(self.key_ids[ai2_name])

        if not decrement_success1 or not decrement_success2:
            # Це дуже малоймовірно, якщо ми перевірили ліміт раніше, але можливо при одночасному використанні.
            raise Exception("Критична помилка: Не вдалося оновити ліміт запитів у базі даних.")


        current_round_data = {
            ai1_name: response1,
            ai2_name: response2
        }
        
        self.history.append(current_round_data)
        self.round += 1
        
        if self.round >= self.MAX_ROUNDS:
            self.is_running = False
        
        return response1, response2