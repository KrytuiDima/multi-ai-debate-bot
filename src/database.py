# src/database.py
import psycopg2
import sqlite3
import os
from typing import Tuple, List, Dict, Optional
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import base64
import hashlib

# Завантажуємо .env локально
load_dotenv()

# --- ФУНКЦІЇ ШИФРУВАННЯ ---

def get_encryption_key() -> bytes:
    """Отримує або генерує ключ шифрування з ENCRYPTION_KEY змінної середовища."""
    key_string = os.getenv('ENCRYPTION_KEY')
    if not key_string:
        raise ValueError("ENCRYPTION_KEY не встановлено у змінних середовища")
    
    # Fernet вимагає ключ довжиною 32 байти (44 символи в base64)
    if len(key_string) == 44 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_' for c in key_string):
        return key_string.encode()
    
    # Якщо це довгий рядок або невідомий формат, хешуємо його і кодуємо
    key_bytes = hashlib.sha256(key_string.encode()).digest()  # 32 байти
    key = base64.urlsafe_b64encode(key_bytes)  # 44 символи
    return key

def encrypt_key(api_key: str) -> str:
    """Шифрує API-ключ."""
    f = Fernet(get_encryption_key())
    return f.encrypt(api_key.encode()).decode()

def decrypt_key(encrypted_key: str) -> str:
    """Дешифрує API-ключ."""
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted_key.encode()).decode()


# --- КЛАС КЕРУВАННЯ БАЗОЮ ДАНИХ ---

class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.is_postgres = bool(self.db_url)
        self._create_tables()

    def _connect(self):
        if self.is_postgres:
            return psycopg2.connect(self.db_url)
        else:
            # Використовуємо SQLite
            return sqlite3.connect('debate_bot.db')

    def _execute(self, sql: str, params: Optional[Tuple] = None, fetch: bool = False, fetchone: bool = False):
        conn = None
        result = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            
            if fetch or fetchone:
                result = cursor.fetchall() if fetch else cursor.fetchone()
            
            conn.commit()
            if not fetch and not fetchone:
                result = cursor.rowcount # Повертаємо кількість змінених рядків
            
        except Exception as e:
            print(f"Помилка виконання SQL: {e}")
            raise
        finally:
            if conn:
                conn.close()
        return result

    def _create_tables(self):
        # ОНОВЛЕНО: calls_remaining INTEGER DEFAULT 0
        tables_pg = [
            """CREATE TABLE IF NOT EXISTS user_profiles (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                first_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS user_api_keys (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                api_key TEXT NOT NULL,
                service VARCHAR(50) NOT NULL,
                calls_remaining INTEGER DEFAULT 0, 
                is_active BOOLEAN DEFAULT TRUE,
                alias VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, alias)
            );"""
        ]
        
        tables_sqlite = [
            """CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                api_key TEXT NOT NULL,
                service VARCHAR(50) NOT NULL,
                calls_remaining INTEGER DEFAULT 0, 
                is_active BOOLEAN DEFAULT TRUE,
                alias VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, alias),
                FOREIGN KEY(owner_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            );"""
        ]
        
        tables = tables_pg if self.is_postgres else tables_sqlite
        
        for sql in tables:
            try:
                self._execute(sql)
            except Exception as e:
                print(f"Помилка створення таблиці: {e}")

    def register_user(self, user_id: int, username: str, first_name: str) -> bool:
        """Реєструє або оновлює користувача."""
        sql = """
            INSERT INTO user_profiles (user_id, username, first_name) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name;
        """
        params = (user_id, username, first_name)
        return self._execute(sql, params) is not None

    def add_api_key(self, owner_id: int, service: str, api_key: str, alias: str, calls_remaining: int = 0) -> bool:
        """Додає новий API-ключ користувача з початковим лімітом."""
        encrypted = encrypt_key(api_key)
        sql = "INSERT INTO user_api_keys (owner_id, api_key, service, alias, calls_remaining) VALUES (%s, %s, %s, %s, %s)"
        params = (owner_id, encrypted, service, alias, calls_remaining)
        
        try:
            res = self._execute(sql, params)
            return bool(res)
        except Exception as e:
            print(f"Помилка додавання ключа: {e}")
            return False

    def get_user_keys_with_alias(self, user_id: int) -> List[Tuple[str, str, int, int]]:
        """Завантажує (alias, service, calls_remaining, id) для користувача."""
        sql = "SELECT alias, service, calls_remaining, id FROM user_api_keys WHERE owner_id = %s AND is_active = TRUE ORDER BY created_at DESC"
        params = (user_id,)
        return self._execute(sql, params, fetch=True) or []

    def get_key_details_by_alias(self, owner_id: int, alias: str) -> Optional[Tuple[int, str, str]]:
        """Повертає (id, service, encrypted_key) для даного ключа користувача."""
        sql = "SELECT id, service, api_key, calls_remaining FROM user_api_keys WHERE owner_id = %s AND alias = %s AND is_active = TRUE"
        params = (owner_id, alias)
        
        result = self._execute(sql, params, fetchone=True)
        
        # Повертаємо тільки (id, service, encrypted_key)
        if result:
            return (result[0], result[1], result[2])
        return None

    def decrement_calls(self, key_id: int, count: int = 1) -> bool:
        """
        Атомарно зменшує лічильник calls_remaining для даного key_id.
        Повертає True, якщо лічильник був успішно зменшений, інакше повертає False.
        """
        sql = """
            UPDATE user_api_keys
            SET calls_remaining = calls_remaining - %s
            WHERE id = %s AND calls_remaining >= %s;
        """
        # %s для count, %s для key_id, %s для перевірки (min value is count)
        params = (count, key_id, count) 

        res = self._execute(sql, params)
        return res > 0

    def get_remaining_calls(self, key_id: int) -> Optional[int]:
        """Отримує поточний залишок запитів для ключа."""
        sql = "SELECT calls_remaining FROM user_api_keys WHERE id = %s"
        params = (key_id,)
        
        result = self._execute(sql, params, fetchone=True)
        if result:
            return result[0] 
        return None

DB_MANAGER = DatabaseManager()