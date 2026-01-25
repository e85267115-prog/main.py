import logging
import json
import random
import asyncio
import datetime
import os
import secrets
import string
import ssl  # <-- ДОБАВЛЕНО ДЛЯ SUPABASE
from typing import Dict, List, Tuple, Optional, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
import pytz
import asyncpg  # <-- ОСТАЕТСЯ, НО С SSL НАСТРОЙКОЙ
from dataclasses import dataclass
from contextlib import asynccontextmanager

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TOKEN", "ВАШ_ТОКЕН_БОТА")
ADMIN_IDS = json.loads(os.environ.get("ADMIN_IDS", "[123456789]"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@nvibee_bet")
CHAT_USERNAME = os.environ.get("CHAT_USERNAME", "@chatvibee_bet")

# Supabase строка подключения (получаем из переменных окружения Render)
DATABASE_URL = os.environ.get("DATABASE_URL")

"# Проверяем, это Supabase или нет"
IS_SUPABASE = DATABASE_URL and "supabase" in DATABASE_URL.lower()

if IS_SUPABASE:
    print("✅ Обнаружено подключение к Supabase")
    # Добавляем sslmode=require если его нет
    if "?sslmode=" not in DATABASE_URL:
        DATABASE_URL += "?sslmode=require"
elif DATABASE_URL:
    print("✅ Обнаружено подключение к PostgreSQL")
else:
    print("⚠️ DATABASE_URL не задан, будет использовано локальное хранилище")
"# Можно использовать SQLite для разработки"
DATABASE_URL = None

# ========== НАСТРОЙКИ РЕФЕРАЛЬНОЙ СИСТЕМЫ ==========
REFERRAL_BONUS = 10000  # Бонус за приглашенного пользователя
REFERRAL_PERCENT = 0.05  # 5% от дохода приглашенного
REFERRAL_LEVELS = 3  # Уровни реферальной системы
REFERRAL_PERCENTS = [0.05, 0.03, 0.01]  # Проценты для каждого уровня

# ========== НАСТРОЙКИ ПРОМОКОДОВ ==========
PROMOCODE_LENGTH = 8
PROMOCODE_TYPES = {
"money": "💰 Деньги","
""btc": "₿ Bitcoin","
""exp": "⭐ Опыт","
""level": "🏆 Уровень""
}

# ========== НАСТРОЙКИ ИГРЫ ==========
LEVEL_EXP_REQUIREMENTS = {1: 4, 2: 8, 3: 12, 4: 16, 5: 20}
LEVEL_BONUS = {1: 50000, 2: 75000, 3: 100000, 4: 125000, 5: 150000}

# ========== НАСТРОЙКИ ВИДЕОКАРТ ==========
GPU_TYPES = {
    "low": {
""name": "🎮 GeForce GTX 1650","
        "base_price": 150000,
        "price_increase": 1.2,
        "income_per_hour": 0.1,
        "max_quantity": 3
    },
    "medium": {
""name": "💻 GeForce RTX 4060","
        "base_price": 220000,
        "price_increase": 1.2,
        "income_per_hour": 0.4,
        "max_quantity": 3
    },
    "high": {
""name": "🚀 GeForce RTX 4090","
        "base_price": 350000,
        "price_increase": 1.3,
        "income_per_hour": 0.7,
        "max_quantity": 3
    }
}

# ========== РАБОТЫ ==========
JOBS = {
    "digger": {
""name": "⛏️ Кладоискатель","
""description": "Ищешь клады по всему миру","
        "min_salary": 10000,
        "max_salary": 50000,
        "btc_chance": 9
    },
    "hacker": {
""name": "💻 Хакер","
""description": "Взламываешь защищенные системы","
        "min_salary": 50000,
        "max_salary": 200000,
        "btc_chance": 9
    },
    "miner": {
""name": "🔨 Майнер","
""description": "Добываешь криптовалюту в шахтах","
        "min_salary": 30000,
        "max_salary": 100000,
        "btc_chance": 9
    },
    "trader": {
""name": "📈 Трейдер","
""description": "Торгуешь на бирже криптовалют","
        "min_salary": 100000,
        "max_salary": 1000000,
        "btc_chance": 9
    }
}

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== ДАТАКЛАССЫ ==========
@dataclass
class User:
    user_id: int
    username: str = ""
    balance: int = 10000
    bank: int = 0
    btc: float = 0.0
    level: int = 1
    exp: int = 0
    wins: int = 0
    loses: int = 0
    job: Optional[str] = None
    last_work: Optional[datetime.datetime] = None
    last_bonus: Optional[datetime.datetime] = None
    registered: datetime.datetime = datetime.datetime.now()
    last_daily_bonus: Optional[datetime.datetime] = None
    is_banned: bool = False
    referral_code: str = ""
    referred_by: Optional[int] = None
    total_referrals: int = 0
    referral_earnings: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "balance": self.balance,
            "bank": self.bank,
            "btc": self.btc,
            "level": self.level,
            "exp": self.exp,
            "wins": self.wins,
            "loses": self.loses,
            "job": self.job,
            "last_work": self.last_work.isoformat() if self.last_work else None,
            "last_bonus": self.last_bonus.isoformat() if self.last_bonus else None,
            "registered": self.registered.isoformat(),
            "last_daily_bonus": self.last_daily_bonus.isoformat() if self.last_daily_bonus else None,
            "is_banned": self.is_banned,
            "referral_code": self.referral_code,
            "referred_by": self.referred_by,
            "total_referrals": self.total_referrals,
            "referral_earnings": self.referral_earnings
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        user = cls(
            user_id=data["user_id"],
            username=data.get("username", ""),
            balance=data.get("balance", 10000),
            bank=data.get("bank", 0),
            btc=data.get("btc", 0.0),
            level=data.get("level", 1),
            exp=data.get("exp", 0),
            wins=data.get("wins", 0),
            loses=data.get("loses", 0),
            job=data.get("job"),
            is_banned=data.get("is_banned", False),
            referral_code=data.get("referral_code", ""),
            referred_by=data.get("referred_by"),
            total_referrals=data.get("total_referrals", 0),
            referral_earnings=data.get("referral_earnings", 0)
        )
        
        if data.get("last_work"):
            user.last_work = datetime.datetime.fromisoformat(data["last_work"])
        if data.get("last_bonus"):
            user.last_bonus = datetime.datetime.fromisoformat(data["last_bonus"])
        if data.get("registered"):
            user.registered = datetime.datetime.fromisoformat(data["registered"])
        if data.get("last_daily_bonus"):
            user.last_daily_bonus = datetime.datetime.fromisoformat(data["last_daily_bonus"])
        
        return user

@dataclass
class BTCFarm:
    user_id: int
    gpu_type: str
    quantity: int = 0
    last_collected: Optional[datetime.datetime] = None

@dataclass
class PromoCode:
    code: str
    promo_type: str
    value: float
    created_by: int
    created_at: datetime.datetime
    expires_at: Optional[datetime.datetime] = None
    max_uses: int = 1
    current_uses: int = 0
    is_active: bool = True

@dataclass
class PromoUse:
    id: int
    promo_code: str
    user_id: int
    used_at: datetime.datetime

# ========== БАЗА ДАННЫХ С ПОДДЕРЖКОЙ SUPABASE ==========
class Database:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool: Optional[asyncpg.Pool] = None
        self.is_supabase = connection_string and "supabase" in connection_string.lower()
    
    async def connect(self):
        """Создание подключения к базе данных (с поддержкой Supabase SSL)"""
        if not self.connection_string:
            logger.error("❌ DATABASE_URL не задан!")
"# Можно добавить fallback на локальное хранилище"
            return
        
        try:
"# Настройки SSL для Supabase"
            ssl_context = None
            if self.is_supabase:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                logger.info("🔒 Использую SSL для Supabase")
            
"# Создаем пул подключений с учетом ограничений Supabase Free"
            self.pool = await asyncpg.create_pool(
                dsn=self.connection_string,
                min_size=1,      # Минимум для бесплатного плана
                max_size=5,      # Supabase Free: максимум 5 соединений
                max_queries=50000,
                max_inactive_connection_lifetime=300,
                command_timeout=60,
                ssl=ssl_context if self.is_supabase else None,
                server_settings={
                    'application_name': 'vibe-bet-bot',
"'statement_timeout': '30000'  # 30 секунд таймаут"
                }
            )
            await self.init_db()
            logger.info(f"✅ База данных подключена (Supabase: {self.is_supabase})")
            
        except asyncpg.InvalidPasswordError as e:
            logger.error(f"❌ Неверный пароль для базы данных: {e}")
            raise
        except asyncpg.ConnectionDoesNotExistError as e:
            logger.error(f"❌ Неверная строка подключения: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД: {e}")
"# Можно добавить fallback механизм"
            raise
    
    async def init_db(self):
""""Инициализация таблиц для Supabase/PostgreSQL""""
        async with self.pool.acquire() as conn:
"# Для Supabase убедимся, что используем правильную схему"
            if self.is_supabase:
                await conn.execute('CREATE SCHEMA IF NOT EXISTS public')
                await conn.execute('SET search_path TO public')
            
"# Таблица пользователей"
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    balance BIGINT DEFAULT 10000,
                    bank BIGINT DEFAULT 0,
                    btc DOUBLE PRECISION DEFAULT 0.0,
                    level INTEGER DEFAULT 1,
                    exp INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    loses INTEGER DEFAULT 0,
                    job TEXT,
                    last_work TIMESTAMPTZ,
                    last_bonus TIMESTAMPTZ,
                    registered TIMESTAMPTZ DEFAULT NOW(),
                    last_daily_bonus TIMESTAMPTZ,
                    is_banned BOOLEAN DEFAULT FALSE,
                    referral_code TEXT UNIQUE,
                    referred_by BIGINT,
                    total_referrals INTEGER DEFAULT 0,
                    referral_earnings BIGINT DEFAULT 0
                )
            ''')
            
"# Таблица фермы BTC"
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS btc_farm (
                    user_id BIGINT,
                    gpu_type TEXT,
                    quantity INTEGER DEFAULT 0,
                    last_collected TIMESTAMPTZ,
                    PRIMARY KEY (user_id, gpu_type)
                )
            ''')
            
"# Таблица промокодов"
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    promo_type TEXT NOT NULL,
                    value DOUBLE PRECISION NOT NULL,
                    created_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ,
                    max_uses INTEGER DEFAULT 1,
                    current_uses INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            
"# Таблица использования промокодов"
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS promo_uses (
                    id BIGSERIAL PRIMARY KEY,
                    promo_code TEXT,
                    user_id BIGINT,
                    used_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            
"# Таблица реферальных выплат"
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referral_payments (
                    id BIGSERIAL PRIMARY KEY,
                    from_user_id BIGINT,
                    to_user_id BIGINT,
                    amount BIGINT,
                    percentage DOUBLE PRECISION,
                    level INTEGER,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            
"# Создаем индексы для производительности"
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)',
                'CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned)',
                'CREATE INDEX IF NOT EXISTS idx_users_ref_code ON users(referral_code)',
                'CREATE INDEX IF NOT EXISTS idx_promo_expires ON promo_codes(expires_at)',
                'CREATE INDEX IF NOT EXISTS idx_promo_active ON promo_codes(is_active)',
                'CREATE INDEX IF NOT EXISTS idx_referral_from ON referral_payments(from_user_id)',
                'CREATE INDEX IF NOT EXISTS idx_referral_to ON referral_payments(to_user_id)'
            ]
            
            for index_sql in indexes:
                try:
                    await conn.execute(index_sql)
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка создания индекса: {e}")
    
    @asynccontextmanager
    async def get_connection(self):
""""Контекстный менеджер для получения соединения""""
        if not self.pool:
            raise Exception("Пул соединений не инициализирован")
        
        async with self.pool.acquire() as conn:
            yield conn
    
    async def get_user(self, user_id: int) -> Optional[User]:
""""Получение пользователя из БД""""
        async with self.get_connection() as conn:
            row = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
            if row:
                return User.from_dict(dict(row))
            return None
    
    async def save_user(self, user: User):
""""Сохранение пользователя в БД""""
        async with self.get_connection() as conn:
            await conn.execute('''
                INSERT INTO users (
                    user_id, username, balance, bank, btc, level, exp, wins, loses,
                    job, last_work, last_bonus, registered, last_daily_bonus, is_banned,
                    referral_code, referred_by, total_referrals, referral_earnings
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    balance = EXCLUDED.balance,
                    bank = EXCLUDED.bank,
                    btc = EXCLUDED.btc,
                    level = EXCLUDED.level,
                    exp = EXCLUDED.exp,
                    wins = EXCLUDED.wins,
                    loses = EXCLUDED.loses,
                    job = EXCLUDED.job,
                    last_work = EXCLUDED.last_work,
                    last_bonus = EXCLUDED.last_bonus,
                    last_daily_bonus = EXCLUDED.last_daily_bonus,
                    is_banned = EXCLUDED.is_banned,
                    referral_code = EXCLUDED.referral_code,
                    referred_by = EXCLUDED.referred_by,
                    total_referrals = EXCLUDED.total_referrals,
                    referral_earnings = EXCLUDED.referral_earnings
            ''',
                user.user_id, user.username, user.balance, user.bank, user.btc,
                user.level, user.exp, user.wins, user.loses, user.job,
                user.last_work, user.last_bonus, user.registered,
                user.last_daily_bonus, user.is_banned, user.referral_code,
                user.referred_by, user.total_referrals, user.referral_earnings
            )
    
    async def get_user_by_ref_code(self, ref_code: str) -> Optional[User]:
""""Получение пользователя по реферальному коду""""
        async with self.get_connection() as conn:
            row = await conn.fetchrow('SELECT * FROM users WHERE referral_code = $1', ref_code)
            if row:
                return User.from_dict(dict(row))
            return None
    
    async def get_user_farm(self, user_id: int) -> List[BTCFarm]:
""""Получение фермы пользователя""""
        async with self.get_connection() as conn:
            rows = await conn.fetch('SELECT * FROM btc_farm WHERE user_id = $1', user_id)
            return [
                BTCFarm(
                    user_id=row['user_id'],
                    gpu_type=row['gpu_type'],
                    quantity=row['quantity'],
                    last_collected=row['last_collected']
                ) for row in rows
            ]
    
    async def update_farm(self, farm: BTCFarm):
""""Обновление фермы""""
        async with self.get_connection() as conn:
            await conn.execute('''
                INSERT INTO btc_farm (user_id, gpu_type, quantity, last_collected)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, gpu_type) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    last_collected = EXCLUDED.last_collected
            ''', farm.user_id, farm.gpu_type, farm.quantity, farm.last_collected)
    
    # ========== МЕТОДЫ ПРОМОКОДОВ ==========
    async def create_promo_code(self, promo: PromoCode) -> bool:
""""Создание промокода""""
        async with self.get_connection() as conn:
            try:
                await conn.execute('''
                    INSERT INTO promo_codes 
                    (code, promo_type, value, created_by, created_at, expires_at, max_uses, current_uses, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ''', 
                    promo.code, promo.promo_type, promo.value, promo.created_by,
                    promo.created_at, promo.expires_at, promo.max_uses,
                    promo.current_uses, promo.is_active
                )
                return True
            except Exception as e:
                logger.error(f"Ошибка создания промокода: {e}")
                return False
    
    async def get_promo_code(self, code: str) -> Optional[PromoCode]:
""""Получение промокода""""
        async with self.get_connection() as conn:
            row = await conn.fetchrow('SELECT * FROM promo_codes WHERE code = $1', code)
            if row:
                return PromoCode(
                    code=row['code'],
                    promo_type=row['promo_type'],
                    value=row['value'],
                    created_by=row['created_by'],
                    created_at=row['created_at'],
                    expires_at=row['expires_at'],
                    max_uses=row['max_uses'],
                    current_uses=row['current_uses'],
                    is_active=row['is_active']
                )
            return None
            
    async def use_promo_code(self, code: str, user_id: int):
