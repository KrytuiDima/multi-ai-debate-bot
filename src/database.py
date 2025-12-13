# src/database.py
import psycopg2
import os
from typing import Tuple, List, Dict
from dotenv import load_dotenv

# Завантажуємо .env локально, хоча на Vercel це робить платформа
load_dotenv()

class DatabaseManager:
    def __init__(self):
        # Отримуємо рядок підключення з Vercel/оточення
        self.db_url = os.getenv("DATABASE_URL")
        if not self.db_url:
            print("WARNING: DATABASE_URL не знайдено. БД функціонуватиме тільки з точкою входу Vercel.")
    
    def _connect(self):
        """Встановлює з'єднання з PostgreSQL з явним SSL."""
        if not self.db_url:
            raise Exception("DATABASE_URL не встановлено.")
        
        # Neon вимагає SSL. Додаємо ці параметри у рядок підключення.
        # Створюємо словник параметрів
        params = {
            'dsn': self.db_url,  # dsn - Data Source Name
            'sslmode': 'require'  # Явно вимагаємо SSL
        }
        
        return psycopg2.connect(**params)  # Передаємо словник параметрів

    def _create_tables(self):
        """Створює необхідні таблиці (використовуємо синтаксис PostgreSQL)."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            # Таблиця 1: API-ключі користувачів
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    user_id BIGINT NOT NULL,
                    ai_service TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    PRIMARY KEY (user_id, ai_service)
                );
            """)

            # Таблиця 2: Профілі користувачів та баланс
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    balance NUMERIC(10, 2) DEFAULT 0.00,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.commit()
            print("Таблиці успішно створені/перевірені.")
        except Exception as e:
            print(f"Помилка створення таблиць: {e}")
        finally:
            if conn:
                conn.close()

    def get_user_profile(self, user_id: int, username: str) -> Tuple[float, str]:
        """Отримує профіль або створює новий."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("SELECT balance, join_date FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            if result:
                balance, join_date = result
                return float(balance), str(join_date)
            else:
                cursor.execute("""
                    INSERT INTO user_profiles (user_id, username)
                    VALUES (%s, %s)
                    RETURNING balance, join_date;
                """, (user_id, username))
                conn.commit()
                balance, join_date = cursor.fetchone()
                return float(balance), str(join_date)
                
        except Exception as e:
            print(f"Помилка отримання/створення профілю: {e}")
            return 0.0, "N/A"
        finally:
            if conn:
                conn.close()

    def update_balance(self, user_id: int, amount: float) -> bool:
        """Оновлює баланс користувача."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_profiles SET balance = balance + %s WHERE user_id = %s
            """, (amount, user_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"Помилка оновлення балансу: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def add_key(self, user_id: int, model_name: str, api_key: str) -> bool:
        """Додає новий API-ключ для користувача."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO api_keys (user_id, ai_service, api_key)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, ai_service) DO NOTHING;
            """, (user_id, model_name, api_key))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            print(f"Помилка додавання ключа: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_keys_by_user(self, user_id: int) -> Dict[str, List[str]]:
        """Завантажує всі ключі для користувача, згруповані за моделлю."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT ai_service, api_key FROM api_keys WHERE user_id = %s
            """, (user_id,))
            
            results: Dict[str, List[str]] = {}
            
            for ai_service, api_key in cursor.fetchall():
                if ai_service not in results:
                    results[ai_service] = []
                results[ai_service].append(api_key)
            
            return results
            
        except Exception as e:
            print(f"Помилка завантаження ключів: {e}")
            return {}
        finally:
            if conn:
                conn.close()

    def close(self):
        """Закриває з'єднання (якщо воно існує)."""
        pass

# Створюємо глобальний об'єкт DatabaseManager
DB_MANAGER = DatabaseManager()

