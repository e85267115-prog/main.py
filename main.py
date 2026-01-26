# -*- coding: utf-8 -*-
import psycopg2
from psycopg2 import pool, extras
import logging
import json
import random
import asyncio
import datetime
import os
import secrets
import string
import ssl
import math
from typing import Dict, List, Tuple, Optional, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
import pytz
import asyncpg
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import aiohttp

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TOKEN", "ВАШ_ТОКЕН_БОТА")
ADMIN_IDS = json.loads(os.environ.get("ADMIN_IDS", "[123456789]"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@nvibee_bet")
CHAT_USERNAME = os.environ.get("CHAT_USERNAME", "@chatvibee_bet")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем Supabase
IS_SUPABASE = DATABASE_URL and "supabase" in DATABASE_URL.lower()
if IS_SUPABASE:
    print("✅ Обнаружено подключение к Supabase")
    if "?sslmode=" not in DATABASE_URL:
        DATABASE_URL += "?sslmode=require"
elif DATABASE_URL:
    print("✅ Обнаружено подключение к PostgreSQL")
else:
    print("⚠️ DATABASE_URL не задан")

# ========== НАСТРОЙКИ ИГРЫ ==========
REFERRAL_BONUS = 10000
REFERRAL_PERCENTS = [0.05, 0.03, 0.01]
REFERRAL_LEVELS = 3
PROMOCODE_LENGTH = 8

# Уровни
LEVEL_EXP_REQUIREMENTS = {1: 4, 2: 8, 3: 12, 4: 16, 5: 20}
LEVEL_BONUS = {1: 50000, 2: 75000, 3: 100000, 4: 125000, 5: 150000}

# Видеокарты
GPU_TYPES = {
    "low": {
        "name": "GeForce GTX 1650",
        "base_price": 150000,
        "price_increase": 1.2,
        "income_per_hour": 0.1,
        "max_quantity": 3
    },
    "medium": {
        "name": "GeForce RTX 4060",
        "base_price": 220000,
        "price_increase": 1.2,
        "income_per_hour": 0.4,
        "max_quantity": 3
    },
    "high": {
        "name": "GeForce RTX 4090",
        "base_price": 350000,
        "price_increase": 1.3,
        "income_per_hour": 0.7,
        "max_quantity": 3
    }
}

# Работы
JOBS = {
    "digger": {
        "name": "Кладоискатель",
        "description": "Ищешь клады по всему миру",
        "min_salary": 10000,
        "max_salary": 50000,
        "btc_chance": 9,
        "cooldown": 300
    },
    "hacker": {
        "name": "Хакер",
        "description": "Взламываешь защищенные системы",
        "min_salary": 50000,
        "max_salary": 200000,
        "btc_chance": 9,
        "cooldown": 600
    },
    "miner": {
        "name": "Майнер",
        "description": "Добываешь криптовалюту в шахтах",
        "min_salary": 30000,
        "max_salary": 100000,
        "btc_chance": 9,
        "cooldown": 300
    },
    "trader": {
        "name": "Трейдер",
        "description": "Торгуешь на бирже криптовалют",
        "min_salary": 100000,
        "max_salary": 1000000,
        "btc_chance": 9,
        "cooldown": 900
    }
}

# Эмодзи
EMOJIS = {
    "money": "💰",
    "bank": "🏦",
    "btc": "₿",
    "level": "🏆",
    "exp": "⭐",
    "gpu": "🎮",
    "job": "💼",
    "wins": "🏅",
    "loses": "💔",
    "alert": "⚠️",
    "check": "✅",
    "cross": "❌",
    "dice": "🎲",
    "football": "⚽",
    "roulette": "🎰",
    "diamond": "💎",
    "mine": "💣",
    "work": "👷",
    "bonus": "🎁",
    "rocket": "🚀",
    "fire": "🔥",
    "up": "⬆️",
    "down": "⬇️",
    "chip": "🪙",
    "id": "🆔",
    "stats": "📊",
    "deposit": "📥",
    "withdraw": "📤",
    "transfer": "🔁",
    "shop": "🛒",
    "farm": "🌾",
    "market": "📈",
    "casino": "🎪",
    "crash": "💥",
    "blackjack": "🃏"
}

# ========== ФУНКЦИИ ХЕЛПЕРЫ ==========
def format_number(num: int) -> str:
    """Форматирование чисел с K, KK, KKK"""
    if num >= 1000000000:
        return f"{num/1000000000:.2f}kkk"
    elif num >= 1000000:
        return f"{num/1000000:.2f}kk"
    elif num >= 1000:
        return f"{num/1000:.2f}k"
    else:
        return str(num)

def get_emoji(name: str) -> str:
    """Получить эмодзи по имени"""
    return EMOJIS.get(name, "")

def get_gpu_display_name(gpu_type: str) -> str:
    """Получить название видеокарты с эмодзи"""
    gpu = GPU_TYPES.get(gpu_type, {})
    return f"{get_emoji('gpu')} {gpu.get('name', 'Неизвестно')}"

def get_job_display_name(job_type: str) -> str:
    """Получить название работы с эмодзи"""
    job = JOBS.get(job_type, {})
    return f"{get_emoji('job')} {job.get('name', 'Неизвестно')}"

def generate_referral_code() -> str:
    """Генерация реферального кода"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

# ========== DATACLASSES ==========
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
    registered: datetime.datetime = field(default_factory=datetime.datetime.now)
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

# ========== БАЗА ДАННЫХ С PSYCOPG2 ==========
class Database:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool = None
        self.is_supabase = connection_string and "supabase" in connection_string.lower()
    
    async def connect(self):
        """Подключение к БД"""
        if not self.connection_string:
            print("⚠️ DATABASE_URL не задан, используется локальное хранилище")
            return
        
        try:
            # Создаем пул соединений psycopg2
            self.pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=self.connection_string,
                sslmode='require' if self.is_supabase else 'prefer'
            )
            
            # Проверяем подключение
            test_conn = self.pool.getconn()
            test_conn.close()
            self.pool.putconn(test_conn)
            
            await self.init_db()
            print(f"✅ База данных подключена (Supabase: {self.is_supabase})")
            
        except Exception as e:
            print(f"❌ Ошибка подключения к БД: {e}")
            print("⚠️ Бот будет работать в режиме без сохранения данных")
            self.pool = None
    
    async def init_db(self):
        """Инициализация таблиц"""
        if not self.pool:
            return
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            
            # Таблица пользователей (со всеми полями из dataclass User)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
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
                    referral_code TEXT DEFAULT '',
                    referred_by BIGINT,
                    total_referrals INTEGER DEFAULT 0,
                    referral_earnings BIGINT DEFAULT 0
                )
            ''')
            
            # Таблица фермы BTC (со всеми полями из dataclass BTCFarm)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS btc_farm (
                    user_id BIGINT,
                    gpu_type TEXT,
                    quantity INTEGER DEFAULT 0,
                    last_collected TIMESTAMPTZ,
                    PRIMARY KEY (user_id, gpu_type)
                )
            ''')
            
            # Таблица транзакций
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount BIGINT,
                    type TEXT,
                    description TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            
            # Таблица промокодов (если используется)
            cursor.execute('''
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
            
            # Таблица использования промокодов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS promo_uses (
                    id BIGSERIAL PRIMARY KEY,
                    promo_code TEXT,
                    user_id BIGINT,
                    used_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            
            conn.commit()
            
            # Создаем индексы для производительности
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)',
                'CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned)',
                'CREATE INDEX IF NOT EXISTS idx_users_ref_code ON users(referral_code)',
                'CREATE INDEX IF NOT EXISTS idx_promo_expires ON promo_codes(expires_at)',
                'CREATE INDEX IF NOT EXISTS idx_promo_active ON promo_codes(is_active)'
            ]
            
            for index_sql in indexes:
                try:
                    cursor.execute(index_sql)
                    conn.commit()
                except Exception as e:
                    print(f"⚠️ Ошибка создания индекса: {e}")
                    
        except Exception as e:
            print(f"❌ Ошибка инициализации БД: {e}")
        finally:
            self.pool.putconn(conn)
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """Получить пользователя из БД"""
        if not self.pool:
            return None
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()
            
            if row:
                # Преобразуем в словарь и создаем User dataclass
                user_dict = dict(row)
                return User.from_dict(user_dict)
            return None
            
        except Exception as e:
            print(f"❌ Ошибка получения пользователя {user_id}: {e}")
            return None
        finally:
            self.pool.putconn(conn)
    
    async def save_user(self, user: User):
        """Сохранение пользователя в БД"""
        if not self.pool:
            return
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            
            # Преобразуем dataclass в кортеж значений
            user_dict = user.to_dict()
            values = (
                user_dict["user_id"],
                user_dict["username"],
                user_dict["balance"],
                user_dict["bank"],
                user_dict["btc"],
                user_dict["level"],
                user_dict["exp"],
                user_dict["wins"],
                user_dict["loses"],
                user_dict["job"],
                user_dict["last_work"],
                user_dict["last_bonus"],
                user_dict["registered"],
                user_dict["last_daily_bonus"],
                user_dict["is_banned"],
                user_dict["referral_code"],
                user_dict["referred_by"],
                user_dict["total_referrals"],
                user_dict["referral_earnings"]
            )
            
            cursor.execute('''
                INSERT INTO users (
                    user_id, username, balance, bank, btc, level, exp, wins, loses,
                    job, last_work, last_bonus, registered, last_daily_bonus, is_banned,
                    referral_code, referred_by, total_referrals, referral_earnings
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            ''', values)
            
            conn.commit()
            
        except Exception as e:
            print(f"❌ Ошибка сохранения пользователя {user.user_id}: {e}")
            conn.rollback()
        finally:
            self.pool.putconn(conn)
    
    async def get_user_farm(self, user_id: int) -> List[BTCFarm]:
        """Получение фермы пользователя"""
        if not self.pool:
            return []
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            cursor.execute('SELECT * FROM btc_farm WHERE user_id = %s', (user_id,))
            rows = cursor.fetchall()
            
            # Создаем список объектов BTCFarm dataclass
            farms = []
            for row in rows:
                farm_dict = dict(row)
                farms.append(BTCFarm(
                    user_id=farm_dict["user_id"],
                    gpu_type=farm_dict["gpu_type"],
                    quantity=farm_dict["quantity"],
                    last_collected=farm_dict["last_collected"]
                ))
            
            return farms
            
        except Exception as e:
            print(f"❌ Ошибка получения фермы пользователя {user_id}: {e}")
            return []
        finally:
            self.pool.putconn(conn)
    
    async def update_farm(self, farm: BTCFarm):
        """Обновление фермы"""
        if not self.pool:
            return
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO btc_farm (user_id, gpu_type, quantity, last_collected)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, gpu_type) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    last_collected = EXCLUDED.last_collected
            ''', (farm.user_id, farm.gpu_type, farm.quantity, farm.last_collected))
            
            conn.commit()
            
        except Exception as e:
            print(f"❌ Ошибка обновления фермы: {e}")
            conn.rollback()
        finally:
            self.pool.putconn(conn)
    
    async def add_transaction(self, user_id: int, amount: int, type_: str, description: str):
        """Добавление транзакции"""
        if not self.pool:
            return
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (%s, %s, %s, %s)
            ''', (user_id, amount, type_, description))
            
            conn.commit()
            
        except Exception as e:
            print(f"❌ Ошибка добавления транзакции: {e}")
            conn.rollback()
        finally:
            self.pool.putconn(conn)
    
    async def get_user_by_ref_code(self, ref_code: str) -> Optional[User]:
        """Получение пользователя по реферальному коду"""
        if not self.pool:
            return None
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            cursor.execute('SELECT * FROM users WHERE referral_code = %s', (ref_code,))
            row = cursor.fetchone()
            
            if row:
                return User.from_dict(dict(row))
            return None
            
        except Exception as e:
            print(f"❌ Ошибка поиска пользователя по коду {ref_code}: {e}")
            return None
        finally:
            self.pool.putconn(conn)
    
    async def create_promo_code(self, promo_code: str, promo_type: str, value: float, 
                               created_by: int, expires_at: datetime = None, 
                               max_uses: int = 1) -> bool:
        """Создание промокода"""
        if not self.pool:
            return False
        
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO promo_codes (code, promo_type, value, created_by, expires_at, max_uses)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (promo_code, promo_type, value, created_by, expires_at, max_uses))
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"❌ Ошибка создания промокода {promo_code}: {e}")
            conn.rollback()
            return False
        finally:
            self.pool.putconn(conn)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database(DATABASE_URL) if DATABASE_URL else None
btc_price = random.randint(10000, 150000)  # Начальная цена BTC
last_btc_update = datetime.datetime.now()

# ========== ФУНКЦИИ ПРОВЕРКИ ==========
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка подписки на канал и чат"""
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
        print(f"Ошибка проверки подписки: {e}")
        return False

async def check_ban(user_id: int) -> bool:
    """Проверка бана"""
    if not db:
        return False
    user = await db.get_user(user_id)
    return user.is_banned if user else False

async def get_or_create_user(user_id: int, username: str = "") -> User:
    """Получить или создать пользователя"""
    if not db:
        # Режим без БД
        return User(user_id=user_id, username=username)
    
    user = await db.get_user(user_id)
    if not user:
        user = User(
            user_id=user_id,
            username=username,
            referral_code=generate_referral_code()
        )
        await db.save_user(user)
    elif username and user.username != username:
        user.username = username
        await db.save_user(user)
    return user

# ========== ОСНОВНЫЕ КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Проверка подписки
    if not await check_subscription(user.id, context):
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("💬 Вступить в чат", url=f"https://t.me/{CHAT_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_photo(
            photo="https://raw.githubusercontent.com/yourusername/yourrepo/main/start_img.jpg",
            caption="🎮 *Добро пожаловать в Vibe Bet!*\n\n"
                   "Для доступа к боту необходимо подписаться на наши каналы:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return
    
    # Основное меню
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('dice')} Игры", callback_data="games_menu"),
         InlineKeyboardButton(f"{get_emoji('work')} Работа", callback_data="work_menu")],
        [InlineKeyboardButton(f"{get_emoji('farm')} Ферма BTC", callback_data="farm_menu"),
         InlineKeyboardButton(f"{get_emoji('bonus')} Бонус", callback_data="bonus")],
        [InlineKeyboardButton(f"{get_emoji('stats')} Профиль", callback_data="profile"),
         InlineKeyboardButton(f"{get_emoji('bank')} Банк", callback_data="bank_menu")],
        [InlineKeyboardButton(f"{get_emoji('market')} Биржа", callback_data="market"),
         InlineKeyboardButton(f"{get_emoji('shop')} Магазин", callback_data="shop")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_photo(
        photo="https://raw.githubusercontent.com/yourusername/yourrepo/main/start_img.jpg",
        caption="🎮 *Добро пожаловать в Vibe Bet!*\n\n"
               "Крути рулетку, рискуй в Краше, а также собирай свою ферму.\n\n"
               f"{get_emoji('dice')} *Игры*: 🎲 Кости, ⚽ Футбол, 🎰 Рулетка, 💎 Алмазы, 💣 Мины\n"
               f"{get_emoji('work')} *Заработок*: 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    # ========== ОБРАБОТКА CALLBACK-ЗАПРОСОВ ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-запросов"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Основное меню
    if data == "main_menu":
        await start(update, context)
    elif data == "check_subscription":
        user = query.from_user
        if await check_subscription(user.id, context):
            await query.answer("✅ Подписка подтверждена!", show_alert=True)
            await start(update, context)
        else:
            await query.answer("❌ Вы не подписаны на каналы!", show_alert=True)
    
    # Профиль
    elif data == "profile":
        await profile(update, context)
    
    # Игры
    elif data == "games_menu":
        await games_menu(update, context)
    elif data.startswith("game_"):
        game = data.split("_")[1]
        if game == "dice":
            await game_dice(update, context)
        elif game == "football":
            await game_football(update, context)
        elif game == "roulette":
            await game_roulette(update, context)
        elif game == "diamonds":
            await game_diamonds(update, context)
        elif game == "mines":
            await game_mines(update, context)
        elif game == "crash":
            await game_crash(update, context)
        elif game == "blackjack":
            await game_blackjack(update, context)
    
    # Кости
    elif data.startswith("dice_"):
        await dice_bet(update, context)
    elif data == "dice_high" or data == "dice_low" or data == "dice_equal":
        context.user_data["game"] = "dice"
        context.user_data["bet_type"] = data.split("_")[1]
        await dice_bet(update, context)
    
    # Футбол
    elif data.startswith("football_"):
        await football_bet(update, context)
    
    # Рулетка
    elif data.startswith("roulette_"):
        await roulette_bet(update, context)
    
    # Алмазы
    elif data.startswith("diamond_"):
        if data == "diamond_claim":
            await diamond_claim(update, context)
        else:
            await diamond_open(update, context)
    
    # Мины
    elif data.startswith("mine_"):
        if data == "mine_gameover":
            return
        elif data == "mines_claim":
            await mines_claim(update, context)
        else:
            await mine_open(update, context)
    
    # Краш
    elif data == "crash_cashout":
        await crash_cashout(update, context)
    
    # Очко
    elif data == "blackjack_hit":
        await blackjack_hit(update, context)
    elif data == "blackjack_stand":
        await blackjack_stand(update, context)
    
    # Биржа
    elif data == "market":
        await market(update, context)
    elif data == "market_buy":
        await market_buy(update, context)
    elif data == "market_sell":
        await market_sell(update, context)
    
    # Магазин
    elif data == "shop":
        await shop(update, context)
    
    # Ферма
    elif data == "farm_menu":
        await farm_menu(update, context)
    elif data == "farm_collect":
        await farm_collect(update, context)
    elif data == "farm_buy":
        await farm_buy(update, context)
    elif data.startswith("farm_purchase_"):
        await farm_purchase(update, context)
    elif data.startswith("farm_max_"):
        await query.answer("Достигнут максимум видеокарт!", show_alert=True)
    elif data == "farm_info":
        await farm_info(update, context)
    
    # Банк
    elif data == "bank_menu":
        await bank_menu(update, context)
    elif data == "bank_deposit":
        await bank_deposit(update, context)
    elif data == "bank_withdraw":
        await bank_withdraw(update, context)
    elif data == "bank_transfer":
        await bank_transfer(update, context)
    elif data == "bank_stats":
        await bank_stats(update, context)
    
    # Работа
    elif data == "work_menu":
        await work_menu(update, context)
    elif data.startswith("work_"):
        if data == "work_perform":
            await work_perform(update, context)
        elif data.startswith("work_confirm_"):
            await work_confirm(update, context)
        else:
            await work_select(update, context)
    
    # Бонусы
    elif data == "bonus":
        await bonus(update, context)
    elif data == "daily_bonus":
        await daily_bonus(update, context)
    elif data == "level_bonus":
        await level_bonus(update, context)
    elif data == "promo_code":
        await promo_code(update, context)
    
    # Админ-панель
    elif data == "admin_panel":
        await admin_panel(update, context)
    elif data == "admin_stats":
        await admin_stats(update, context)
    
    # Если не найдено обработчика
    else:
        await query.answer("Команда не реализована", show_alert=True)

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ==========
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user = update.effective_user
    text = update.message.text.strip()
    
    # Проверяем, забанен ли пользователь
    if await check_ban(user.id):
        await update.message.reply_text(
            f"{get_emoji('cross')} Вы заблокированы в этом боте!",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Обработка игр
    if context.user_data.get("game"):
        game = context.user_data["game"]
        
        if game == "dice":
            await dice_play(update, context)
        elif game == "football":
            await football_play(update, context)
        elif game == "roulette":
            await roulette_play(update, context)
        elif game == "diamonds_claim":
            await diamond_finish(update, context)
        elif game == "mines_claim":
            await mines_finish(update, context)
        elif game == "crash":
            await crash_play(update, context)
        elif game == "blackjack":
            await blackjack_play(update, context)
    
    # Обработка действий банка/биржи
    elif context.user_data.get("action"):
        action = context.user_data["action"]
        
        if action.startswith("market_"):
            await handle_market_action(update, context)
        elif action.startswith("bank_"):
            await handle_bank_action(update, context)
        elif action == "promo_code":
            await handle_promo_code(update, context)
    
    # Обработка админских команд
    elif context.user_data.get("admin_action"):
        await handle_admin_action(update, context)
    
    # Обработка команд без слеша
    elif text.lower() in ["профиль", "profile"]:
        await profile(update, context)
    elif text.lower() in ["игры", "games"]:
        await games_menu(update, context)
    elif text.lower() in ["работа", "work"]:
        await work_menu(update, context)
    elif text.lower() in ["ферма", "farm"]:
        await farm_menu(update, context)
    elif text.lower() in ["банк", "bank"]:
        await bank_menu(update, context)
    elif text.lower() in ["биржа", "market"]:
        await market(update, context)
    elif text.lower() in ["магазин", "shop"]:
        await shop(update, context)
    elif text.lower() in ["бонус", "bonus"]:
        await bonus(update, context)
    elif text.lower() in ["рефералы", "referral"]:
        await referral(update, context)
    elif text.lower() in ["админ", "admin"]:
        await admin_panel(update, context)
    
    # Если это число, предлагаем игры
    elif text.isdigit():
        amount = int(text)
        if 100 <= amount <= 1000000:
            keyboard = [
                [InlineKeyboardButton("🎲 Кости", callback_data="game_dice"),
                 InlineKeyboardButton("⚽ Футбол", callback_data="game_football")],
                [InlineKeyboardButton("🎰 Рулетка", callback_data="game_roulette"),
                 InlineKeyboardButton("💎 Алмазы", callback_data="game_diamonds")],
                [InlineKeyboardButton("💣 Мины", callback_data="game_mines"),
                 InlineKeyboardButton("💥 Краш", callback_data="game_crash")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"{get_emoji('money')} Вы ввели сумму: {format_number(amount)}\n"
                f"Выберите игру для ставки:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            context.user_data["quick_bet"] = amount

# ========== КОМАНДЫ ==========
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /balance"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await update.message.reply_text(
        f"{get_emoji('money')} *Ваш баланс:* {format_number(user_data.balance)}",
        parse_mode=ParseMode.MARKDOWN
    )

async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /level"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    next_level_exp = LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4)
    level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
    
    await update.message.reply_text(
        f"{get_emoji('level')} *Уровень:* {user_data.level}\n"
        f"{get_emoji('exp')} *EXP:* {user_data.exp}/{next_level_exp}\n"
        f"{get_emoji('bonus')} *Бонус уровня:* {format_number(level_bonus)}\n\n"
        f"{get_emoji('alert')} *Следующий уровень:*\n"
        f"Требуется EXP: {next_level_exp}\n"
        f"Бонус: {format_number(LEVEL_BONUS.get(user_data.level + 1, level_bonus + 25000))}",
        parse_mode=ParseMode.MARKDOWN
    )

async def job_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /job"""
    await work_menu(update, context)

async def farm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /farm"""
    await farm_menu(update, context)

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /bank"""
    await bank_menu(update, context)

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /market"""
    await market(update, context)

async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /bonus"""
    await bonus(update, context)

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /referral"""
    await referral(update, context)

# ========== АДМИН КОМАНДЫ ==========
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    await admin_panel(update, context)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats (админ)"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    # Простая статистика
    text = (
        f"{get_emoji('stats')} *СТАТИСТИКА БОТА*\n\n"
        f"🕐 *Время работы:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"💎 *Курс BTC:* {format_number(btc_price)} ₽\n"
        f"⚙️ *База данных:* {'✅ Подключена' if db else '❌ Не подключена'}\n\n"
        f"{get_emoji('alert')} *Для детальной статистики:*\n"
        f"Используйте админ-панель"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== ФУНКЦИЯ ДЛЯ ЕЖЕДНЕВНЫХ ПРОЦЕНТОВ ==========
async def daily_interest_task(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное начисление процентов в банке"""
    if not db:
        return
    
    try:
        # Получаем всех пользователей
        async with db.pool.acquire() as conn:
            users = await conn.fetch('SELECT * FROM users WHERE bank > 0')
            
            for user_row in users:
                user = User.from_dict(dict(user_row))
                interest = int(user.bank * 0.05)  # 5% процентов
                
                if interest > 0:
                    user.bank += interest
                    await db.save_user(user)
                    
                    # Отправляем уведомление
                    try:
                        await context.bot.send_message(
                            chat_id=user.user_id,
                            text=f"{get_emoji('bank')} *НАЧИСЛЕНЫ ПРОЦЕНТЫ!*\n\n"
                                 f"{get_emoji('money')} Сумма: {format_number(interest)} ₽\n"
                                 f"{get_emoji('bank')} Теперь в банке: {format_number(user.bank)}\n\n"
                                 f"{get_emoji('alert')} Проценты начисляются ежедневно в 00:00 по МСК",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass  # Если не удалось отправить сообщение
        
        print(f"✅ Начислены проценты {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    except Exception as e:
        print(f"❌ Ошибка при начислении процентов: {e}")
        # ========== ИГРЫ - ПРОДОЛЖЕНИЕ ==========
async def game_mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра Мины"""
    query = update.callback_query
    await query.answer()
    
    # Генерация мин (5 из 25)
    mines = random.sample(range(1, 26), 5)
    context.user_data["mines_positions"] = mines
    context.user_data["mines_opened"] = []
    context.user_data["mines_multiplier"] = 1.0
    context.user_data["game"] = "mines"
    
    keyboard = []
    for i in range(1, 26):
        if (i-1) % 5 == 0:
            keyboard.append([])
        keyboard[-1].append(InlineKeyboardButton("🟦", callback_data=f"mine_{i}"))
    keyboard.append([
        InlineKeyboardButton("💰 Забрать", callback_data="mines_claim"),
        InlineKeyboardButton("🔙 Назад", callback_data="games_menu")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="💣 *МИНЫ*\n\n"
             "Избегайте мин! Открывайте безопасные ячейки.\n"
             "Чем больше откроете - тем больше множитель!\n"
             "Всего мин: 5 из 25\n\n"
             f"{get_emoji('money')} Множитель: 1.00x",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def mine_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открытие ячейки в Минах"""
    query = update.callback_query
    await query.answer()
    
    cell_num = int(query.data.split("_")[1])
    mines = context.user_data.get("mines_positions", [])
    opened = context.user_data.get("mines_opened", [])
    
    if cell_num in opened:
        return
    
    opened.append(cell_num)
    context.user_data["mines_opened"] = opened
    
    # Проверка на мину
    if cell_num in mines:
        # Попали на мину - проигрыш
        context.user_data["mines_game_over"] = True
        
        # Показываем все мины
        keyboard = []
        for i in range(1, 26):
            if (i-1) % 5 == 0:
                keyboard.append([])
            if i in mines:
                keyboard[-1].append(InlineKeyboardButton("💥", callback_data="mine_gameover"))
            elif i in opened:
                keyboard[-1].append(InlineKeyboardButton("✅", callback_data="mine_gameover"))
            else:
                keyboard[-1].append(InlineKeyboardButton("🟦", callback_data="mine_gameover"))
        
        keyboard.append([InlineKeyboardButton("💣 Играть снова", callback_data="game_mines"),
                         InlineKeyboardButton("🔙 В меню", callback_data="games_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="💥 *ВЫ НАТКНУЛИСЬ НА МИНУ!*\n\n"
                 "Игра окончена. Вы проиграли ставку.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return
    
    # Увеличиваем множитель
    multiplier = context.user_data.get("mines_multiplier", 1.0)
    multiplier = round(multiplier * 1.21, 2)  # Увеличение на 21% за каждую ячейку
    context.user_data["mines_multiplier"] = multiplier
    
    # Обновляем клавиатуру
    keyboard = []
    for i in range(1, 26):
        if (i-1) % 5 == 0:
            keyboard.append([])
        if i in opened:
            keyboard[-1].append(InlineKeyboardButton("✅", callback_data=f"mine_{i}"))
        else:
            keyboard[-1].append(InlineKeyboardButton("🟦", callback_data=f"mine_{i}"))
    
    keyboard.append([
        InlineKeyboardButton(f"💰 Забрать {multiplier}x", callback_data="mines_claim"),
        InlineKeyboardButton("🔙 Назад", callback_data="games_menu")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"💣 *МИНЫ*\n\n"
             f"✅ Открыто ячеек: {len(opened)}\n"
             f"💣 Мин осталось: {5 - sum(1 for m in mines if m in opened)}\n"
             f"🎯 Множитель: {multiplier}x\n\n"
             f"Следующая ячейка может увеличить множитель!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def mines_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Забрать выигрыш в Минах"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Запрос ставки
    multiplier = context.user_data.get("mines_multiplier", 1.0)
    
    await query.edit_message_text(
        text=f"💣 *МИНЫ*\n\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n"
             f"🎯 Множитель: {multiplier}x\n"
             f"✅ Открыто ячеек: {len(context.user_data.get('mines_opened', []))}\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "mines_claim"

async def mines_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение игры Мины"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    try:
        bet = int(update.message.text)
        if bet < 100:
            await update.message.reply_text(f"{get_emoji('alert')} Минимальная ставка: 100")
            return
        if bet > user_data.balance:
            await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств")
            return
    except:
        await update.message.reply_text(f"{get_emoji('alert')} Введите число!")
        return
    
    multiplier = context.user_data.get("mines_multiplier", 1.0)
    win_amount = int(bet * multiplier)
    
    user_data.balance += win_amount - bet
    user_data.wins += 1
    
    # Добавление EXP
    if random.random() < 0.5:
        user_data.exp += 1
    
    await db.save_user(user_data)
    
    text = (
        f"💣 *МИНЫ - РЕЗУЛЬТАТ*\n\n"
        f"✅ Открыто ячеек: {len(context.user_data.get('mines_opened', []))}\n"
        f"🎯 Множитель: {multiplier}x\n"
        f"🎉 Вы успешно забрали выигрыш!\n\n"
        f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
        f"💰 Выигрыш: {format_number(win_amount)}\n"
        f"💣 Баланс: {format_number(user_data.balance)}"
    )
    
    keyboard = [[InlineKeyboardButton("💣 Играть снова", callback_data="game_mines"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def game_crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра Краш"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text="💥 *КРАШ*\n\n"
             "Ставьте и выводите деньги до того, как график упадет!\n"
             "Множитель растет с каждой секундой.\n\n"
             f"{get_emoji('money')} Минимальная ставка: 100\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "crash"

async def crash_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в Краш"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    try:
        bet = int(update.message.text)
        if bet < 100:
            await update.message.reply_text(f"{get_emoji('alert')} Минимальная ставка: 100")
            return
        if bet > user_data.balance:
            await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств")
            return
    except:
        await update.message.reply_text(f"{get_emoji('alert')} Введите число!")
        return
    
    # Генерация точки краша (от 1.01 до 10.0)
    crash_point = round(random.uniform(1.01, 10.0), 2)
    
    keyboard = [
        [InlineKeyboardButton("💥 Вывести сейчас", callback_data="crash_cashout")],
        [InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем начальное сообщение
    message = await update.message.reply_text(
        text=f"💥 *КРАШ ИГРА НАЧАЛАСЬ!*\n\n"
             f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
             f"🎯 Множитель: 1.00x\n"
             f"⏱ Ожидание краша...",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    context.user_data["crash_bet"] = bet
    context.user_data["crash_point"] = crash_point
    context.user_data["crash_message"] = message
    context.user_data["crash_start"] = datetime.datetime.now()
    context.user_data["crash_cashed_out"] = False
    
    # Запускаем анимацию краша
    asyncio.create_task(crash_animation(update, context, user_data))

async def crash_animation(update: Update, context: ContextTypes.DEFAULT_TYPE, user_data):
    """Анимация игры Краш"""
    message = context.user_data.get("crash_message")
    crash_point = context.user_data.get("crash_point", 5.0)
    bet = context.user_data.get("crash_bet", 100)
    
    multiplier = 1.0
    start_time = datetime.datetime.now()
    
    while multiplier < crash_point:
        # Проверяем, не забрал ли игрок выигрыш
        if context.user_data.get("crash_cashed_out", False):
            win_amount = int(bet * multiplier)
            user_data.balance += win_amount - bet
            user_data.wins += 1
            
            # Добавление EXP
            if random.random() < 0.5:
                user_data.exp += 1
            
            await db.save_user(user_data)
            
            text = (
                f"🎉 *ВЫ УСПЕЛИ ВЫВЕСТИ!*\n\n"
                f"📈 Множитель: {multiplier:.2f}x\n"
                f"💸 Ставка: {format_number(bet)}\n"
                f"💰 Выигрыш: {format_number(win_amount)}\n"
                f"💥 Баланс: {format_number(user_data.balance)}"
            )
            
            keyboard = [[InlineKeyboardButton("💥 Играть снова", callback_data="game_crash"),
                         InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            except:
                pass
            return
        
        # Увеличиваем множитель
        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        multiplier = 1.0 + (elapsed * 0.1)  # Множитель растет на 0.1 каждую секунду
        
        # Обновляем сообщение
        try:
            await message.edit_text(
                text=f"💥 *КРАШ ИДЕТ...*\n\n"
                     f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
                     f"🎯 Множитель: {multiplier:.2f}x\n"
                     f"📈 Точка краша: {crash_point:.2f}x\n"
                     f"⏱ Время: {elapsed:.1f}с",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=message.reply_markup
            )
        except:
            pass
        
        await asyncio.sleep(0.5)  # Обновляем каждые 0.5 секунд
    
    # Краш случился
    user_data.balance -= bet
    user_data.loses += 1
    
    # Добавление EXP
    if random.random() < 0.5:
        user_data.exp += 1
    
    await db.save_user(user_data)
    
    text = (
        f"😔 *ВЫ ПРОИГРАЛИ!*\n\n"
        f"📈 Точка краша: {crash_point:.2f}x\n"
        f"🎯 Множитель: {multiplier:.2f}x\n"
        f"💸 Ставка: {format_number(bet)}\n"
        f"💰 Баланс: {format_number(user_data.balance)}"
    )
    
    keyboard = [[InlineKeyboardButton("💥 Играть снова", callback_data="game_crash"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except:
        pass

async def crash_cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вывод в игре Краш"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["crash_cashed_out"] = True
    
    await query.answer("✅ Вы успешно вывели деньги!", show_alert=True)

async def game_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра Очко (21)"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text="🃏 *ОЧКО (21)*\n\n"
             "Цель: набрать 21 очко или больше дилера, но не больше 21.\n"
             "Карты: 2-10 = номинал, J/Q/K = 10, A = 1 или 11\n\n"
             f"{get_emoji('money')} Минимальная ставка: 100\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "blackjack"

async def blackjack_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в Очко"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    try:
        bet = int(update.message.text)
        if bet < 100:
            await update.message.reply_text(f"{get_emoji('alert')} Минимальная ставка: 100")
            return
        if bet > user_data.balance:
            await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств")
            return
    except:
        await update.message.reply_text(f"{get_emoji('alert')} Введите число!")
        return
    
    # Начинаем игру
    deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4  # Упрощенная колода
    random.shuffle(deck)
    
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    
    context.user_data["blackjack_bet"] = bet
    context.user_data["blackjack_deck"] = deck
    context.user_data["blackjack_player"] = player_hand
    context.user_data["blackjack_dealer"] = dealer_hand
    context.user_data["blackjack_game_over"] = False
    
    # Проверяем блэкджек у игрока
    player_score = calculate_hand_score(player_hand)
    dealer_score = calculate_hand_score([dealer_hand[0]])  # Видна только одна карта дилера
    
    keyboard = []
    if player_score == 21:
        # У игрока блэкджек
        context.user_data["blackjack_game_over"] = True
        
        # Открываем карты дилера
        dealer_score_full = calculate_hand_score(dealer_hand)
        
        if dealer_score_full == 21:
            # Ничья
            result = "🤝 Ничья! Оба имеют блэкджек"
            win_amount = bet
        else:
            # Игрок выиграл с блэкджеком
            win_amount = int(bet * 2.5)  # Блэкджек платит 3:2
            user_data.balance += win_amount - bet
            user_data.wins += 1
            result = "🎉 БЛЭКДЖЕК! Вы выиграли 3:2"
    else:
        # Игра продолжается
        keyboard = [
            [InlineKeyboardButton("🃏 Еще карту", callback_data="blackjack_hit"),
             InlineKeyboardButton("✋ Хватит", callback_data="blackjack_stand")],
            [InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]
        ]
        result = None
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    text = f"🃏 *ОЧКО - НАЧАЛО ИГРЫ*\n\n" \
           f"{get_emoji('money')} Ставка: {format_number(bet)}\n\n" \
           f"👤 *Ваши карты:* {format_hand(player_hand)} ({player_score})\n" \
           f"🤵 *Карта дилера:* {dealer_hand[0]} ?\n\n"
    
    if result:
        text += f"{result}\n\n"
        if context.user_data["blackjack_game_over"]:
            text += f"🤵 *Карты дилера:* {format_hand(dealer_hand)} ({dealer_score_full if 'dealer_score_full' in locals() else dealer_score})\n"
            text += f"💰 Выигрыш: {format_number(win_amount) if 'win_amount' in locals() else format_number(bet)}"
            
            # Добавление EXP
            if random.random() < 0.5:
                user_data.exp += 1
            
            await db.save_user(user_data)
            
            keyboard = [[InlineKeyboardButton("🃏 Играть снова", callback_data="game_blackjack"),
                         InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

def calculate_hand_score(hand: List[int]) -> int:
    """Подсчет очков в руке"""
    score = sum(hand)
    aces = hand.count(11)
    
    while score > 21 and aces:
        score -= 10  # Превращаем туз из 11 в 1
        aces -= 1
    
    return score

def format_hand(hand: List[int]) -> str:
    """Форматирование карт в руке"""
    cards = []
    for card in hand:
        if card == 11:
            cards.append("A")
        elif card == 10:
            cards.append(random.choice(["10", "J", "Q", "K"]))
        else:
            cards.append(str(card))
    return " ".join(cards)

async def blackjack_hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Взять еще карту в Очко"""
    query = update.callback_query
    await query.answer()
    
    if context.user_data.get("blackjack_game_over", False):
        return
    
    deck = context.user_data.get("blackjack_deck", [])
    player_hand = context.user_data.get("blackjack_player", [])
    dealer_hand = context.user_data.get("blackjack_dealer", [])
    bet = context.user_data.get("blackjack_bet", 100)
    
    # Даем игроку карту
    player_hand.append(deck.pop())
    context.user_data["blackjack_player"] = player_hand
    context.user_data["blackjack_deck"] = deck
    
    player_score = calculate_hand_score(player_hand)
    
    if player_score > 21:
        # Перебор
        context.user_data["blackjack_game_over"] = True
        user = query.from_user
        user_data = await get_or_create_user(user.id, user.username)
        
        user_data.balance -= bet
        user_data.loses += 1
        
        # Добавление EXP
        if random.random() < 0.5:
            user_data.exp += 1
        
        await db.save_user(user_data)
        
        text = f"🃏 *ОЧКО - ПЕРЕБОР!*\n\n" \
               f"{get_emoji('money')} Ставка: {format_number(bet)}\n\n" \
               f"👤 *Ваши карты:* {format_hand(player_hand)} ({player_score}) ❌\n" \
               f"🤵 *Карты дилера:* {format_hand(dealer_hand)} ({calculate_hand_score(dealer_hand)})\n\n" \
               f"😔 Перебор! Вы проиграли.\n" \
               f"💰 Баланс: {format_number(user_data.balance)}"
        
        keyboard = [[InlineKeyboardButton("🃏 Играть снова", callback_data="game_blackjack"),
                     InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return
    
    # Игра продолжается
    keyboard = [
        [InlineKeyboardButton("🃏 Еще карту", callback_data="blackjack_hit"),
         InlineKeyboardButton("✋ Хватит", callback_data="blackjack_stand")],
        [InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"🃏 *ОЧКО - ИГРА ПРОДОЛЖАЕТСЯ*\n\n" \
           f"{get_emoji('money')} Ставка: {format_number(bet)}\n\n" \
           f"👤 *Ваши карты:* {format_hand(player_hand)} ({player_score})\n" \
           f"🤵 *Карта дилера:* {dealer_hand[0]} ?\n\n" \
           f"Выберите действие:"
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def blackjack_stand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановиться в Очко"""
    query = update.callback_query
    await query.answer()
    
    if context.user_data.get("blackjack_game_over", False):
        return
    
    player_hand = context.user_data.get("blackjack_player", [])
    dealer_hand = context.user_data.get("blackjack_dealer", [])
    deck = context.user_data.get("blackjack_deck", [])
    bet = context.user_data.get("blackjack_bet", 100)
    
    # Дилер берет карты
    dealer_score = calculate_hand_score(dealer_hand)
    while dealer_score < 17:
        dealer_hand.append(deck.pop())
        dealer_score = calculate_hand_score(dealer_hand)
    
    player_score = calculate_hand_score(player_hand)
    context.user_data["blackjack_game_over"] = True
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Определяем победителя
    if dealer_score > 21:
        # Дилер перебрал
        win_amount = int(bet * 2)
        user_data.balance += win_amount - bet
        user_data.wins += 1
        result = "🎉 Дилер перебрал! Вы выиграли"
    elif player_score > dealer_score:
        # Игрок выиграл
        win_amount = int(bet * 2)
        user_data.balance += win_amount - bet
        user_data.wins += 1
        result = "🎉 Вы выиграли! У вас больше очков"
    elif player_score < dealer_score:
        # Дилер выиграл
        user_data.balance -= bet
        user_data.loses += 1
        result = "😔 Вы проиграли. У дилера больше очков"
        win_amount = 0
    else:
        # Ничья
        win_amount = bet
        result = "🤝 Ничья!"
    
    # Добавление EXP
    if random.random() < 0.5:
        user_data.exp += 1
    
    await db.save_user(user_data)
    
    text = f"🃏 *ОЧКО - РЕЗУЛЬТАТ*\n\n" \
           f"{get_emoji('money')} Ставка: {format_number(bet)}\n\n" \
           f"👤 *Ваши карты:* {format_hand(player_hand)} ({player_score})\n" \
           f"🤵 *Карты дилера:* {format_hand(dealer_hand)} ({dealer_score})\n\n" \
           f"{result}\n"
    
    if win_amount > 0 and win_amount != bet:
        text += f"💰 Выигрыш: {format_number(win_amount)}\n"
    
    text += f"💰 Баланс: {format_number(user_data.balance)}"
    
    keyboard = [[InlineKeyboardButton("🃏 Играть снова", callback_data="game_blackjack"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== БИРЖА BTC ==========
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Биржа BTC"""
    query = update.callback_query if update.callback_query else None
    
    global btc_price, last_btc_update
    
    # Обновляем цену раз в час
    now = datetime.datetime.now()
    if (now - last_btc_update).total_seconds() > 3600:
        btc_price = random.randint(10000, 150000)
        last_btc_update = now
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('btc')} Купить BTC", callback_data="market_buy"),
         InlineKeyboardButton(f"{get_emoji('money')} Продать BTC", callback_data="market_sell")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="market"),
         InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user_id = query.from_user.id if query else update.effective_user.id
    user_data = await get_or_create_user(user_id)
    
    text = (
        f"{get_emoji('market')} *БИРЖА BTC*\n\n"
        f"{get_emoji('btc')} Текущий курс: 1 BTC = {format_number(btc_price)} ₽\n"
        f"{get_emoji('alert')} Курс обновляется каждый час\n\n"
        f"*Ваш баланс:*\n"
        f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}\n"
        f"{get_emoji('btc')} BTC: {user_data.btc:.6f}\n\n"
        f"Выберите действие:"
    )
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def market_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупка BTC"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await query.edit_message_text(
        text=f"{get_emoji('btc')} *ПОКУПКА BTC*\n\n"
             f"{get_emoji('btc')} Курс: 1 BTC = {format_number(btc_price)} ₽\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n\n"
             "Введите сумму в рублях для покупки BTC:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "market_buy"

async def market_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продажа BTC"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await query.edit_message_text(
        text=f"{get_emoji('money')} *ПРОДАЖА BTC*\n\n"
             f"{get_emoji('btc')} Курс: 1 BTC = {format_number(btc_price)} ₽\n"
             f"{get_emoji('btc')} Ваш BTC: {user_data.btc:.6f}\n\n"
             "Введите количество BTC для продажи:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "market_sell"

async def handle_market_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки/продажи BTC"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    action = context.user_data.get("action")
    
    try:
        if action == "market_buy":
            amount_rub = int(update.message.text)
            if amount_rub < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма: 100 ₽")
                return
            if amount_rub > user_data.balance:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств!")
                return
            
            btc_amount = amount_rub / btc_price
            user_data.balance -= amount_rub
            user_data.btc += btc_amount
            
            await db.save_user(user_data)
            
            text = (
                f"{get_emoji('check')} *BTC КУПЛЕН!*\n\n"
                f"{get_emoji('money')} Потрачено: {format_number(amount_rub)} ₽\n"
                f"{get_emoji('btc')} Получено: {btc_amount:.6f} BTC\n"
                f"{get_emoji('btc')} Всего BTC: {user_data.btc:.6f}\n"
                f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}"
            )
            
        elif action == "market_sell":
            btc_amount = float(update.message.text)
            if btc_amount <= 0:
                await update.message.reply_text(f"{get_emoji('alert')} Введите положительное число!")
                return
            if btc_amount > user_data.btc:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно BTC!")
                return
            
            rub_amount = int(btc_amount * btc_price)
            user_data.btc -= btc_amount
            user_data.balance += rub_amount
            
            await db.save_user(user_data)
            
            text = (
                f"{get_emoji('check')} *BTC ПРОДАН!*\n\n"
                f"{get_emoji('btc')} Продано: {btc_amount:.6f} BTC\n"
                f"{get_emoji('money')} Получено: {format_number(rub_amount)} ₽\n"
                f"{get_emoji('btc')} Осталось BTC: {user_data.btc:.6f}\n"
                f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}"
            )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Еще операция", callback_data="market"),
             InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        
    except ValueError:
        await update.message.reply_text(f"{get_emoji('alert')} Введите число!")

# ========== МАГАЗИН ==========
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Магазин"""
    query = update.callback_query if update.callback_query else None
    
    text = (
        f"{get_emoji('shop')} *МАГАЗИН*\n\n"
        "🛒 Товары временно недоступны\n"
        "Скоро здесь появятся уникальные предметы!\n\n"
        "Следите за обновлениями!"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== ФЕРМА BTC ==========
async def farm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню фермы BTC"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Получаем текущую ферму пользователя
    user_farm = await db.get_user_farm(user.id) if db else []
    farm_dict = {farm.gpu_type: farm for farm in user_farm}
    
    # Считаем общий доход
    total_income = 0
    btc_to_collect = 0
    
    for farm in user_farm:
        if farm.last_collected:
            hours_passed = (datetime.datetime.now() - farm.last_collected).total_seconds() / 3600
            gpu_info = GPU_TYPES.get(farm.gpu_type, {})
            income = gpu_info.get("income_per_hour", 0) * farm.quantity * hours_passed
            btc_to_collect += income
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('farm')} Собрать доход", callback_data="farm_collect")],
        [InlineKeyboardButton(f"{get_emoji('shop')} Купить видеокарты", callback_data="farm_buy")],
        [InlineKeyboardButton("📊 Моя ферма", callback_data="farm_info"),
         InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Строим текст с информацией о ферме
    farm_text = f"{get_emoji('farm')} *ФЕРМА BTC*\n\n"
    
    if user_farm:
        farm_text += f"{get_emoji('btc')} *Доход в час:*\n"
        for farm in user_farm:
            gpu_info = GPU_TYPES.get(farm.gpu_type, {})
            hourly = gpu_info.get("income_per_hour", 0) * farm.quantity
            farm_text += f"  {get_gpu_display_name(farm.gpu_type)} x{farm.quantity}: {hourly:.2f} BTC/ч\n"
        
        farm_text += f"\n{get_emoji('btc')} *Накоплено:* {btc_to_collect:.4f} BTC\n"
        farm_text += f"{get_emoji('money')} *Примерная стоимость:* {format_number(int(btc_to_collect * btc_price))}\n"
    else:
        farm_text += "У вас пока нет видеокарт.\n"
        farm_text += "Купите свою первую видеокарту для майнинга BTC!\n\n"
    
    farm_text += f"\n{get_emoji('alert')} *Доход начисляется каждую секунду*\n"
    farm_text += "Собирайте его регулярно!"
    
    await query.edit_message_text(
        text=farm_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def farm_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Собрать доход с фермы"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    if not db:
        await query.answer("База данных недоступна", show_alert=True)
        return
    
    user_farm = await db.get_user_farm(user.id)
    
    if not user_farm:
        await query.answer("У вас нет фермы!", show_alert=True)
        return
    
    total_collected = 0
    now = datetime.datetime.now()
    
    # Собираем доход с каждой фермы
    for farm in user_farm:
        if farm.last_collected:
            hours_passed = (now - farm.last_collected).total_seconds() / 3600
            gpu_info = GPU_TYPES.get(farm.gpu_type, {})
            income = gpu_info.get("income_per_hour", 0) * farm.quantity * hours_passed
            
            if income > 0:
                total_collected += income
                farm.last_collected = now
                await db.update_farm(farm)
        else:
            # Первый сбор
            farm.last_collected = now
            await db.update_farm(farm)
    
    if total_collected > 0:
        user_data.btc += total_collected
        await db.save_user(user_data)
        
        # Обновляем сообщение
        await farm_menu(update, context)
        
        # Отправляем отдельное сообщение о сборе
        await query.message.reply_text(
            text=f"{get_emoji('check')} *ДОХОД СОБРАН!*\n\n"
                 f"{get_emoji('btc')} Собрано: {total_collected:.6f} BTC\n"
                 f"{get_emoji('money')} Стоимость: ~{format_number(int(total_collected * btc_price))} ₽\n"
                 f"{get_emoji('btc')} Всего BTC: {user_data.btc:.6f}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.answer("Пока нечего собирать", show_alert=True)

async def farm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупка видеокарт"""
    query = update.callback_query
    await query.answer()
    
    keyboard = []
    for gpu_type, gpu_info in GPU_TYPES.items():
        user_farm = await db.get_user_farm(query.from_user.id) if db else []
        farm_dict = {farm.gpu_type: farm for farm in user_farm}
        
        current_quantity = farm_dict.get(gpu_type, BTCFarm(query.from_user.id, gpu_type)).quantity
        max_quantity = gpu_info["max_quantity"]
        
        if current_quantity >= max_quantity:
            button_text = f"{get_gpu_display_name(gpu_type)} (MAX)"
            callback_data = f"farm_max_{gpu_type}"
        else:
            # Рассчитываем цену
            price = int(gpu_info["base_price"] * (gpu_info["price_increase"] ** current_quantity))
            button_text = f"{get_gpu_display_name(gpu_type)} - {format_number(price)}"
            callback_data = f"farm_purchase_{gpu_type}"
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="farm_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"{get_emoji('shop')} *КУПИТЬ ВИДЕОКАРТЫ*\n\n"
             f"{get_emoji('alert')} *Важно:*\n"
             "• Цена увеличивается с каждой покупкой\n"
             "• Максимум 3 карты каждого типа\n"
             "• Доход суммируется со всех карт\n\n"
             f"{get_emoji('money')} *Ваш баланс:* {format_number((await get_or_create_user(query.from_user.id)).balance)}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def farm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупка конкретной видеокарты"""
    query = update.callback_query
    await query.answer()
    
    gpu_type = query.data.split("_")[2]
    gpu_info = GPU_TYPES.get(gpu_type)
    
    if not gpu_info:
        await query.answer("Ошибка: неверный тип видеокарты", show_alert=True)
        return
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    if not db:
        await query.answer("База данных недоступна", show_alert=True)
        return
    
    # Получаем текущее количество
    user_farm = await db.get_user_farm(user.id)
    farm_dict = {farm.gpu_type: farm for farm in user_farm}
    
    current_farm = farm_dict.get(gpu_type, BTCFarm(user.id, gpu_type))
    current_quantity = current_farm.quantity
    
    if current_quantity >= gpu_info["max_quantity"]:
        await query.answer(f"Достигнут максимум ({gpu_info['max_quantity']} шт.)", show_alert=True)
        return
    
    # Рассчитываем цену
    price = int(gpu_info["base_price"] * (gpu_info["price_increase"] ** current_quantity))
    
    if user_data.balance < price:
        await query.answer(f"Недостаточно средств! Нужно {format_number(price)}", show_alert=True)
        return
    
    # Совершаем покупку
    user_data.balance -= price
    current_farm.quantity += 1
    if not current_farm.last_collected:
        current_farm.last_collected = datetime.datetime.now()
    
    await db.save_user(user_data)
    await db.update_farm(current_farm)
    
    # Обновляем сообщение
    await farm_buy(update, context)
    
    # Отправляем сообщение о покупке
    await query.message.reply_text(
        text=f"{get_emoji('check')} *ВИДЕОКАРТА КУПЛЕНА!*\n\n"
             f"{get_emoji('gpu')} {gpu_info['name']}\n"
             f"{get_emoji('money')} Цена: {format_number(price)}\n"
             f"{get_emoji('btc')} Доход: {gpu_info['income_per_hour']} BTC/час\n"
             f"{get_emoji('gpu')} Количество: {current_farm.quantity}/{gpu_info['max_quantity']}\n"
             f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}\n\n"
             f"{get_emoji('alert')} Доход будет начисляться автоматически!",
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о ферме"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    if not db:
        await query.answer("База данных недоступна", show_alert=True)
        return
    
    user_farm = await db.get_user_farm(user.id)
    
    if not user_farm:
        text = f"{get_emoji('farm')} *ВАША ФЕРМА*\n\n" \
               "У вас пока нет видеокарт.\n" \
               "Купите свою первую видеокарту в меню покупки!"
    else:
        text = f"{get_emoji('farm')} *ВАША ФЕРМА*\n\n"
        
        total_hourly = 0
        total_btc = 0
        now = datetime.datetime.now()
        
        for farm in user_farm:
            gpu_info = GPU_TYPES.get(farm.gpu_type, {})
            hourly = gpu_info.get("income_per_hour", 0) * farm.quantity
            total_hourly += hourly
            
            if farm.last_collected:
                hours_passed = (now - farm.last_collected).total_seconds() / 3600
                total_btc += hourly * hours_passed
            
            text += f"{get_gpu_display_name(farm.gpu_type)}:\n"
            text += f"  ×{farm.quantity} шт. | {hourly:.2f} BTC/ч\n"
            if farm.last_collected:
                last = farm.last_collected.strftime("%H:%M:%S")
                text += f"  Последний сбор: {last}\n"
            text += "\n"
        
        text += f"{get_emoji('btc')} *Общий доход в час:* {total_hourly:.4f} BTC\n"
        text += f"{get_emoji('money')} *В рублях:* ~{format_number(int(total_hourly * btc_price))}/ч\n"
        
        if total_btc > 0:
            text += f"\n{get_emoji('alert')} *Накоплено к сбору:* {total_btc:.6f} BTC\n"
            text += f"{get_emoji('money')} *Стоимость:* ~{format_number(int(total_btc * btc_price))}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="farm_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== БАНК ==========
async def bank_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню банка"""
    query = update.callback_query if update.callback_query else None
    user = query.from_user if query else update.effective_user
    
    user_data = await get_or_create_user(user.id, user.username)
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('deposit')} Пополнить", callback_data="bank_deposit"),
         InlineKeyboardButton(f"{get_emoji('withdraw')} Снять", callback_data="bank_withdraw")],
        [InlineKeyboardButton(f"{get_emoji('transfer')} Перевести", callback_data="bank_transfer"),
         InlineKeyboardButton("📊 Статистика", callback_data="bank_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{get_emoji('bank')} *БАНК*\n\n"
        f"{get_emoji('money')} *Наличные:* {format_number(user_data.balance)}\n"
        f"{get_emoji('bank')} *В банке:* {format_number(user_data.bank)}\n\n"
        f"{get_emoji('alert')} *Ежедневные проценты:* 5%\n"
        f"Начисляются каждый день в 00:00 по МСК\n\n"
        "Выберите действие:"
    )
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def bank_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пополнение банка"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await query.edit_message_text(
        text=f"{get_emoji('deposit')} *ПОПОЛНЕНИЕ БАНКА*\n\n"
             f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}\n"
             f"{get_emoji('bank')} В банке: {format_number(user_data.bank)}\n\n"
             "Введите сумму для пополнения:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "bank_deposit"

async def bank_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Снятие из банка"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await query.edit_message_text(
        text=f"{get_emoji('withdraw')} *СНЯТИЕ ИЗ БАНКА*\n\n"
             f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}\n"
             f"{get_emoji('bank')} В банке: {format_number(user_data.bank)}\n\n"
             "Введите сумму для снятия:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "bank_withdraw"

async def bank_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перевод другому пользователю"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await query.edit_message_text(
        text=f"{get_emoji('transfer')} *ПЕРЕВОД СРЕДСТВ*\n\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n\n"
             "Введите в формате:\n"
             "`ID_получателя СУММА`\n\n"
             "Пример: `123456789 1000`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "bank_transfer"

async def bank_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика банка"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Расчет ежедневных процентов
    daily_interest = int(user_data.bank * 0.05)
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="bank_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{get_emoji('stats')} *СТАТИСТИКА БАНКА*\n\n"
        f"{get_emoji('money')} *Наличные:* {format_number(user_data.balance)}\n"
        f"{get_emoji('bank')} *В банке:* {format_number(user_data.bank)}\n\n"
        f"{get_emoji('alert')} *Ежедневный процент:* 5%\n"
        f"{get_emoji('money')} *Завтра получите:* +{format_number(daily_interest)}\n\n"
        f"{get_emoji('alert')} Проценты начисляются каждый день\n"
        "в 00:00 по московскому времени."
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def handle_bank_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий банка"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    action = context.user_data.get("action")
    
    try:
        if action == "bank_deposit":
            amount = int(update.message.text)
            if amount < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма: 100")
                return
            if amount > user_data.balance:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств!")
                return
            
            user_data.balance -= amount
            user_data.bank += amount
            
            await db.save_user(user_data)
            
            text = (
                f"{get_emoji('check')} *СРЕДСТВА ПОПОЛНЕНЫ!*\n\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}\n"
                f"{get_emoji('bank')} В банке: {format_number(user_data.bank)}\n\n"
                f"{get_emoji('alert')} Завтра получите 5% от этой суммы!"
            )
        
        elif action == "bank_withdraw":
            amount = int(update.message.text)
            if amount < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма: 100")
                return
            if amount > user_data.bank:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств в банке!")
                return
            
            user_data.bank -= amount
            user_data.balance += amount
            
            await db.save_user(user_data)
            
            text = (
                f"{get_emoji('check')} *СРЕДСТВА СНЯТЫ!*\n\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}\n"
                f"{get_emoji('bank')} В банке: {format_number(user_data.bank)}"
            )
        
        elif action == "bank_transfer":
            parts = update.message.text.split()
            if len(parts) != 2:
                await update.message.reply_text(
                    f"{get_emoji('alert')} Неверный формат!\n"
                    "Используйте: `ID_получателя СУММА`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            try:
                receiver_id = int(parts[0])
                amount = int(parts[1])
            except ValueError:
                await update.message.reply_text(f"{get_emoji('alert')} Введите корректные числа!")
                return
            
            if amount < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма: 100")
                return
            
            if amount > user_data.balance:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств!")
                return
            
            # Проверяем, существует ли получатель
            receiver = await get_or_create_user(receiver_id)
            
            if receiver.user_id == user.id:
                await update.message.reply_text(f"{get_emoji('alert')} Нельзя перевести себе!")
                return
            
            # Совершаем перевод
            user_data.balance -= amount
            receiver.balance += amount
            
            await db.save_user(user_data)
            await db.save_user(receiver)
            
            # Отправляем уведомление получателю
            try:
                await context.bot.send_message(
                    chat_id=receiver_id,
                    text=f"{get_emoji('money')} *ВЫ ПОЛУЧИЛИ ПЕРЕВОД!*\n\n"
                         f"От: {user.first_name} (@{user.username or 'нет'})\n"
                         f"Сумма: {format_number(amount)}\n"
                         f"Ваш баланс: {format_number(receiver.balance)}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass  # Если не удалось отправить уведомление
            
            text = (
                f"{get_emoji('check')} *ПЕРЕВОД ВЫПОЛНЕН!*\n\n"
                f"👤 Получатель: {receiver_id}\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n\n"
                f"{get_emoji('alert')} Получатель уведомлен о переводе."
            )
        
        keyboard = [
            [InlineKeyboardButton("🏦 В банк", callback_data="bank_menu"),
             InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        
    except ValueError:
        await update.message.reply_text(f"{get_emoji('alert')} Введите число!")

# ========== РАБОТА ==========
async def work_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню работы"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    keyboard = []
    for job_type, job_info in JOBS.items():
        display_name = get_job_display_name(job_type)
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"work_{job_type}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_job = None
    if user_data.job:
        current_job = JOBS.get(user_data.job, {})
    
    text = f"{get_emoji('work')} *РАБОТА*\n\n"
    
    if current_job:
        text += f"{get_emoji('job')} *Текущая работа:* {get_job_display_name(user_data.job)}\n"
        text += f"{get_emoji('alert')} *Описание:* {current_job.get('description', '')}\n\n"
    else:
        text += "У вас пока нет работы.\n"
        text += "Выберите профессию из списка:\n\n"
    
    text += f"{get_emoji('money')} *Доступные профессии:*\n"
    
    for job_type, job_info in JOBS.items():
        salary_range = f"{format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])}"
        btc_chance = job_info['btc_chance']
        text += f"• {get_job_display_name(job_type)}: {salary_range} ₽ | {btc_chance}% BTC\n"
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def work_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор работы"""
    query = update.callback_query
    await query.answer()
    
    job_type = query.data.split("_")[1]
    job_info = JOBS.get(job_type)
    
    if not job_info:
        await query.answer("Ошибка: работа не найдена", show_alert=True)
        return
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Если уже работает, спросим о смене
    if user_data.job == job_type:
        await query.answer(f"Вы уже работаете {job_info['name']}!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("✅ Сменить работу", callback_data=f"work_confirm_{job_type}"),
         InlineKeyboardButton("❌ Отмена", callback_data="work_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{get_emoji('work')} *СМЕНА РАБОТЫ*\n\n"
        f"📝 *Профессия:* {get_job_display_name(job_type)}\n"
        f"📄 *Описание:* {job_info['description']}\n\n"
        f"💰 *Зарплата:* {format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])} ₽\n"
        f"{get_emoji('btc')} *Шанс BTC:* {job_info['btc_chance']}%\n"
        f"⏱ *Перерыв:* {job_info['cooldown']} сек.\n\n"
        f"Вы уверены, что хотите сменить работу?"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def work_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение смены работы"""
    query = update.callback_query
    await query.answer()
    
    job_type = query.data.split("_")[2]
    job_info = JOBS.get(job_type)
    
    if not job_info:
        await query.answer("Ошибка: работа не найдена", show_alert=True)
        return
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Меняем работу
    user_data.job = job_type
    user_data.last_work = None  # Сбрасываем таймер работы
    await db.save_user(user_data)
    
    await query.edit_message_text(
        text=f"{get_emoji('check')} *РАБОТА СМЕНЕНА!*\n\n"
             f"Теперь вы работаете: {get_job_display_name(job_type)}\n"
             f"Можете начинать работать сразу!",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Показываем меню работы через секунду
    await asyncio.sleep(1)
    await work_menu(update, context)

async def work_perform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение работы"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    if not user_data.job:
        await query.answer("Сначала выберите работу!", show_alert=True)
        await work_menu(update, context)
        return
    
    job_info = JOBS.get(user_data.job, {})
    
    # Проверяем перерыв
    if user_data.last_work:
        cooldown = job_info.get("cooldown", 300)
        seconds_passed = (datetime.datetime.now() - user_data.last_work).total_seconds()
        
        if seconds_passed < cooldown:
            remaining = int(cooldown - seconds_passed)
            minutes = remaining // 60
            seconds = remaining % 60
            
            await query.answer(
                f"⏱ Отдохните еще {minutes}:{seconds:02d}",
                show_alert=True
            )
            return
    
    # Выполняем работу
    salary = random.randint(job_info.get("min_salary", 10000), job_info.get("max_salary", 50000))
    btc_found = 0
    
    # Шанс найти BTC
    if random.randint(1, 100) <= job_info.get("btc_chance", 9):
        btc_found = round(random.uniform(0.0001, 0.001), 6)
        user_data.btc += btc_found
    
    user_data.balance += salary
    user_data.last_work = datetime.datetime.now()
    
    # Шанс получить EXP
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
    
    await db.save_user(user_data)
    
    # Формируем текст результата
    result_text = f"{get_emoji('check')} *РАБОТА ВЫПОЛНЕНА!*\n\n"
    result_text += f"{get_emoji('job')} *Профессия:* {get_job_display_name(user_data.job)}\n"
    result_text += f"{get_emoji('money')} *Зарплата:* {format_number(salary)} ₽\n"
    
    if btc_found > 0:
        result_text += f"{get_emoji('btc')} *Найден BTC:* {btc_found:.6f}\n"
        result_text += f"{get_emoji('money')} *Стоимость:* ~{format_number(int(btc_found * btc_price))} ₽\n"
    
    result_text += f"\n{get_emoji('money')} *Баланс:* {format_number(user_data.balance)}\n"
    
    if btc_found > 0:
        result_text += f"{get_emoji('btc')} *BTC:* {user_data.btc:.6f}\n"
    
    # Проверяем, повысился ли уровень
    if user_data.exp == 1:  # Только что получили EXP
        result_text += f"\n{get_emoji('exp')} Получен 1 EXP! ({user_data.exp}/{LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4)})\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Работать снова", callback_data="work_perform"),
         InlineKeyboardButton("🔙 В меню", callback_data="work_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    # ========== БОНУСЫ ==========
async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню бонусов"""
    query = update.callback_query if update.callback_query else None
    user = query.from_user if query else update.effective_user
    
    user_data = await get_or_create_user(user.id, user.username)
    
    # Проверяем доступность ежедневного бонуса
    daily_available = False
    if user_data.last_daily_bonus:
        now = datetime.datetime.now()
        last = user_data.last_daily_bonus
        hours_passed = (now - last).total_seconds() / 3600
        daily_available = hours_passed >= 24
    else:
        daily_available = True
    
    # Проверяем доступность бонуса уровня
    level_bonus_available = user_data.level >= 1
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('bonus')} Ежедневный бонус", callback_data="daily_bonus")],
        [InlineKeyboardButton(f"{get_emoji('level')} Бонус уровня", callback_data="level_bonus")],
        [InlineKeyboardButton(f"{get_emoji('gift')} Промокод", callback_data="promo_code")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"{get_emoji('bonus')} *БОНУСЫ*\n\n"
    
    # Ежедневный бонус
    if daily_available:
        text += f"{get_emoji('check')} *Ежедневный бонус:* Доступен\n"
    else:
        next_bonus = user_data.last_daily_bonus + datetime.timedelta(hours=24)
        remaining = next_bonus - datetime.datetime.now()
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        text += f"{get_emoji('alert')} *Ежедневный бонус:* Через {hours}ч {minutes}м\n"
    
    # Бонус уровня
    level_bonus_amount = LEVEL_BONUS.get(user_data.level, 50000)
    text += f"{get_emoji('level')} *Бонус уровня {user_data.level}:* {format_number(level_bonus_amount)}\n\n"
    
    text += "Выберите бонус:"
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный бонус"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Проверяем, можно ли получить бонус
    if user_data.last_daily_bonus:
        now = datetime.datetime.now()
        last = user_data.last_daily_bonus
        hours_passed = (now - last).total_seconds() / 3600
        
        if hours_passed < 24:
            next_bonus = last + datetime.timedelta(hours=24)
            remaining = next_bonus - now
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            
            await query.answer(f"Бонус доступен через {hours}ч {minutes}м", show_alert=True)
            return
    
    # Выдаем бонус
    # Бонус зависит от уровня
    bonus_amount = 10000 + (user_data.level * 5000)  # 10к + 5к за уровень
    user_data.balance += bonus_amount
    user_data.last_daily_bonus = datetime.datetime.now()
    
    # Добавление EXP
    if random.random() < 0.5:
        user_data.exp += 1
    
    await db.save_user(user_data)
    
    text = (
        f"{get_emoji('bonus')} *ЕЖЕДНЕВНЫЙ БОНУС ПОЛУЧЕН!*\n\n"
        f"{get_emoji('money')} Сумма: {format_number(bonus_amount)}\n"
        f"{get_emoji('level')} Уровень: {user_data.level}\n"
        f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}\n"
        f"{get_emoji('exp')} EXP: {user_data.exp}/{LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4)}\n\n"
        f"{get_emoji('alert')} Следующий бонус через 24 часа"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="bonus")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def level_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бонус за уровень"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Проверяем, получал ли уже бонус за текущий уровень
    # Для простоты - бонус можно получать только при достижении нового уровня
    # В реальной системе нужно отслеживать, получал ли уже бонус за этот уровень
    
    level_bonus_amount = LEVEL_BONUS.get(user_data.level, 50000)
    
    # Для демонстрации - просто выдаем бонус
    user_data.balance += level_bonus_amount
    
    # Добавление EXP
    if random.random() < 0.5:
        user_data.exp += 1
    
    await db.save_user(user_data)
    
    text = (
        f"{get_emoji('level')} *БОНУС УРОВНЯ ПОЛУЧЕН!*\n\n"
        f"{get_emoji('level')} Уровень: {user_data.level}\n"
        f"{get_emoji('money')} Бонус: {format_number(level_bonus_amount)}\n"
        f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}\n\n"
        f"{get_emoji('alert')} Повышайте уровень для большего бонуса!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 В меню", callback_data="main_menu"),
         InlineKeyboardButton("📊 Профиль", callback_data="profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод промокода"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text=f"{get_emoji('gift')} *ПРОМОКОД*\n\n"
             "Введите промокод:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "promo_code"

async def handle_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка промокода"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    promo = update.message.text.strip().upper()
    
    # Простая проверка промокодов (в реальной системе нужно хранить в БД)
    valid_promos = {
        "WELCOME2024": {"type": "money", "value": 50000},
        "VIPCODE": {"type": "btc", "value": 0.01},
        "LEVELUP": {"type": "exp", "value": 10},
        "BONUS100K": {"type": "money", "value": 100000}
    }
    
    if promo in valid_promos:
        promo_info = valid_promos[promo]
        
        if promo_info["type"] == "money":
            amount = promo_info["value"]
            user_data.balance += amount
            message = f"{get_emoji('money')} Получено: {format_number(amount)} ₽"
        elif promo_info["type"] == "btc":
            amount = promo_info["value"]
            user_data.btc += amount
            message = f"{get_emoji('btc')} Получено: {amount} BTC"
        elif promo_info["type"] == "exp":
            amount = int(promo_info["value"])
            user_data.exp += amount
            message = f"{get_emoji('exp')} Получено: {amount} EXP"
        
        await db.save_user(user_data)
        
        text = (
            f"{get_emoji('check')} *ПРОМОКОД АКТИВИРОВАН!*\n\n"
            f"Код: {promo}\n"
            f"{message}\n\n"
            f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}\n"
            f"{get_emoji('btc')} BTC: {user_data.btc:.6f}\n"
            f"{get_emoji('exp')} EXP: {user_data.exp}"
        )
        
        # Помечаем промокод как использованный (в реальной системе)
        # Можно добавить в БД таблицу использованных промокодов
        
    else:
        text = f"{get_emoji('cross')} *ПРОМОКОД НЕДЕЙСТВИТЕЛЕН!*\n\nПопробуйте другой код."
    
    keyboard = [
        [InlineKeyboardButton("🎁 Другой промокод", callback_data="promo_code"),
         InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реферальная система"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Если пользователь пришел по реферальной ссылке
    if len(context.args) > 0:
        ref_code = context.args[0]
        
        # Нельзя использовать свой же код
        if ref_code == user_data.referral_code:
            await update.message.reply_text(
                f"{get_emoji('alert')} Нельзя использовать свой реферальный код!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Проверяем, есть ли уже реферер
        if user_data.referred_by:
            await update.message.reply_text(
                f"{get_emoji('alert')} У вас уже есть реферер!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Ищем пользователя по реферальному коду
        ref_user = None
        if db:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow('SELECT * FROM users WHERE referral_code = $1', ref_code)
                if row:
                    ref_user = User.from_dict(dict(row))
        
        if ref_user and ref_user.user_id != user.id:
            # Регистрируем реферала
            user_data.referred_by = ref_user.user_id
            
            # Начисляем бонус рефереру
            ref_user.balance += REFERRAL_BONUS
            ref_user.total_referrals += 1
            
            await db.save_user(user_data)
            await db.save_user(ref_user)
            
            # Уведомляем реферера
            try:
                await context.bot.send_message(
                    chat_id=ref_user.user_id,
                    text=f"{get_emoji('money')} *НОВЫЙ РЕФЕРАЛ!*\n\n"
                         f"Пользователь {user.first_name} (@{user.username or 'нет'}) "
                         f"зарегистрировался по вашей ссылке!\n"
                         f"Бонус: {format_number(REFERRAL_BONUS)} ₽\n"
                         f"Всего рефералов: {ref_user.total_referrals}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            await update.message.reply_text(
                f"{get_emoji('check')} *ВЫ ЗАРЕГИСТРИРОВАНЫ ПО РЕФЕРАЛЬНОЙ ССЫЛКЕ!*\n\n"
                f"Реферер: {ref_user.username or 'Аноним'}\n"
                f"Вы получили доступ ко всем функциям бота!\n\n"
                f"{get_emoji('money')} Ваш реферальный код: `{user_data.referral_code}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    # Показываем информацию о реферальной системе
    ref_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user_data.referral_code}"
    
    text = (
        f"{get_emoji('money')} *РЕФЕРАЛЬНАЯ СИСТЕМА*\n\n"
        f"{get_emoji('alert')} *Приглашайте друзей и получайте бонусы!*\n\n"
        f"{get_emoji('check')} *За каждого приглашенного:*\n"
        f"• {format_number(REFERRAL_BONUS)} ₽ сразу\n"
        f"• {REFERRAL_PERCENTS[0]*100}% от их доходов (1 уровень)\n"
        f"• {REFERRAL_PERCENTS[1]*100}% (2 уровень)\n"
        f"• {REFERRAL_PERCENTS[2]*100}% (3 уровень)\n\n"
        f"{get_emoji('stats')} *Ваша статистика:*\n"
        f"• Рефералов: {user_data.total_referrals}\n"
        f"• Заработано: {format_number(user_data.referral_earnings)} ₽\n\n"
        f"{get_emoji('link')} *Ваша реферальная ссылка:*\n"
        f"`{ref_link}`\n\n"
        f"{get_emoji('id')} *Ваш реферальный код:*\n"
        f"`{user_data.referral_code}`"
    )
    
    keyboard = [
        [InlineKeyboardButton("📢 Поделиться ссылкой", 
         url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся%20к%20Vibe%20Bet!")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def distribute_referral_bonus(user_id: int, amount: int, context: ContextTypes.DEFAULT_TYPE):
    """Распределение реферального бонуса по уровням"""
    if not db or amount <= 0:
        return
    
    current_user_id = user_id
    level = 1
    processed_users = set()
    
    while level <= REFERRAL_LEVELS and current_user_id:
        # Защита от циклов
        if current_user_id in processed_users:
            break
        processed_users.add(current_user_id)
        
        # Получаем текущего пользователя
        user = await db.get_user(current_user_id)
        if not user or not user.referred_by:
            break
        
        # Получаем реферера
        referrer_id = user.referred_by
        referrer = await db.get_user(referrer_id)
        if not referrer:
            current_user_id = referrer_id
            level += 1
            continue
        
        # Вычисляем бонус
        bonus_percent = REFERRAL_PERCENTS[level-1] if level <= len(REFERRAL_PERCENTS) else 0
        bonus_amount = int(amount * bonus_percent)
        
        if bonus_amount > 0:
            # Начисляем бонус рефереру
            referrer.balance += bonus_amount
            referrer.referral_earnings += bonus_amount
            
            await db.save_user(referrer)
            
            # Логируем выплату
            if db:
                await db.add_transaction(
                    referrer_id,
                    bonus_amount,
                    "referral",
                    f"Реферальный бонус уровня {level} от {current_user_id}"
                )
            
            # Отправляем уведомление
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"{get_emoji('money')} *РЕФЕРАЛЬНЫЙ БОНУС!*\n\n"
                         f"Уровень: {level}\n"
                         f"Сумма: {format_number(bonus_amount)} ₽\n"
                         f"От: {user.username or 'Аноним'}\n\n"
                         f"{get_emoji('money')} Баланс: {format_number(referrer.balance)}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
        
        # Переходим к следующему уровню
        current_user_id = referrer_id
        level += 1

# ========== АДМИН-ПАНЕЛЬ ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ-панель"""
    user = update.effective_user
    
    # Проверка прав
    if user.id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer("У вас нет доступа!", show_alert=True)
        else:
            await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton("👤 Поиск пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton("💰 Выдать деньги", callback_data="admin_give_money"),
         InlineKeyboardButton("❌ Забрать деньги", callback_data="admin_take_money")],
        [InlineKeyboardButton("🚫 Бан пользователя", callback_data="admin_ban"),
         InlineKeyboardButton("✅ Разбан пользователя", callback_data="admin_unban")],
        [InlineKeyboardButton("🎁 Создать промокод", callback_data="admin_create_promo"),
         InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"👑 *АДМИН-ПАНЕЛЬ*\n\n"
        f"Пользователь: {user.first_name} (@{user.username or 'нет'})\n"
        f"ID: `{user.id}`\n\n"
        f"Выберите действие:"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика для админа"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    # Базовая статистика (в реальной системе нужно считать из БД)
    text = (
        f"📊 *СТАТИСТИКА СИСТЕМЫ*\n\n"
        f"🕐 *Время сервера:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"💎 *Курс BTC:* {format_number(btc_price)} ₽\n"
        f"⚙️ *База данных:* {'✅ Подключена' if db else '❌ Не подключена'}\n\n"
        f"{get_emoji('alert')} *Детальная статистика:*\n"
        f"Для получения полной статистики\n"
        f"необходимо подключение к базе данных.\n\n"
        f"*Доступные команды:*\n"
        f"• /stats - общая статистика\n"
        f"• Поиск пользователя - детальная информация"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def admin_find_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск пользователя"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="🔍 *ПОИСК ПОЛЬЗОВАТЕЛЯ*\n\n"
             "Введите ID пользователя или @username:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "find_user"

async def admin_give_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача денег"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="💰 *ВЫДАЧА ДЕНЕГ*\n\n"
             "Введите в формате:\n"
             "`ID_пользователя СУММА`\n\n"
             "Пример: `123456789 10000`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_money"

async def admin_take_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Забирание денег"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="❌ *ЗАБИРАНИЕ ДЕНЕГ*\n\n"
             "Введите в формате:\n"
             "`ID_пользователя СУММА`\n\n"
             "Пример: `123456789 10000`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "take_money"

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бан пользователя"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="🚫 *БАН ПОЛЬЗОВАТЕЛЯ*\n\n"
             "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "ban_user"

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разбан пользователя"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="✅ *РАЗБАН ПОЛЬЗОВАТЕЛЯ*\n\n"
             "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "unban_user"

async def admin_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="🎁 *СОЗДАНИЕ ПРОМОКОДА*\n\n"
             "Введите в формате:\n"
             "`КОД ТИП ЗНАЧЕНИЕ`\n\n"
             "Типы: money, btc, exp, level\n"
             "Пример: `WELCOME money 50000`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "create_promo"

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассылка сообщений"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text="📢 *РАССЫЛКА СООБЩЕНИЙ*\n\n"
             "Введите сообщение для рассылки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "broadcast"

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка админских действий"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа!")
        return
    
    action = context.user_data.get("admin_action")
    text = update.message.text.strip()
    
    try:
        if action == "find_user":
            # Поиск пользователя
            try:
                user_id = int(text)
            except:
                # Попробуем найти по username (без @)
                username = text.lstrip('@')
                if db:
                    async with db.pool.acquire() as conn:
                        row = await conn.fetchrow('SELECT * FROM users WHERE username = $1', username)
                        if row:
                            user_data = User.from_dict(dict(row))
                            user_id = user_data.user_id
                        else:
                            await update.message.reply_text("Пользователь не найден!")
                            return
                else:
                    await update.message.reply_text("База данных не подключена!")
                    return
            
            # Получаем данные пользователя
            target_user = await get_or_create_user(user_id)
            
            response = (
                f"👤 *ДАННЫЕ ПОЛЬЗОВАТЕЛЯ*\n\n"
                f"ID: `{target_user.user_id}`\n"
                f"Username: @{target_user.username or 'нет'}\n"
                f"Баланс: {format_number(target_user.balance)}\n"
                f"В банке: {format_number(target_user.bank)}\n"
                f"BTC: {target_user.btc:.6f}\n"
                f"Уровень: {target_user.level}\n"
                f"EXP: {target_user.exp}/{LEVEL_EXP_REQUIREMENTS.get(target_user.level, 4)}\n"
                f"Побед: {target_user.wins}\n"
                f"Поражений: {target_user.loses}\n"
                f"Работа: {target_user.job or 'нет'}\n"
                f"Забанен: {'Да' if target_user.is_banned else 'Нет'}\n"
                f"Рефералов: {target_user.total_referrals}\n"
                f"Реферальный код: `{target_user.referral_code}`\n"
                f"Регистрация: {target_user.registered.strftime('%Y-%m-%d %H:%M')}"
            )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        
        elif action == "give_money":
            # Выдача денег
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text("Неверный формат!")
                return
            
            user_id = int(parts[0])
            amount = int(parts[1])
            
            target_user = await get_or_create_user(user_id)
            target_user.balance += amount
            
            await db.save_user(target_user)
            
            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎁 *АДМИН ВЫДАЛ ВАМ ДЕНЬГИ!*\n\n"
                         f"Сумма: {format_number(amount)} ₽\n"
                         f"Баланс: {format_number(target_user.balance)}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            response = (
                f"✅ *ДЕНЬГИ ВЫДАНЫ!*\n\n"
                f"Пользователь: {user_id}\n"
                f"Сумма: {format_number(amount)}\n"
                f"Новый баланс: {format_number(target_user.balance)}"
            )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        
        elif action == "take_money":
            # Забирание денег
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text("Неверный формат!")
                return
            
            user_id = int(parts[0])
            amount = int(parts[1])
            
            target_user = await get_or_create_user(user_id)
            
            if amount > target_user.balance:
                amount = target_user.balance
            
            target_user.balance -= amount
            
            await db.save_user(target_user)
            
            response = (
                f"✅ *ДЕНЬГИ ЗАБРАНЫ!*\n\n"
                f"Пользователь: {user_id}\n"
                f"Сумма: {format_number(amount)}\n"
                f"Новый баланс: {format_number(target_user.balance)}"
            )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        
        elif action == "ban_user":
            # Бан пользователя
            user_id = int(text)
            
            target_user = await get_or_create_user(user_id)
            target_user.is_banned = True
            
            await db.save_user(target_user)
            
            response = f"✅ Пользователь {user_id} забанен!"
            await update.message.reply_text(response)
        
        elif action == "unban_user":
            # Разбан пользователя
            user_id = int(text)
            
            target_user = await get_or_create_user(user_id)
            target_user.is_banned = False
            
            await db.save_user(target_user)
            
            response = f"✅ Пользователь {user_id} разбанен!"
            await update.message.reply_text(response)
        
        elif action == "create_promo":
            # Создание промокода
            parts = text.split()
            if len(parts) != 3:
                await update.message.reply_text("Неверный формат!")
                return
            
            code = parts[0].upper()
            promo_type = parts[1]
            value = float(parts[2])
            
            # Сохраняем промокод (в реальной системе - в БД)
            # Здесь просто подтверждаем создание
            
            response = (
                f"✅ *ПРОМОКОД СОЗДАН!*\n\n"
                f"Код: `{code}`\n"
                f"Тип: {promo_type}\n"
                f"Значение: {value}"
            )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        
        elif action == "broadcast":
            # Рассылка
            message = text
            
            # В реальной системе нужно получить всех пользователей из БД
            # Здесь просто подтверждаем
            
            response = (
                f"✅ *РАССЫЛКА НАЧАТА!*\n\n"
                f"Сообщение:\n{message}\n\n"
                f"В реальной системе сообщение будет отправлено всем пользователям."
            )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    except ValueError as e:
        await update.message.reply_text(f"Ошибка: {e}")
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {e}")
        # ========== ОБРАБОТКА CALLBACK-ЗАПРОСОВ ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-запросов"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Основное меню
    if data == "main_menu":
        await start(update, context)
    elif data == "check_subscription":
        user = query.from_user
        if await check_subscription(user.id, context):
            await query.answer("✅ Подписка подтверждена!", show_alert=True)
            await start(update, context)
        else:
            await query.answer("❌ Вы не подписаны на каналы!", show_alert=True)
    
    # Профиль
    elif data == "profile":
        await profile(update, context)
    
    # Игры
    elif data == "games_menu":
        await games_menu(update, context)
    elif data.startswith("game_"):
        game = data.split("_")[1]
        if game == "dice":
            await game_dice(update, context)
        elif game == "football":
            await game_football(update, context)
        elif game == "roulette":
            await game_roulette(update, context)
        elif game == "diamonds":
            await game_diamonds(update, context)
        elif game == "mines":
            await game_mines(update, context)
        elif game == "crash":
            await game_crash(update, context)
        elif game == "blackjack":
            await game_blackjack(update, context)
    
    # Кости
    elif data.startswith("dice_"):
        await dice_bet(update, context)
    elif data == "dice_high" or data == "dice_low" or data == "dice_equal":
        context.user_data["game"] = "dice"
        context.user_data["bet_type"] = data.split("_")[1]
        await dice_bet(update, context)
    
    # Футбол
    elif data.startswith("football_"):
        await football_bet(update, context)
    
    # Рулетка
    elif data.startswith("roulette_"):
        await roulette_bet(update, context)
    
    # Алмазы
    elif data.startswith("diamond_"):
        if data == "diamond_claim":
            await diamond_claim(update, context)
        else:
            await diamond_open(update, context)
    
    # Мины
    elif data.startswith("mine_"):
        if data == "mine_gameover":
            return
        elif data == "mines_claim":
            await mines_claim(update, context)
        else:
            await mine_open(update, context)
    
    # Краш
    elif data == "crash_cashout":
        await crash_cashout(update, context)
    
    # Очко
    elif data == "blackjack_hit":
        await blackjack_hit(update, context)
    elif data == "blackjack_stand":
        await blackjack_stand(update, context)
    
    # Биржа
    elif data == "market":
        await market(update, context)
    elif data == "market_buy":
        await market_buy(update, context)
    elif data == "market_sell":
        await market_sell(update, context)
    
    # Магазин
    elif data == "shop":
        await shop(update, context)
    
    # Ферма
    elif data == "farm_menu":
        await farm_menu(update, context)
    elif data == "farm_collect":
        await farm_collect(update, context)
    elif data == "farm_buy":
        await farm_buy(update, context)
    elif data.startswith("farm_purchase_"):
        await farm_purchase(update, context)
    elif data.startswith("farm_max_"):
        await query.answer("Достигнут максимум видеокарт!", show_alert=True)
    elif data == "farm_info":
        await farm_info(update, context)
    
    # Банк
    elif data == "bank_menu":
        await bank_menu(update, context)
    elif data == "bank_deposit":
        await bank_deposit(update, context)
    elif data == "bank_withdraw":
        await bank_withdraw(update, context)
    elif data == "bank_transfer":
        await bank_transfer(update, context)
    elif data == "bank_stats":
        await bank_stats(update, context)
    
    # Работа
    elif data == "work_menu":
        await work_menu(update, context)
    elif data.startswith("work_"):
        if data == "work_perform":
            await work_perform(update, context)
        elif data.startswith("work_confirm_"):
            await work_confirm(update, context)
        else:
            await work_select(update, context)
    
    # Бонусы
    elif data == "bonus":
        await bonus(update, context)
    elif data == "daily_bonus":
        await daily_bonus(update, context)
    elif data == "level_bonus":
        await level_bonus(update, context)
    elif data == "promo_code":
        await promo_code(update, context)
    
    # Админ-панель
    elif data == "admin_panel":
        await admin_panel(update, context)
    elif data == "admin_stats":
        await admin_stats(update, context)
    
    # Если не найдено обработчика
    else:
        await query.answer("Команда не реализована", show_alert=True)

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ==========
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user = update.effective_user
    text = update.message.text.strip()
    
    # Проверяем, забанен ли пользователь
    if await check_ban(user.id):
        await update.message.reply_text(
            f"{get_emoji('cross')} Вы заблокированы в этом боте!",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Обработка игр
    if context.user_data.get("game"):
        game = context.user_data["game"]
        
        if game == "dice":
            await dice_play(update, context)
        elif game == "football":
            await football_play(update, context)
        elif game == "roulette":
            await roulette_play(update, context)
        elif game == "diamonds_claim":
            await diamond_finish(update, context)
        elif game == "mines_claim":
            await mines_finish(update, context)
        elif game == "crash":
            await crash_play(update, context)
        elif game == "blackjack":
            await blackjack_play(update, context)
    
    # Обработка действий банка/биржи
    elif context.user_data.get("action"):
        action = context.user_data["action"]
        
        if action.startswith("market_"):
            await handle_market_action(update, context)
        elif action.startswith("bank_"):
            await handle_bank_action(update, context)
        elif action == "promo_code":
            await handle_promo_code(update, context)
    
    # Обработка админских команд
    elif context.user_data.get("admin_action"):
        await handle_admin_action(update, context)
    
    # Обработка команд без слеша
    elif text.lower() in ["профиль", "profile"]:
        await profile(update, context)
    elif text.lower() in ["игры", "games"]:
        await games_menu(update, context)
    elif text.lower() in ["работа", "work"]:
        await work_menu(update, context)
    elif text.lower() in ["ферма", "farm"]:
        await farm_menu(update, context)
    elif text.lower() in ["банк", "bank"]:
        await bank_menu(update, context)
    elif text.lower() in ["биржа", "market"]:
        await market(update, context)
    elif text.lower() in ["магазин", "shop"]:
        await shop(update, context)
    elif text.lower() in ["бонус", "bonus"]:
        await bonus(update, context)
    elif text.lower() in ["рефералы", "referral"]:
        await referral(update, context)
    elif text.lower() in ["админ", "admin"]:
        await admin_panel(update, context)
    
    # Если это число, предлагаем игры
    elif text.isdigit():
        amount = int(text)
        if 100 <= amount <= 1000000:
            keyboard = [
                [InlineKeyboardButton("🎲 Кости", callback_data="game_dice"),
                 InlineKeyboardButton("⚽ Футбол", callback_data="game_football")],
                [InlineKeyboardButton("🎰 Рулетка", callback_data="game_roulette"),
                 InlineKeyboardButton("💎 Алмазы", callback_data="game_diamonds")],
                [InlineKeyboardButton("💣 Мины", callback_data="game_mines"),
                 InlineKeyboardButton("💥 Краш", callback_data="game_crash")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"{get_emoji('money')} Вы ввели сумму: {format_number(amount)}\n"
                f"Выберите игру для ставки:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            context.user_data["quick_bet"] = amount

# ========== КОМАНДЫ ==========
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /balance"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await update.message.reply_text(
        f"{get_emoji('money')} *Ваш баланс:* {format_number(user_data.balance)}",
        parse_mode=ParseMode.MARKDOWN
    )

async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /level"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    next_level_exp = LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4)
    level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
    
    await update.message.reply_text(
        f"{get_emoji('level')} *Уровень:* {user_data.level}\n"
        f"{get_emoji('exp')} *EXP:* {user_data.exp}/{next_level_exp}\n"
        f"{get_emoji('bonus')} *Бонус уровня:* {format_number(level_bonus)}\n\n"
        f"{get_emoji('alert')} *Следующий уровень:*\n"
        f"Требуется EXP: {next_level_exp}\n"
        f"Бонус: {format_number(LEVEL_BONUS.get(user_data.level + 1, level_bonus + 25000))}",
        parse_mode=ParseMode.MARKDOWN
    )

async def job_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /job"""
    await work_menu(update, context)

async def farm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /farm"""
    await farm_menu(update, context)

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /bank"""
    await bank_menu(update, context)

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /market"""
    await market(update, context)

async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /bonus"""
    await bonus(update, context)

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /referral"""
    await referral(update, context)

# ========== АДМИН КОМАНДЫ ==========
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    await admin_panel(update, context)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats (админ)"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    # Простая статистика
    text = (
        f"{get_emoji('stats')} *СТАТИСТИКА БОТА*\n\n"
        f"🕐 *Время работы:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"💎 *Курс BTC:* {format_number(btc_price)} ₽\n"
        f"⚙️ *База данных:* {'✅ Подключена' if db else '❌ Не подключена'}\n\n"
        f"{get_emoji('alert')} *Для детальной статистики:*\n"
        f"Используйте админ-панель"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== ФУНКЦИЯ ДЛЯ ЕЖЕДНЕВНЫХ ПРОЦЕНТОВ ==========
async def daily_interest_task(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное начисление процентов в банке"""
    if not db:
        return
    
    try:
        # Получаем всех пользователей
        async with db.pool.acquire() as conn:
            users = await conn.fetch('SELECT * FROM users WHERE bank > 0')
            
            for user_row in users:
                user = User.from_dict(dict(user_row))
                interest = int(user.bank * 0.05)  # 5% процентов
                
                if interest > 0:
                    user.bank += interest
                    await db.save_user(user)
                    
                    # Отправляем уведомление
                    try:
                        await context.bot.send_message(
                            chat_id=user.user_id,
                            text=f"{get_emoji('bank')} *НАЧИСЛЕНЫ ПРОЦЕНТЫ!*\n\n"
                                 f"{get_emoji('money')} Сумма: {format_number(interest)} ₽\n"
                                 f"{get_emoji('bank')} Теперь в банке: {format_number(user.bank)}\n\n"
                                 f"{get_emoji('alert')} Проценты начисляются ежедневно в 00:00 по МСК",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass  # Если не удалось отправить сообщение
        
        print(f"✅ Начислены проценты {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    except Exception as e:
        print(f"❌ Ошибка при начислении процентов: {e}")

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
async def main():
    """Основная функция запуска бота"""
    # Проверяем наличие токена
    if TOKEN == "ВАШ_ТОКЕН_БОТА":
        print("❌ Установите токен бота в переменной окружения TOKEN")
        return
    
    # Подключаемся к базе данных
    if db:
        try:
            await db.connect()
            print("✅ База данных подключена")
        except Exception as e:
            print(f"❌ Ошибка подключения к БД: {e}")
            print("⚠️ Бот будет работать в режиме без сохранения данных")
    
    # Создаем приложение
    app = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("level", level_command))
    app.add_handler(CommandHandler("games", games_menu))
    app.add_handler(CommandHandler("job", job_command))
    app.add_handler(CommandHandler("work", job_command))
    app.add_handler(CommandHandler("farm", farm_command))
    app.add_handler(CommandHandler("bank", bank_command))
    app.add_handler(CommandHandler("market", market_command))
    app.add_handler(CommandHandler("bonus", bonus_command))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", stats_command))
    
    # Добавляем обработчики callback-запросов
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Добавляем обработчик текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Настраиваем задачу для ежедневных процентов
    job_queue = app.job_queue
    if job_queue:
        # Начисляем проценты каждый день в 00:00 по МСК
        # Для теста можно поставить каждую минуту: timedelta(minutes=1)
        job_queue.run_daily(
            daily_interest_task,
            time=datetime.time(hour=21, minute=0),  # 00:00 МСК = 21:00 UTC
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        print("✅ Задача ежедневных процентов настроена")
    
    # Запускаем бота
    print("🤖 Бот запускается...")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"📢 Канал: {CHANNEL_USERNAME}")
    print(f"💬 Чат: {CHAT_USERNAME}")
    
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

# ========== ЗАПУСК БОТА ==========
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    
    # Запуск
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
