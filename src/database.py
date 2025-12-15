# src/database.py
import psycopg2
import sqlite3
import os
from typing import Tuple, List, Dict, Optional
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import base64
import hashlib
import logging
from datetime import datetime

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

# Ініціалізуємо Fernet
try:
    _fernet = Fernet(get_encryption_key())
except ValueError as e:
    logger.error(f"Помилка ініціалізації Fernet: {e}")
    _fernet = None

def encrypt_key(api_key: str) -> bytes:
    """Шифрує API-ключ."""
    if not _fernet:
        raise Exception("Шифрування не ініціалізовано.")
    return _fernet.encrypt(api_key.encode())

def decrypt_key(encrypted_key: bytes) -> str:
    """Дешифрує API-ключ."""
    if not _fernet:
        raise Exception("Шифрування не ініціалізовано.")
    return _fernet.decrypt(encrypted_key).decode()

# --- КЕРІВНИК БАЗИ ДАНИХ ---

class DBManager:
    def __init__(self):
        self.DATABASE_URL = os.getenv("DATABASE_URL")
        self.is_sqlite = not self.DATABASE_URL
        if self.is_sqlite:
            self.db_name = "bot_data.db"
            print(f"Використовується SQLite: {self.db_name}")
        else:
            print("Використовується PostgreSQL.")
            
        self._create_tables()

    def _connect(self):
        """Встановлює з'єднання з БД."""
        if self.is_sqlite:
            return sqlite3.connect(self.db_name)
        else:
            return psycopg2.connect(self.DATABASE_URL)

    def _create_tables(self):
        """Створює необхідні таблиці при ініціалізації."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.is_sqlite:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        ai_service TEXT NOT NULL,
                        api_key BLOB NOT NULL,
                        alias TEXT,
                        calls_limit INTEGER NOT NULL DEFAULT 0,
                        calls_remaining INTEGER NOT NULL DEFAULT 0,
                        last_call TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (user_id, ai_service, alias)
                    );
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        ai_service TEXT NOT NULL,
                        api_key BYTEA NOT NULL,
                        alias TEXT,
                        calls_limit INTEGER NOT NULL DEFAULT 0,
                        calls_remaining INTEGER NOT NULL DEFAULT 0,
                        last_call TIMESTAMP WITH TIME ZONE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        UNIQUE (user_id, ai_service, alias)
                    );
                """)
            conn.commit()
            print("Таблиці БД успішно створено/перевірено.")
        except Exception as e:
            logger.error(f"Помилка створення таблиць: {e}")
        finally:
            if conn:
                conn.close()

    def add_new_key(self, user_id: int, ai_service: str, api_key: str, alias: str, calls_limit: int) -> bool:
        """Додає новий API-ключ з унікальним аліасом та лімітом."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            encrypted_key = encrypt_key(api_key)
            
            # В SQLite blob - це просто bytes (b'...')
            # В PostgreSQL bytea - це bytes (\x...)
            
            if self.is_sqlite:
                cursor.execute("""
                    INSERT INTO api_keys (user_id, ai_service, api_key, alias, calls_limit, calls_remaining)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (user_id, ai_service, encrypted_key, alias, calls_limit, calls_limit))
            else:
                cursor.execute("""
                    INSERT INTO api_keys (user_id, ai_service, api_key, alias, calls_limit, calls_remaining)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (user_id, ai_service, encrypted_key, alias, calls_limit, calls_limit))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            # Ловимо унікальне обмеження
            if 'unique constraint' in str(e).lower() or 'UNIQUE constraint failed' in str(e):
                logger.warning(f"Спроба додати неунікальний ключ/аліас для user {user_id}: {ai_service}/{alias}")
            else:
                logger.error(f"Помилка додавання ключа: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_keys_by_user(self, user_id: int) -> List[Tuple[int, str, str, str, int, int]]:
        """Завантажує всі ключі для користувача: (id, service, key, alias, limit, remaining)"""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, ai_service, api_key, alias, calls_limit, calls_remaining
                FROM api_keys WHERE user_id = ?
            """ if self.is_sqlite else """
                SELECT id, ai_service, api_key, alias, calls_limit, calls_remaining
                FROM api_keys WHERE user_id = %s
            """, (user_id,))
            
            results = []
            for key_id, ai_service, encrypted_key, alias, calls_limit, calls_remaining in cursor.fetchall():
                try:
                    decrypted_key = decrypt_key(encrypted_key)
                    results.append((key_id, ai_service, decrypted_key, alias, calls_limit, calls_remaining))
                except Exception as e:
                    logger.error(f"Помилка дешифрування ключа ID {key_id}: {e}")
                    # Пропускаємо пошкоджений ключ
            
            return results
            
        except Exception as e:
            logger.error(f"Помилка завантаження ключів: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_key_details(self, key_id: int) -> Optional[Tuple[int, str, str, str, int, int]]:
        """Завантажує деталі одного ключа за його ID."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT user_id, ai_service, api_key, alias, calls_limit, calls_remaining
                FROM api_keys WHERE id = ?
            """ if self.is_sqlite else """
                SELECT user_id, ai_service, api_key, alias, calls_limit, calls_remaining
                FROM api_keys WHERE id = %s
            """, (key_id,))
            
            row = cursor.fetchone()
            if row:
                user_id, ai_service, encrypted_key, alias, calls_limit, calls_remaining = row
                decrypted_key = decrypt_key(encrypted_key)
                return (key_id, ai_service, decrypted_key, alias, calls_limit, calls_remaining)
            return None
            
        except Exception as e:
            logger.error(f"Помилка отримання деталей ключа {key_id}: {e}")
            return None
        finally:
            if conn:
                conn.close()
                
    def delete_key(self, user_id: int, key_id: int) -> bool:
        """Видаляє ключ за ID та перевіряє власника."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM api_keys WHERE id = ? AND user_id = ?
            """ if self.is_sqlite else """
                DELETE FROM api_keys WHERE id = %s AND user_id = %s
            """, (key_id, user_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Помилка видалення ключа {key_id} для user {user_id}: {e}")
            return False
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
                # Це може бути, якщо ліміт вичерпано або ключ не знайдено
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Помилка декременту ліміту для ключа {key_id}: {e}")
            return False
        finally:
            if conn:
                conn.close()

# Ініціалізуємо глобальний об'єкт
DB_MANAGER = DBManager()