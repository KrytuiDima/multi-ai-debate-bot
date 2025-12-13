# src/database.py
import psycopg2
import sqlite3
import os
from typing import Tuple, List, Dict, Optional
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import base64
import hashlib

# Завантажуємо .env локально, хоча на Railway це робить платформа
load_dotenv()

# --- ФУНКЦІЇ ШИФРУВАННЯ ---

def get_encryption_key() -> bytes:
    """Отримує або генерує ключ шифрування з ENCRYPTION_KEY змінної середовища."""
    key_string = os.getenv('ENCRYPTION_KEY')
    if not key_string:
        raise ValueError("ENCRYPTION_KEY не встановлено у змінних середовища")
    
    # Переконуємось, що ключ має правильний формат для Fernet (32 байти, base64 encoded = 44 символи)
    if len(key_string) == 44:
        # Це вже правильно закодований ключ
        try:
            return key_string.encode() if isinstance(key_string, str) else key_string
        except Exception:
            pass
    
    # Якщо це довгий рядок або невідомий формат, хешуємо його і кодуємо
    key_bytes = hashlib.sha256(key_string.encode()).digest()  # 32 байти
    key = base64.urlsafe_b64encode(key_bytes)  # 44 символи
    return key

def encrypt_key(api_key: str) -> str:
    """Шифрує API-ключ."""
    try:
        key = get_encryption_key()
        cipher = Fernet(key)
        encrypted = cipher.encrypt(api_key.encode())
        return encrypted.decode()
    except Exception as e:
        print(f"Помилка при шифруванні ключа: {e}")
        raise

def decrypt_key(encrypted_key: str) -> str:
    """Розшифровує API-ключ."""
    try:
        key = get_encryption_key()
        cipher = Fernet(key)
        decrypted = cipher.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"Помилка при розшифруванні ключа: {e}")
        raise


