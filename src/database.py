# src/database.py
import psycopg2
import sqlite3
import os
from typing import Tuple, List, Dict, Optional, Any
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import base64
import hashlib

load_dotenv()

# --- ШИФРУВАННЯ ---

def get_encryption_key() -> bytes:
    key_string = os.getenv('ENCRYPTION_KEY', 'default-unsafe-key-change-me-in-prod')
    if len(key_string) == 44:
        return key_string.encode()
    # Хешуємо, якщо формат не Fernet
    key_bytes = hashlib.sha256(key_string.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)

def encrypt_key(api_key: str) -> str:
    f = Fernet(get_encryption_key())
    return f.encrypt(api_key.encode()).decode()

def decrypt_key(encrypted_key: str) -> str:
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted_key.encode()).decode()

# --- МЕНЕДЖЕР БАЗИ ДАНИХ ---

class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.using_postgres = bool(self.db_url) and self.db_url.startswith("postgres")
        self.db_file = "debate_bot.db"
        
        if not self.using_postgres:
            print(f"⚠️ Using SQLite ({self.db_file}) - Local Mode")
        else:
            print("✅ Using PostgreSQL - Production Mode")

    def _get_connection(self):
        if self.using_postgres:
            return psycopg2.connect(self.db_url, sslmode='require')
        else:
            conn = sqlite3.connect(self.db_file, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

    def _execute(self, sql: str, params: tuple = ()) -> Any:
        """Універсальний виконавець запитів, що адаптує синтаксис."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Адаптація синтаксису для SQLite
            if not self.using_postgres:
                sql = sql.replace('%s', '?')
            
            cursor.execute(sql, params)
            
            if sql.strip().upper().startswith(("SELECT", "RETURNING")):
                return cursor.fetchall()
            else:
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            print(f"SQL Error: {e}")
            print(f"Query: {sql}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()

    def _create_tables(self):
        # SQL для PostgreSQL
        tables_pg = [
            """CREATE TABLE IF NOT EXISTS user_profiles (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance NUMERIC(10, 2) DEFAULT 0.00,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active_key_id INTEGER DEFAULT NULL
            );""",
            """CREATE TABLE IF NOT EXISTS user_api_keys (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                api_key TEXT NOT NULL,
                service VARCHAR(50) NOT NULL,
                calls_remaining INTEGER DEFAULT 1000,
                is_active BOOLEAN DEFAULT TRUE,
                alias VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, alias)
            );"""
        ]
        
        # SQL для SQLite
        tables_sqlite = [
            """CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.00,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active_key_id INTEGER DEFAULT NULL
            );""",
            """CREATE TABLE IF NOT EXISTS user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                api_key TEXT NOT NULL,
                service VARCHAR(50) NOT NULL,
                calls_remaining INTEGER DEFAULT 1000,
                is_active BOOLEAN DEFAULT TRUE,
                alias VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, alias),
                FOREIGN KEY(owner_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            );"""
        ]

        queries = tables_pg if self.using_postgres else tables_sqlite
        for q in queries:
            self._execute(q)
        print("✅ Таблиці перевірено/створено.")

    # --- МЕТОДИ РОБОТИ З ДАНИМИ ---

    def get_user_profile(self, user_id: int, username: str) -> Tuple[float, str]:
        # Спочатку пробуємо створити (якщо нема), ігноруючи конфлікт
        self._execute(
            "INSERT INTO user_profiles (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING",
            (user_id, username)
        )
        # Тепер вибираємо
        res = self._execute("SELECT balance, join_date FROM user_profiles WHERE user_id = %s", (user_id,))
        if res:
            return float(res[0][0] if self.using_postgres else res[0]['balance']), str(res[0][1] if self.using_postgres else res[0]['join_date'])
        return 0.0, "N/A"

    def add_api_key(self, owner_id: int, service: str, api_key: str, alias: str) -> bool:
        encrypted = encrypt_key(api_key)
        res = self._execute(
            "INSERT INTO user_api_keys (owner_id, api_key, service, alias) VALUES (%s, %s, %s, %s)",
            (owner_id, encrypted, service, alias)
        )
        return bool(res)

    def get_user_api_keys(self, user_id: int) -> List[Dict]:
        res = self._execute(
            "SELECT id, alias, service, calls_remaining, is_active FROM user_api_keys WHERE owner_id = %s ORDER BY created_at DESC",
            (user_id,)
        )
        if not res: return []
        
        keys = []
        for row in res:
            # Обробка різниці між tuple (pg) та Row (sqlite)
            if self.using_postgres:
                keys.append({'id': row[0], 'alias': row[1], 'service': row[2], 'calls_remaining': row[3], 'is_active': row[4]})
            else:
                keys.append(dict(row))
        return keys

    def get_api_key_decrypted(self, key_id: int, user_id: int) -> Optional[Tuple[str, str]]:
        res = self._execute(
            "SELECT api_key, service FROM user_api_keys WHERE id = %s AND owner_id = %s",
            (key_id, user_id)
        )
        if res:
            row = res[0]
            enc_key = row[0] if self.using_postgres else row['api_key']
            service = row[1] if self.using_postgres else row['service']
            return decrypt_key(enc_key), service
        return None

    def decrement_calls(self, key_id: int, user_id: int):
        self._execute(
            "UPDATE user_api_keys SET calls_remaining = calls_remaining - 1 WHERE id = %s AND owner_id = %s",
            (key_id, user_id)
        )

    def set_active_key(self, user_id: int, key_id: int) -> bool:
        res = self._execute("UPDATE user_profiles SET active_key_id = %s WHERE user_id = %s", (key_id, user_id))
        return bool(res)

    def get_active_key_id(self, user_id: int) -> Optional[int]:
        res = self._execute("SELECT active_key_id FROM user_profiles WHERE user_id = %s", (user_id,))
        if res:
            return res[0][0] if self.using_postgres else res[0]['active_key_id']
        return None

DB_MANAGER = DatabaseManager()