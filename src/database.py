# src/database.py
import psycopg2
import sqlite3
import os
from typing import Tuple, List, Dict, Optional
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import base64
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# Завантажуємо .env локально, хоча на Railway це робить платформа
load_dotenv()

# --- ФУНКЦІЇ ШИФРУВАННЯ ---

def get_encryption_key() -> bytes:
    """Отримує або генерує ключ шифрування з ENCRYPTION_KEY змінної середовища."""
    key_string = os.getenv('ENCRYPTION_KEY')
    if not key_string:
        # У виробничому середовищі це має викликати помилку, але для розробки дамо підказку
        logger.warning("ENCRYPTION_KEY не встановлено. Використовується ключ за замовчуванням.")
        key_string = "default_key_for_dev_do_not_use_in_prod!"

    # Переконуємось, що ключ має правильний формат для Fernet (32 байти, base64 encoded = 44 символи)
    key_bytes = hashlib.sha256(key_string.encode()).digest()  # 32 байти
    key = base64.urlsafe_b64encode(key_bytes)  # 44 символи, base64
    return key

FERNET_KEY = get_encryption_key()
FERNET = Fernet(FERNET_KEY)

def encrypt_key(api_key: str) -> str:
    """Шифрує API ключ."""
    return FERNET.encrypt(api_key.encode()).decode()

def decrypt_key(encrypted_key: str) -> str:
    """Дешифрує API ключ."""
    return FERNET.decrypt(encrypted_key.encode()).decode()

# --- КЛАС DBManager ---

class DBManager:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.is_sqlite = not self.db_url
        self._init_db()
        
    def _connect(self):
        """Встановлює з'єднання з БД (SQLite або PostgreSQL)."""
        if self.is_sqlite:
            # SQLite для локальної розробки
            return sqlite3.connect('bot_data.db')
        else:
            # PostgreSQL для продакшену
            return psycopg2.connect(self.db_url)

    def _init_db(self):
        """Ініціалізує таблиці бази даних."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            # Для PostgreSQL/SQLite
            if not self.is_sqlite:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id BIGINT PRIMARY KEY,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # PostgreSQL: UNIQUE constraint для user_id та alias
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES users(id),
                        ai_service VARCHAR(50) NOT NULL,
                        api_key TEXT NOT NULL,
                        alias VARCHAR(100) NOT NULL,
                        calls_remaining INTEGER DEFAULT 0,
                        last_call TIMESTAMP,
                        UNIQUE (user_id, alias)
                    );
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # SQLite: UNIQUE constraint
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER,
                        ai_service TEXT NOT NULL,
                        api_key TEXT NOT NULL,
                        alias TEXT NOT NULL,
                        calls_remaining INTEGER DEFAULT 0,
                        last_call DATETIME,
                        UNIQUE (user_id, alias),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    );
                """)
            
            conn.commit()
        except Exception as e:
            logger.error(f"Помилка ініціалізації БД: {e}")
        finally:
            if conn:
                conn.close()

    def register_user(self, user_id: int, username: str, first_name: str) -> None:
        """Реєструє користувача, якщо його ще немає."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.is_sqlite:
                 cursor.execute("INSERT OR IGNORE INTO users (id, username, first_name) VALUES (?, ?, ?)", 
                                (user_id, username, first_name))
            else:
                cursor.execute("""
                    INSERT INTO users (id, username, first_name) 
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (user_id, username, first_name))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Помилка реєстрації користувача {user_id}: {e}")
        finally:
            if conn:
                conn.close()

    def add_api_key(self, owner_id: int, service: str, api_key: str, alias: str, calls_remaining: int) -> bool:
        """Додає новий API ключ до бази даних."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            encrypted_key = encrypt_key(api_key)
            
            if self.is_sqlite:
                cursor.execute("""
                    INSERT INTO api_keys (user_id, ai_service, api_key, alias, calls_remaining)
                    VALUES (?, ?, ?, ?, ?)
                """, (owner_id, service, encrypted_key, alias, calls_remaining))
            else:
                cursor.execute("""
                    INSERT INTO api_keys (user_id, ai_service, api_key, alias, calls_remaining)
                    VALUES (%s, %s, %s, %s, %s)
                """, (owner_id, service, encrypted_key, alias, calls_remaining))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            # UNIQUE constraint error, alias already exists
            logger.error(f"Помилка додавання ключа: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_user_keys_with_alias(self, user_id: int) -> List[Tuple[str, str, int, int]]:
        """Завантажує (alias, service, calls_remaining, id) для користувача."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.is_sqlite:
                cursor.execute("""
                    SELECT alias, ai_service, calls_remaining, id FROM api_keys WHERE user_id = ?
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT alias, ai_service, calls_remaining, id FROM api_keys WHERE user_id = %s
                """, (user_id,))
            
            # (alias, service, remaining, key_id)
            return cursor.fetchall()
            
        except Exception as e:
            logger.error(f"Помилка завантаження ключів з alias: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_key_details_by_alias(self, user_id: int, alias: str) -> Optional[Tuple[int, str, str]]:
        """Завантажує (key_id, service, encrypted_key) за alias."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.is_sqlite:
                cursor.execute("""
                    SELECT id, ai_service, api_key FROM api_keys WHERE user_id = ? AND alias = ?
                """, (user_id, alias))
            else:
                cursor.execute("""
                    SELECT id, ai_service, api_key FROM api_keys WHERE user_id = %s AND alias = %s
                """, (user_id, alias))
            
            # (key_id, service, encrypted_key)
            return cursor.fetchone()
            
        except Exception as e:
            logger.error(f"Помилка завантаження деталей ключа {alias}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_remaining_calls(self, key_id: int) -> Optional[int]:
        """Повертає кількість запитів, що залишилися для ключа."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.is_sqlite:
                cursor.execute("SELECT calls_remaining FROM api_keys WHERE id = ?", (key_id,))
            else:
                cursor.execute("SELECT calls_remaining FROM api_keys WHERE id = %s", (key_id,))
            
            result = cursor.fetchone()
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Помилка отримання залишку дзвінків для ключа {key_id}: {e}")
            return None
        finally:
            if conn:
                conn.close()
                
    def decrement_calls(self, key_id: int, count: int = 1) -> bool:
        """Зменшує лічильник запитів для ключа, перевіряючи, чи він не стане від'ємним."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.is_sqlite:
                # Атомарна операція в SQLite
                cursor.execute("""
                    UPDATE api_keys 
                    SET calls_remaining = calls_remaining - ?, last_call = CURRENT_TIMESTAMP 
                    WHERE id = ? AND calls_remaining >= ?
                """, (count, key_id, count))
            else:
                # Атомарна операція в PostgreSQL
                cursor.execute("""
                    UPDATE api_keys 
                    SET calls_remaining = calls_remaining - %s, last_call = NOW() 
                    WHERE id = %s AND calls_remaining >= %s
                """, (count, key_id, count))
            
            conn.commit()
            
            if cursor.rowcount == 0:
                raise Exception("Ліміт запитів вичерпано або ключ не знайдено.")
            
            return True
            
        except Exception as e:
            logger.error(f"Помилка декременту ліміту для ключа {key_id}: {e}")
            return False
        finally:
            if conn:
                conn.close()

# Створюємо глобальний об'єкт менеджера БД
DB_MANAGER = DBManager()