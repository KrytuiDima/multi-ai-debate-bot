# src/debate_manager.py
import asyncio
from typing import Dict, List, Tuple
from enum import Enum
import abc
import logging

# Імпортуємо DB_MANAGER та BaseAI
from database import DB_MANAGER
# Імпортуємо BaseAI з ai_clients для коректної типізації
try:
    # Робимо імпорт BaseAI стійким до того, якщо ai_clients ще не запущений
    from ai_clients import BaseAI 
except ImportError:
    # Запасний варіант, якщо запускається окремо
    class BaseAI(abc.ABC): 
        @abc.abstractmethod
        async def generate_response(self, system_prompt: str, debate_history: str, topic: str) -> str: pass

logger = logging.getLogger(__name__)

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
        # Історія: List[Dict[AI_Name, Response_Text]]
        self.history: List[Dict[str, str]] = [] 
        self.round = 0
        self.is_running = False
        self.MAX_ROUNDS = max_rounds 

    def get_system_prompt(self, current_ai_name: str) -> str:
        """
        Генерує динамічний системний промпт для конкретної моделі на поточному раунді.
        """
        clients_list = list(self.clients.keys())
        # Переконаємося, що у нас є 2 клієнти
        if len(clients_list) < 2:
            raise ValueError("Для дебатів потрібно два AI-клієнти.")
            
        ai1_name, ai2_name = clients_list[0], clients_list[1]
        
        # Визначаємо ролі
        if current_ai_name == ai1_name:
            role = "головний захисник (позитивна сторона)"
            opponent_name = ai2_name
        else:
            role = "головний опонент (негативна сторона)"
            opponent_name = ai1_name
            
        # Залежно від раунду, формуємо завдання
        if self.round == 1:
            task = f"Твоя перша місія - чітко сформулювати свою позицію. Ти {role} у дебатах на тему '{self.topic}'. Зроби вступне слово, щоб закласти основу для свого аргументу."
        elif self.round < self.MAX_ROUNDS:
            task = f"Ти {role}. Проаналізуй останній хід твого опонента ({opponent_name}). Спростуй його основні тези та посиль свою позицію, використовуючи нові, переконливі аргументи."
        else:
            task = f"Це останній, фінальний раунд. Ти {role}. На основі всієї історії дебатів, створи потужний підсумок. Зверни увагу на ключові моменти, в яких ти переміг, і зроби останнє переконливе твердження, не відповідаючи прямо на останній хід опонента, а підбиваючи загальний підсумок."

        # Головний промпт для моделі
        system_prompt = (
            "Ти — висококваліфікований AI-дебатер. "
            "Твоя мета — переконати незалежних суддів у своїй правоті. "
            f"Твоя роль: {role}. "
            f"Тема: '{self.topic}'. "
            "Дотримуйся наступних правил: "
            "1. Будь логічним, послідовним та використовуй факти. "
            "2. Уникай повторень. "
            "3. Твої відповіді повинні бути лаконічними, але змістовними (до 3-4 абзаців). "
            f"Поточне завдання: {task}"
        )
        return system_prompt

    def get_full_history(self) -> str:
        """Форматує всю історію дебатів у зручний для LLM рядок."""
        if not self.history:
            return "Дебати ще не розпочато."
        
        history_str = ""
        for i, round_data in enumerate(self.history):
            round_num = i + 1
            for name, response in round_data.items():
                history_str += f"--- РАУНД {round_num} | Хід AI '{name}' ---\n"
                history_str += f"{response}\n\n"
        return history_str.strip()

    def get_last_round_summary(self) -> str:
        """Форматує результат останнього раунду для виводу користувачу."""
        if not self.history:
            return "Дебати ще не розпочато."
            
        last_round = self.history[-1]
        summary = f"**🔥 РАУНД {self.round}/{self.MAX_ROUNDS} ЗАВЕРШЕНО!**\n\n"
        
        for name, response in last_round.items():
            summary += f"**🤖 AI '{name}' (Хід):**\n"
            summary += f"{response}\n\n---\n"
            
        return summary.strip()

    async def next_round(self) -> Tuple[bool, str]:
        """Запускає наступний раунд дебатів (обидва AI відповідають одночасно)."""
        if self.round >= self.MAX_ROUNDS:
            return True, "Дебати завершено. Немає більше раундів."

        self.is_running = True
        self.round += 1
        
        # Визначаємо, хто ходить першим (для історії)
        client_names = list(self.clients.keys())
        ai1_name, ai2_name = client_names[0], client_names[1]
        
        # Історія для поточного промпту (беремо історію ДО цього раунду)
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
        
        # Перевірка на помилки в генерації
        if "Помилка" in response1 or "Помилка" in response2:
            self.is_running = False
            self.round -= 1 # Відкочуємо раунд
            error_msg = f"Помилка під час генерації в раунді {self.round+1}:\n"
            if "Помилка" in response1: error_msg += f"AI '{ai1_name}': {response1}\n"
            if "Помилка" in response2: error_msg += f"AI '{ai2_name}': {response2}\n"
            return False, error_msg

        # 3. Зменшення лімітів ПІСЛЯ успішного отримання відповідей
        decrement_success1 = DB_MANAGER.decrement_calls(self.key_ids[ai1_name])
        decrement_success2 = DB_MANAGER.decrement_calls(self.key_ids[ai2_name])

        if not decrement_success1 or not decrement_success2:
            self.is_running = False
            self.round -= 1 # Відкочуємо раунд
            logger.error(f"Failed to decrement calls for {self.key_ids[ai1_name]} or {self.key_ids[ai2_name]}")
            return False, "Критична помилка: Не вдалося оновити ліміт запитів у базі даних. Дебати зупинено."


        current_round_data = {
            ai1_name: response1,
            ai2_name: response2
        }
        
        self.history.append(current_round_data)
        self.is_running = False
        
        # Перевірка, чи це був останній раунд
        is_finished = self.round >= self.MAX_ROUNDS
        
        return is_finished, self.get_last_round_summary()