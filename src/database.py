# src/database.py
import sqlite3
from typing import Dict, List, Optional, Tuple

class DatabaseManager:
    """Керує базою даних SQLite для зберігання ключів користувачів."""
    
    def __init__(self, db_name='debate_bot.db'):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self._create_table()
        self._create_profile_table()

    def _create_table(self):
        """Створює таблицю, якщо вона ще не існує."""
        # user_id - унікальний ID користувача Telegram
        # model_name - назва моделі (e.g., 'Gemini', 'Llama3 (Groq)')
        # api_key - сам ключ
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                user_id INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                api_key TEXT NOT NULL,
                UNIQUE(user_id, model_name, api_key)
            )
        """)
        self.conn.commit()

    def _create_profile_table(self):
        """Створює таблицю профілів користувачів (баланс, ім'я, дата)."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                join_date TEXT
            )
        """)
        self.conn.commit()

    def get_user_profile(self, user_id: int, username: str) -> Tuple[float, str]:
        """Отримує баланс та дату приєднання; створює профіль, якщо його немає."""
        self.cursor.execute("SELECT balance, join_date FROM user_profiles WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()

        if result is None:
            # Створюємо новий профіль
            self.cursor.execute("""
                INSERT INTO user_profiles (user_id, username, balance, join_date) 
                VALUES (?, ?, 0.0, datetime('now'))
            """, (user_id, username))
            self.conn.commit()
            return 0.0, "Сьогодні"

        return result[0], result[1]

    def update_balance(self, user_id: int, amount: float):
        """Змінює баланс користувача (додає/віднімає значення)."""
        self.cursor.execute("UPDATE user_profiles SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        self.conn.commit()

    def add_key(self, user_id: int, model_name: str, api_key: str) -> bool:
        """Додає новий ключ для користувача."""
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO api_keys (user_id, model_name, api_key) 
                VALUES (?, ?, ?)
            """, (user_id, model_name, api_key))
            self.conn.commit()
            # Перевіряємо, чи був вставлений новий рядок
            return self.cursor.rowcount > 0
        except Exception as e:
            print(f"Помилка при додаванні ключа: {e}")
            return False

    def get_keys_by_user(self, user_id: int) -> Dict[str, List[str]]:
        """Завантажує всі ключі для користувача, згруповані за моделлю."""
        self.cursor.execute("""
            SELECT model_name, api_key FROM api_keys WHERE user_id = ?
        """, (user_id,))
        
        results: Dict[str, List[str]] = {}
        
        for model_name, api_key in self.cursor.fetchall():
            if model_name not in results:
                results[model_name] = []
            results[model_name].append(api_key)
            
        return results

    def close(self):
        self.conn.close()

# Ініціалізуємо менеджер БД
db_manager = DatabaseManager()