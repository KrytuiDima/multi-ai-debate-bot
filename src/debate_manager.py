# src/debate_manager.py
import asyncio
from typing import Dict, List, Tuple
from enum import Enum
import abc

# Припускаємо, що BaseAI імпортовано з ai_clients, якщо запускатиметься окремо
class BaseAI(abc.ABC):
    pass 

class DebateStatus(Enum):
    THINKING = "⏳ Думає..."
    FINISHED = "✅ Готово"

class DebateSession:
    """Керує всіма раундами, історією та промптингом для дебатів."""
    
    # Виправляємо конструктор для прийому clients_map та max_rounds
    def __init__(self, topic: str, clients_map: Dict[str, BaseAI], max_rounds: int = 3): 
        self.topic = topic
        self.clients: Dict[str, BaseAI] = clients_map
        # Історія тепер зберігає повні результати раунду: List[Dict[AI_Name, Response_Text]]
        self.history: List[Dict[str, str]] = [] 
        self.round = 0
        self.is_running = False
        self.MAX_ROUNDS = max_rounds # Використовуємо динамічне значення

    def get_system_prompt(self, model_name: str) -> str:
        """
        Генерує динамічний системний промпт для конкретної моделі на поточному раунді.
        """
        clients_list = list(self.clients.keys())
        opponent_name = clients_list[1] if clients_list[0] == model_name else clients_list[0]
        
        # Динамічна зміна ролі
        role_type = "Почни дебати, зайнявши ПРО-позицію." if self.round == 0 else "Продовжуй аргументацію, відповідаючи на останній хід опонента."
        
        base_prompt = (
            f"Ти - учасник дебатів: **{model_name}**. Твій опонент: {opponent_name}. "
            f"Тема: '{self.topic}'. Це Раунд {self.round + 1}/{self.MAX_ROUNDS}. "
            f"Твоє завдання - переконати у своїй позиції та прагнути до єдиного компромісного рішення, коли раунди закінчаться. "
            f"Твій хід: {role_type} "
            f"Відповідь має бути ЛАКОНІЧНОЮ та ПЕРЕКОНЛИВОЮ."
        )
        return base_prompt

    def get_full_history(self) -> str:
        """Форматує повну історію дебатів для фінального висновку."""
        formatted_history = ""
        for i, round_data in enumerate(self.history):
            formatted_history += f"--- РАУНД {i + 1} ---\n"
            for name, response in round_data.items():
                formatted_history += f"[{name}]: {response}\n"
            formatted_history += "\n"
        return formatted_history.strip()

    async def run_next_round(self) -> Dict[str, str]:
        """Виконує один раунд (ходи обох моделей) та повертає результати."""
        if self.round >= self.MAX_ROUNDS:
            raise ValueError("Дебати завершено. Немає більше раундів.")

        self.is_running = True
        self.round += 1
        
        # Визначаємо, хто ходить першим
        client_names = list(self.clients.keys())
        ai1_name, ai2_name = client_names[0], client_names[1]
        
        # Історія для поточного промпту
        debate_history = self.get_full_history()

        # 1. Створення завдань для обох моделей
        task1 = self.clients[ai1_name].generate_response(
            system_prompt=self.get_system_prompt(ai1_name),
            debate_history=debate_history,
            topic=self.topic
        )
        
        # 2. Якщо це не перший раунд, AI2 відповідає на хід AI1.
        # Для простоти асинхронності, вони відповідають паралельно, але на основі СТАРОЇ історії.
        task2 = self.clients[ai2_name].generate_response(
            system_prompt=self.get_system_prompt(ai2_name),
            debate_history=debate_history,
            topic=self.topic
        )
        
        # 3. Очікування результатів
        response1, response2 = await asyncio.gather(task1, task2)
        
        current_round_results = {
            ai1_name: response1,
            ai2_name: response2
        }
        
        # Додаємо результати раунду до загальної історії
        self.history.append(current_round_results)
        self.is_running = False
        
        return current_round_results