class DatabaseManager:
    def __init__(self):
        # Отримуємо рядок підключення з Railway/оточення
        self.db_url = os.getenv("DATABASE_URL")
        self.using_postgres = bool(self.db_url)
        self.db_file = "debate_bot.db"
        
        if not self.using_postgres:
            print("Using SQLite (debate_bot.db) for local development")
    
    def _execute_query(self, conn, sql: str, params: tuple = ()):
        """Виконує запит з автоматичною конвертацією параметрів для SQLite/PostgreSQL."""
        cursor = conn.cursor()
        
        # Конвертуємо %s на ? для SQLite
        if not self.using_postgres:
            sql = sql.replace('%s', '?')
        
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        return cursor
    
    def _connect(self):
        """Встановлює з'єднання з PostgreSQL або SQLite."""
        if self.using_postgres:
            # PostgreSQL (Neon на Railway)
            try:
                params = {
                    'dsn': self.db_url,
                    'sslmode': 'require'
                }
                return psycopg2.connect(**params)
            except Exception as e:
                print(f"Error connecting to PostgreSQL: {e}")
                raise
        else:
            # SQLite (локальна розробка)
            conn = sqlite3.connect(self.db_file, check_same_thread=False)
            conn.row_factory = sqlite3.Row  # Enable column access by name
            return conn

    def _create_tables(self):
        """Створює необхідні таблиці (PostgreSQL або SQLite синтаксис)."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            if self.using_postgres:
                # PostgreSQL таблиці
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        user_id BIGINT NOT NULL,
                        ai_service TEXT NOT NULL,
                        api_key TEXT NOT NULL,
                        PRIMARY KEY (user_id, ai_service)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        balance NUMERIC(10, 2) DEFAULT 0.00,
                        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        active_key_id INTEGER DEFAULT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_api_keys (
                        id SERIAL PRIMARY KEY,
                        owner_id BIGINT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                        api_key TEXT NOT NULL,
                        service VARCHAR(50) NOT NULL,
                        calls_remaining INTEGER DEFAULT 1000,
                        is_active BOOLEAN DEFAULT TRUE,
                        alias VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(owner_id, alias)
                    );
                """)
            else:
                # SQLite таблиці
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        user_id INTEGER NOT NULL,
                        ai_service TEXT NOT NULL,
                        api_key TEXT NOT NULL,
                        PRIMARY KEY (user_id, ai_service)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        balance REAL DEFAULT 0.00,
                        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        active_key_id INTEGER DEFAULT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_api_keys (
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
                    );
                """)

            conn.commit()
            print("Tables created successfully")
        except Exception as e:
            print(f"Помилка створення таблиць: {e}")
        finally:
            if conn:
                conn.close()

    def add_api_key(self, owner_id: int, service: str, api_key: str, alias: str) -> bool:
        """Додає новий зашифрований API-ключ."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            encrypted_key = encrypt_key(api_key)
            
            cursor.execute("""
                INSERT INTO user_api_keys (owner_id, api_key, service, alias)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (owner_id, alias) DO NOTHING;
            """, (owner_id, encrypted_key, service, alias))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Помилка додавання API ключа: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_user_api_keys(self, user_id: int) -> List[Dict]:
        """Отримує всі ключи користувача."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, alias, service, calls_remaining, is_active 
                FROM user_api_keys 
                WHERE owner_id = %s
                ORDER BY created_at DESC;
            """, (user_id,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'alias': row[1],
                    'service': row[2],
                    'calls_remaining': row[3],
                    'is_active': row[4]
                })
            return results
        except Exception as e:
            print(f"Помилка отримання ключів: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_api_key_decrypted(self, key_id: int, user_id: int) -> Optional[Tuple[str, str]]:
        """Отримує розшифрований ключ та сервіс за ID."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT api_key, service 
                FROM user_api_keys 
                WHERE id = %s AND owner_id = %s;
            """, (key_id, user_id))
            
            row = cursor.fetchone()
            if row:
                decrypted_key = decrypt_key(row[0])
                return decrypted_key, row[1]
            return None
        except Exception as e:
            print(f"Помилка отримання розшифрованого ключа: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def decrement_calls(self, key_id: int, user_id: int) -> bool:
        """Зменшує кількість залишків запитів на 1."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE user_api_keys 
                SET calls_remaining = calls_remaining - 1 
                WHERE id = %s AND owner_id = %s;
            """, (key_id, user_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Помилка зменшення запитів: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def set_active_key(self, user_id: int, key_id: int) -> bool:
        """Встановлює активний ключ для користувача."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE user_profiles 
                SET active_key_id = %s 
                WHERE user_id = %s;
            """, (key_id, user_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Помилка встановлення активного ключа: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_active_key_id(self, user_id: int) -> Optional[int]:
        """Отримує ID активного ключа користувача."""
        conn = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT active_key_id 
                FROM user_profiles 
                WHERE user_id = %s;
            """, (user_id,))
            
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            print(f"Помилка отримання активного ключа: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_user_profile(self, user_id: int, username: str) -> Tuple[float, str]:
        """Отримує профіль або створює новий."""
        conn = None
        try:
            conn = self._connect()
            
            cursor = self._execute_query(conn, 
                "SELECT balance, join_date FROM user_profiles WHERE user_id = ?", 
                (user_id,))
            result = cursor.fetchone()
            
            if result:
                balance, join_date = result
                return float(balance), str(join_date)
            else:
                self._execute_query(conn, 
                    "INSERT INTO user_profiles (user_id, username) VALUES (?, ?)",
                    (user_id, username))
                conn.commit()
                
                # Fetch the created record
                cursor = self._execute_query(conn,
                    "SELECT balance, join_date FROM user_profiles WHERE user_id = ?",
                    (user_id,))
                balance, join_date = cursor.fetchone()
                return float(balance), str(join_date)
                
        except Exception as e:
            print(f"Error getting/creating profile: {e}")
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

# Створюємо глобальний об'єкт DatabaseManager
DB_MANAGER = DatabaseManager()

