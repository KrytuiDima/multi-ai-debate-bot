# src/debate_manager.py
import asyncio
from typing import Dict, List, Tuple
from enum import Enum
import abc

# Імпорт для роботи з лімітами
try:
    from database import DB_MANAGER
except ImportError:
    # Заглушка, якщо файл запускається окремо
    class MockDBManager:
        def decrement_calls(self, key_id: int, count: int = 1) -> bool:
            print(f"MockDB: Decrementing {count} calls for key {key_id}")
            return True
    DB_MANAGER = MockDBManager()

# Припускаємо, що BaseAI імпортовано з ai_clients
class BaseAI(abc.ABC):
    pass 

class DebateStatus(Enum):
    THINKING = "⏳ Думає..."
    FINISHED = "✅ Готово"

class DebateSession:
    """Керує всіма раундами, історією та промптингом для дебатів."""
    
    # ОНОВЛЕНО: додано key_ids_map
    def __init__(self, topic: str, clients_map: Dict[str, BaseAI], key_ids_map: Dict[str, int], max_rounds: int = 3): 
        self.topic = topic
        self.clients: Dict[str, BaseAI] = clients_map
        self.key_ids: Dict[str, int] = key_ids_map # НОВЕ: Зберігаємо ID ключів
        self.history: List[Dict[str, str]] = [] 
        self.round = 0
        self.is_running = False
        self.MAX_ROUNDS = max_rounds 

    def get_system_prompt(self, model_name: str) -> str:
        """
        Генерує динамічний системний промпт для конкретної моделі на поточному раунді.
        """
        clients_list = list(self.clients.keys())
        ai1_name, ai2_name = clients_list[0], clients_list[1]
        
        # Динамічна роль
        if model_name == ai1_name:
            role = f"Ти - {ai1_name}. Твоя мета - переконати у своїй позиції. Ти починаєш першим."
        else:
            role = f"Ти - {ai2_name}. Твоя мета - спростувати аргументи {ai1_name} та переконати у своїй позиції."

        return (
            f"{role}\n"
            f"Формат відповіді: [Ваш аргумент].\n"
            f"Будь ласка, будь лаконічним, чітким та переконливим. Використовуй факти та логіку."
        )

    def get_full_history(self) -> str:
        """Форматує історію дебатів для включення в промпт наступного раунду."""
        if not self.history:
            return "Дебати ще не розпочато."
        
        formatted_history = []
        for i, round_data in enumerate(self.history):
            round_str = f"--- Раунд {i + 1} ---\n"
            for name, response in round_data.items():
                round_str += f"[{name}]: {response}\n"
            formatted_history.append(round_str)
            
        return "\n".join(formatted_history)

    async def run_next_round(self) -> Tuple[str, str]:
        """
        Виконує наступний раунд дебатів, генеруючи відповіді обох AI 
        та декрементуючи їхні ліміти запитів.
        """
        if self.round >= self.MAX_ROUNDS:
            raise ValueError("Дебати завершено. Немає більше раундів.")

        # --- НОВА ПЕРЕВІРКА ТА ДЕКРЕМЕНТ ЛІМІТУ ---
        client_names = list(self.clients.keys())
        ai1_name, ai2_name = client_names[0], client_names[1]

        # Декрементуємо лічильник на 1 для AI1. Якщо не спрацювало, кидаємо помилку.
        if not DB_MANAGER.decrement_calls(self.key_ids[ai1_name], count=1):
            raise Exception(f"Ліміт запитів для ключа '{ai1_name}' вичерпано.")
            
        # Декрементуємо лічильник на 1 для AI2.
        if not DB_MANAGER.decrement_calls(self.key_ids[ai2_name], count=1):
            raise Exception(f"Ліміт запитів для ключа '{ai2_name}' вичерпано.")
        
        # ЛОГІКА ДЕКРЕМЕНТУ ПРОЙШЛА УСПІШНО
        self.is_running = True
        self.round += 1
        
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
        
        current_round_history = {
            ai1_name: response1,
            ai2_name: response2
        }
        self.history.append(current_round_history)
        self.is_running = False
        
        return response1, response2