# src/debate_manager.py
import asyncio
from typing import Dict, List
from enum import Enum

class DebateStatus(Enum):
    THINKING = "⏳ Думає..."

class DebateSession:
    def __init__(self, topic: str, clients_map: Dict, max_rounds: int = 3): 
        self.topic = topic
        self.clients = clients_map
        self.history: List[Dict[str, str]] = [] 
        self.round = 0
        self.MAX_ROUNDS = max_rounds

    def get_history_str(self) -> str:
        text = ""
        for i, h in enumerate(self.history):
            text += f"--- Round {i+1} ---\n"
            for k, v in h.items():
                text += f"{k}: {v}\n"
        return text

    async def run_next_round(self) -> Dict[str, str]:
        if self.round >= self.MAX_ROUNDS:
            return {}
        
        self.round += 1
        hist_str = self.get_history_str()
        names = list(self.clients.keys())
        
        # Simple Logic: Both models generate response based on history
        # Model 1
        prompt1 = f"You are {names[0]}. You are debating {names[1]}. Defend your side."
        task1 = self.clients[names[0]].generate_response(prompt1, hist_str, self.topic)
        
        # Model 2
        prompt2 = f"You are {names[1]}. You are debating {names[0]}. Defend your side."
        task2 = self.clients[names[1]].generate_response(prompt2, hist_str, self.topic)
        
        res1, res2 = await asyncio.gather(task1, task2)
        
        round_res = {names[0]: res1, names[1]: res2}
        self.history.append(round_res)
        return round_res