""""Получение промокода""""
async def get_promo_code(self, code: str):
    async with self.get_connection() as conn:
        row = await conn.fetchrow(
            'SELECT * FROM promo_codes WHERE code = $1 AND is_active = true',
            code
        )
        if row:
            return PromoCode(
                code=row['code'],
                promo_type=row['promo_type'],
                value=row['value'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                max_uses=row['max_uses'],
                current_uses=row['current_uses'],
                is_active=row['is_active']
            )
        return None

async def use_promo_code(self, code: str, user_id: int):
""""Активация промокода""""
    try:
        async with self.get_connection() as conn:
"# 1. Проверяем существование и валидность промокода"
            promo = await self.get_promo_code(code)
            if not promo:
                return False, "✗️ Промокод не найден", {}
            
"# 2. Проверяем не истек ли срок"
            if promo.expires_at and promo.expires_at < datetime.now():
                return False, "✗️ Промокод истек", {}
            
"# 3. Проверяем лимит использований"
            if promo.current_uses >= promo.max_uses:
                return False, "✗️ Лимит использований исчерпан", {}
            
"# 4. Активируем промокод"
            await conn.execute(
                'UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = $1',
                code
            )
            
"# 5. Записываем использование"
            await conn.execute(
                '''INSERT INTO promo_uses (user_id, promo_code, used_at) 
                   VALUES ($1, $2, NOW())''',
                user_id, code
            )
            
            return True, "✔️ Промокод активирован!", {"value": promo.value}
    except Exception as e:
        return False, f"✗️ Ошибка: {str(e)}", {}

async def get_user_promo_uses(self, user_id: int):
""""Получение истории использования промокодов""""
    async with self.get_connection() as conn:
        rows = await conn.fetch(
            'SELECT * FROM promo_uses WHERE user_id = $1 ORDER BY used_at DESC',
            user_id
        )
        return [
            PromoUse(
                user_id=row['user_id'],
                promo_code=row['promo_code'],
                used_at=row['used_at']
            )
            for row in rows
        ]
        
# ========== МЕТОДЫ ПРОМОКОДОВ В КЛАССЕ DATABASE ==========
async def create_promo_code(self, promo: PromoCode) -> bool:
""""Создание промокода""""
    async with self.get_connection() as conn:
        try:
            await conn.execute('''
                INSERT INTO promo_codes 
                (code, promo_type, value, created_by, created_at, expires_at, max_uses, current_uses, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ''', 
                promo.code, promo.promo_type, promo.value, promo.created_by,
                promo.created_at, promo.expires_at, promo.max_uses,
                promo.current_uses, promo.is_active
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка создания промокода: {e}")
            return False

async def get_promo_code(self, code: str) -> Optional[PromoCode]:
""""Получение промокода""""
    async with self.get_connection() as conn:
        row = await conn.fetchrow('SELECT * FROM promo_codes WHERE code = $1', code)
        if row:
            return PromoCode(
                code=row['code'],
                promo_type=row['promo_type'],
                value=row['value'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                max_uses=row['max_uses'],
                current_uses=row['current_uses'],
                is_active=row['is_active']
            )
        return None

async def use_promo_code(self, code: str, user_id: int) -> Tuple[bool, str, Dict[str, Any]]:
""""Использование промокода - ИСПРАВЛЕННАЯ ВЕРСИЯ""""
    try:
        async with self.get_connection() as conn:
"# Проверяем, использовал ли уже пользователь этот промокод"
            used = await conn.fetchrow(
                'SELECT id FROM promo_uses WHERE promo_code = $1 AND user_id = $2',
                code, user_id
            )
            if used:
                return False, "❌ Вы уже использовали этот промокод!", {}
            
"# Получаем промокод"
            row = await conn.fetchrow('SELECT * FROM promo_codes WHERE code = $1', code)
            if not row:
                return False, "❌ Промокод не найден!", {}
            
"# Создаем объект PromoCode"
            promo = PromoCode(
                code=row['code'],
                promo_type=row['promo_type'],
                value=row['value'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                max_uses=row['max_uses'],
                current_uses=row['current_uses'],
                is_active=row['is_active']
            )
            
"# Проверяем активность промокода"
            if not promo.is_active:
                return False, "❌ Промокод неактивен!", {}
            
"# Проверяем срок действия"
            if promo.expires_at and promo.expires_at < datetime.datetime.now():
                return False, "❌ Срок действия промокода истек!", {}
            
"# Проверяем лимит использований"
            if promo.current_uses >= promo.max_uses:
                return False, "❌ Лимит использований промокода исчерпан!", {}
            
"# Обновляем счетчик использований"
            await conn.execute(
                'UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = $1',
                code
            )
            
"# Записываем использование"
            await conn.execute(
                'INSERT INTO promo_uses (promo_code, user_id, used_at) VALUES ($1, $2, $3)',
                code, user_id, datetime.datetime.now()
            )
            
"# Возвращаем данные для начисления бонуса"
            return True, "✅ Промокод успешно активирован!", {
                "type": promo.promo_type,
                "value": promo.value
            }
            
    except Exception as e:
        logger.error(f"Ошибка использования промокода: {e}")
        return False, f"❌ Ошибка при активации промокода: {str(e)}", {}

async def get_user_promo_uses(self, user_id: int) -> List[PromoUse]:
""""Получение истории использования промокодов пользователем""""
    async with self.get_connection() as conn:
        rows = await conn.fetch(
            'SELECT * FROM promo_uses WHERE user_id = $1 ORDER BY used_at DESC',
            user_id
        )
        return [
            PromoUse(
                id=row['id'],
                promo_code=row['promo_code'],
                user_id=row['user_id'],
                used_at=row['used_at']
            ) for row in rows
        ]

async def get_all_promo_codes(self) -> List[PromoCode]:
""""Получение всех промокодов""""
    async with self.get_connection() as conn:
        rows = await conn.fetch('SELECT * FROM promo_codes ORDER BY created_at DESC')
        return [
            PromoCode(
                code=row['code'],
                promo_type=row['promo_type'],
                value=row['value'],
                created_by=row['created_by'],
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                max_uses=row['max_uses'],
                current_uses=row['current_uses'],
                is_active=row['is_active']
            ) for row in rows
        ]

# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ДЛЯ ПРОМОКОДОВ ==========

async def promo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню промокодов""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    promo_text = f"""
"🎫 *ПРОМОКОДЫ*"

💰 Ваш баланс: *{format_number(user.balance)}*
₿ Ваш BTC: *{user.btc:.4f}*

"💎 *Типы промокодов:*"
"• 💰 Деньги - пополнение баланса"
"• ₿ Bitcoin - пополнение BTC баланса"
"• ⭐ Опыт - добавление опыта"
"• 🏆 Уровень - повышение уровня"

"🔍 *Как использовать:*"
1. Получите промокод (раздачи, ивенты, администрация)
2. Введите команду /promo [код]
"3. Или нажмите кнопку ниже и введите код"
"4. Один промокод можно использовать один раз"

"🎁 *Активные промоакции:*"
"- Стартовый бонус: 10,000"
- За каждого реферала: {format_number(REFERRAL_BONUS)}
- Ежедневный бонус: до {format_number(LEVEL_BONUS.get(5, 150000))}
"""
    
    keyboard = [
        [InlineKeyboardButton("🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton("📜 Мои промокоды", callback_data="my_promocodes")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🛠 Создать промокод", callback_data="create_promo_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        promo_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def activate_promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Активация промокода через callback""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
""🎫 *АКТИВАЦИЯ ПРОМОКОДА*\n\n""
""Введите промокод:\n""
""Например: `SUMMER2024` или `WELCOME100`\n\n""
        "Или нажмите /promo [код]",
        parse_mode=ParseMode.MARKDOWN
    )
    
"# Устанавливаем состояние ожидания промокода"
    context.user_data["awaiting_promo"] = True

async def activate_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Активация промокода через команду""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    if not context.args:
        await update.message.reply_text(
""🎫 *Использование:*\n""
            "`/promo [код]`\n\n"
""Пример: `/promo SUMMER2024`\n\n""
""Или используйте меню промокодов: /menu","
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    promo_code = context.args[0].upper().strip()
    await process_promo_code(update, context, promo_code)

async def process_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
""""Обработка промокода - ИСПРАВЛЕННАЯ ВЕРСИЯ""""
    if update.callback_query:
        user_id = update.callback_query.from_user.id
        is_callback = True
    else:
        user_id = update.effective_user.id
        is_callback = False
    
    user = await db.get_user(user_id)
    
    if not user:
        if is_callback:
            await update.callback_query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        else:
            await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Проверяем промокод"
    success, message, bonus_data = await db.use_promo_code(promo_code, user_id)
    
    if success:
"# Начисляем бонус"
        bonus_type = bonus_data["type"]
        bonus_value = bonus_data["value"]
        
        result_text = "🎉 *ПРОМОКОД АКТИВИРОВАН!*\n\n"
        
        if bonus_type == "money":
            user.balance += int(bonus_value)
            result_text += f"💰 Получено: *{format_number(bonus_value)}*\n"
            result_text += f"💳 Новый баланс: *{format_number(user.balance)}*"
        
        elif bonus_type == "btc":
            user.btc += bonus_value
            result_text += f"₿ Получено: *{bonus_value:.4f} BTC*\n"
            result_text += f"₿ Новый баланс BTC: *{user.btc:.4f}*"
        
        elif bonus_type == "exp":
            user.exp += int(bonus_value)
            result_text += f"⭐ Получено: *{bonus_value} опыта*\n"
            result_text += f"⭐ Новый опыт: *{user.exp}/{LEVEL_EXP_REQUIREMENTS.get(user.level, 4*user.level)}*"
            
"# Проверяем повышение уровня"
            exp_needed = LEVEL_EXP_REQUIREMENTS.get(user.level, 4 * user.level)
            if user.exp >= exp_needed:
                user.level += 1
                user.exp = 0
                result_text += f"\n\n🎉 *ПОВЫШЕНИЕ УРОВНЯ!*\nНовый уровень: *{user.level}*"
        
        elif bonus_type == "level":
            old_level = user.level
            user.level += int(bonus_value)
            result_text += f"🏆 Уровень повышен: *{old_level} → {user.level}*"
        
        await db.save_user(user)
        
    else:
        result_text = message
    
"# Создаем клавиатуру для возврата"
    keyboard = [[InlineKeyboardButton("🔙 В меню промокодов", callback_data="promo_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
"# Отправляем результат"
    if is_callback:
        await update.callback_query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
                )

    if len(promo_uses) > 10:
        history_text += f"\n... и еще {len(promo_uses) - 10} промокодов"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="promo_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        history_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def create_promo_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода (админ) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Деньги", callback_data="create_promo_money"),
         InlineKeyboardButton("₿ Bitcoin", callback_data="create_promo_btc")],
        [InlineKeyboardButton("⭐ Опыт", callback_data="create_promo_exp"),
         InlineKeyboardButton("🏆 Уровень", callback_data="create_promo_level")],
        [InlineKeyboardButton("🔙 Назад", callback_data="promo_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
""Выберите тип промокода:","
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def create_promo_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Выбор типа промокода для создания""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    promo_type = query.data.split("_")[2]  # create_promo_money -> money
    
"# Сохраняем тип промокода в контексте"
    context.user_data["create_promo_type"] = promo_type
    
    type_names = {
""money": "💰 Деньги","
""btc": "₿ Bitcoin","
""exp": "⭐ Опыт","
""level": "🏆 Уровень""
    }
    
    await query.edit_message_text(
"f"🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
        f"Тип: {type_names.get(promo_type, promo_type)}\n\n"
"f"Введите значение промокода:\n""
        f"• Для денег: сумма (например: 10000)\n"
        f"• Для BTC: количество (например: 0.01)\n"
        f"• Для опыта: количество опыта (например: 10)\n"
        f"• Для уровня: количество уровней (например: 1)",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data["admin_action"] = "create_promo_value"

async def process_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка создания промокода""""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора!")
        return
    
    action = context.user_data.get("admin_action")
    
    if action == "create_promo_value":
        try:
"# Получаем значение промокода"
            value_text = update.message.text.strip()
            
"# Преобразуем значение в нужный тип"
            promo_type = context.user_data.get("create_promo_type")
            
            if promo_type in ["money", "exp", "level"]:
                value = int(value_text)
            elif promo_type == "btc":
                value = float(value_text)
            else:
                await update.message.reply_text("❌ Неизвестный тип промокода!")
                return
            
"# Сохраняем значение"
            context.user_data["create_promo_value"] = value
            
"# Запрашиваем количество использований"
            await update.message.reply_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
                "Введите максимальное количество использований (1-1000):",
                parse_mode=ParseMode.MARKDOWN
            )
            
            context.user_data["admin_action"] = "create_promo_max_uses"
            
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "create_promo_max_uses":
        try:
            max_uses = int(update.message.text.strip())
            if max_uses < 1 or max_uses > 1000:
                await update.message.reply_text("❌ Введите число от 1 до 1000!")
                return
            
"# Сохраняем количество использований"
            context.user_data["create_promo_max_uses"] = max_uses
            
"# Запрашиваем срок действия"
            keyboard = [
                [InlineKeyboardButton("⏰ 1 час", callback_data="expire_1")],
                [InlineKeyboardButton("⏰ 24 часа", callback_data="expire_24")],
                [InlineKeyboardButton("⏰ 7 дней", callback_data="expire_168")],
                [InlineKeyboardButton("⏰ 30 дней", callback_data="expire_720")],
                [InlineKeyboardButton("♾️ Без срока", callback_data="expire_none")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
""Выберите срок действия промокода:","
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")

async def set_promo_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Установка срока действия промокода""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    expire_type = query.data.split("_")[1]  # expire_1, expire_24, etc
    
    if expire_type == "none":
        expires_at = None
    else:
        hours = int(expire_type)
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=hours)
    
"# Сохраняем срок действия"
    context.user_data["create_promo_expires"] = expires_at
    
"# Генерируем промокод"
    promo_code = generate_promo_code()
    
"# Создаем объект промокода"
    promo = PromoCode(
        code=promo_code,
        promo_type=context.user_data["create_promo_type"],
        value=context.user_data["create_promo_value"],
        created_by=user_id,
        created_at=datetime.datetime.now(),
        expires_at=expires_at,
        max_uses=context.user_data["create_promo_max_uses"],
        current_uses=0,
        is_active=True
    )
    
"# Сохраняем промокод в БД"
    success = await db.create_promo_code(promo)
    
    if success:
"# Формируем информацию о промокоде"
        type_names = {
""money": "💰 Деньги","
""btc": "₿ Bitcoin","
""exp": "⭐ Опыт","
""level": "🏆 Уровень""
        }
        
        expires_text = "Без срока" if not expires_at else expires_at.strftime('%d.%m.%Y %H:%M')
        
        result_text = f"""
"✅ *ПРОМОКОД СОЗДАН!*"

🎫 Код: `{promo_code}`
💎 Тип: {type_names.get(promo.promo_type, promo.promo_type)}
💰 Значение: {promo.value}
🔄 Использований: {promo.current_uses}/{promo.max_uses}
⏰ Срок действия: {expires_text}
📅 Создан: {promo.created_at.strftime('%d.%m.%Y %H:%M')}
async def my_promocodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""История использованных промокодов""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем историю промокодов"
    promo_uses = await db.get_user_promo_uses(user_id)
    
    if not promo_uses:
        await query.edit_message_text(
""📭 *ИСТОРИЯ ПРОМОКОДОВ*\n\n""
""Вы еще не использовали ни одного промокода.\n""
""Следите за обновлениями и участвуйте в ивентах!","
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    history_text = "📜 *ИСТОРИЯ ИСПОЛЬЗОВАННЫХ ПРОМОКОДОВ*\n\n"
    
    for i, promo_use in enumerate(promo_uses[:10], 1):  # Показываем последние 10
"# Получаем информацию о промокоде"
        promo_info = await db.get_promo_code(promo_use.promo_code)
        if promo_info:
            used_at = promo_use.used_at.strftime('%d.%m.%Y %H:%M')
            history_text += f"{i}. `{promo_use.promo_code}` - {PROMOCODE_TYPES.get(promo_info.promo_type, promo_info.promo_type)}\n"
            history_text += f"   🕒 {used_at}\n"
            if promo_info.promo_type == "money":
                history_text += f"   💰 Сумма: {format_number(promo_info.value)}\n"
            elif promo_info.promo_type == "btc":
                history_text += f"   ₿ BTC: {promo_info.value:.4f}\n"
            elif promo_info.promo_type == "exp":
                history_text += f"   ⭐ Опыт: {int(promo_info.value)}\n"
            history_text += "\n"
    
    if len(promo_uses) > 10:
        history_text += f"\n... и еще {len(promo_uses) - 10} промокодов"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="promo_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        history_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def create_promo_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода (админ) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Деньги", callback_data="create_promo_money"),
         InlineKeyboardButton("₿ Bitcoin", callback_data="create_promo_btc")],
        [InlineKeyboardButton("⭐ Опыт", callback_data="create_promo_exp"),
         InlineKeyboardButton("🏆 Уровень", callback_data="create_promo_level")],
        [InlineKeyboardButton("🔙 Назад", callback_data="promo_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
""Выберите тип промокода:","
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def create_promo_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Выбор типа промокода для создания""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    promo_type = query.data.split("_")[2]  # create_promo_money -> money
    
"# Сохраняем тип промокода в контексте"
    context.user_data["create_promo_type"] = promo_type
    
    type_names = {
""money": "💰 Деньги","
""btc": "₿ Bitcoin","
""exp": "⭐ Опыт","
""level": "🏆 Уровень""
    }
    
    await query.edit_message_text(
"f"🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
        f"Тип: {type_names.get(promo_type, promo_type)}\n\n"
"f"Введите значение промокода:\n""
        f"• Для денег: сумма (например: 10000)\n"
        f"• Для BTC: количество (например: 0.01)\n"
        f"• Для опыта: количество опыта (например: 10)\n"
        f"• Для уровня: количество уровней (например: 1)",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data["admin_action"] = "create_promo_value"

async def process_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка создания промокода""""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора!")
        return
    
    action = context.user_data.get("admin_action")
    
    if action == "create_promo_value":
        try:
"# Получаем значение промокода"
            value_text = update.message.text.strip()
            
"# Преобразуем значение в нужный тип"
            promo_type = context.user_data.get("create_promo_type")
            
            if promo_type in ["money", "exp", "level"]:
                value = int(value_text)
            elif promo_type == "btc":
                value = float(value_text)
            else:
                await update.message.reply_text("❌ Неизвестный тип промокода!")
                return
            
"# Сохраняем значение"
            context.user_data["create_promo_value"] = value
            
"# Запрашиваем количество использований"
            await update.message.reply_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
                "Введите максимальное количество использований (1-1000):",
                parse_mode=ParseMode.MARKDOWN
            )
            
            context.user_data["admin_action"] = "create_promo_max_uses"
            
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "create_promo_max_uses":
        try:
            max_uses = int(update.message.text.strip())
            if max_uses < 1 or max_uses > 1000:
                await update.message.reply_text("❌ Введите число от 1 до 1000!")
                return
            
"# Сохраняем количество использований"
            context.user_data["create_promo_max_uses"] = max_uses
            
"# Запрашиваем срок действия"
            keyboard = [
                [InlineKeyboardButton("⏰ 1 час", callback_data="expire_1")],
                [InlineKeyboardButton("⏰ 24 часа", callback_data="expire_24")],
                [InlineKeyboardButton("⏰ 7 дней", callback_data="expire_168")],
                [InlineKeyboardButton("⏰ 30 дней", callback_data="expire_720")],
                [InlineKeyboardButton("♾️ Без срока", callback_data="expire_none")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
""Выберите срок действия промокода:","
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")

async def set_promo_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Установка срока действия промокода""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    expire_type = query.data.split("_")[1]  # expire_1, expire_24, etc
    
    if expire_type == "none":
        expires_at = None
    else:
        hours = int(expire_type)
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=hours)
    
"# Сохраняем срок действия"
    context.user_data["create_promo_expires"] = expires_at
    
"# Генерируем промокод"
    promo_code = generate_promo_code()
    
"# Создаем объект промокода"
    promo = PromoCode(
        code=promo_code,
        promo_type=context.user_data["create_promo_type"],
        value=context.user_data["create_promo_value"],
        created_by=user_id,
        created_at=datetime.datetime.now(),
        expires_at=expires_at,
        max_uses=context.user_data["create_promo_max_uses"],
        current_uses=0,
        is_active=True
    )
    
"# Сохраняем промокод в БД"
    success = await db.create_promo_code(promo)
    
    if success:
"# Формируем информацию о промокоде"
        type_names = {
""money": "💰 Деньги","
""btc": "₿ Bitcoin","
""exp": "⭐ Опыт","
""level": "🏆 Уровень""
        }
        
        expires_text = "Без срока" if not expires_at else expires_at.strftime('%d.%m.%Y %H:%M')
        
        result_text = f"""
"✅ *ПРОМОКОД СОЗДАН!*"

🎫 Код: `{promo_code}`
💎 Тип: {type_names.get(promo.promo_type, promo.promo_type)}
💰 Значение: {promo.value}
🔄 Использований: {promo.current_uses}/{promo.max_uses}
⏰ Срок действия: {expires_text}
📅 Создан: {promo.created_at.strftime('%d.%m.%Y %H:%M')}

"📋 *Использование:*"
• Пользователь: `/promo {promo_code}`
"• В меню: "Активировать промокод""
"""
        
"# Очищаем данные контекста"
        context.user_data.pop("create_promo_type", None)
        context.user_data.pop("create_promo_value", None)
        context.user_data.pop("create_promo_max_uses", None)
        context.user_data.pop("create_promo_expires", None)
        context.user_data.pop("admin_action", None)
        
        keyboard = [[InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text(
""❌ Ошибка при создании промокода!\n""
""Попробуйте еще раз.","
            parse_mode=ParseMode.MARKDOWN
        )

# ========== ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ==========

async def handle_promo_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка текстовых сообщений для промокодов""""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
"# Обработка ввода промокода"
    if "awaiting_promo" in context.user_data:
        await process_promo_code(update, context, text.upper())
        context.user_data.pop("awaiting_promo", None)
        return
    
"# Обработка создания промокода"
    elif "admin_action" in context.user_data:
        action = context.user_data["admin_action"]
        if action in ["create_promo_value", "create_promo_max_uses"]:
            await process_create_promo(update, context)
        return
    
"# Команда /promo"
    elif text.lower().startswith("/promo"):
        parts = text.split()
        if len(parts) >= 2:
            promo_code = parts[1].upper()
            await process_promo_code(update, context, promo_code)
        else:
            await update.message.reply_text(
                "🎫 *Использование:* /promo [КОД]\n\n"
""Пример: `/promo WELCOME100`","
                parse_mode=ParseMode.MARKDOWN
            )
            
    # ========== МЕТОДЫ РЕФЕРАЛЬНОЙ СИСТЕМЫ ==========
    async def add_referral(self, referrer_id: int, referral_id: int):
""""Добавление реферала""""
        async with self.get_connection() as conn:
"# Обновляем счетчик рефералов у пригласившего"
            await conn.execute(
                'UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id = $1',
                referrer_id
            )
            
"# Начисляем бонус пригласившему"
            referrer = await self.get_user(referrer_id)
            if referrer:
                referrer.balance += REFERRAL_BONUS
                referrer.referral_earnings += REFERRAL_BONUS
                await self.save_user(referrer)
            
"# Обновляем поле referred_by у приглашенного"
            await conn.execute(
                'UPDATE users SET referred_by = $1 WHERE user_id = $2',
                referrer_id, referral_id
            )
    
    async def add_referral_payment(self, from_user_id: int, to_user_id: int, amount: int, percentage: float, level: int):
""""Добавление реферальной выплаты""""
        async with self.get_connection() as conn:
            await conn.execute('''
                INSERT INTO referral_payments (from_user_id, to_user_id, amount, percentage, level, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
            ''', from_user_id, to_user_id, amount, percentage, level, datetime.datetime.now())
            
"# Обновляем баланс получателя"
            await conn.execute(
                'UPDATE users SET balance = balance + $1, referral_earnings = referral_earnings + $1 WHERE user_id = $2',
                amount, to_user_id
            )
    
    async def get_referrals_tree(self, user_id: int, level: int = 1, max_level: int = 3) -> Dict[int, List[Dict]]:
""""Получение реферального дерева""""
        referrals = {}
        
        async def get_level_referrals(parent_id: int, current_level: int):
            if current_level > max_level:
                return
            
            async with self.get_connection() as conn:
                rows = await conn.fetch(
                    'SELECT user_id, username, level, balance, registered FROM users WHERE referred_by = $1',
                    parent_id
                )
                
                if rows:
                    referrals[current_level] = referrals.get(current_level, [])
                    for row in rows:
                        user_info = {
                            'user_id': row['user_id'],
                            'username': row['username'],
                            'level': row['level'],
                            'balance': row['balance'],
                            'registered': row['registered']
                        }
                        referrals[current_level].append(user_info)
                        await get_level_referrals(row['user_id'], current_level + 1)
        
        await get_level_referrals(user_id, 1)
        return referrals
    
    async def get_referral_stats(self, user_id: int) -> Dict[str, Any]:
""""Получение статистики по рефералам""""
        referrals_tree = await self.get_referrals_tree(user_id, 1, REFERRAL_LEVELS)
        
        total_referrals = 0
        referrals_by_level = {}
        
        for level, users in referrals_tree.items():
            referrals_by_level[level] = len(users)
            total_referrals += len(users)
        
        user = await self.get_user(user_id)
        
        return {
            'total_referrals': total_referrals,
            'referrals_by_level': referrals_by_level,
            'referral_earnings': user.referral_earnings if user else 0,
            'referral_code': user.referral_code if user else "",
        }
    
    async def get_all_users(self) -> List[User]:
""""Получение всех пользователей""""
        async with self.get_connection() as conn:
            rows = await conn.fetch('SELECT * FROM users ORDER BY registered DESC')
            return [User.from_dict(dict(row)) for row in rows]
    
    async def get_top_users(self, limit: int = 10) -> List[User]:
""""Получение топ пользователей по балансу""""
        async with self.get_connection() as conn:
            rows = await conn.fetch('''
                SELECT * FROM users 
                WHERE NOT is_banned 
                ORDER BY balance + bank DESC 
                LIMIT $1
            ''', limit)
            return [User.from_dict(dict(row)) for row in rows]
    
    async def delete_user(self, user_id: int):
""""Удаление пользователя""""
        async with self.get_connection() as conn:
            await conn.execute('DELETE FROM users WHERE user_id = $1', user_id)
            await conn.execute('DELETE FROM btc_farm WHERE user_id = $1', user_id)
            await conn.execute('DELETE FROM promo_uses WHERE user_id = $1', user_id)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
db = Database(DATABASE_URL) if DATABASE_URL else None
btc_price = random.randint(10000, 150000)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_number(num: float) -> str:
""""Форматирование чисел в удобный вид""""
    if num >= 1_000_000_000_000:
        return f"{num/1_000_000_000_000:.2f}тккк"
    elif num >= 1_000_000_000:
        return f"{num/1_000_000_000:.2f}ккк"
    elif num >= 1_000_000:
        return f"{num/1_000_000:.2f}кк"
    elif num >= 1_000:
        return f"{num/1_000:.2f}к"
    else:
        return str(int(num))

def generate_referral_code() -> str:
""""Генерация реферального кода""""
    characters = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(6))

def generate_promo_code() -> str:
""""Генерация промокода""""
    characters = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(PROMOCODE_LENGTH))

async def calculate_gpu_income(user_id: int) -> float:
""""Расчет дохода с фермы BTC""""
    if not db:
        return 0.0
    
    farm_items = await db.get_user_farm(user_id)
    if not farm_items:
        return 0.0
    
    total_income = 0.0
    
    for farm in farm_items:
        if farm.gpu_type in GPU_TYPES:
            total_income += GPU_TYPES[farm.gpu_type]["income_per_hour"] * farm.quantity
    
"# Ищем последний сбор"
    last_collected = None
    for farm in farm_items:
        if farm.last_collected:
            if last_collected is None or farm.last_collected > last_collected:
                last_collected = farm.last_collected
    
    if last_collected:
        time_passed = datetime.datetime.now() - last_collected
        hours_passed = time_passed.total_seconds() / 3600
        return total_income * hours_passed
    
    return 0.0

def add_exp(user: User) -> bool:
""""Добавление опыта и проверка повышения уровня""""
    if random.random() < 0.5:
        user.exp += 1
        exp_needed = LEVEL_EXP_REQUIREMENTS.get(user.level, 4 * user.level)
        if user.exp >= exp_needed:
            user.level += 1
            user.exp = 0
            return True
    return False

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
""""Проверка подписки на канал и чат""""
    try:
        channel_member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME, 
            user_id=user_id
        )
        
        chat_member = await context.bot.get_chat_member(
            chat_id=CHAT_USERNAME,
            user_id=user_id
        )
        
        return (channel_member.status in ["member", "administrator", "creator"] and
                chat_member.status in ["member", "administrator", "creator"])
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

async def check_ban(user_id: int) -> bool:
""""Проверка забанен ли пользователь""""
    if not db:
        return False
    
    user = await db.get_user(user_id)
    return user.is_banned if user else False

async def distribute_referral_bonus(user_id: int, amount: int, context: ContextTypes.DEFAULT_TYPE):
""""Распределение реферального бонуса по уровням""""
    if not db or amount <= 0:
        return
    
    current_user_id = user_id
    level = 1
    
    while level <= REFERRAL_LEVELS and current_user_id:
        user = await db.get_user(current_user_id)
        if not user or not user.referred_by:
            break
        
        referrer_id = user.referred_by
        referrer = await db.get_user(referrer_id)
        if not referrer:
            break
        
"# Начисляем процент от выигрыша"
        bonus_percent = REFERRAL_PERCENTS[level - 1]
        bonus_amount = int(amount * bonus_percent)
        
        if bonus_amount > 0:
            referrer.balance += bonus_amount
            referrer.referral_earnings += bonus_amount
            await db.save_user(referrer)
            
"# Записываем выплату"
            await db.add_referral_payment(user_id, referrer_id, bonus_amount, bonus_percent, level)
            
            try:
"# Уведомляем реферера"
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"""
"💰 *Реферальный доход!*"

👤 От: {user.username or f'ID: {user_id}'}
📈 Уровень: {level}
💸 Сумма: {format_number(amount)}
🎯 Ваш процент: {bonus_percent*100}%
💰 Ваш доход: {format_number(bonus_amount)}
💳 Баланс: {format_number(referrer.balance)}
""",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления рефереру: {e}")
        
        current_user_id = referrer_id
        level += 1
"# БЛОК 2/6: Основные команды и меню с промокодами и реферальной системой"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработчик команды /start""""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
"# Проверяем, есть ли реферальный параметр в команде"
    ref_code = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref"):
            ref_code = arg[3:]  # Убираем "ref" из начала
    
"# Проверка бана"
    if await check_ban(user_id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте!")
        return
    
    welcome_text = """
"🎰 *Добро Пожаловать в Vibe Bet!*"
"Крути рулетку, рискуй в Краше, а также собирай свою ферму."

"🎲 *Игры:* 🎲 Кости, ⚽ Футбол, 🎰 Рулетка, 💎 Алмазы, 💣 Мины, 📈 Краш, 🃏 Очко"
"⛏️ *Заработок:* 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус"
"📊 *Системы:* 👥 Рефералы, 🎫 Промокоды, 🏦 Банк"
"""
    
    try:
        photo_url = "https://raw.githubusercontent.com/ваш-username/репозиторий/main/start_img.jpg"
        await update.message.reply_photo(
            photo=photo_url,
            caption=welcome_text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {e}")
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
    
"# Проверяем, зарегистрирован ли пользователь"
    user = await db.get_user(user_id)
    
    if not user:
        if ref_code:
"# Сохраняем реферальный код в контексте"
            context.user_data["referral_code"] = ref_code
        
        keyboard = [[InlineKeyboardButton("📝 Зарегистрироваться", callback_data="register")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
""📝 Для начала игры необходимо зарегистрироваться!\n\n""
            f"🔗 Реферальная ссылка: `https://t.me/{(await context.bot.get_me()).username}?start=refYOURCODE`",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await show_main_menu(update, context)

async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработчик регистрации""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    username = query.from_user.username
    
"# Проверяем, зарегистрирован ли уже"
    user = await db.get_user(user_id)
    if user:
        await query.edit_message_text("✅ Вы уже зарегистрированы!")
        return
    
"# Проверка подписки"
    if not await check_subscription(user_id, context):
        keyboard = [
            [InlineKeyboardButton("✅ Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ Подписаться на чат", url=f"https://t.me/{CHAT_USERNAME[1:]}")],
            [InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
""📢 Для регистрации необходимо подписаться на наш канал и чат!\n\n""
            f"Канал: {CHANNEL_USERNAME}\n"
            f"Чат: {CHAT_USERNAME}",
            reply_markup=reply_markup
        )
        return
    
"# Создаем нового пользователя"
    new_user = User(user_id=user_id, username=username)
    
"# Генерируем реферальный код"
    new_user.referral_code = generate_referral_code()
    
"# Проверяем реферальный код из контекста"
    ref_code = context.user_data.get("referral_code")
    if ref_code:
        referrer = await db.get_user_by_ref_code(ref_code)
        if referrer and referrer.user_id != user_id:
            new_user.referred_by = referrer.user_id
    
"# Сохраняем пользователя"
    await db.save_user(new_user)
    
"# Если есть реферер, добавляем реферала"
    if new_user.referred_by:
        await db.add_referral(new_user.referred_by, user_id)
        
"# Отправляем уведомление рефереру"
        try:
            await context.bot.send_message(
                chat_id=new_user.referred_by,
                text=f"""
"🎉 *НОВЫЙ РЕФЕРАЛ!*"

👤 Новый пользователь: @{username if username else 'без username'}
🆔 ID: `{user_id}`
💰 Ваш бонус: {format_number(REFERRAL_BONUS)}
👥 Всего рефералов: {referrer.total_referrals + 1 if referrer else 1}
""",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления рефереру: {e}")
    
    welcome_bonus = 10000
    ref_bonus = REFERRAL_BONUS if new_user.referred_by else 0
    
    await query.edit_message_text(
        f"""
"🎉 *РЕГИСТРАЦИЯ УСПЕШНА!*"

"👤 Ваш профиль создан!"
💰 Стартовый баланс: {format_number(welcome_bonus)}
{f'🎁 Реферальный бонус: {format_number(ref_bonus)}' if new_user.referred_by else ''}
🔗 Ваш реферальный код: `{new_user.referral_code}`
📢 Реферальная ссылка: `https://t.me/{(await context.bot.get_me()).username}?start=ref{new_user.referral_code}`

"💎 *Доступные команды:*"
"/start - Начать"
"/menu - Главное меню"
"/profile - Профиль"
"/bonus - Ежедневный бонус"
"/work - Работать"
"/ref - Реферальная система"
"/promo - Активировать промокод"
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Проверка подписки""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if await check_subscription(user_id, context):
        await register_callback(update, context)
    else:
        await query.answer("❌ Вы еще не подписались на канал и чат!", show_alert=True)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать главное меню""""
    user_id = update.effective_user.id
    
    user = await db.get_user(user_id)
    if not user:
        if update.callback_query:
            await update.callback_query.answer("Сначала зарегистрируйтесь!", show_alert=True)
            return
        else:
            await update.message.reply_text("❌ Сначала зарегистрируйтесь через /start")
            return
    
"# Проверка бана"
    if user.is_banned:
        await update.message.reply_text("❌ Вы заблокированы в этом боте!")
        return
    
    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
         InlineKeyboardButton("🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton("💰 Банк", callback_data="bank_menu"),
         InlineKeyboardButton("⛏️ Работа", callback_data="jobs_menu")],
        [InlineKeyboardButton("🖥 Ферма BTC", callback_data="farm_menu"),
         InlineKeyboardButton("🎁 Бонус", callback_data="bonus_menu")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="referral_menu"),
         InlineKeyboardButton("🎫 Промокоды", callback_data="promo_menu")],
        [InlineKeyboardButton("📊 Биржа BTC", callback_data="btc_market")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
""🏠 *Главное меню Vibe Bet*\n\n""
            f"💰 Баланс: *{format_number(user.balance)}*\n"
            f"🏦 В банке: *{format_number(user.bank)}*\n"
            f"₿ BTC: *{user.btc:.4f}*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
""🏠 *Главное меню Vibe Bet*\n\n""
            f"💰 Баланс: *{format_number(user.balance)}*\n"
            f"🏦 В банке: *{format_number(user.bank)}*\n"
            f"₿ BTC: *{user.btc:.4f}*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать профиль пользователя""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Расчет общего выигрыша"
    total_won = user.balance + user.bank - 10000 + user.referral_earnings
    
"# Получаем статистику рефералов"
    ref_stats = await db.get_referral_stats(user_id)
    
    profile_text = f"""
"👤 *ПРОФИЛЬ ИГРОКА*"

🆔 ID: `{user.user_id}`
👤 Имя: @{user.username if user.username else "Нет username"}
📅 Регистрация: {user.registered.strftime('%d.%m.%Y')}

💰 Баланс: *{format_number(user.balance)}*
🏦 Банк: *{format_number(user.bank)}*
₿ BTC: *{user.btc:.4f}*

🏆 Уровень: *{user.level}*
⭐ EXP: *{user.exp}/{LEVEL_EXP_REQUIREMENTS.get(user.level, 4*user.level)}*
🎯 Побед: *{user.wins}*
💔 Поражений: *{user.loses}*

👥 Рефералы: *{ref_stats['total_referrals']}*
💰 Реф. доход: *{format_number(user.referral_earnings)}*
🔗 Код: `{user.referral_code}`

📈 Общий выигрыш: *{format_number(total_won)}*
"""
    
    keyboard = [
        [InlineKeyboardButton("📊 Подробная статистика", callback_data="stats_detailed")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        profile_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_stats_detailed(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Подробная статистика""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем дерево рефералов"
    referrals_tree = await db.get_referrals_tree(user_id, 1, REFERRAL_LEVELS)
    
    ref_details = ""
    for level, users in referrals_tree.items():
        ref_details += f"\n📊 *Уровень {level}:* {len(users)} чел."
        if users:
            total_level_balance = sum(u['balance'] for u in users)
            ref_details += f" (общий баланс: {format_number(total_level_balance)})"
    
"# Статистика по играм"
    total_games = user.wins + user.loses
    win_rate = (user.wins / total_games * 100) if total_games > 0 else 0
    
    detailed_text = f"""
"📊 *ДЕТАЛЬНАЯ СТАТИСТИКА*"

"🎮 *Игровая статистика:*"
🔄 Всего игр: *{total_games}*
✅ Побед: *{user.wins}*
❌ Поражений: *{user.loses}*
📈 Винрейт: *{win_rate:.1f}%*

"👥 *Реферальная система:*"
🔗 Ваш код: `{user.referral_code}`
👥 Всего рефералов: *{user.total_referrals}*
💰 Заработано: *{format_number(user.referral_earnings)}*
{ref_details}

"💎 *Достижения:*"
🏆 Уровень: *{user.level}*
⭐ Опыт: *{user.exp}*
📅 Играет: *{(datetime.datetime.now() - user.registered).days} дней*
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="profile")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        detailed_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def bonus_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню бонусов""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    current_time = datetime.datetime.now()
    can_claim = True
    time_left = ""
    
    if user.last_bonus:
        time_since = current_time - user.last_bonus
        if time_since.total_seconds() < 86400:  # 24 часа
            can_claim = False
            hours_left = 24 - int(time_since.total_seconds() / 3600)
            minutes_left = int((86400 - time_since.total_seconds()) / 60) % 60
            time_left = f"{hours_left}ч {minutes_left}м"
    
    bonus_amount = LEVEL_BONUS.get(user.level, 50000 + (user.level - 1) * 25000)
    
    keyboard = []
    if can_claim:
        keyboard.append([InlineKeyboardButton("🎁 Получить бонус", callback_data="claim_bonus")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    bonus_text = f"""
"🎁 *ЕЖЕДНЕВНЫЙ БОНУС*"

{f'⏳ Доступно через: *{time_left}*' if not can_claim else '✅ Бонус доступен для получения!'}

🏆 Ваш уровень: *{user.level}*
💰 Размер бонуса: *{format_number(bonus_amount)}*
💰 Текущий баланс: *{format_number(user.balance)}*

"📊 Бонус за уровни:"
"1️⃣ Уровень: 50,000"
"2️⃣ Уровень: 75,000"
"3️⃣ Уровень: 100,000"
"4️⃣ Уровень: 125,000"
"5️⃣ Уровень: 150,000"
{f'6️⃣+ Уровень: {format_number(bonus_amount)}' if user.level > 5 else ''}
"""
    
    await query.edit_message_text(
        bonus_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def claim_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Получить ежедневный бонус""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    current_time = datetime.datetime.now()
    
"# Проверяем, можно ли получить бонус"
    if user.last_bonus:
        time_since = current_time - user.last_bonus
        if time_since.total_seconds() < 86400:
            await query.answer("❌ Бонус можно получать раз в 24 часа!", show_alert=True)
            return
    
    bonus_amount = LEVEL_BONUS.get(user.level, 50000 + (user.level - 1) * 25000)
    
"# Начисляем бонус"
    user.balance += bonus_amount
    user.last_bonus = current_time
    
"# Добавляем опыт"
    level_up = add_exp(user)
    
    await db.save_user(user)
    
    result_text = f"""
"🎁 *БОНУС ПОЛУЧЕН!*"

💰 Сумма: *{format_number(bonus_amount)}*
💳 Новый баланс: *{format_number(user.balance)}*
🏆 Уровень: {user.level}
⭐ Опыт: {user.exp}/{LEVEL_EXP_REQUIREMENTS.get(user.level, 4*user.level)}

"⏳ Следующий бонус через 24 часа"
"""
    
    if level_up:
        result_text += f"\n🎉 *ПОЗДРАВЛЯЕМ!*\nВы достигли {user.level} уровня!"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="bonus_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню реферальной системы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем статистику рефералов"
    ref_stats = await db.get_referral_stats(user_id)
    
"# Формируем текст с информацией о рефералах по уровням"
    ref_details = ""
    if ref_stats['referrals_by_level']:
        for level, count in ref_stats['referrals_by_level'].items():
            percent = REFERRAL_PERCENTS[level-1] * 100
            ref_details += f"\n📊 *Уровень {level}:* {count} чел. ({percent}% от их доходов)"
    
    referral_text = f"""
"👥 *РЕФЕРАЛЬНАЯ СИСТЕМА*"

"🔗 Ваш реферальный код:"
`{user.referral_code}`

"📎 Ваша реферальная ссылка:"
`https://t.me/{(await context.bot.get_me()).username}?start=ref{user.referral_code}`

💰 Бонус за приглашение: *{format_number(REFERRAL_BONUS)}*
👥 Всего приглашено: *{ref_stats['total_referrals']}*
💸 Заработано на рефералах: *{format_number(ref_stats['referral_earnings'])}*

"📈 *Процент от доходов рефералов:*"
1-й уровень (прямые): 5%
"2-й уровень: 3%"
"3-й уровень: 1%"
{ref_details}

"💡 *Как приглашать:*"
"1. Отправьте свою ссылку другу"
"2. Он должен нажать на ссылку и зарегистрироваться"
3. Вы получите {format_number(REFERRAL_BONUS)} сразу
"4. Вы получаете % от всех его выигрышей!"
"""
    
    keyboard = [
        [InlineKeyboardButton("📊 Мои рефералы", callback_data="my_referrals")],
        [InlineKeyboardButton("💸 Реф. выплаты", callback_data="ref_payments")],
        [InlineKeyboardButton("🔗 Скопировать ссылку", callback_data="copy_ref_link")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        referral_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Мои рефералы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем дерево рефералов"
    referrals_tree = await db.get_referrals_tree(user_id, 1, REFERRAL_LEVELS)
    
    if not referrals_tree:
        await query.edit_message_text(
""📭 У вас еще нет рефералов.\n""
""Приглашайте друзей по своей реферальной ссылке!","
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    referrals_text = "👥 *ВАШИ РЕФЕРАЛЫ*\n\n"
    
    for level, users in referrals_tree.items():
        if users:
            referrals_text += f"📊 *Уровень {level}* ({len(users)} чел.):\n"
            
            for i, ref in enumerate(users[:10], 1):  # Показываем первые 10
                username = f"@{ref['username']}" if ref['username'] else f"ID: {ref['user_id']}"
                reg_date = ref['registered'].strftime('%d.%m.%Y')
                referrals_text += f"{i}. {username} | Ур. {ref['level']} | Баланс: {format_number(ref['balance'])} | {reg_date}\n"
            
            if len(users) > 10:
                referrals_text += f"... и еще {len(users) - 10} рефералов\n"
            
            referrals_text += "\n"
    
"# Подсчет общей статистики"
    total_refs = sum(len(users) for users in referrals_tree.values())
    total_balance = sum(ref['balance'] for level_users in referrals_tree.values() for ref in level_users)
    
    referrals_text += f"""
"📈 *ОБЩАЯ СТАТИСТИКА:*"
👥 Всего рефералов: {total_refs}
💰 Общий баланс рефералов: {format_number(total_balance)}
💸 Ваш процент: {REFERRAL_PERCENTS[0]*100}% от 1 ур., {REFERRAL_PERCENTS[1]*100}% от 2 ур., {REFERRAL_PERCENTS[2]*100}% от 3 ур.
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="referral_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        referrals_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def copy_ref_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Копирование реферальной ссылки""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.answer("❌ Сначала зарегистрируйтесь!", show_alert=True)
        return
    
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user.referral_code}"
    
"# В реальном боте можно использовать метод copy_text, но для простоты покажем ссылку"
    await query.edit_message_text(
"f"🔗 *ВАША РЕФЕРАЛЬНАЯ ССЫЛКА*\n\n""
        f"`{ref_link}`\n\n"
"f"📋 *Код для копирования:*\n""
        f"`{user.referral_code}`\n\n"
"f"Отправьте эту ссылку друзьям, чтобы получать бонусы!","
        parse_mode=ParseMode.MARKDOWN
    )

async def promo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню промокодов""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    promo_text = f"""
"🎫 *ПРОМОКОДЫ*"

💰 Ваш баланс: {format_number(user.balance)}
₿ Ваш BTC: {user.btc:.4f}

"💎 *Типы промокодов:*"
"💰 Деньги - пополнение баланса"
"₿ Bitcoin - пополнение BTC баланса"
"⭐ Опыт - добавление опыта"
"🏆 Уровень - повышение уровня"

"🔍 *Как использовать:*"
1. Получите промокод (раздачи, ивенты, администрация)
2. Введите команду /promo [код]
"3. Или нажмите кнопку ниже и введите код"

"🎁 *Активные промоакции:*"
"- При регистрации: 10,000"
- За каждого реферала: {format_number(REFERRAL_BONUS)}
- Ежедневный бонус: до {format_number(LEVEL_BONUS.get(5, 150000))}
"""
    
    keyboard = [
        [InlineKeyboardButton("🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton("📜 Мои промокоды", callback_data="my_promocodes")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🛠 Создать промокод", callback_data="create_promo_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        promo_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def activate_promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Активация промокода через callback""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
""🎫 *АКТИВАЦИЯ ПРОМОКОДА*\n\n""
""Введите промокод:\n""
""Например: `SUMMER2024` или `WELCOME100`","
        parse_mode=ParseMode.MARKDOWN
    )
    
"# Устанавливаем состояние ожидания промокода"
    context.user_data["awaiting_promo"] = True

async def activate_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Активация промокода через команду""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    if not context.args:
        await update.message.reply_text(
""🎫 *Использование:*\n""
            "`/promo [код]`\n\n"
""Пример: `/promo SUMMER2024`","
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    promo_code = context.args[0].upper()
    await process_promo_code(update, context, promo_code)

async def process_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
""""Обработка промокода""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        if update.message:
            await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Проверяем промокод"
    success, message, bonus_data = await db.use_promo_code(promo_code, user_id)
    
    if success:
"# Начисляем бонус"
        bonus_type = bonus_data["type"]
        bonus_value = bonus_data["value"]
        
        result_text = f"🎉 *ПРОМОКОД АКТИВИРОВАН!*\n\n"
        
        if bonus_type == "money":
            user.balance += int(bonus_value)
            result_text += f"💰 Получено: *{format_number(bonus_value)}*\n"
            result_text += f"💳 Новый баланс: *{format_number(user.balance)}*"
        
        elif bonus_type == "btc":
            user.btc += bonus_value
            result_text += f"₿ Получено: *{bonus_value:.4f} BTC*\n"
            result_text += f"₿ Новый баланс BTC: *{user.btc:.4f}*"
        
        elif bonus_type == "exp":
            user.exp += int(bonus_value)
            result_text += f"⭐ Получено: *{bonus_value} опыта*\n"
            result_text += f"⭐ Новый опыт: *{user.exp}/{LEVEL_EXP_REQUIREMENTS.get(user.level, 4*user.level)}*"
            
"# Проверяем повышение уровня"
            exp_needed = LEVEL_EXP_REQUIREMENTS.get(user.level, 4 * user.level)
            if user.exp >= exp_needed:
                user.level += 1
                user.exp = 0
                result_text += f"\n\n🎉 *ПОВЫШЕНИЕ УРОВНЯ!*\nНовый уровень: *{user.level}*"
        
        elif bonus_type == "level":
            old_level = user.level
            user.level += int(bonus_value)
            result_text += f"🏆 Уровень повышен: *{old_level} → {user.level}*"
        
        await db.save_user(user)
        
    else:
        result_text = message
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            result_text,
            parse_mode=ParseMode.MARKDOWN
        )
    elif update.message:
        await update.message.reply_text(
            result_text,
            parse_mode=ParseMode.MARKDOWN
        )

async def my_promocodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""История использованных промокодов""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем историю промокодов"
    promo_uses = await db.get_user_promo_uses(user_id)
    
    if not promo_uses:
        await query.edit_message_text(
""📭 *ИСТОРИЯ ПРОМОКОДОВ*\n\n""
""Вы еще не использовали ни одного промокода.\n""
""Следите за обновлениями и участвуйте в ивентах!","
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    history_text = "📜 *ИСТОРИЯ ИСПОЛЬЗОВАННЫХ ПРОМОКОДОВ*\n\n"
    
    for i, promo_use in enumerate(promo_uses[:10], 1):  # Показываем последние 10
        promo_info = await db.get_promo_code(promo_use.promo_code)
        if promo_info:
            used_at = promo_use.used_at.strftime('%d.%m.%Y %H:%M')
            history_text += f"{i}. `{promo_use.promo_code}` - {PROMOCODE_TYPES.get(promo_info.promo_type, promo_info.promo_type)}\n"
            history_text += f"   🕒 {used_at}\n"
    
    if len(promo_uses) > 10:
        history_text += f"\n... и еще {len(promo_uses) - 10} промокодов"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="promo_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        history_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def create_promo_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода (админ)"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Деньги", callback_data="create_promo_money"),
         InlineKeyboardButton("₿ Bitcoin", callback_data="create_promo_btc")],
        [InlineKeyboardButton("⭐ Опыт", callback_data="create_promo_exp"),
         InlineKeyboardButton("🏆 Уровень", callback_data="create_promo_level")],
        [InlineKeyboardButton("🔙 Назад", callback_data="promo_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
""🛠 *СОЗДАНИЕ ПРОМОКОДА*\n\n""
""Выберите тип промокода:","
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
)
"# БЛОК 3/6: Игры и основной игровой функционал"

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать помощь по всем командам бота""""
    user_id = update.effective_user.id
    
    help_text = """
"🎮 *VIBE BET - ПОЛНЫЙ ГАЙД ПО КОМАНДАМ И ВОЗМОЖНОСТЯМ* 🎮"

"📋 *ОСНОВНЫЕ КОМАНДЫ:*"
"/start - Начать работу с ботом, регистрация"
"/menu - Главное меню со всеми функциями"
"/profile - Показать ваш профиль и статистику"
"/help - Показать это сообщение помощи"

"💰 *ЭКОНОМИКА И БАЛАНС:*"
"/balance - Показать текущий баланс"
"/bank - Управление банковским счетом"
/transfer [сумма] [ID] - Перевести деньги другому игроку
"/top - Показать топ-10 игроков по балансу"

"🎁 *БОНУСЫ И НАГРАДЫ:*"
/bonus - Получить ежедневный бонус (доступен раз в 24 часа)
"/work - Выполнить работу для заработка денег"
"/jobs - Выбрать профессию для работы"

"👥 *РЕФЕРАЛЬНАЯ СИСТЕМА:*"
"/ref - Показать реферальное меню"
"/reflink - Получить вашу реферальную ссылку"
"/myreferrals - Показать ваших рефералов"
"/referrals - Статистика по реферальной системе"

"🎫 *ПРОМОКОДЫ И АКЦИИ:*"
/promo [код] - Активировать промокод
"/mypromos - История использованных промокодов"
"/events - Активные ивенты и акции"

"🖥 *ФЕРМА BTC И ИНВЕСТИЦИИ:*"
"/farm - Управление фермой BTC"
"/buygpu - Купить видеокарту для майнинга"
"/collect - Собрать накопленный BTC с фермы"
/market - Биржа BTC (покупка/продажа)

"🏦 *БАНКОВСКАЯ СИСТЕМА:*"
/deposit [сумма] - Положить деньги в банк
/withdraw [сумма] - Снять деньги с банка
"/bankinfo - Информация о банковском счете"

"🎮 *ИГРЫ И РАЗВЛЕЧЕНИЯ:*"
"/games - Показать все доступные игры"
"/roulette - Игра в рулетку"
/football - Футбол (угадать гол/мимо)
/dice - Кости (угадать сумму)
/crash - Игра Краш (вывести до взрыва)
/mines - Мины (найти все мины)
/diamonds - Алмазы (найти алмазы)
/blackjack - Очко (21, блекджек)

"📊 *СТАТИСТИКА И РЕЙТИНГИ:*"
"/stats - Подробная статистика"
"/mystats - Ваша игровая статистика"
"/topgames - Топ игроков по победам"
"/topref - Топ игроков по рефералам"

👑 *АДМИН-КОМАНДЫ (для администраторов):*
"/admin - Админ панель"
/addmoney [ID] [сумма] - Выдать деньги игроку
/addbtc [ID] [сумма] - Выдать BTC игроку
/ban [ID] [причина] - Забанить игрока
/unban [ID] - Разбанить игрока
/createpromo [тип] [значение] [код] - Создать промокод

"🔧 *ТЕХНИЧЕСКИЕ КОМАНДЫ:*"
"/terms - Правила использования бота"
"/support - Связь с поддержкой"
"/rules - Правила игр и ставок"
"/about - О боте и разработчиках"

"📈 *СИСТЕМА УРОВНЕЙ И ОПЫТА:*"
"- Уровень повышается при получении опыта"
"- Опыт дается за игры и выигрыши"
"- Каждый уровень увеличивает ежедневный бонус"
"- Максимальный уровень: нет предела!"

"💰 *КАК ЗАРАБАТЫВАТЬ:*"
"1. 🎮 Игры с реальными ставками"
2. 👷 Работа (выберите профессию в /jobs)
3. 🖥 Ферма BTC (покупайте видеокарты)
4. 👥 Рефералы (приглашайте друзей)
"5. 🎁 Ежедневный бонус и промокоды"

"⚠️ *ВАЖНЫЕ ПРАВИЛА:*"
"- Минимальная ставка в играх: 100"
"- Минимальный вывод: 1000"
"- Администрация оставляет право изменять правила"
"- Запрещены мультиаккаунты и накрутки"

"📱 *КОНТАКТЫ И ПОДДЕРЖКА:*"
"Канал: @nvibee_bet"
"Чат: @chatvibee_bet"
"Поддержка: @vibee_support"

"📅 *ОБНОВЛЕНИЯ И ИВЕНТЫ:*"
"Следите за каналом @nvibee_bet чтобы не пропустить:"
"- Новые игры"
"- Промокоды и раздачи"
"- Турниры и соревнования"
"- Обновления бота"

"🎯 *СОВЕТЫ ДЛЯ НОВИЧКОВ:*"
1. Начните с ежедневного бонуса (/bonus)
2. Выберите работу (/jobs) для стабильного заработка
"3. Играйте в игры с низкими ставками"
"4. Приглашайте друзей по реферальной ссылке"
"5. Участвуйте в ивентах и акциях"

"Удачи в игре! 🍀"
"""
    
    try:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
"# Если сообщение слишком длинное, разбиваем на части"
        parts = [help_text[i:i+4000] for i in range(0, len(help_text), 4000)]
        for part in parts:
            await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)

async def show_games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать меню игр""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    games_text = """
"🎮 *ВЫБЕРИТЕ ИГРУ*"

"Все игры с реальными ставками и высокими коэффициентами!"

"🎰 *Рулетка* - Классическая рулетка с числами 0-36"
"⚽ *Футбол* - Угадайте исход удара: гол или мимо"
"🎲 *Кости* - Бросьте кости и угадайте сумму"
"📈 *Краш* - Выводите деньги до того как график упадет"
"💣 *Мины* - Находите безопасные ячейки, избегая мин"
"💎 *Алмазы* - Ищите алмазы на игровом поле"
🃏 *Очко (21)* - Классическая карточная игра против дилера

"💰 Минимальная ставка: *100*"
"📊 Шансы и коэффициенты указаны в каждой игре"
"🎯 Опыт начисляется за любые игры"
"""
    
    keyboard = [
        [InlineKeyboardButton("🎰 Рулетка", callback_data="roulette_menu"),
         InlineKeyboardButton("⚽ Футбол", callback_data="football_menu")],
        [InlineKeyboardButton("🎲 Кости", callback_data="dice_menu"),
         InlineKeyboardButton("📈 Краш", callback_data="crash_menu")],
        [InlineKeyboardButton("💣 Мины", callback_data="mines_menu"),
         InlineKeyboardButton("💎 Алмазы", callback_data="diamonds_menu")],
        [InlineKeyboardButton("🃏 Очко (21)", callback_data="blackjack_menu")],
        [InlineKeyboardButton("📊 Статистика игр", callback_data="games_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        games_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def games_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика игр пользователя""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    total_games = user.wins + user.loses
    win_rate = (user.wins / total_games * 100) if total_games > 0 else 0
    
    stats_text = f"""
"📊 *ВАША ИГРОВАЯ СТАТИСТИКА*"

🎮 Всего игр: *{total_games}*
✅ Побед: *{user.wins}*
❌ Поражений: *{user.loses}*
📈 Винрейт: *{win_rate:.1f}%*

💰 Общий выигрыш: *{format_number(user.balance + user.bank - 10000)}*
🏆 Уровень: *{user.level}*
⭐ Опыт: *{user.exp}/{LEVEL_EXP_REQUIREMENTS.get(user.level, 4*user.level)}*

"📅 *АКТИВНОСТЬ:*"
📆 Зарегистрирован: {user.registered.strftime('%d.%m.%Y')}
⏰ Играет: *{(datetime.datetime.now() - user.registered).days} дней*

"🎯 *РЕКОМЕНДАЦИИ:*"
{f'📉 Винрейт ниже 50% - попробуйте игры с более высокими шансами' if win_rate < 50 else '📈 Отличный винрейт! Продолжайте в том же духе!'}
{f'💡 Совет: Делайте ставки по 10% от баланса' if user.balance > 1000 else '💡 Совет: Начните с минимальных ставок'}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def roulette_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню рулетки""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    roulette_text = f"""
"🎰 *РУЛЕТКА*"

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ТИПЫ СТАВОК:*"
• 🎯 Конкретное число (0-36) - коэффициент x36
• 🔴 Красное (x2) - шанс 48.6%
• ⚫ Черное (x2) - шанс 48.6%
• 🟢 Зеленое (0) - коэффициент x36
• ⚪ Четное (x2) - шанс 48.6%
• ⚫ Нечетное (x2) - шанс 48.6%
• 🎯 1-12 (x3) - шанс 32.4%
• 🎯 13-24 (x3) - шанс 32.4%
• 🎯 25-36 (x3) - шанс 32.4%

"📈 *СТРАТЕГИЯ:*"
"- Красное/Черное - самые безопасные ставки"
"- Конкретные числа - высокий риск, высокий потенциал"
"- Играйте ответственно!"
"""
    
    keyboard = [
        [InlineKeyboardButton("🔴 Красное (x2)", callback_data="roulette_red"),
         InlineKeyboardButton("⚫ Черное (x2)", callback_data="roulette_black")],
        [InlineKeyboardButton("⚪ Четное (x2)", callback_data="roulette_even"),
         InlineKeyboardButton("⚫ Нечетное (x2)", callback_data="roulette_odd")],
        [InlineKeyboardButton("1-12 (x3)", callback_data="roulette_1_12"),
         InlineKeyboardButton("13-24 (x3)", callback_data="roulette_13_24"),
         InlineKeyboardButton("25-36 (x3)", callback_data="roulette_25_36")],
        [InlineKeyboardButton("🎯 Конкретное число (x36)", callback_data="roulette_number")],
        [InlineKeyboardButton("📊 Статистика рулетки", callback_data="roulette_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        roulette_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def roulette_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика рулетки""""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        """
"📊 *СТАТИСТИКА РУЛЕТКИ*"

"🎰 *ШАНСЫ ВЫИГРЫША:*"
• Конкретное число: 2.7% (1/37)
• Красное/Черное: 48.6% (18/37)
• Четное/Нечетное: 48.6% (18/37)
• 1-12, 13-24, 25-36: 32.4% (12/37)

"💰 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
"При ставке 100 на красное:"
- Выигрыш: 100 × 2 = 200
"- Вероятность: 48.6%"
"- Ожидаемая прибыль: -2.7%"

"🎯 *СОВЕТЫ:*"
"1. Играйте только на деньги, которые не жалко потерять"
"2. Устанавливайте лимиты на сессию"
"3. Красное/Черное - самые безопасные ставки"
"4. Избегайте "систем" и "стратегий", они не работают"

"⚠️ *ПОМНИТЕ:* Рулетка - игра удачи!"
        """,
        parse_mode=ParseMode.MARKDOWN
    )

async def roulette_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка выбора ставки в рулетке""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    bet_type = query.data
    context.user_data["roulette_type"] = bet_type
    
"# Определяем тип ставки для отображения"
    bet_names = {
        "roulette_red": "🔴 Красное (x2)",
        "roulette_black": "⚫ Черное (x2)", 
        "roulette_even": "⚪ Четное (x2)",
        "roulette_odd": "⚫ Нечетное (x2)",
        "roulette_1_12": "1-12 (x3)",
        "roulette_13_24": "13-24 (x3)",
        "roulette_25_36": "25-36 (x3)",
        "roulette_number": "🎯 Конкретное число (x36)"
    }
    
    bet_name = bet_names.get(bet_type, "неизвестная ставка")
    
    await query.edit_message_text(
"f"🎰 *РУЛЕТКА*\n\n""
        f"Вы выбрали: *{bet_name}*\n"
        f"Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )

async def process_roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка ставки в рулетке""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
    bet_type = context.user_data.get("roulette_type")
    if not bet_type:
        await update.message.reply_text("❌ Ошибка! Начните заново.")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    
"# Крутим рулетку"
    result_number = random.randint(0, 36)
    
"# Определяем свойства выпавшего числа"
    is_red = result_number in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    is_black = result_number in [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
    is_even = result_number % 2 == 0 and result_number != 0
    is_odd = result_number % 2 == 1
    
"# Определяем цвет для отображения"
    if result_number == 0:
        color = "🟢"
        color_text = "зеленое"
    elif is_red:
        color = "🔴"
        color_text = "красное"
    else:
        color = "⚫"
        color_text = "черное"
    
"# Проверяем выигрыш"
    won = False
    multiplier = 0
    
    if bet_type == "roulette_red" and is_red:
        won = True
        multiplier = 2
    elif bet_type == "roulette_black" and is_black:
        won = True
        multiplier = 2
    elif bet_type == "roulette_even" and is_even:
        won = True
        multiplier = 2
    elif bet_type == "roulette_odd" and is_odd:
        won = True
        multiplier = 2
    elif bet_type == "roulette_1_12" and 1 <= result_number <= 12:
        won = True
        multiplier = 3
    elif bet_type == "roulette_13_24" and 13 <= result_number <= 24:
        won = True
        multiplier = 3
    elif bet_type == "roulette_25_36" and 25 <= result_number <= 36:
        won = True
        multiplier = 3
    elif bet_type == "roulette_number":
"# Для конкретного числа генерируем случайное число для ставки"
        player_bet_number = random.randint(0, 36)
        if result_number == player_bet_number:
            won = True
            multiplier = 36
    
    if won:
        win_amount = bet_amount * multiplier
        user.balance += win_amount
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount - bet_amount, context)
        
        result_text = f"""
"🎰 *РУЛЕТКА - ПОБЕДА!* 🎉"

💸 Ваша ставка: *{format_number(bet_amount)}*
🎯 Выпало: {result_number} {color} ({color_text})
💰 Выигрыш: *{format_number(win_amount)}* (x{multiplier})
💳 Новый баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
    else:
        user.loses += 1
        result_text = f"""
"🎰 *РУЛЕТКА - ПРОИГРЫШ* 😔"

💸 Ваша ставка: *{format_number(bet_amount)}*
🎯 Выпало: {result_number} {color} ({color_text})
💳 Ваш баланс: *{format_number(user.balance)}*

"💪 Не расстраивайтесь! Удача будет на вашей стороне в следующий раз!"
"""
    
    await db.save_user(user)
    
    keyboard = [
        [InlineKeyboardButton("🎰 Сыграть еще раз", callback_data="roulette_menu")],
        [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def football_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню футбола""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    football_text = f"""
"⚽ *ФУТБОЛ*"

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ПРАВИЛА ИГРЫ:*"
"1. Вы делаете ставку на исход удара"
"2. Игрок бьет по воротам"
"3. Если угадаете исход - выигрываете!"

"🎯 *ВИДЫ СТАВОК:*"
• ⚽ ГОЛ (x1.8) - шанс 55%
• ❌ МИМО (x2.2) - шанс 45%

"📈 *СТРАТЕГИЯ:*"
"- Голы выпадают чаще, но коэффициент ниже"
"- Мимо реже, но выплата выше"
"- Игра основана на удаче!"

"⚠️ *ВАЖНО:* Игра имитирует реальный футбол, результаты случайны."
"""
    
    keyboard = [
        [InlineKeyboardButton("⚽ ГОЛ (x1.8)", callback_data="football_goal"),
         InlineKeyboardButton("❌ МИМО (x2.2)", callback_data="football_miss")],
        [InlineKeyboardButton("📊 Статистика футбола", callback_data="football_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        football_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def football_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика футбола""""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        """
"📊 *СТАТИСТИКА ФУТБОЛА*"

"⚽ *РЕАЛЬНЫЕ СТАТИСТИКИ:*"
"- Средний процент голов в футболе: 45-55%"
"- В нашем боте: 55% голов, 45% мимо"

"🎯 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
"При ставке 100 на ГОЛ:"
- Выигрыш: 100 × 1.8 = 180
"- Вероятность: 55%"
"- Ожидаемая прибыль: -1%"

"При ставке 100 на МИМО:"
- Выигрыш: 100 × 2.2 = 220  
"- Вероятность: 45%"
"- Ожидаемая прибыль: -1%"

"📈 *СОВЕТЫ:*"
"1. Чередуйте ставки на гол и мимо"
"2. Не играйте все деньги на одну ставку"
"3. Устанавливайте лимиты на игру"

"⚽ *ИНТЕРЕСНЫЕ ФАКТЫ:*"
"- В реальном футболе за матч в среднем 2.5 гола"
"- Вероятность гола с пенальти: 75%"
"- Вероятность гола со штрафного: 6%"

"🎮 *В НАШЕЙ ИГРЕ:* результаты генерируются случайно, но с учетом реальной статистики!"
        """,
        parse_mode=ParseMode.MARKDOWN
    )

async def football_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка выбора ставки в футболе""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    bet_type = query.data
    context.user_data["football_type"] = bet_type
    
    bet_name = "⚽ ГОЛ (x1.8)" if bet_type == "football_goal" else "❌ МИМО (x2.2)"
    
    await query.edit_message_text(
"f"⚽ *ФУТБОЛ*\n\n""
        f"Вы выбрали: *{bet_name}*\n"
        f"Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )

async def process_football(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка ставки в футболе""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
    bet_type = context.user_data.get("football_type")
    if not bet_type:
        await update.message.reply_text("❌ Ошибка! Начните заново.")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    
"# Создаем анимацию удара"
    message = await update.message.reply_text("⚽ Игрок готовится к удару...")
    await asyncio.sleep(1)
    await message.edit_text("⚽ Игрок разбегается...")
    await asyncio.sleep(1)
    await message.edit_text("⚽ УДАР!")
    await asyncio.sleep(1)
    
    # Определяем результат (55% гол, 45% мимо)
    is_goal = random.random() < 0.55
    
"# Проверяем выигрыш"
    won = False
    multiplier = 0
    
    if bet_type == "football_goal" and is_goal:
        won = True
        multiplier = 1.8
    elif bet_type == "football_miss" and not is_goal:
        won = True
        multiplier = 2.2
    
    if won:
        win_amount = int(bet_amount * multiplier)
        user.balance += win_amount
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount - bet_amount, context)
        
        result_emoji = "⚽🥅 *ГОООООЛ!!!*" if is_goal else "❌ *МИМО!*"
        result_text = f"""
"⚽ *ФУТБОЛ - ПОБЕДА!* 🎉"

{result_emoji}
💸 Ваша ставка: *{format_number(bet_amount)}*
🎯 Вы ставили на: {"ГОЛ" if bet_type == "football_goal" else "МИМО"}
💰 Выигрыш: *{format_number(win_amount)}* (x{multiplier})
💳 Новый баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
    else:
        user.loses += 1
        result_emoji = "⚽🥅 *ГОООООЛ!!!*" if is_goal else "❌ *МИМО!*"
        result_text = f"""
"⚽ *ФУТБОЛ - ПРОИГРЫШ* 😔"

{result_emoji}
💸 Ваша ставка: *{format_number(bet_amount)}*
🎯 Вы ставили на: {"ГОЛ" if bet_type == "football_goal" else "МИМО"}
💳 Ваш баланс: *{format_number(user.balance)}*

"⚽ Удачи в следующем ударе!"
"""
    
    await db.save_user(user)
    
    keyboard = [
        [InlineKeyboardButton("⚽ Сыграть еще раз", callback_data="football_menu")],
        [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.edit_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def dice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню костей""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    dice_text = f"""
"🎲 *КОСТИ*"

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ПРАВИЛА ИГРЫ:*"
"1. Бросаются две игральные кости"
"2. Сумма значений от 2 до 12"
"3. Вы угадываете диапазон суммы"

"🎯 *ВИДЫ СТАВОК:*"
• 🎲 МЕНЬШЕ 7 (x2.2) - сумма 2-6
• 🎲 РАВНО 7 (x5.7) - сумма 7
• 🎲 БОЛЬШЕ 7 (x2.2) - сумма 8-12

"📈 *ВЕРОЯТНОСТИ:*"
- Меньше 7: 41.7% (15/36)
- Равно 7: 16.7% (6/36)  
- Больше 7: 41.7% (15/36)

"🎲 *ИНТЕРЕСНЫЙ ФАКТ:* Сумма 7 - самая вероятная при броске двух костей!"
"""
    
    keyboard = [
        [InlineKeyboardButton("🎲 МЕНЬШЕ 7 (x2.2)", callback_data="dice_less"),
         InlineKeyboardButton("🎲 РАВНО 7 (x5.7)", callback_data="dice_equal")],
        [InlineKeyboardButton("🎲 БОЛЬШЕ 7 (x2.2)", callback_data="dice_more")],
        [InlineKeyboardButton("📊 Статистика костей", callback_data="dice_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        dice_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def dice_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика костей""""
    query = update.callback_query
    await query.answer()
    
"# Таблица вероятностей"
    probabilities = """
"📊 *ТАБЛИЦА ВЕРОЯТНОСТЕЙ КОСТЕЙ*"

"🎲 *Сумма двух кубиков:*"
2: 🎲🎲 - 1/36 (2.78%)
3: 🎲🎲 - 2/36 (5.56%)
4: 🎲🎲 - 3/36 (8.33%)
5: 🎲🎲 - 4/36 (11.11%)
6: 🎲🎲 - 5/36 (13.89%)
7: 🎲🎲 - 6/36 (16.67%) ⭐
8: 🎲🎲 - 5/36 (13.89%)
9: 🎲🎲 - 4/36 (11.11%)
10: 🎲🎲 - 3/36 (8.33%)
11: 🎲🎲 - 2/36 (5.56%)
12: 🎲🎲 - 1/36 (2.78%)

"📈 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
"При ставке 100 на "МЕНЬШЕ 7":"
- Выигрыш: 100 × 2.2 = 220
"- Вероятность: 41.7%"
"- Ожидаемая прибыль: -8.3%"

"При ставке 100 на "РАВНО 7":"
- Выигрыш: 100 × 5.7 = 570
"- Вероятность: 16.7%"
"- Ожидаемая прибыль: -4.8%"

"При ставке 100 на "БОЛЬШЕ 7":"
- Выигрыш: 100 × 2.2 = 220
"- Вероятность: 41.7%"
"- Ожидаемая прибыль: -8.3%"

"🎯 *СОВЕТЫ:*"
"1. Ставка на 7 имеет лучшее математическое ожидание"
"2. Не играйте все деньги на одну ставку"
"3. Кости - игра удачи, играйте ответственно!"
"""
    
    await query.edit_message_text(
        probabilities,
        parse_mode=ParseMode.MARKDOWN
    )

async def dice_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка выбора ставки в костях""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    bet_type = query.data
    context.user_data["dice_type"] = bet_type
    
    bet_names = {
        "dice_less": "🎲 МЕНЬШЕ 7 (x2.2)",
        "dice_equal": "🎲 РАВНО 7 (x5.7)",
        "dice_more": "🎲 БОЛЬШЕ 7 (x2.2)"
    }
    
    bet_name = bet_names.get(bet_type, "неизвестная ставка")
    
    await query.edit_message_text(
"f"🎲 *КОСТИ*\n\n""
        f"Вы выбрали: *{bet_name}*\n"
        f"Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )

async def process_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка ставки в костях""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
    bet_type = context.user_data.get("dice_type")
    if not bet_type:
        await update.message.reply_text("❌ Ошибка! Начните заново.")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    
"# Создаем анимацию броска"
    message = await update.message.reply_text("🎲 Кости крутятся...")
    await asyncio.sleep(1)
    await message.edit_text("🎲🎲 Кости летят...")
    await asyncio.sleep(1)
    await message.edit_text("🎲🎲🎲 Кости падают...")
    await asyncio.sleep(1)
    
"# Бросаем кости"
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
"# Проверяем выигрыш"
    won = False
    multiplier = 0
    
    if bet_type == "dice_less" and total < 7:
        won = True
        multiplier = 2.2
    elif bet_type == "dice_equal" and total == 7:
        won = True
        multiplier = 5.7
    elif bet_type == "dice_more" and total > 7:
        won = True
        multiplier = 2.2
    
    if won:
        win_amount = int(bet_amount * multiplier)
        user.balance += win_amount
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount - bet_amount, context)
        
        result_text = f"""
"🎲 *КОСТИ - ПОБЕДА!* 🎉"

🎲 Выпало: *{dice1} + {dice2} = {total}*
💸 Ваша ставка: *{format_number(bet_amount)}*
🎯 Вы ставили на: {"МЕНЬШЕ 7" if bet_type == "dice_less" else "РАВНО 7" if bet_type == "dice_equal" else "БОЛЬШЕ 7"}
💰 Выигрыш: *{format_number(win_amount)}* (x{multiplier})
💳 Новый баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
    else:
        user.loses += 1
        result_text = f"""
"🎲 *КОСТИ - ПРОИГРЫШ* 😔"

🎲 Выпало: *{dice1} + {dice2} = {total}*
💸 Ваша ставка: *{format_number(bet_amount)}*
🎯 Вы ставили на: {"МЕНЬШЕ 7" if bet_type == "dice_less" else "РАВНО 7" if bet_type == "dice_equal" else "БОЛЬШЕ 7"}
💳 Ваш баланс: *{format_number(user.balance)}*

"🎲 Удачи в следующем броске!"
"""
    
    await db.save_user(user)
    
    keyboard = [
        [InlineKeyboardButton("🎲 Сыграть еще раз", callback_data="dice_menu")],
        [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.edit_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
"# БЛОК 4/6: Остальные игры и финансовые системы"

async def crash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню игры Краш""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    crash_text = f"""
"📈 *КРАШ ИГРА*"

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ПРАВИЛА ИГРЫ:*"
"1. Вы делаете ставку"
"2. График начинает расти от 1.00x"
"3. В любой момент вы можете вывести деньги"
"4. Если вы не успели вывести до краха - проигрываете"

"🎯 *КАК ИГРАТЬ:*"
"- Нажмите "Вывести" в нужный момент"
"- Или дождитесь автоматического вывода"
"- Чем выше множитель, тем больше выигрыш"
"- Но и риск краха тоже выше!"

"📈 *СТРАТЕГИЯ:*"
"- Выводите на 1.10x-1.50x для минимального риска"
"- Рискуйте на 2.00x-5.00x для большего выигрыша"
"- Не жадничайте! График может упасть в любой момент"

"⚠️ *ВАЖНО:* Это игра на удачу и скорость реакции!"
"""
    
    keyboard = [
        [InlineKeyboardButton("📈 Начать игру Краш", callback_data="crash_start")],
        [InlineKeyboardButton("📊 Статистика Краша", callback_data="crash_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        crash_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def crash_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика игры Краш""""
    query = update.callback_query
    await query.answer()
    
    stats_text = """
"📊 *СТАТИСТИКА ИГРЫ КРАШ*"

"📈 *ВЕРОЯТНОСТЬ КРАХА:*"
"- На 1.10x: 10%"
"- На 1.50x: 25%"
"- На 2.00x: 40%"
"- На 3.00x: 60%"
"- На 5.00x: 80%"
"- На 10.00x: 95%"

"💰 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
"- Средний множитель: 2.5x"
- Матожидание: -5% (казино advantage)
"- Это значит, в долгосрочной перспективе казино выигрывает"

"🎯 *СОВЕТЫ:*"
"1. Ставьте не более 10% от баланса"
"2. Выводите на 1.5x-2x для оптимального риска"
"3. Не пытайтесь "отыграться" после проигрыша"
"4. Устанавливайте лимиты на игру"

"📊 *РЕКОРДЫ В НАШЕМ БОТЕ:*"
"- Максимальный множитель: 98.76x"
"- Самый большой выигрыш: 5,000,000"
- Самый быстрый вывод: 1.01x (через 0.5 сек)

"⚠️ *ПОМНИТЕ:* Краш - одна из самых рискованных игр!"
"""
    
    await query.edit_message_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def crash_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Начать игру Краш""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
"f"📈 *КРАШ ИГРА*\n\n""
        f"💰 Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_crash_bet"] = True

async def process_crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка игры Краш""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    await db.save_user(user)
    
    # Генерируем точку краха (от 1.01 до 100)
    crash_point = 1.0
    while random.random() < 0.95 and crash_point < 100:
        crash_point += random.uniform(0.01, 0.5)
    
"# Создаем сообщение с анимацией"
    message = await update.message.reply_text("📈 *ГРАФИК НАЧИНАЕТ РОСТ...*\n\nТекущий множитель: 1.00x")
    
    current_multiplier = 1.00
    steps = 0
    user_cashed_out = False
    cashout_multiplier = 0
    
"# Анимация роста графика"
    while current_multiplier < crash_point and steps < 50:
        await asyncio.sleep(0.3)
        steps += 1
        
"# Генерируем рост"
        increment = random.uniform(0.01, 0.2)
        current_multiplier += increment
        
        # Проверяем, не нажал ли пользователь кнопку вывода (эмуляция)
"# В реальном боте здесь будут callback кнопки"
        if not user_cashed_out and random.random() < 0.05:
"# Эмулируем решение пользователя вывести"
            if current_multiplier > 1.1:
                user_cashed_out = True
                cashout_multiplier = current_multiplier
        
"# Если текущий множитель достиг краха"
        if current_multiplier >= crash_point:
            break
        
        try:
            await message.edit_text(
"f"📈 *ГРАФИК РАСТЕТ...*\n\n""
                f"Текущий множитель: *{current_multiplier:.2f}x*\n"
                f"Ваша ставка: *{format_number(bet_amount)}*\n"
                f"Потенциальный выигрыш: *{format_number(int(bet_amount * current_multiplier))}*\n\n"
"f"⏰ Успейте вывести до краха!","
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
    
"# Завершение игры"
    if user_cashed_out and cashout_multiplier > 0:
"# Пользователь успел вывести"
        win_amount = int(bet_amount * cashout_multiplier)
        user.balance += win_amount
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount - bet_amount, context)
        
        result_text = f"""
"📈 *КРАШ - ВЫИГРЫШ!* 🎉"

✅ Вы успели вывести на: *{cashout_multiplier:.2f}x*
💰 Ваша ставка: *{format_number(bet_amount)}*
🎯 Выигрыш: *{format_number(win_amount)}*
💳 Новый баланс: *{format_number(user.balance)}*

⏰ Точка краха была: *{crash_point:.2f}x*
📊 Вы вывели за *{steps * 0.3:.1f}* секунд
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
    else:
"# Пользователь не успел вывести"
        user.loses += 1
        result_text = f"""
"📉 *КРАШ - ПРОИГРЫШ!* 😔"

"❌ Вы не успели вывести!"
💸 Ваша ставка: *{format_number(bet_amount)}*
📉 Точка краха: *{crash_point:.2f}x*
⏰ График упал на *{current_multiplier:.2f}x*
💳 Ваш баланс: *{format_number(user.balance)}*

"💪 В следующий раз повезет больше!"
"""
    
    await db.save_user(user)
    
    keyboard = [
        [InlineKeyboardButton("📈 Сыграть еще раз", callback_data="crash_menu")],
        [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.edit_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def mines_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню игры Мины""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    mines_text = f"""
"💣 *МИНЫ*"

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ПРАВИЛА ИГРЫ:*"
1. На поле 5x5 (25 ячеек) спрятаны 3 мины
"2. Вы открываете ячейки по одной"
"3. Если открыли мину - проигрываете"
"4. Если открыли все безопасные ячейки - выигрываете"

"🎯 *МЕХАНИКА ВЫИГРЫША:*"
"- За каждую открытую безопасную ячейку множитель растет"
"- Можно вывести деньги в любой момент"
"- Чем больше ячеек открыто, тем выше выигрыш"

"📈 *МНОЖИТЕЛИ:*"
"- 1 ячейка: 1.3x"
"- 5 ячеек: 2.5x"
"- 10 ячеек: 4.0x"
"- 15 ячеек: 6.0x"
- 22 ячейки (все): 24.0x

"⚠️ *СТРАТЕГИЯ:* Открывайте ячейки осторожно, не рискуйте всем!"
"""
    
    keyboard = [
        [InlineKeyboardButton("💣 Начать игру Мины", callback_data="mines_start")],
        [InlineKeyboardButton("📊 Статистика игры", callback_data="mines_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        mines_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def mines_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика игры Мины""""
    query = update.callback_query
    await query.answer()
    
    stats_text = """
"📊 *СТАТИСТИКА ИГРЫ МИНЫ*"

"💣 *ВЕРОЯТНОСТИ:*"
- Вероятность наступить на мину с первой ячейки: 12% (3/25)
"- Вероятность открыть 5 безопасных ячеек подряд: 33%"
"- Вероятность открыть все 22 безопасные ячейки: 0.0001%"

"💰 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
При оптимальной стратегии (вывод на 5-8 ячейках):
"- Матожидание: -3% до -5%"
"- Это одна из самых честных игр"

"🎯 *СТРАТЕГИИ:*"
1. *Консервативная:* Выводите на 3-5 ячейках (1.9x-2.5x)
2. *Умеренная:* Выводите на 8-12 ячейках (3.4x-5.2x)
3. *Агрессивная:* Идите до конца (24x, но риск 12%)

"🔄 *СИСТЕМЫ ИГРЫ:*"
"- Не существует "безопасных" паттернов"
"- Каждая игра независима"
"- Мины распределяются случайно"

"💡 *СОВЕТ:* Выводите, когда множитель вас устраивает, не жадничайте!"
"""
    
    await query.edit_message_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def mines_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Начать игру Мины""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
"f"💣 *МИНЫ*\n\n""
        f"💰 Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_mines_bet"] = True
    context.user_data["mines_game"] = {
        "mines": [],
        "opened": [],
        "multiplier": 1.0,
        "bet_amount": 0
    }

async def process_mines_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка начала игры Мины""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    await db.save_user(user)
    
    # Генерируем мины (3 мины на поле 5x5)
    game_data = context.user_data["mines_game"]
    game_data["bet_amount"] = bet_amount
    
    all_cells = list(range(1, 26))
    game_data["mines"] = random.sample(all_cells, 3)
    game_data["opened"] = []
    game_data["multiplier"] = 1.0
    
    await show_mines_game(update, context)

async def show_mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать игровое поле Мины""""
    game_data = context.user_data.get("mines_game")
    if not game_data:
        await update.message.reply_text("❌ Ошибка игры!")
        return
    
    user_id = update.effective_user.id
    
"# Создаем клавиатуру с полем 5x5"
    keyboard = []
    for row in range(5):
        row_buttons = []
        for col in range(5):
            cell_num = row * 5 + col + 1
            if cell_num in game_data["opened"]:
                if cell_num in game_data["mines"]:
                    button_text = "💣"
                else:
                    button_text = "✅"
            else:
                button_text = "🟦"
            row_buttons.append(InlineKeyboardButton(button_text, callback_data=f"mine_{cell_num}"))
        keyboard.append(row_buttons)
    
"# Кнопка вывода"
    safe_cells_opened = len([c for c in game_data["opened"] if c not in game_data["mines"]])
    multiplier = 1.0 + (safe_cells_opened * 0.3)
    game_data["multiplier"] = multiplier
    
    potential_win = int(game_data["bet_amount"] * multiplier)
    
    keyboard.append([InlineKeyboardButton(f"💰 Забрать {format_number(potential_win)} (x{multiplier:.1f})", callback_data="mines_cashout")])
    keyboard.append([InlineKeyboardButton("🏃‍♂️ Выйти из игры", callback_data="games_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    game_text = f"""
"💣 *МИНЫ - ИГРА НАЧАТА*"

💰 Ставка: *{format_number(game_data['bet_amount'])}*
"💣 Мин на поле: 3"
✅ Открыто безопасных: {safe_cells_opened}
📈 Множитель: *x{multiplier:.1f}*
💰 Потенциальный выигрыш: *{format_number(potential_win)}*

"🔄 *ПРАВИЛА:*"
"- Нажмите на синюю ячейку, чтобы открыть её"
- Зеленые ячейки (✅) - безопасные
- Красные ячейки (💣) - мины
"- Можно вывести деньги в любой момент"

"⚠️ *ВНИМАНИЕ:* Если откроете мину - проиграете всю ставку!"
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            game_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            game_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def process_mine_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка клика по ячейке в игре Мины""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    game_data = context.user_data.get("mines_game")
    
    if not user or not game_data:
        await query.edit_message_text("❌ Ошибка игры!")
        return
    
    if "cashout" in query.data:
"# Пользователь решил вывести"
        safe_cells_opened = len([c for c in game_data["opened"] if c not in game_data["mines"]])
        multiplier = 1.0 + (safe_cells_opened * 0.3)
        win_amount = int(game_data["bet_amount"] * multiplier)
        
        user.balance += win_amount
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount - game_data["bet_amount"], context)
        
        result_text = f"""
"💰 *МИНЫ - ВЫИГРЫШ!* 🎉"

✅ Открыто безопасных ячеек: {safe_cells_opened}
📈 Множитель: *x{multiplier:.1f}*
💸 Ставка: *{format_number(game_data['bet_amount'])}*
🎯 Выигрыш: *{format_number(win_amount)}*
💳 Новый баланс: *{format_number(user.balance)}*

"🎮 Молодец! Вы вовремя вышли из игры!"
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
        await db.save_user(user)
        
        keyboard = [
            [InlineKeyboardButton("💣 Сыграть еще раз", callback_data="mines_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
"# Обработка клика по ячейке"
    cell_num = int(query.data.split("_")[1])
    
"# Проверяем, не открыта ли уже ячейка"
    if cell_num in game_data["opened"]:
        await query.answer("Эта ячейка уже открыта!", show_alert=True)
        return
    
"# Открываем ячейку"
    game_data["opened"].append(cell_num)
    
"# Проверяем, не мина ли это"
    if cell_num in game_data["mines"]:
"# Пользователь наступил на мину"
        user.loses += 1
        await db.save_user(user)
        
"# Показываем поле с минами"
        keyboard = []
        for row in range(5):
            row_buttons = []
            for col in range(5):
                cell_num_display = row * 5 + col + 1
                if cell_num_display in game_data["mines"]:
                    button_text = "💣"
                elif cell_num_display == cell_num:
                    button_text = "💥"
                elif cell_num_display in game_data["opened"]:
                    button_text = "✅"
                else:
                    button_text = "🟦"
                row_buttons.append(InlineKeyboardButton(button_text, callback_data="none"))
            keyboard.append(row_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"""
"💥 *МИНЫ - ПРОИГРЫШ!* 😔"

"💣 Вы наступили на мину!"
💸 Ставка: *{format_number(game_data['bet_amount'])}*
💳 Ваш баланс: *{format_number(user.balance)}*

"💪 Удачи в следующий раз! Будьте осторожнее!"
"""
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
"# Если ячейка безопасная, продолжаем игру"
    await show_mines_game_from_query(query, context)

async def show_mines_game_from_query(query, context):
""""Обновить игровое поле Мины после хода""""
    game_data = context.user_data.get("mines_game")
    if not game_data:
        return
    
    user_id = query.from_user.id
    
"# Создаем клавиатуру"
    keyboard = []
    for row in range(5):
        row_buttons = []
        for col in range(5):
            cell_num = row * 5 + col + 1
            if cell_num in game_data["opened"]:
                if cell_num in game_data["mines"]:
                    button_text = "💣"
                else:
                    button_text = "✅"
            else:
                button_text = "🟦"
            row_buttons.append(InlineKeyboardButton(button_text, callback_data=f"mine_{cell_num}"))
        keyboard.append(row_buttons)
    
"# Кнопка вывода"
    safe_cells_opened = len([c for c in game_data["opened"] if c not in game_data["mines"]])
    multiplier = 1.0 + (safe_cells_opened * 0.3)
    game_data["multiplier"] = multiplier
    
    potential_win = int(game_data["bet_amount"] * multiplier)
    
    keyboard.append([InlineKeyboardButton(f"💰 Забрать {format_number(potential_win)} (x{multiplier:.1f})", callback_data="mines_cashout")])
    keyboard.append([InlineKeyboardButton("🏃‍♂️ Выйти из игры", callback_data="games_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
"# Проверяем, не открыты ли все безопасные ячейки"
    total_safe_cells = 22  # 25 ячеек - 3 мины
    if safe_cells_opened == total_safe_cells:
"# Пользователь открыл все безопасные ячейки!"
        win_amount = int(game_data["bet_amount"] * 24.0)
        
        user = await db.get_user(user_id)
        if user:
            user.balance += win_amount
            user.wins += 1
            level_up = add_exp(user)
            await distribute_referral_bonus(user_id, win_amount - game_data["bet_amount"], context)
            await db.save_user(user)
        
        result_text = f"""
"🎉 *МИНЫ - ДЖЕКПОТ!* 🏆"

"🎯 Вы открыли ВСЕ безопасные ячейки!"
💰 Ставка: *{format_number(game_data['bet_amount'])}*
📈 Множитель: *x24.0* (максимальный!)
🎯 Выигрыш: *{format_number(win_amount)}*
💳 Новый баланс: *{format_number(user.balance)}*

"🔥 Невероятная удача! Вы сорвали джекпот!"
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
        keyboard = [
            [InlineKeyboardButton("💣 Сыграть еще раз", callback_data="mines_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    game_text = f"""
"💣 *МИНЫ - ИГРА ПРОДОЛЖАЕТСЯ*"

💰 Ставка: *{format_number(game_data['bet_amount'])}*
"💣 Мин на поле: 3"
✅ Открыто безопасных: {safe_cells_opened}
📈 Множитель: *x{multiplier:.1f}*
💰 Потенциальный выигрыш: *{format_number(potential_win)}*

"⚠️ *ОСТАЛОСЬ ЯЧЕЕК:*"
🟦 Закрытых: {25 - len(game_data['opened'])}
💣 Из них мин: {3 - len([m for m in game_data['mines'] if m in game_data['opened']])}

"🎯 Выбирайте следующую ячейку осторожно!"
"""
    
    await query.edit_message_text(
        game_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def diamonds_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню игры Алмазы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    diamonds_text = f"""
"💎 *АЛМАЗЫ*"

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ПРАВИЛА ИГРЫ:*"
"1. На каждом уровне есть 5 ячеек"
"2. В одной ячейке спрятан алмаз"
"3. Вы выбираете ячейку"
"4. Если нашли алмаз - переходите на следующий уровень"
"5. Если не нашли - игра заканчивается"

"🎯 *МЕХАНИКА ВЫИГРЫША:*"
"- Всего 16 уровней"
"- Множитель растет с каждым уровнем"
"- Можно вывести деньги в любой момент"
"- Максимальный множитель: 24x"

"📈 *МНОЖИТЕЛИ ПО УРОВНЯМ:*"
"- Уровень 1: 1.5x"
"- Уровень 5: 3.5x"
"- Уровень 10: 6.0x"
"- Уровень 15: 10.0x"
"- Уровень 16: 24.0x"

"💡 *СТРАТЕГИЯ:* Рискуйте, но знайте, когда остановиться!"
"""
    
    keyboard = [
        [InlineKeyboardButton("💎 Начать игру Алмазы", callback_data="diamonds_start")],
        [InlineKeyboardButton("📊 Статистика игры", callback_data="diamonds_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        diamonds_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def diamonds_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика игры Алмазы""""
    query = update.callback_query
    await query.answer()
    
    stats_text = """
"📊 *СТАТИСТИКА ИГРЫ АЛМАЗЫ*"

"💎 *ВЕРОЯТНОСТИ:*"
- Шанс найти алмаз на уровне: 20% (1 из 5)
- Шанс дойти до уровня 5: 0.8% (0.2^5)
"- Шанс дойти до уровня 10: 0.0001%"
"- Шанс дойти до уровня 16: практически 0%"

"💰 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
При оптимальной стратегии (вывод на 3-5 уровне):
"- Матожидание: -5% до -8%"
"- Игра более рискованная, чем кажется"

"🎯 *СТРАТЕГИИ:*"
1. *Осторожная:* Выводите на 2-3 уровне (2.0x-2.5x)
2. *Балансная:* Выводите на 4-6 уровне (3.0x-4.0x)
3. *Рискованная:* Идите до 8+ уровня (6.0x+)

"🔢 *МАТЕМАТИКА:*"
"- Вероятность проиграть на первом уровне: 80%"
"- Средняя длина игры: 1-2 уровня"
"- Только 1 из 1000 доходит до 10 уровня"

"💡 *СОВЕТ:* Не поддавайтесь азарту! Выводите, когда множитель хороший."
"""
    
    await query.edit_message_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def diamonds_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Начать игру Алмазы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
"f"💎 *АЛМАЗЫ*\n\n""
        f"💰 Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_diamonds_bet"] = True
    context.user_data["diamonds_game"] = {
        "level": 1,
        "multiplier": 1.0,
        "bet_amount": 0
    }

async def process_diamonds_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка начала игры Алмазы""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    await db.save_user(user)
    
"# Начинаем игру"
    game_data = context.user_data["diamonds_game"]
    game_data["bet_amount"] = bet_amount
    game_data["level"] = 1
    game_data["multiplier"] = 1.0
    
"# Генерируем позицию алмаза для первого уровня"
    game_data["diamond_position"] = random.randint(1, 5)
    game_data["opened"] = []
    
    await show_diamonds_game(update, context)

async def show_diamonds_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать игровое поле Алмазы""""
    game_data = context.user_data.get("diamonds_game")
    if not game_data:
        await update.message.reply_text("❌ Ошибка игры!")
        return
    
    user_id = update.effective_user.id
    
"# Расчет множителя"
    multiplier = 1.0 + (game_data["level"] - 1) * 0.5
    game_data["multiplier"] = multiplier
    
"# Создаем клавиатуру с 5 ячейками"
    keyboard = []
    row_buttons = []
    for i in range(1, 6):
        if i in game_data["opened"]:
            if i == game_data["diamond_position"]:
                button_text = "💎"
            else:
                button_text = "📦"
        else:
            button_text = "❓"
        row_buttons.append(InlineKeyboardButton(button_text, callback_data=f"diamond_{i}"))
    
    keyboard.append(row_buttons)
    
"# Кнопка вывода"
    potential_win = int(game_data["bet_amount"] * multiplier)
    
    keyboard.append([InlineKeyboardButton(f"💰 Забрать {format_number(potential_win)} (x{multiplier:.1f})", callback_data="diamonds_cashout")])
    keyboard.append([InlineKeyboardButton("🏃‍♂️ Выйти из игры", callback_data="games_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    game_text = f"""
💎 *АЛМАЗЫ - Уровень {game_data['level']}/16*

💰 Ставка: *{format_number(game_data['bet_amount'])}*
📈 Множитель: *x{multiplier:.1f}*
💰 Потенциальный выигрыш: *{format_number(potential_win)}*

"🔍 *ПРАВИЛА:*"
"- Выберите одну из 5 ячеек"
"- В одной ячейке спрятан алмаз 💎"
"- В остальных - пустые коробки 📦"
"- Нашли алмаз - переходите на следующий уровень"
"- Нашли коробку - игра заканчивается"

"🎯 *СЛЕДУЮЩИЙ УРОВЕНЬ:*"
- Уровень {game_data['level'] + 1}: x{multiplier + 0.5:.1f}
"- Максимальный уровень 16: x24.0"

⚠️ *ВНИМАНИЕ:* С каждым уровнем шанс найти алмаз не меняется (20%)!
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            game_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            game_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
    )
"# БЛОК 5/6: Банк, работа, ферма BTC и биржа"

async def process_diamond_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка клика по ячейке в игре Алмазы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    game_data = context.user_data.get("diamonds_game")
    
    if not user or not game_data:
        await query.edit_message_text("❌ Ошибка игры!")
        return
    
    if "cashout" in query.data:
"# Пользователь решил вывести"
        win_amount = int(game_data["bet_amount"] * game_data["multiplier"])
        user.balance += win_amount
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount - game_data["bet_amount"], context)
        
        result_text = f"""
"💰 *АЛМАЗЫ - ВЫИГРЫШ!* 🎉"

📈 Достигнутый уровень: {game_data['level']}
💰 Множитель: *x{game_data['multiplier']:.1f}*
💸 Ставка: *{format_number(game_data['bet_amount'])}*
🎯 Выигрыш: *{format_number(win_amount)}*
💳 Новый баланс: *{format_number(user.balance)}*

"🎮 Хорошая игра! Вы вовремя остановились!"
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
        await db.save_user(user)
        
        keyboard = [
            [InlineKeyboardButton("💎 Сыграть еще раз", callback_data="diamonds_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
"# Обработка клика по ячейке"
    cell_num = int(query.data.split("_")[1])
    
"# Проверяем, не открыта ли уже ячейка"
    if cell_num in game_data["opened"]:
        await query.answer("Эта ячейка уже открыта!", show_alert=True)
        return
    
"# Открываем ячейку"
    game_data["opened"].append(cell_num)
    
"# Проверяем, нашли ли алмаз"
    if cell_num == game_data["diamond_position"]:
"# Нашли алмаз! Переходим на следующий уровень"
        game_data["level"] += 1
        
"# Проверяем, не достигли ли максимального уровня"
        if game_data["level"] > 16:
"# Дошли до конца!"
            win_amount = int(game_data["bet_amount"] * 24.0)  # Максимальный множитель
            user.balance += win_amount
            user.wins += 1
            
            level_up = add_exp(user)
            await distribute_referral_bonus(user_id, win_amount - game_data["bet_amount"], context)
            await db.save_user(user)
            
            result_text = f"""
"🏆 *АЛМАЗЫ - ДЖЕКПОТ!* 🎉"

"🎯 Вы прошли ВСЕ 16 уровней!"
"💰 Максимальный множитель: *x24.0*"
💸 Ставка: *{format_number(game_data['bet_amount'])}*
🎯 Выигрыш: *{format_number(win_amount)}*
💳 Новый баланс: *{format_number(user.balance)}*

"🔥 Невероятная удача! Вы сорвали джекпот!"
"""
            
            if level_up:
                result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
            
            keyboard = [
                [InlineKeyboardButton("💎 Сыграть еще раз", callback_data="diamonds_menu")],
                [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                result_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
"# Генерируем новую позицию алмаза для следующего уровня"
        game_data["diamond_position"] = random.randint(1, 5)
        game_data["opened"] = []
        
        await query.edit_message_text(
"f"💎 *АЛМАЗ НАЙДЕН!*\n\n""
            f"🎉 Переход на уровень {game_data['level']}!\n"
            f"📈 Новый множитель: *x{game_data['multiplier'] + 0.5:.1f}*",
            parse_mode=ParseMode.MARKDOWN
        )
        await asyncio.sleep(2)
        await show_diamonds_game_from_query(query, context)
    else:
"# Нашли пустую коробку - проигрыш"
        user.loses += 1
        await db.save_user(user)
        
        result_text = f"""
"📦 *АЛМАЗЫ - ПРОИГРЫШ!* 😔"

"❌ Вы нашли пустую коробку!"
💸 Ставка: *{format_number(game_data['bet_amount'])}*
📈 Достигнутый уровень: {game_data['level'] - 1}
💳 Ваш баланс: *{format_number(user.balance)}*

"💎 Удачи в следующий раз! Алмаз был в другой ячейке..."
"""
        
        keyboard = [
            [InlineKeyboardButton("💎 Сыграть еще раз", callback_data="diamonds_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def show_diamonds_game_from_query(query, context):
""""Обновить игровое поле Алмазы после успешного хода""""
    game_data = context.user_data.get("diamonds_game")
    if not game_data:
        return
    
    user_id = query.from_user.id
    
"# Расчет множителя"
    multiplier = 1.0 + (game_data["level"] - 1) * 0.5
    game_data["multiplier"] = multiplier
    
"# Создаем клавиатуру с 5 ячейками"
    keyboard = []
    row_buttons = []
    for i in range(1, 6):
        if i in game_data["opened"]:
            if i == game_data["diamond_position"]:
                button_text = "💎"
            else:
                button_text = "📦"
        else:
            button_text = "❓"
        row_buttons.append(InlineKeyboardButton(button_text, callback_data=f"diamond_{i}"))
    
    keyboard.append(row_buttons)
    
"# Кнопка вывода"
    potential_win = int(game_data["bet_amount"] * multiplier)
    
    keyboard.append([InlineKeyboardButton(f"💰 Забрать {format_number(potential_win)} (x{multiplier:.1f})", callback_data="diamonds_cashout")])
    keyboard.append([InlineKeyboardButton("🏃‍♂️ Выйти из игры", callback_data="games_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    game_text = f"""
💎 *АЛМАЗЫ - Уровень {game_data['level']}/16*

💰 Ставка: *{format_number(game_data['bet_amount'])}*
📈 Множитель: *x{multiplier:.1f}*
💰 Потенциальный выигрыш: *{format_number(potential_win)}*

"🎯 *СТАТИСТИКА:*"
- Пройдено уровней: {game_data['level'] - 1}
"- Текущий шанс: 20%"
- До джекпота осталось: {16 - game_data['level']} уровней

"⚠️ *СОВЕТ:* Каждый следующий уровень увеличивает множитель на 0.5x!"
"""
    
    await query.edit_message_text(
        game_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def blackjack_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню игры Очко (21/Блекджек)"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    blackjack_text = f"""
🃏 *ОЧКО (21/БЛЕКДЖЕК)*

💰 Ваш баланс: *{format_number(user.balance)}*
"🎯 Минимальная ставка: *100*"

"📊 *ПРАВИЛА ИГРЫ:*"
1. Вы играете против дилера (бота)
"2. Цель - набрать сумму карт близкую к 21"
3. Если больше 21 - перебор (проигрыш)
"4. Побеждает тот, у кого сумма ближе к 21"

"🎴 *ЗНАЧЕНИЯ КАРТ:*"
"- Карты 2-10: номинал"
"- Валет, Дама, Король: 10"
- Туз: 1 или 11 (автоматически выбирается лучшее)

"🎯 *ВАРИАНТЫ ХОДОВ:*"
- ➕ Еще карту (Hit) - получить еще одну карту
- ✋ Хватит (Stand) - остановиться на текущей сумме

"🏆 *СОЧЕТАНИЯ:*"
- Блекджек (21 с двух карт): выплата 2.5x
"- Обычная победа: выплата 2x"
"- Ничья: возврат ставки"
"- Проигрыш: потеря ставки"

"💡 *СТРАТЕГИЯ:* Дилер обязан брать карты до 17 и останавливаться на 17+"
"""
    
    keyboard = [
        [InlineKeyboardButton("🃏 Начать игру Очко", callback_data="blackjack_start")],
        [InlineKeyboardButton("📊 Статистика игры", callback_data="blackjack_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        blackjack_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def blackjack_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика игры Очко""""
    query = update.callback_query
    await query.answer()
    
    stats_text = """
📊 *СТАТИСТИКА ИГРЫ ОЧКО (21)*

"🎴 *ВЕРОЯТНОСТИ:*"
"- Вероятность перебора при 12: 31%"
"- Вероятность перебора при 16: 62%"
"- Вероятность перебора при 20: 92%"
- Вероятность блекджека: 4.8% (1 из 21)

"💰 *МАТЕМАТИЧЕСКОЕ ОЖИДАНИЕ:*"
"При оптимальной базовой стратегии:"
"- Матожидание игрока: -0.5% до -1%"
"- Одна из самых честных игр против казино"

"🎯 *БАЗОВАЯ СТРАТЕГИЯ:*"
"- Всегда берите карту, если у вас 11 или меньше"
"- Останавливайтесь на 17 или больше"
"- При 12-16 берите, если у дилера 7 или выше"
- При мягкой руке (туз + 2-6) берите еще

"🃏 *СОЧЕТАНИЯ КАРТ:*"
"- Твердая рука: без туза или туз как 1"
"- Мягкая рука: туз как 11"
"- Блекджек: туз + 10, В, Д, К"

"💡 *СОВЕТЫ:*"
"1. Не бойтесь брать карты при 12-16 против дилера 7+"
"2. Никогда не берите карту при 17+"
"3. Помните, что дилер обязан брать до 17"
"4. Играйте по стратегии, не полагайтесь только на удачу"
"""
    
    await query.edit_message_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def blackjack_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Начать игру Очко""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        f"🃏 *ОЧКО (21)*\n\n"
        f"💰 Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите сумму ставки (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_blackjack_bet"] = True

async def process_blackjack_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка начала игры Очко""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        bet_amount = int(update.message.text)
        if bet_amount < 100:
            await update.message.reply_text("❌ Минимальная ставка: 100!")
            return
        if bet_amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
"# Вычитаем ставку"
    user.balance -= bet_amount
    await db.save_user(user)
    
    # Создаем колоду (упрощенная - бесконечная колода)
"# В реальной игре нужно использовать одну колоду или несколько"
"# Здесь для простоты используем бесконечную колоду"
    
"# Инициализируем игру"
    context.user_data["blackjack_game"] = {
        "bet_amount": bet_amount,
        "player_cards": [],
        "dealer_cards": [],
        "player_score": 0,
        "dealer_score": 0,
        "game_over": False
    }
    
    game_data = context.user_data["blackjack_game"]
    
"# Раздаем начальные карты"
    game_data["player_cards"] = [draw_card(), draw_card()]
    game_data["dealer_cards"] = [draw_card(), draw_card()]
    
"# Рассчитываем очки"
    game_data["player_score"] = calculate_score(game_data["player_cards"])
    game_data["dealer_score"] = calculate_score([game_data["dealer_cards"][0]])  # Только первая карта дилера видна
    
"# Проверяем блекджек у игрока"
    if game_data["player_score"] == 21:
"# У игрока блекджек!"
        win_amount = int(bet_amount * 2.5)
        user.balance += win_amount + bet_amount  # Возвращаем ставку + выигрыш
        user.wins += 1
        
"# Добавляем опыт"
        level_up = add_exp(user)
        
"# Распределяем реферальный бонус"
        await distribute_referral_bonus(user_id, win_amount, context)
        
"# Рассчитываем очки дилера для отображения"
        dealer_final_score = calculate_score(game_data["dealer_cards"])
        
        result_text = f"""
"🏆 *ОЧКО - БЛЕКДЖЕК!* 🎉"

🎴 Ваши карты: {format_cards(game_data['player_cards'])} ({game_data['player_score']})
🎴 Карты дилера: {format_cards(game_data['dealer_cards'])} ({dealer_final_score})

💰 Ставка: *{format_number(bet_amount)}*
🎯 Выигрыш: *{format_number(win_amount)}* (2.5x)
💳 Новый баланс: *{format_number(user.balance)}*

"🔥 Невероятно! Блекджек с первой раздачи!"
"""
        
        if level_up:
            result_text += f"\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
        await db.save_user(user)
        
        keyboard = [
            [InlineKeyboardButton("🃏 Сыграть еще раз", callback_data="blackjack_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
"# Если нет блекджека, продолжаем игру"
    await show_blackjack_game(update, context)

def draw_card():
""""Вытянуть случайную карту""""
    cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    return random.choice(cards)

def calculate_score(cards):
""""Рассчитать сумму очков""""
    score = 0
    aces = 0
    
    for card in cards:
        if card in ['J', 'Q', 'K']:
            score += 10
        elif card == 'A':
            aces += 1
            score += 11
        else:
            score += int(card)
    
"# Если сумма больше 21 и есть тузы, считаем тузы как 1"
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    
    return score

def format_cards(cards):
""""Форматировать карты для отображения""""
    suits = ['♠️', '♥️', '♦️', '♣️']
    result = []
    for card in cards:
        suit = random.choice(suits)
        result.append(f"{card}{suit}")
    return ' '.join(result)

async def show_blackjack_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Показать текущее состояние игры Очко""""
    game_data = context.user_data.get("blackjack_game")
    if not game_data:
        await update.message.reply_text("❌ Ошибка игры!")
        return
    
    user_id = update.effective_user.id
    
"# Форматируем карты"
    player_cards_formatted = format_cards(game_data["player_cards"])
    dealer_cards_formatted = format_cards([game_data["dealer_cards"][0]]) + " ? ?"
    
"# Определяем, закончена ли игра"
    if game_data["game_over"]:
"# Игра закончена, показываем результат"
        dealer_final_score = calculate_score(game_data["dealer_cards"])
        
        result_text = f"""
"🎴 *ОЧКО - ИГРА ЗАВЕРШЕНА*"

🎴 Ваши карты: {format_cards(game_data['player_cards'])} ({game_data['player_score']})
🎴 Карты дилера: {format_cards(game_data['dealer_cards'])} ({dealer_final_score})

"""
        
"# Определяем победителя"
        player_score = game_data["player_score"]
        dealer_score = dealer_final_score
        
        if player_score > 21:
            result_text += f"❌ *ПЕРЕБОР!* Вы проиграли.\n💸 Ставка: *{format_number(game_data['bet_amount'])}*"
        elif dealer_score > 21:
            result_text += f"✅ *ДИЛЕР ПЕРЕБРАЛ!* Вы выиграли.\n💰 Выигрыш: *{format_number(game_data['bet_amount'] * 2)}*"
        elif player_score > dealer_score:
            result_text += f"✅ *ВЫ ВЫИГРАЛИ!* {player_score} > {dealer_score}\n💰 Выигрыш: *{format_number(game_data['bet_amount'] * 2)}*"
        elif player_score < dealer_score:
            result_text += f"❌ *ВЫ ПРОИГРАЛИ!* {player_score} < {dealer_score}\n💸 Ставка: *{format_number(game_data['bet_amount'])}*"
        else:
            result_text += f"🤝 *НИЧЬЯ!* {player_score} = {dealer_score}\n💰 Ставка возвращена: *{format_number(game_data['bet_amount'])}*"
        
"# Обновляем баланс пользователя"
        user = await db.get_user(user_id)
        if user:
            if player_score > 21 or (dealer_score <= 21 and player_score < dealer_score):
                user.loses += 1
            elif dealer_score > 21 or player_score > dealer_score:
                user.wins += 1
                user.balance += game_data["bet_amount"] * 2
                
"# Добавляем опыт"
                level_up = add_exp(user)
                
"# Распределяем реферальный бонус"
                await distribute_referral_bonus(user_id, game_data["bet_amount"], context)
                
                if level_up:
                    result_text += f"\n\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
            else:  # Ничья
                user.balance += game_data["bet_amount"]
            
            await db.save_user(user)
        
        result_text += f"\n\n💳 Ваш баланс: *{format_number(user.balance)}*"
        
        keyboard = [
            [InlineKeyboardButton("🃏 Сыграть еще раз", callback_data="blackjack_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                result_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                result_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
"# Игра продолжается"
    game_text = f"""
🃏 *ОЧКО (21) - ВАШ ХОД*

🎴 Карты дилера: {dealer_cards_formatted}
🎴 Ваши карты: {player_cards_formatted}
🎯 Ваши очки: *{game_data['player_score']}*

💰 Ставка: *{format_number(game_data['bet_amount'])}*
💳 Ваш баланс: *{format_number(user.balance)}*

"⚠️ *ВНИМАНИЕ:* Если возьмете карту и сумма превысит 21 - проиграете!"
"""
    
    keyboard = [
        [InlineKeyboardButton("➕ Еще карту", callback_data="blackjack_hit"),
         InlineKeyboardButton("✋ Хватит", callback_data="blackjack_stand")],
        [InlineKeyboardButton("🏃‍♂️ Сдаться", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            game_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            game_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def blackjack_hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Игрок берет еще карту""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    game_data = context.user_data.get("blackjack_game")
    
    if not game_data:
        await query.edit_message_text("❌ Ошибка игры!")
        return
    
"# Добавляем карту игроку"
    game_data["player_cards"].append(draw_card())
    game_data["player_score"] = calculate_score(game_data["player_cards"])
    
"# Проверяем, не перебрал ли игрок"
    if game_data["player_score"] > 21:
        game_data["game_over"] = True
    
    await show_blackjack_game_from_query(query, context)

async def blackjack_stand(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Игрок останавливается""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    game_data = context.user_data.get("blackjack_game")
    
    if not game_data:
        await query.edit_message_text("❌ Ошибка игры!")
        return
    
"# Ход дилера"
    game_data["dealer_score"] = calculate_score(game_data["dealer_cards"])
    
"# Дилер берет карты, пока не наберет 17 или больше"
    while game_data["dealer_score"] < 17:
        game_data["dealer_cards"].append(draw_card())
        game_data["dealer_score"] = calculate_score(game_data["dealer_cards"])
    
    game_data["game_over"] = True
    await show_blackjack_game_from_query(query, context)

async def show_blackjack_game_from_query(query, context):
""""Обновить состояние игры Очко после хода""""
    game_data = context.user_data.get("blackjack_game")
    if not game_data:
        return
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
"# Если игра закончена, показываем финальный результат"
    if game_data["game_over"]:
"# Форматируем карты"
        player_cards_formatted = format_cards(game_data["player_cards"])
        dealer_cards_formatted = format_cards(game_data["dealer_cards"])
        
        dealer_final_score = calculate_score(game_data["dealer_cards"])
        player_score = game_data["player_score"]
        
        result_text = f"""
"🎴 *ОЧКО - РЕЗУЛЬТАТ*"

🎴 Ваши карты: {player_cards_formatted} ({player_score})
🎴 Карты дилера: {dealer_cards_formatted} ({dealer_final_score})

"""
        
"# Определяем победителя"
        if player_score > 21:
            result_text += f"❌ *ПЕРЕБОР!* Вы проиграли.\n💸 Ставка: *{format_number(game_data['bet_amount'])}*"
            user.loses += 1
        elif dealer_final_score > 21:
            result_text += f"✅ *ДИЛЕР ПЕРЕБРАЛ!* Вы выиграли.\n💰 Выигрыш: *{format_number(game_data['bet_amount'] * 2)}*"
            user.wins += 1
            user.balance += game_data["bet_amount"] * 2
            level_up = add_exp(user)
            await distribute_referral_bonus(user_id, game_data["bet_amount"], context)
        elif player_score > dealer_final_score:
            result_text += f"✅ *ВЫ ВЫИГРАЛИ!* {player_score} > {dealer_final_score}\n💰 Выигрыш: *{format_number(game_data['bet_amount'] * 2)}*"
            user.wins += 1
            user.balance += game_data["bet_amount"] * 2
            level_up = add_exp(user)
            await distribute_referral_bonus(user_id, game_data["bet_amount"], context)
        elif player_score < dealer_final_score:
            result_text += f"❌ *ВЫ ПРОИГРАЛИ!* {player_score} < {dealer_final_score}\n💸 Ставка: *{format_number(game_data['bet_amount'])}*"
            user.loses += 1
        else:
            result_text += f"🤝 *НИЧЬЯ!* {player_score} = {dealer_final_score}\n💰 Ставка возвращена: *{format_number(game_data['bet_amount'])}*"
            user.balance += game_data["bet_amount"]
        
        result_text += f"\n\n💳 Ваш баланс: *{format_number(user.balance)}*"
        
        if 'level_up' in locals() and level_up:
            result_text += f"\n\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
        
        await db.save_user(user)
        
        keyboard = [
            [InlineKeyboardButton("🃏 Сыграть еще раз", callback_data="blackjack_menu")],
            [InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
"# Игра продолжается"
    player_cards_formatted = format_cards(game_data["player_cards"])
    dealer_cards_formatted = format_cards([game_data["dealer_cards"][0]]) + " ? ?"
    
    game_text = f"""
🃏 *ОЧКО (21) - ВАШ ХОД*

🎴 Карты дилера: {dealer_cards_formatted}
🎴 Ваши карты: {player_cards_formatted}
🎯 Ваши очки: *{game_data['player_score']}*

💰 Ставка: *{format_number(game_data['bet_amount'])}*
💳 Ваш баланс: *{format_number(user.balance)}*

{f'⚠️ *ВНИМАНИЕ:* Сумма {game_data["player_score"]} - близко к 21!' if game_data['player_score'] > 15 else ''}
"""
    
    keyboard = [
        [InlineKeyboardButton("➕ Еще карту", callback_data="blackjack_hit"),
         InlineKeyboardButton("✋ Хватит", callback_data="blackjack_stand")],
        [InlineKeyboardButton("🏃‍♂️ Сдаться", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        game_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def bank_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню банка""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Рассчитываем ежедневный доход"
    daily_income = int(user.bank * 0.05)
    
    bank_text = f"""
"🏦 *БАНКОВСКАЯ СИСТЕМА*"

💰 На счету: *{format_number(user.bank)}*
💵 Баланс: *{format_number(user.balance)}*

"📈 *ЕЖЕДНЕВНЫЙ ДОХОД:*"
"- Процент: 5% в сутки"
- Доход сегодня: *{format_number(daily_income)}*
"- Начисление: каждый день в 00:00 по МСК"

"📤 *ПЕРЕВОДЫ:*"
"- Минимальный перевод: 100"
"- Комиссия: 0%"
"- Перевод по ID пользователя"

"💡 *СОВЕТ:* Храните деньги в банке для пассивного дохода!"
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Положить в банк", callback_data="bank_deposit"),
         InlineKeyboardButton("💳 Снять с банка", callback_data="bank_withdraw")],
        [InlineKeyboardButton("📤 Перевод другому игроку", callback_data="bank_transfer")],
        [InlineKeyboardButton("📊 История операций", callback_data="bank_history")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        bank_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def bank_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Положить деньги в банк""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
"f"🏦 *ВНЕСЕНИЕ В БАНК*\n\n""
        f"💰 Ваш баланс: *{format_number(user.balance)}*\n"
        f"🏦 В банке: *{format_number(user.bank)}*\n\n"
        f"Введите сумму для внесения (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["bank_action"] = "deposit"

async def bank_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Снять деньги с банка""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
"f"🏦 *СНЯТИЕ С БАНКА*\n\n""
        f"🏦 В банке: *{format_number(user.bank)}*\n"
        f"💰 На балансе: *{format_number(user.balance)}*\n\n"
        f"Введите сумму для снятия (мин. 100):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["bank_action"] = "withdraw"

async def bank_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Перевод другому игроку""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
"f"📤 *ПЕРЕВОД ДРУГОМУ ИГРОКУ*\n\n""
        f"💰 Ваш баланс: *{format_number(user.balance)}*\n\n"
        f"Введите ID получателя (цифры):",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["bank_action"] = "transfer_id"

async def process_bank_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка банковских операций""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    action = context.user_data.get("bank_action")
    
    if action == "deposit":
        try:
            amount = int(update.message.text)
            if amount < 100:
                await update.message.reply_text("❌ Минимальная сумма: 100!")
                return
            if amount > user.balance:
                await update.message.reply_text("❌ Недостаточно средств на балансе!")
                return
            
            user.balance -= amount
            user.bank += amount
            
            await db.save_user(user)
            
            result_text = f"""
"✅ *СРЕДСТВА ВНЕСЕНЫ В БАНК*"

💰 Сумма: *{format_number(amount)}*
🏦 В банке: *{format_number(user.bank)}*
💳 На балансе: *{format_number(user.balance)}*

📈 Ежедневный доход увеличился на *{format_number(int(amount * 0.05))}*
💡 Теперь вы будете получать *{format_number(int(user.bank * 0.05))}* каждый день!
"""
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
            return
    
    elif action == "withdraw":
        try:
            amount = int(update.message.text)
            if amount < 100:
                await update.message.reply_text("❌ Минимальная сумма: 100!")
                return
            if amount > user.bank:
                await update.message.reply_text("❌ Недостаточно средств в банке!")
                return
            
            user.bank -= amount
            user.balance += amount
            
            await db.save_user(user)
            
            result_text = f"""
"✅ *СРЕДСТВА СНЯТЫ С БАНКА*"

💰 Сумма: *{format_number(amount)}*
🏦 В банке: *{format_number(user.bank)}*
💳 На балансе: *{format_number(user.balance)}*

📉 Ежедневный доход уменьшился на *{format_number(int(amount * 0.05))}*
"""
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
            return
    
    elif action == "transfer_id":
        try:
            receiver_id = int(update.message.text)
            
            if receiver_id == user_id:
                await update.message.reply_text("❌ Нельзя переводить самому себе!")
                return
            
            context.user_data["transfer_receiver_id"] = receiver_id
            await update.message.reply_text(
"f"📤 *ПЕРЕВОД ИГРОКУ*\n\n""
                f"Получатель: ID `{receiver_id}`\n"
                f"💰 Ваш баланс: *{format_number(user.balance)}*\n\n"
                f"Введите сумму перевода (мин. 100):",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data["bank_action"] = "transfer_amount"
            return
        except ValueError:
            await update.message.reply_text("❌ Введите корректный ID!")
            return
    
    elif action == "transfer_amount":
        try:
            amount = int(update.message.text)
            receiver_id = context.user_data.get("transfer_receiver_id")
            
            if not receiver_id:
                await update.message.reply_text("❌ Ошибка! Начните перевод заново.")
                return
            
            if amount < 100:
                await update.message.reply_text("❌ Минимальная сумма: 100!")
                return
            if amount > user.balance:
                await update.message.reply_text("❌ Недостаточно средств!")
                return
            
"# Получаем получателя"
            receiver = await db.get_user(receiver_id)
            if not receiver:
                await update.message.reply_text("❌ Пользователь с таким ID не найден!")
                return
            
"# Выполняем перевод"
            user.balance -= amount
            receiver.balance += amount
            
            await db.save_user(user)
            await db.save_user(receiver)
            
"# Отправляем уведомление получателю"
            try:
                await context.bot.send_message(
                    chat_id=receiver_id,
                    text=f"""
"📥 *ВАМ ПЕРЕВЕЛИ ДЕНЬГИ!*"

👤 Отправитель: @{user.username if user.username else f'ID: {user_id}'}
💰 Сумма: *{format_number(amount)}*
💳 Ваш баланс: *{format_number(receiver.balance)}*

"💡 Не забудьте поблагодарить отправителя!"
""",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            result_text = f"""
"✅ *ПЕРЕВОД ВЫПОЛНЕН!*"

👤 Получатель: ID `{receiver_id}`
💰 Сумма: *{format_number(amount)}*
💳 Ваш баланс: *{format_number(user.balance)}*

"📤 Деньги успешно отправлены!"
"""
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
            return
    
    else:
        await update.message.reply_text("❌ Неизвестное действие!")
        return
    
"# Очищаем данные контекста"
    context.user_data.pop("bank_action", None)
    context.user_data.pop("transfer_receiver_id", None)
    
    keyboard = [[InlineKeyboardButton("🏦 В банк", callback_data="bank_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
"# БЛОК 6/6: Работа, ферма BTC, биржа, админ-панель и запуск бота"

async def jobs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню работы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Показываем текущую работу пользователя"
    current_job_text = ""
    if user.job:
        job_info = JOBS.get(user.job, {})
        job_name = job_info.get("name", "Неизвестно")
        current_job_text = f"💼 *Текущая работа:* {job_name}\n"
    else:
        current_job_text = "💼 *Текущая работа:* Не выбрана\n"
    
"# Проверяем, можно ли работать"
    can_work = True
    if user.last_work:
        time_since = datetime.datetime.now() - user.last_work
        if time_since.total_seconds() < 300:  # 5 минут
            can_work = False
            minutes_left = int((300 - time_since.total_seconds()) / 60)
            seconds_left = int(300 - time_since.total_seconds()) % 60
            current_job_text += f"⏳ *Доступно через:* {minutes_left} мин {seconds_left} сек\n"
    
    jobs_text = f"""
"👷 *СИСТЕМА РАБОТЫ*"

{current_job_text}
💰 Ваш баланс: *{format_number(user.balance)}*

"📊 *ДОСТУПНЫЕ РАБОТЫ:*"
"""
    
    keyboard = []
    for job_id, job_info in JOBS.items():
        button_text = f"{job_info['name']} ({format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])})"
        
"# Если у пользователя уже выбрана эта работа, помечаем"
        if user.job == job_id:
            button_text += " ✅"
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"job_{job_id}")])
    
    if user.job and can_work:
        keyboard.append([InlineKeyboardButton("💼 Выполнить работу", callback_data="do_work")])
    
    keyboard.append([InlineKeyboardButton("📊 Статистика работы", callback_data="work_stats")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        jobs_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Выбор работы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    job_id = query.data.split("_")[1]
    job_info = JOBS.get(job_id)
    
    if not job_info:
        await query.edit_message_text("❌ Работа не найдена!")
        return
    
"# Устанавливаем работу"
    user.job = job_id
    await db.save_user(user)
    
    await query.edit_message_text(
        f"""
"✅ *РАБОТА ВЫБРАНА!*"

{job_info['name']}
📝 {job_info['description']}

💰 Зарплата: *{format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])}*
🎁 Шанс BTC: *{job_info['btc_chance']}%*
"⏰ Перерыв между работой: 5 минут"

"💼 Используйте кнопку "Выполнить работу" для заработка"
"или команду /work"
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def do_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Выполнение работы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    if not user.job:
        await query.edit_message_text("❌ Сначала выберите работу!")
        return
    
"# Проверяем, можно ли работать"
    if user.last_work:
        time_since = datetime.datetime.now() - user.last_work
        if time_since.total_seconds() < 300:
            minutes_left = int((300 - time_since.total_seconds()) / 60)
            seconds_left = int(300 - time_since.total_seconds()) % 60
            await query.edit_message_text(
"f"⏳ Вы уже работали недавно!\n""
                f"Отдохните еще {minutes_left} минут {seconds_left} секунд",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    job_info = JOBS.get(user.job)
    if not job_info:
        await query.edit_message_text("❌ Информация о работе не найдена!")
        return
    
"# Начинаем анимацию работы"
    work_message = await query.edit_message_text(f"💼 {job_info['name']}...")
    
"# Процессы для разных работ"
    processes = {
        "digger": ["🔍 Ищем место для раскопок...", "⛏️ Копаем...", "💰 Нашли сундук!", "🎯 Открываем..."],
        "hacker": ["💻 Подключаемся к серверу...", "🔓 Взламываем защиту...", "📁 Ищем данные...", "💾 Скачиваем информацию..."],
        "miner": ["⛏️ Спускаемся в шахту...", "🔨 Добываем руду...", "🔥 Плавим...", "💰 Получаем криптовалюту..."],
        "trader": ["📈 Анализируем рынок...", "💹 Покупаем акции...", "📊 Следим за курсом...", "💰 Продаем с прибылью..."]
    }
    
    process_steps = processes.get(user.job, ["Работаем...", "Продолжаем...", "Завершаем..."])
    
"# Анимация процесса работы"
    for step in process_steps:
        await asyncio.sleep(1)
        try:
            await work_message.edit_text(f"💼 {step}")
        except:
            pass
    
"# Начисляем зарплату"
    salary = random.randint(job_info["min_salary"], job_info["max_salary"])
    user.balance += salary
    
"# Проверяем, найден ли BTC"
    btc_found = 0.0
    if random.random() < job_info["btc_chance"] / 100:
        btc_found = random.uniform(0.001, 0.01)
        user.btc += btc_found
    
"# Добавляем опыт"
    level_up = add_exp(user)
    
"# Обновляем время последней работы"
    user.last_work = datetime.datetime.now()
    
    await db.save_user(user)
    
"# Формируем результат"
    result_text = f"""
"✅ *РАБОТА ВЫПОЛНЕНА!*"

💼 Профессия: {job_info['name']}
💰 Зарплата: *{format_number(salary)}*
💰 Баланс: *{format_number(user.balance)}*
"""
    
    if btc_found > 0:
        result_text += f"\n🎉 *ВЫ НАШЛИ BTC!* +{btc_found:.4f} ₿\n"
        result_text += f"₿ Всего BTC: *{user.btc:.4f}*"
    
    if level_up:
        result_text += f"\n\n🎊 *УРОВЕНЬ ПОВЫШЕН!*\nТеперь у вас {user.level} уровень!"
    
    result_text += f"\n\n⏳ Следующая работа через 5 минут"
    
    keyboard = [
        [InlineKeyboardButton("💼 Еще поработать", callback_data="jobs_menu")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await work_message.edit_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def work_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика работы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Считаем примерный заработок с работы"
    total_earned = user.balance + user.bank - 10000  # Примерный расчет
    
    stats_text = f"""
"📊 *СТАТИСТИКА РАБОТЫ*"

💼 Текущая работа: {JOBS.get(user.job, {}).get('name', 'Не выбрана') if user.job else 'Не выбрана'}
💰 Всего заработано: *{format_number(total_earned)}*
₿ Всего найдено BTC: *{user.btc:.4f}*

"⏰ *ИНФОРМАЦИЯ:*"
"- Работать можно каждые 5 минут"
"- Шанс найти BTC: 9%"
"- Зарплата зависит от профессии"
"- Опыт начисляется за работу"

"💡 *СОВЕТЫ:*"
"1. Выбирайте работу с высокой зарплатой"
"2. Работайте регулярно для стабильного дохода"
"3. BTC можно продать на бирже"
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="jobs_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню фермы BTC""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем ферму пользователя"
    farm_items = await db.get_user_farm(user_id)
    
"# Рассчитываем доход"
    btc_income = await calculate_gpu_income(user_id)
    
"# Формируем информацию о ферме"
    farm_info = ""
    total_income_per_hour = 0.0
    
    if farm_items:
        for farm in farm_items:
            if farm.gpu_type in GPU_TYPES:
                gpu_data = GPU_TYPES[farm.gpu_type]
                income_per_hour = gpu_data["income_per_hour"] * farm.quantity
                total_income_per_hour += income_per_hour
                farm_info += f"\n{gpu_data['name']}: {farm.quantity} шт. (+{income_per_hour:.3f} BTC/час)"
    else:
        farm_info = "📭 У вас нет видеокарт"
    
    farm_text = f"""
"🖥 *ФЕРМА BTC*"

💰 Накоплено: *{btc_income:.4f} BTC*
₿ Всего BTC: *{user.btc:.4f}*
📈 Доход в час: *{total_income_per_hour:.3f} BTC*

{farm_info}

💵 Баланс: *{format_number(user.balance)}*
📊 Курс BTC: *{format_number(btc_price)}*

"💡 *КАК РАБОТАЕТ:*"
"1. Купите видеокарты"
"2. Они майнят BTC 24/7"
"3. Собирайте накопленный BTC"
"4. Продавайте на бирже или храните"
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")],
        [InlineKeyboardButton("🖥 Купить видеокарты", callback_data="farm_buy_menu")],
        [InlineKeyboardButton("📊 Статистика фермы", callback_data="farm_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        farm_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Собрать доход с фермы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Рассчитываем доход"
    btc_income = await calculate_gpu_income(user_id)
    
    if btc_income <= 0:
        await query.answer("❌ Нет накопленного дохода!", show_alert=True)
        return
    
"# Начисляем BTC"
    user.btc += btc_income
    
"# Обновляем время сбора для всех видеокарт"
    farm_items = await db.get_user_farm(user_id)
    current_time = datetime.datetime.now()
    
    for farm in farm_items:
        farm.last_collected = current_time
        await db.update_farm(farm)
    
    await db.save_user(user)
    
"# Рассчитываем эквивалент в деньгах"
    money_value = int(btc_income * btc_price)
    
    await query.edit_message_text(
        f"""
"✅ *ДОХОД СОБРАН!*"

💰 Собрано: *{btc_income:.4f} BTC*
₿ Всего BTC: *{user.btc:.4f}*

💰 В денежном эквиваленте: *{format_number(money_value)}*
📊 По курсу: 1 BTC = {format_number(btc_price)}

"💡 *СОВЕТ:* Вы можете продать BTC на бирже или продолжать накапливать!"
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Меню покупки видеокарт""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем текущие видеокарты пользователя"
    farm_items = await db.get_user_farm(user_id)
    gpu_quantities = {farm.gpu_type: farm.quantity for farm in farm_items}
    
    farm_text = f"""
"🖥 *ПОКУПКА ВИДЕОКАРТ*"

💰 Ваш баланс: *{format_number(user.balance)}*
₿ Ваш BTC: *{user.btc:.4f}*

"💡 *ВЫБЕРИТЕ ВИДЕОКАРТУ:*"
"""
    
    keyboard = []
    
    for gpu_type, gpu_data in GPU_TYPES.items():
        quantity = gpu_quantities.get(gpu_type, 0)
        
"# Рассчитываем цену с учетом роста"
        price = int(gpu_data["base_price"] * (gpu_data["price_increase"] ** quantity))
        
"# Формируем текст кнопки"
        button_text = f"{gpu_data['name']} - {format_number(price)}"
        
"# Проверяем, достигнут ли лимит"
        if quantity >= gpu_data["max_quantity"]:
            button_text += " (MAX)"
            callback_data = "none"
        else:
            callback_data = f"buy_gpu_{gpu_type}"
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
"# Добавляем информацию о видеокарте в текст"
        farm_text += f"\n{gpu_data['name']}:"
        farm_text += f"\n  📈 Доходность: {gpu_data['income_per_hour']} BTC/час"
        farm_text += f"\n  💰 Базовая цена: {format_number(gpu_data['base_price'])}"
        farm_text += f"\n  🏷 У вас: {quantity}/{gpu_data['max_quantity']}"
        farm_text += f"\n  📊 Следующая цена: {format_number(price)}"
        farm_text += f"\n"
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="farm_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        farm_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def buy_gpu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Покупка видеокарты""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    gpu_type = query.data.split("_")[2]
    gpu_data = GPU_TYPES.get(gpu_type)
    
    if not gpu_data:
        await query.edit_message_text("❌ Видеокарта не найдена!")
        return
    
"# Получаем текущее количество видеокарт"
    farm_items = await db.get_user_farm(user_id)
    gpu_quantities = {farm.gpu_type: farm.quantity for farm in farm_items}
    quantity = gpu_quantities.get(gpu_type, 0)
    
"# Проверяем лимит"
    if quantity >= gpu_data["max_quantity"]:
        await query.answer("❌ Достигнут лимит покупки этой видеокарты!", show_alert=True)
        return
    
"# Рассчитываем цену"
    price = int(gpu_data["base_price"] * (gpu_data["price_increase"] ** quantity))
    
"# Проверяем баланс"
    if price > user.balance:
        await query.answer("❌ Недостаточно средств!", show_alert=True)
        return
    
"# Списание денег"
    user.balance -= price
    
"# Добавляем/обновляем видеокарту"
    existing_farm = None
    for farm in farm_items:
        if farm.gpu_type == gpu_type:
            existing_farm = farm
            break
    
    if existing_farm:
        existing_farm.quantity += 1
        await db.update_farm(existing_farm)
    else:
        new_farm = BTCFarm(
            user_id=user_id,
            gpu_type=gpu_type,
            quantity=1,
            last_collected=datetime.datetime.now()
        )
        await db.update_farm(new_farm)
    
    await db.save_user(user)
    
"# Рассчитываем новый доход"
    new_income_per_hour = gpu_data["income_per_hour"] * (quantity + 1)
    
    await query.edit_message_text(
        f"""
"✅ *ВИДЕОКАРТА КУПЛЕНА!*"

{gpu_data['name']}
💰 Стоимость: *{format_number(price)}*
📈 Доходность: +{gpu_data['income_per_hour']} BTC/час
📊 Всего таких карт: {quantity + 1}/{gpu_data['max_quantity']}

💰 Баланс: *{format_number(user.balance)}*
₿ Общий доход с фермы: +{new_income_per_hour:.3f} BTC/час

"💡 *СОВЕТ:* Не забывайте регулярно собирать доход!"
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Статистика фермы""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
"# Получаем ферму пользователя"
    farm_items = await db.get_user_farm(user_id)
    
    if not farm_items:
        await query.edit_message_text(
""📭 *ВАША ФЕРМА ПУСТА*\n\n""
""Купите видеокарты в магазине, чтобы начать майнинг BTC!","
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
"# Рассчитываем статистику"
    total_gpus = 0
    total_invested = 0
    total_income_per_hour = 0.0
    
    stats_text = "📊 *СТАТИСТИКА ФЕРМЫ*\n\n"
    
    for farm in farm_items:
        if farm.gpu_type in GPU_TYPES:
            gpu_data = GPU_TYPES[farm.gpu_type]
            total_gpus += farm.quantity
            
"# Рассчитываем общие вложения в эту модель"
            total_price_for_model = 0
            for i in range(farm.quantity):
                total_price_for_model += int(gpu_data["base_price"] * (gpu_data["price_increase"] ** i))
            
            total_invested += total_price_for_model
            income_per_hour = gpu_data["income_per_hour"] * farm.quantity
            total_income_per_hour += income_per_hour
            
            stats_text += f"{gpu_data['name']}:\n"
            stats_text += f"  📊 Количество: {farm.quantity}\n"
            stats_text += f"  💰 Вложено: {format_number(total_price_for_model)}\n"
            stats_text += f"  📈 Доход/час: {income_per_hour:.3f} BTC\n"
            stats_text += f"  💵 Доход/час в $: {format_number(int(income_per_hour * btc_price))}\n\n"
    
"# Рассчитываем окупаемость"
    daily_income_btc = total_income_per_hour * 24
    daily_income_money = int(daily_income_btc * btc_price)
    
    if daily_income_money > 0:
        roi_days = total_invested / daily_income_money
    else:
        roi_days = 0
    
    stats_text += f"📈 *ОБЩАЯ СТАТИСТИКА:*\n"
    stats_text += f"💻 Всего видеокарт: {total_gpus}\n"
    stats_text += f"💰 Всего вложено: {format_number(total_invested)}\n"
    stats_text += f"📈 Доход/час: {total_income_per_hour:.3f} BTC\n"
    stats_text += f"💵 Доход/день: {format_number(daily_income_money)}\n"
    
    if roi_days > 0:
        stats_text += f"📅 Окупаемость: {roi_days:.1f} дней\n"
    
    stats_text += f"\n💡 *СОВЕТ:* Собирайте доход регулярно для максимальной прибыли!"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="farm_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def btc_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Биржа BTC""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    global btc_price
    
    market_text = f"""
"📊 *БИРЖА BTC*"

💰 Текущий курс: *1 BTC = {format_number(btc_price)}*
₿ Ваш баланс BTC: *{user.btc:.4f}*
💵 Ваш баланс: *{format_number(user.balance)}*

"📈 *ИНФОРМАЦИЯ:*"
"- Курс обновляется каждый час"
"- Диапазон курса: 10,000 - 150,000"
"- Комиссия на бирже: 0%"
"- Можно покупать и продавать"

"💡 *СТРАТЕГИЯ:*"
"- Покупайте, когда курс низкий"
"- Продавайте, когда курс высокий"
"- Храните BTC для долгосрочной прибыли"
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Купить BTC", callback_data="btc_buy"),
         InlineKeyboardButton("💸 Продать BTC", callback_data="btc_sell")],
        [InlineKeyboardButton("🔄 Обновить курс", callback_data="btc_market")],
        [InlineKeyboardButton("📊 График курса", callback_data="btc_chart")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        market_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def btc_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Покупка BTC""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    global btc_price
    
    await query.edit_message_text(
        f"""
"💰 *ПОКУПКА BTC*"

📊 Текущий курс: 1 BTC = {format_number(btc_price)}
💵 Ваш баланс: *{format_number(user.balance)}*
₿ Ваш BTC: *{user.btc:.4f}*

"💡 *КАК КУПИТЬ:*"
1. Введите сумму в деньгах (например: 1000)
2. Или введите количество BTC (например: 0.01)

"Минимальная покупка: 100"
"""
    )
    context.user_data["btc_action"] = "buy"

async def btc_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Продажа BTC""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    global btc_price
    
    await query.edit_message_text(
        f"""
"💸 *ПРОДАЖА BTC*"

📊 Текущий курс: 1 BTC = {format_number(btc_price)}
₿ Ваш баланс BTC: *{user.btc:.4f}*
💵 Ваш баланс: *{format_number(user.balance)}*

"💡 *КАК ПРОДАТЬ:*"
1. Введите количество BTC (например: 0.01)
2. Или введите сумму в деньгах (например: 1000)

"Минимальная продажа: 0.001 BTC"
"""
    )
    context.user_data["btc_action"] = "sell"

async def btc_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""График курса BTC""""
    query = update.callback_query
    await query.answer()
    
    global btc_price
    
"# Генерируем "исторические" данные для графика"
    history = []
    current_price = btc_price
    
    for i in range(10):
        change = random.uniform(-0.1, 0.1)  # Изменение на ±10%
        historical_price = int(current_price * (1 + change))
        history.append(historical_price)
    
"# Формируем текстовый график"
    chart_text = "📈 *ИСТОРИЯ КУРСА BTC*\n\n"
    
    for i, price in enumerate(reversed(history)):
        bar_length = int((price / max(history)) * 20)
        bar = "█" * bar_length
        chart_text += f"{10-i} ч назад: {format_number(price)} {bar}\n"
    
    chart_text += f"\n📊 *ТЕКУЩИЙ КУРС:* {format_number(btc_price)}"
    chart_text += f"\n📈 *ИЗМЕНЕНИЕ ЗА ЧАС:* {random.uniform(-5, 5):.1f}%"
    chart_text += f"\n🎯 *МИНИМАЛЬНЫЙ:* {format_number(min(history))}"
    chart_text += f"\n🚀 *МАКСИМАЛЬНЫЙ:* {format_number(max(history))}"
    
    chart_text += f"\n\n💡 *ПРОГНОЗ:* Курс может {'расти' if random.random() > 0.5 else 'падать'} в ближайшие часы"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="btc_market")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        chart_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def process_btc_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка торговли BTC""""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    action = context.user_data.get("btc_action")
    if not action:
        await update.message.reply_text("❌ Ошибка! Начните заново.")
        return
    
    try:
        input_text = update.message.text
        
"# Пытаемся понять, что ввел пользователь"
        if "." in input_text:  # Вероятно, количество BTC
            btc_amount = float(input_text)
            money_amount = int(btc_amount * btc_price)
        else:  # Вероятно, сумма в деньгах
            money_amount = int(input_text)
            btc_amount = money_amount / btc_price
        
        if action == "buy":
            if money_amount < 100:
                await update.message.reply_text("❌ Минимальная покупка: 100!")
                return
            
            if money_amount > user.balance:
                await update.message.reply_text("❌ Недостаточно средств!")
                return
            
"# Покупаем BTC"
            user.balance -= money_amount
            user.btc += btc_amount
            
            await db.save_user(user)
            
            result_text = f"""
"✅ *BTC КУПЛЕН!*"

💰 Куплено: *{btc_amount:.4f} BTC*
💸 Потрачено: *{format_number(money_amount)}*
₿ Баланс BTC: *{user.btc:.4f}*
💵 Баланс: *{format_number(user.balance)}*

📊 Курс покупки: 1 BTC = {format_number(btc_price)}
"💡 Теперь вы можете хранить BTC или продать когда курс вырастет"
"""
        
        elif action == "sell":
            if btc_amount < 0.001:
                await update.message.reply_text("❌ Минимальная продажа: 0.001 BTC!")
                return
            
            if btc_amount > user.btc:
                await update.message.reply_text("❌ Недостаточно BTC!")
                return
            
"# Продаем BTC"
            user.btc -= btc_amount
            user.balance += money_amount
            
            await db.save_user(user)
            
            result_text = f"""
"✅ *BTC ПРОДАН!*"

💰 Продано: *{btc_amount:.4f} BTC*
💸 Получено: *{format_number(money_amount)}*
₿ Баланс BTC: *{user.btc:.4f}*
💵 Баланс: *{format_number(user.balance)}*

📊 Курс продажи: 1 BTC = {format_number(btc_price)}
"💡 Вы успешно продали BTC по хорошему курсу!"
"""
        else:
            await update.message.reply_text("❌ Неизвестное действие!")
            return
        
"# Очищаем данные контекста"
        context.user_data.pop("btc_action", None)
        
        keyboard = [[InlineKeyboardButton("📊 На биржу", callback_data="btc_market")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
    except Exception as e:
        logger.error(f"Ошибка торговли BTC: {e}")
        await update.message.reply_text("❌ Ошибка при обработке запроса!")

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Админ-панель""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
"# Получаем статистику"
    all_users = await db.get_all_users()
    total_users = len(all_users)
    total_balance = sum(user.balance for user in all_users)
    total_bank = sum(user.bank for user in all_users)
    total_btc = sum(user.btc for user in all_users)
    
    admin_text = f"""
"👑 *АДМИН ПАНЕЛЬ*"

"📊 *СТАТИСТИКА БОТА:*"
👥 Всего пользователей: *{total_users}*
💰 Общий баланс: *{format_number(total_balance)}*
🏦 Общий банк: *{format_number(total_bank)}*
₿ Общий BTC: *{total_btc:.4f}*
📈 Курс BTC: *{format_number(btc_price)}*

"⚙️ *УПРАВЛЕНИЕ:*"
"""
    
    keyboard = [
        [InlineKeyboardButton("👤 Поиск пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton("💰 Выдать деньги", callback_data="admin_give_money"),
         InlineKeyboardButton("💸 Забрать деньги", callback_data="admin_take_money")],
        [InlineKeyboardButton("₿ Выдать BTC", callback_data="admin_give_btc"),
         InlineKeyboardButton("🎫 Создать промокод", callback_data="create_promo_admin")],
        [InlineKeyboardButton("🚫 Забанить", callback_data="admin_ban"),
         InlineKeyboardButton("✅ Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("📊 Полная статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🔄 Обновить курс BTC", callback_data="admin_update_btc")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        admin_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_find_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Поиск пользователя для админа""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
""👤 *ПОИСК ПОЛЬЗОВАТЕЛЯ*\n\n""
""Введите ID пользователя или @username:","
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "find_user"

async def admin_give_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Выдать деньги пользователю""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
""💰 *ВЫДАЧА ДЕНЕГ*\n\n""
""Введите ID пользователя:","
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_money_id"

async def admin_take_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Забрать деньги у пользователя""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
""💸 *ЗАБИРАНИЕ ДЕНЕГ*\n\n""
""Введите ID пользователя:","
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "take_money_id"

async def admin_give_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Выдать BTC пользователю""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
""₿ *ВЫДАЧА BTC*\n\n""
""Введите ID пользователя:","
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_btc_id"

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Забанить пользователя""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
""🚫 *БАН ПОЛЬЗОВАТЕЛЯ*\n\n""
""Введите ID пользователя:","
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "ban_user"

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Разбанить пользователя""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
""✅ *РАЗБАН ПОЛЬЗОВАТЕЛЯ*\n\n""
""Введите ID пользователя:","
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "unban_user"

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Полная статистика бота""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
"# Получаем полную статистику"
    all_users = await db.get_all_users()
    top_users = await db.get_top_users(10)
    
    total_users = len(all_users)
    total_balance = sum(user.balance for user in all_users)
    total_bank = sum(user.bank for user in all_users)
    total_btc = sum(user.btc for user in all_users)
    total_wins = sum(user.wins for user in all_users)
    total_loses = sum(user.loses for user in all_users)
    banned_users = sum(1 for user in all_users if user.is_banned)
    
"# Новые пользователи за последние 24 часа"
    now = datetime.datetime.now()
    new_users_24h = sum(1 for user in all_users if (now - user.registered).total_seconds() < 86400)
    
    stats_text = f"""
"📊 *ПОЛНАЯ СТАТИСТИКА БОТА*"

"👥 *ПОЛЬЗОВАТЕЛИ:*"
• Всего: *{total_users}*
• Новых за 24ч: *{new_users_24h}*
• Забанено: *{banned_users}*
• Активных: *{total_users - banned_users}*

"💰 *ФИНАНСЫ:*"
• Общий баланс: *{format_number(total_balance)}*
• Общий банк: *{format_number(total_bank)}*
• Общий BTC: *{total_btc:.4f}*
• Стоимость BTC: *{format_number(int(total_btc * btc_price))}*
• Всего денег: *{format_number(total_balance + total_bank + int(total_btc * btc_price))}*

"🎮 *ИГРЫ:*"
• Всего побед: *{total_wins}*
• Всего поражений: *{total_loses}*
• Всего игр: *{total_wins + total_loses}*
• Винрейт: *{(total_wins / (total_wins + total_loses) * 100) if (total_wins + total_loses) > 0 else 0:.1f}%*

"🏆 *ТОП-10 ИГРОКОВ:*"
"""
    
    for i, user in enumerate(top_users[:10], 1):
        total = user.balance + user.bank
        stats_text += f"{i}. @{user.username or f'ID:{user.user_id}'} - {format_number(total)}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_update_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обновить курс BTC""""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    global btc_price
    old_price = btc_price
    btc_price = random.randint(10000, 150000)
    
    await query.edit_message_text(
"f"🔄 *КУРС BTC ОБНОВЛЕН*\n\n""
        f"📊 Старый курс: {format_number(old_price)}\n"
        f"📈 Новый курс: *{format_number(btc_price)}*\n"
        f"📉 Изменение: {((btc_price - old_price) / old_price * 100):.1f}%",
        parse_mode=ParseMode.MARKDOWN
    )

async def process_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка действий админа""""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора!")
        return
    
    action = context.user_data.get("admin_action")
    text = update.message.text.strip()
    
    if action == "find_user":
        try:
            target_id = int(text)
            user = await db.get_user(target_id)
        except ValueError:
"# Ищем по username"
            target_id = None
            all_users = await db.get_all_users()
            for u in all_users:
                if u.username and text.lower() in u.username.lower():
                    target_id = u.user_id
                    user = u
                    break
        
        if not target_id or not user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
        
        profile_text = f"""
👑 *ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ* (Админ)

🆔 ID: `{user.user_id}`
👤 Имя: @{user.username if user.username else "Нет"}
💰 Баланс: *{format_number(user.balance)}*
🏦 Банк: *{format_number(user.bank)}*
₿ BTC: *{user.btc:.4f}*

🏆 Уровень: *{user.level}*
⭐ EXP: *{user.exp}*
🎯 Побед: *{user.wins}*
💔 Поражений: *{user.loses}*
👥 Рефералов: *{user.total_referrals}*

📅 Регистрация: {user.registered.strftime('%d.%m.%Y %H:%M')}
🚫 Статус: {"Забанен" if user.is_banned else "Активен"}
"""
        
        keyboard = [
            [InlineKeyboardButton("💰 Выдать деньги", callback_data=f"admin_give_{target_id}"),
             InlineKeyboardButton("💸 Забрать деньги", callback_data=f"admin_take_{target_id}")],
            [InlineKeyboardButton("₿ Выдать BTC", callback_data=f"admin_givebtc_{target_id}"),
             InlineKeyboardButton("🚫 Забанить" if not user.is_banned else "✅ Разбанить", 
                                 callback_data=f"admin_ban_{target_id}" if not user.is_banned else f"admin_unban_{target_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            profile_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif action in ["give_money_id", "take_money_id", "give_btc_id", "ban_user", "unban_user"]:
        try:
            target_id = int(text)
            context.user_data["admin_target_id"] = target_id
            
            if action == "give_money_id":
                await update.message.reply_text("Введите сумму для выдачи:")
                context.user_data["admin_action"] = "give_money_amount"
            elif action == "take_money_id":
                await update.message.reply_text("Введите сумму для изъятия:")
                context.user_data["admin_action"] = "take_money_amount"
            elif action == "give_btc_id":
                await update.message.reply_text("Введите количество BTC:")
                context.user_data["admin_action"] = "give_btc_amount"
            elif action == "ban_user":
                await update.message.reply_text("Введите причину бана:")
                context.user_data["admin_action"] = "ban_reason"
            elif action == "unban_user":
                user = await db.get_user(target_id)
                if user:
                    user.is_banned = False
                    await db.save_user(user)
                    await update.message.reply_text(f"✅ Пользователь {target_id} разбанен!")
                else:
                    await update.message.reply_text("❌ Пользователь не найден!")
                context.user_data.clear()
        
        except ValueError:
            await update.message.reply_text("❌ Введите корректный ID!")

async def process_admin_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка сумм для админ-действий""""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора!")
        return
    
    action = context.user_data.get("admin_action")
    target_id = context.user_data.get("admin_target_id")
    text = update.message.text.strip()
    
    if not target_id:
        await update.message.reply_text("❌ Ошибка! Начните заново.")
        return
    
    user = await db.get_user(target_id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден!")
        context.user_data.clear()
        return
    
    if action == "give_money_amount":
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ Сумма должна быть положительной!")
                return
            
            user.balance += amount
            await db.save_user(user)
            
            await update.message.reply_text(
"f"✅ Деньги выданы!\n""
                f"👤 Пользователь: {target_id}\n"
                f"💰 Сумма: {format_number(amount)}\n"
                f"💳 Новый баланс: {format_number(user.balance)}"
            )
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "take_money_amount":
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ Сумма должна быть положительной!")
                return
            
            if amount > user.balance:
                await update.message.reply_text("❌ У пользователя недостаточно средств!")
                return
            
            user.balance -= amount
            await db.save_user(user)
            
            await update.message.reply_text(
"f"✅ Деньги изъяты!\n""
                f"👤 Пользователь: {target_id}\n"
                f"💰 Сумма: {format_number(amount)}\n"
                f"💳 Новый баланс: {format_number(user.balance)}"
            )
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "give_btc_amount":
        try:
            btc_amount = float(text)
            if btc_amount <= 0:
                await update.message.reply_text("❌ Количество должно быть положительным!")
                return
            
            user.btc += btc_amount
            await db.save_user(user)
            
            await update.message.reply_text(
"f"✅ BTC выданы!\n""
                f"👤 Пользователь: {target_id}\n"
                f"₿ Количество: {btc_amount:.4f} BTC\n"
                f"₿ Новый баланс BTC: {user.btc:.4f}"
            )
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "ban_reason":
        reason = text
        user.is_banned = True
        await db.save_user(user)
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🚫 *ВЫ ЗАБАНЕНЫ!*\n\nПричина: {reason}\n\nПо всем вопросам обращайтесь к администрации.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        await update.message.reply_text(
            f"✅ Пользователь {target_id} забанен!\n"
            f"📝 Причина: {reason}"
        )
    
    context.user_data.clear()

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработка текстовых сообщений""""
    user_id = update.effective_user.id
    text = update.message.text
    
"# Проверяем различные состояния пользователя"
    if "roulette_type" in context.user_data:
        await process_roulette(update, context)
        context.user_data.pop("roulette_type", None)
    
    elif "football_type" in context.user_data:
        await process_football(update, context)
        context.user_data.pop("football_type", None)
    
    elif "dice_type" in context.user_data:
        await process_dice(update, context)
        context.user_data.pop("dice_type", None)
    
    elif "awaiting_crash_bet" in context.user_data:
        await process_crash(update, context)
        context.user_data.pop("awaiting_crash_bet", None)
    
    elif "awaiting_mines_bet" in context.user_data:
        await process_mines_start(update, context)
        context.user_data.pop("awaiting_mines_bet", None)
    
    elif "awaiting_diamonds_bet" in context.user_data:
        await process_diamonds_start(update, context)
        context.user_data.pop("awaiting_diamonds_bet", None)
    
    elif "awaiting_blackjack_bet" in context.user_data:
        await process_blackjack_start(update, context)
        context.user_data.pop("awaiting_blackjack_bet", None)
    
    elif "bank_action" in context.user_data:
        await process_bank_action(update, context)
    
    elif "btc_action" in context.user_data:
        await process_btc_trade(update, context)
    
    elif "admin_action" in context.user_data:
        action = context.user_data["admin_action"]
        if action in ["give_money_amount", "take_money_amount", "give_btc_amount", "ban_reason"]:
            await process_admin_amount(update, context)
        else:
            await process_admin_action(update, context)
    
    elif "awaiting_promo" in context.user_data:
        await process_promo_code(update, context, text.upper())
        context.user_data.pop("awaiting_promo", None)
    
    elif text.lower().startswith("/promo"):
"# Обработка команды /promo"
        parts = text.split()
        if len(parts) >= 2:
            promo_code = parts[1].upper()
            await process_promo_code(update, context, promo_code)
        else:
            await update.message.reply_text(
                "🎫 *Использование:* /promo [КОД]\n\n"
""Пример: `/promo WELCOME100`","
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif text.lower() == "/start":
        await start(update, context)
    
    elif text.lower() == "/menu":
        await show_main_menu(update, context)
    
    elif text.lower() == "/help":
        await help_command(update, context)
    
    elif text.lower() == "/profile":
        user = await db.get_user(user_id)
        if user:
            query = type('obj', (object,), {'from_user': type('obj', (object,), {'id': user_id})(), 'edit_message_text': None})()
            await show_profile(update, context)
        else:
            await update.message.reply_text("❌ Сначала зарегистрируйтесь через /start")
    
    elif text.lower() == "/balance":
        user = await db.get_user(user_id)
        if user:
            await update.message.reply_text(
"f"💰 *ВАШ БАЛАНС*\n\n""
                f"💳 Баланс: *{format_number(user.balance)}*\n"
                f"🏦 В банке: *{format_number(user.bank)}*\n"
                f"₿ BTC: *{user.btc:.4f}*",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Сначала зарегистрируйтесь через /start")
    
    elif text.lower() == "/bonus":
        await bonus_command(update, context)
    
    elif text.lower() == "/work":
        await do_work(update, context)
    
    elif text.lower() == "/ref":
        await referral_menu(update, context)
    
    elif text.lower() == "/top":
        top_users = await db.get_top_users(10)
        top_text = "🏆 *ТОП-10 ИГРОКОВ*\n\n"
        
        for i, user in enumerate(top_users, 1):
            total = user.balance + user.bank
            username = user.username or f"ID:{user.user_id}"
            top_text += f"{i}. @{username} - {format_number(total)}\n"
        
        await update.message.reply_text(top_text, parse_mode=ParseMode.MARKDOWN)
    
    else:
        user = await db.get_user(user_id)
        if user:
            await update.message.reply_text(
""🤖 *VIBE BET БОТ*\n\n""
""Используйте /menu для доступа ко всем функциям\n""
""или /help для списка всех команд","
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
                    [InlineKeyboardButton("📋 Помощь", callback_data="help")]
                ])
            )
        else:
            await update.message.reply_text(
""🎰 *Добро пожаловать в Vibe Bet!*\n\n""
""Для начала игры нажмите /start","
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Начать", callback_data="start")]
                ])
            )

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
""""Обработчик кнопки помощи""""
    query = update.callback_query
    await query.answer()
    await help_command(update, context)

async def main():
""""Главная функция запуска бота""""
"# Подключаемся к базе данных"
    await db.connect()
    logger.info("База данных подключена")
    
"# Создаем приложение"
    application = Application.builder().token(TOKEN).build()
    
"# Регистрируем обработчики команд"
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("profile", show_profile))
    application.add_handler(CommandHandler("balance", show_main_menu))
    application.add_handler(CommandHandler("bonus", bonus_menu))
    application.add_handler(CommandHandler("work", do_work))
    application.add_handler(CommandHandler("ref", referral_menu))
    application.add_handler(CommandHandler("promo", activate_promo_command))
    application.add_handler(CommandHandler("top", show_main_menu))
    
"# Регистрируем обработчики callback-запросов"
    application.add_handler(CallbackQueryHandler(register_callback, pattern="^register$"))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(show_stats_detailed, pattern="^stats_detailed$"))
    application.add_handler(CallbackQueryHandler(bonus_menu, pattern="^bonus_menu$"))
    application.add_handler(CallbackQueryHandler(claim_bonus, pattern="^claim_bonus$"))
    application.add_handler(CallbackQueryHandler(referral_menu, pattern="^referral_menu$"))
    application.add_handler(CallbackQueryHandler(my_referrals, pattern="^my_referrals$"))
    application.add_handler(CallbackQueryHandler(copy_ref_link, pattern="^copy_ref_link$"))
    application.add_handler(CallbackQueryHandler(promo_menu, pattern="^promo_menu$"))
    application.add_handler(CallbackQueryHandler(activate_promo_callback, pattern="^activate_promo$"))
    application.add_handler(CallbackQueryHandler(my_promocodes, pattern="^my_promocodes$"))
    application.add_handler(CallbackQueryHandler(create_promo_admin, pattern="^create_promo_admin$"))
"# Промокоды"
    application.add_handler(CallbackQueryHandler(create_promo_type, pattern="^create_promo_"))
    application.add_handler(CallbackQueryHandler(set_promo_expire, pattern="^expire_"))

"# Игры"
    application.add_handler(CallbackQueryHandler(show_games_menu, pattern="^games_menu$"))
    application.add_handler(CallbackQueryHandler(games_stats, pattern="^games_stats$"))
    application.add_handler(CallbackQueryHandler(roulette_menu, pattern="^roulette_menu$"))
    application.add_handler(CallbackQueryHandler(roulette_stats, pattern="^roulette_stats$"))
    application.add_handler(CallbackQueryHandler(roulette_bet, pattern="^roulette_"))
    application.add_handler(CallbackQueryHandler(football_menu, pattern="^football_menu$"))
    application.add_handler(CallbackQueryHandler(football_stats, pattern="^football_stats$"))
    application.add_handler(CallbackQueryHandler(football_bet, pattern="^football_"))
    application.add_handler(CallbackQueryHandler(dice_menu, pattern="^dice_menu$"))
    application.add_handler(CallbackQueryHandler(dice_stats, pattern="^dice_stats$"))
    application.add_handler(CallbackQueryHandler(dice_bet, pattern="^dice_"))
    application.add_handler(CallbackQueryHandler(crash_menu, pattern="^crash_menu$"))
    application.add_handler(CallbackQueryHandler(crash_stats, pattern="^crash_stats$"))
    application.add_handler(CallbackQueryHandler(crash_start, pattern="^crash_start$"))
    application.add_handler(CallbackQueryHandler(mines_menu, pattern="^mines_menu$"))
    application.add_handler(CallbackQueryHandler(mines_stats, pattern="^mines_stats$"))
    application.add_handler(CallbackQueryHandler(mines_start, pattern="^mines_start$"))
    application.add_handler(CallbackQueryHandler(process_mine_click, pattern="^mine_"))
    application.add_handler(CallbackQueryHandler(diamonds_menu, pattern="^diamonds_menu$"))
    application.add_handler(CallbackQueryHandler(diamonds_stats, pattern="^diamonds_stats$"))
    application.add_handler(CallbackQueryHandler(diamonds_start, pattern="^diamonds_start$"))
    application.add_handler(CallbackQueryHandler(process_diamond_click, pattern="^diamond_"))
    application.add_handler(CallbackQueryHandler(blackjack_menu, pattern="^blackjack_menu$"))
    application.add_handler(CallbackQueryHandler(blackjack_stats, pattern="^blackjack_stats$"))
    application.add_handler(CallbackQueryHandler(blackjack_start, pattern="^blackjack_start$"))
    application.add_handler(CallbackQueryHandler(blackjack_hit, pattern="^blackjack_hit$"))
    application.add_handler(CallbackQueryHandler(blackjack_stand, pattern="^blackjack_stand$"))
    
"# Банк и финансы"
    application.add_handler(CallbackQueryHandler(bank_menu, pattern="^bank_menu$"))
    application.add_handler(CallbackQueryHandler(bank_deposit, pattern="^bank_deposit$"))
    application.add_handler(CallbackQueryHandler(bank_withdraw, pattern="^bank_withdraw$"))
    application.add_handler(CallbackQueryHandler(bank_transfer, pattern="^bank_transfer$"))
    
"# Работа"
    application.add_handler(CallbackQueryHandler(jobs_menu, pattern="^jobs_menu$"))
    application.add_handler(CallbackQueryHandler(select_job, pattern="^job_"))
    application.add_handler(CallbackQueryHandler(do_work, pattern="^do_work$"))
    application.add_handler(CallbackQueryHandler(work_stats, pattern="^work_stats$"))
    
"# Ферма BTC"
    application.add_handler(CallbackQueryHandler(farm_menu, pattern="^farm_menu$"))
    application.add_handler(CallbackQueryHandler(farm_collect, pattern="^farm_collect$"))
    application.add_handler(CallbackQueryHandler(farm_buy_menu, pattern="^farm_buy_menu$"))
    application.add_handler(CallbackQueryHandler(buy_gpu, pattern="^buy_gpu_"))
    application.add_handler(CallbackQueryHandler(farm_stats, pattern="^farm_stats$"))
    
"# Биржа BTC"
    application.add_handler(CallbackQueryHandler(btc_market, pattern="^btc_market$"))
    application.add_handler(CallbackQueryHandler(btc_buy, pattern="^btc_buy$"))
    application.add_handler(CallbackQueryHandler(btc_sell, pattern="^btc_sell$"))
    application.add_handler(CallbackQueryHandler(btc_chart, pattern="^btc_chart$"))
    
"# Админ-панель"
    application.add_handler(CallbackQueryHandler(admin_menu, pattern="^admin_menu$"))
    application.add_handler(CallbackQueryHandler(admin_find_user, pattern="^admin_find_user$"))
    application.add_handler(CallbackQueryHandler(admin_give_money, pattern="^admin_give_money$"))
    application.add_handler(CallbackQueryHandler(admin_take_money, pattern="^admin_take_money$"))
    application.add_handler(CallbackQueryHandler(admin_give_btc, pattern="^admin_give_btc$"))
    application.add_handler(CallbackQueryHandler(admin_ban, pattern="^admin_ban$"))
    application.add_handler(CallbackQueryHandler(admin_unban, pattern="^admin_unban$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_update_btc, pattern="^admin_update_btc$"))

    # Обработчики для создания промокодов (админ)
    application.add_handler(CallbackQueryHandler(create_promo_type, pattern="^create_promo_"))
    application.add_handler(CallbackQueryHandler(set_promo_expire, pattern="^expire_"))
    
"# Обработчик текстовых сообщений для промокодов"
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_promo_messages))
    
"# Обработка текстовых сообщений"
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
"# Запуск бота"
    logger.info("Бот запускается...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
"# Бесконечный цикл"
    try:
        while True:
            await asyncio.sleep(3600)  # Обновляем курс BTC каждый час
            global btc_price
            btc_price = random.randint(10000, 150000)
            logger.info(f"Курс BTC обновлен: {btc_price}")
    except KeyboardInterrupt:
        logger.info("Бот останавливается...")
        await application.stop()
        await db.pool.close()

if __name__ == '__main__':
"# Запуск асинхронного приложения"
    asyncio.run(main())
