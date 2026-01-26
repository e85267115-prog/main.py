# -*- coding: utf-8 -*-
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
import threading
from typing import Dict, List, Tuple, Optional, Any
from flask import Flask, jsonify
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
import pytz

# ИЗМЕНЕНО: psycopg2 вместо asyncpg
import psycopg2
from psycopg2 import pool, extras

from dataclasses import dataclass, field
import aiohttp

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = json.loads(os.environ.get("ADMIN_IDS", "[123456789]"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@nvibee_bet")
CHAT_USERNAME = os.environ.get("CHAT_USERNAME", "@chatvibee_bet")
DATABASE_URL = os.environ.get("DATABASE_URL")
PORT = int(os.environ.get("PORT", 8000))
print("DEBUG TOKEN =", repr(TOKEN))
# ========== FLASK ДЛЯ KEEP-ALIVE ==========
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram Bot",
        "timestamp": datetime.datetime.now().isoformat()
    })

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@flask_app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    """Запуск Flask сервера"""
    print(f"🌐 Starting Flask server on port {PORT}")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)

# Проверяем Supabase
IS_SUPABASE = DATABASE_URL and "supabase" in DATABASE_URL.lower()
if IS_SUPABASE:
    print("✅ Обнаружено подключение к Supabase")
elif DATABASE_URL:
    print("✅ Обнаружено подключение к PostgreSQL")
else:
    print("⚠️ DATABASE_URL не задан")

# ========== НАСТРОЙКИ ИГРЫ ==========
REFERRAL_BONUS = 50000  # Реферальный бонус 50к
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
    "blackjack": "🃏",
    "gift": "🎁",
    "user": "👤",
    "referral": "👥",
    "time": "⏰",
    "coin": "🪙",
    "card": "💳"
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
        
        # Преобразование строк в datetime
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

# ========== БАЗА ДАННЫХ PSYCOPG2 ==========
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
            # Настройки SSL для Supabase
            ssl_mode = 'require' if self.is_supabase else 'prefer'
            
            # Создаем пул соединений psycopg2
            self.pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=self.connection_string,
                sslmode=ssl_mode
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
            
            # Таблица пользователей
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
            
            # Таблица фермы BTC
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
            
            conn.commit()
            print("✅ Таблицы базы данных созданы/проверены")
            
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
                return User.from_dict(dict(row))
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
            
            values = (
                user.user_id, user.username, user.balance, user.bank, user.btc,
                user.level, user.exp, user.wins, user.loses, user.job,
                user.last_work, user.last_bonus, user.registered,
                user.last_daily_bonus, user.is_banned, user.referral_code,
                user.referred_by, user.total_referrals, user.referral_earnings
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
            
            farms = []
            for row in rows:
                farms.append(BTCFarm(
                    user_id=row['user_id'],
                    gpu_type=row['gpu_type'],
                    quantity=row['quantity'],
                    last_collected=row['last_collected']
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
        return User(
            user_id=user_id,
            username=username,
            referral_code=generate_referral_code()
        )
    
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
    """Команда /start с регистрацией"""
    user = update.effective_user
    
    # Регистрация пользователя
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
    
    # Основное меню после регистрации
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('dice')} Игры", callback_data="games_menu"),
         InlineKeyboardButton(f"{get_emoji('work')} Работа", callback_data="work_menu")],
        [InlineKeyboardButton(f"{get_emoji('farm')} Ферма BTC", callback_data="farm_menu"),
         InlineKeyboardButton(f"{get_emoji('bonus')} Бонус", callback_data="bonus")],
        [InlineKeyboardButton(f"{get_emoji('stats')} Профиль", callback_data="profile"),
         InlineKeyboardButton(f"{get_emoji('bank')} Банк", callback_data="bank_menu")],
        [InlineKeyboardButton(f"{get_emoji('market')} Биржа", callback_data="market"),
         InlineKeyboardButton(f"{get_emoji('shop')} Магазин", callback_data="shop")],
        [InlineKeyboardButton(f"{get_emoji('referral')} Рефералы", callback_data="referral")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_photo(
        photo="https://raw.githubusercontent.com/yourusername/yourrepo/main/start_img.jpg",
        caption="🎮 *Добро пожаловать в Vibe Bet!*\n\n"
               "Крути рулетку, рискуй в Краше, а также собирай свою ферму.\n\n"
               f"🎲 *Игры:* 🎲 Кости, ⚽ Футбол, 🎰 Рулетка, 💎 Алмазы, 💣 Мины\n"
               f"⛏️ *Заработок:* 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /profile открывается на 'Я' или 'Профиль'"""
    await profile(update, context)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать профиль пользователя"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Расчет дохода с фермы
    farm_income = 0
    if db:
        farm = await db.get_user_farm(user.id)
        for gpu in farm:
            if gpu.last_collected:
                hours_passed = (datetime.datetime.now() - gpu.last_collected).total_seconds() / 3600
                gpu_info = GPU_TYPES.get(gpu.gpu_type, {})
                farm_income += gpu_info.get("income_per_hour", 0) * gpu.quantity * hours_passed
    
    # Расчет следующего уровня
    next_level_exp = LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4)
    level_progress = (user_data.exp / next_level_exp) * 100
    
    # Создаем прогресс бар
    progress_bar_length = 10
    filled = int(progress_bar_length * level_progress / 100)
    progress_bar = "█" * filled + "░" * (progress_bar_length - filled)
    
    text = (
        f"{get_emoji('user')} *ПРОФИЛЬ*\n\n"
        f"{get_emoji('id')} ID: `{user.id}`\n"
        f"{get_emoji('level')} Уровень: *{user_data.level}*\n"
        f"{get_emoji('exp')} Опыт: {user_data.exp}/{next_level_exp}\n"
        f"{progress_bar} {level_progress:.1f}%\n\n"
        f"{get_emoji('money')} Баланс: *{format_number(user_data.balance)}*\n"
        f"{get_emoji('wins')} Побед: *{user_data.wins}*\n"
        f"{get_emoji('loses')} Поражений: *{user_data.loses}*\n"
        f"{get_emoji('btc')} BTC: *{user_data.btc:.6f}* (~{format_number(int(user_data.btc * btc_price))})\n"
        f"{get_emoji('farm')} Доход фермы: *{farm_income:.2f} BTC/час*"
    )
    
    if user_data.job:
        job_info = JOBS.get(user_data.job, {})
        text += f"\n{get_emoji('job')} Работа: *{job_info.get('name', 'Неизвестно')}*"
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('stats')} Подробнее", callback_data="profile_detailed"),
         InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def profile_detailed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подробный профиль"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Статистика
    total_games = user_data.wins + user_data.loses
    win_rate = (user_data.wins / total_games * 100) if total_games > 0 else 0
    
    # Реферальная информация
    referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user_data.referral_code}"
    
    text = (
        f"{get_emoji('stats')} *ДЕТАЛЬНАЯ СТАТИСТИКА*\n\n"
        f"{get_emoji('user')} Пользователь: @{user.username if user.username else 'Нет username'}\n"
        f"{get_emoji('time')} Зарегистрирован: {user_data.registered.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"{get_emoji('stats')} *Игровая статистика:*\n"
        f"🎮 Всего игр: {total_games}\n"
        f"🏅 Побед: {user_data.wins}\n"
        f"💔 Поражений: {user_data.loses}\n"
        f"📊 Винрейт: {win_rate:.1f}%\n\n"
        f"{get_emoji('referral')} *Реферальная система:*\n"
        f"👥 Приглашено: {user_data.total_referrals}\n"
        f"💰 Заработано: {format_number(user_data.referral_earnings)}\n"
        f"🔗 Ваша ссылка: `{referral_link}`\n\n"
        f"{get_emoji('alert')} Пригласи друга и получи {format_number(REFERRAL_BONUS)}!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile"),
         InlineKeyboardButton("📋 Основное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== КОМАНДЫ АЛИАСЫ ==========
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /balance или 'Баланс'"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    await update.message.reply_text(
        f"{get_emoji('money')} *Ваш баланс:* {format_number(user_data.balance)}",
        parse_mode=ParseMode.MARKDOWN
    )

async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /level или 'Уровень'"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    next_level_exp = LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4)
    level_bonus = LEVEL_BONUS.get(user_data.level + 1, LEVEL_BONUS.get(user_data.level, 50000) + 25000)
    
    await update.message.reply_text(
        f"{get_emoji('level')} *Уровень:* {user_data.level}\n"
        f"{get_emoji('exp')} *EXP:* {user_data.exp}/{next_level_exp}\n"
        f"{get_emoji('bonus')} *Следующий бонус:* {format_number(level_bonus)}\n\n"
        f"{get_emoji('alert')} Получайте EXP за каждое действие в боте!",
        parse_mode=ParseMode.MARKDOWN
    )

# ========== ИГРЫ ==========
async def games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню игр"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('dice')} Кости", callback_data="game_dice"),
         InlineKeyboardButton(f"{get_emoji('football')} Футбол", callback_data="game_football")],
        [InlineKeyboardButton(f"{get_emoji('roulette')} Рулетка", callback_data="game_roulette"),
         InlineKeyboardButton(f"{get_emoji('diamond')} Алмазы", callback_data="game_diamonds")],
        [InlineKeyboardButton(f"{get_emoji('mine')} Мины", callback_data="game_mines"),
         InlineKeyboardButton(f"{get_emoji('crash')} Краш", callback_data="game_crash")],
        [InlineKeyboardButton(f"{get_emoji('blackjack')} Очко (21)", callback_data="game_blackjack"),
         InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🎮 *ВЫБЕРИТЕ ИГРУ*\n\n"
        "🎲 *Кости* - угадайте больше/меньше/равно\n"
        "⚽ *Футбол* - угадайте гол/мимо\n"
        "🎰 *Рулетка* - классическая рулетка\n"
        "💎 *Алмазы* - найдите алмаз среди 16 ячеек\n"
        "💣 *Мины* - избегайте мин\n"
        "💥 *Краш* - выведите деньги до краха\n"
        "🃏 *Очко* - наберите 21 очко"
    )
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# Кости
async def game_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в кости"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎲 Больше (2.2x)", callback_data="dice_high"),
         InlineKeyboardButton("🎲 Меньше (2.2x)", callback_data="dice_low")],
        [InlineKeyboardButton("🎲 Равно (5.7x)", callback_data="dice_equal"),
         InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="🎲 *ИГРА В КОСТИ*\n\n"
             "Угадайте результат броска двух кубиков:\n"
             "• Больше 7 (2.2x)\n"
             "• Меньше 7 (2.2x)\n"
             "• Равно 7 (5.7x)\n\n"
             f"{get_emoji('money')} Минимальная ставка: 100",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def dice_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ставка в кости"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    bet_type = query.data.split("_")[1]
    
    await query.edit_message_text(
        text=f"🎲 *КОСТИ - {bet_type.upper()}*\n\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "dice"
    context.user_data["bet_type"] = bet_type

async def dice_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в кости с эмодзи"""
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
    
    bet_type = context.user_data.get("bet_type", "high")
    
    # Анимация броска
    dice_emojis = ["🎲", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    msg = await update.message.reply_text("🎲 Бросаем кубики...")
    
    for i in range(3):
        await asyncio.sleep(0.5)
        await msg.edit_text(f"{dice_emojis[random.randint(1, 6)]} {dice_emojis[random.randint(1, 6)]}")
    
    await asyncio.sleep(0.5)
    
    # Бросок кубиков
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
    # Определение результата
    multiplier = 1
    result_text = ""
    
    if bet_type == "high":
        if total > 7:
            multiplier = 2.2
            result_text = "🎉 Вы выиграли! Больше 7!"
            user_data.wins += 1
        else:
            result_text = "😔 Вы проиграли! Не больше 7."
            user_data.loses += 1
    elif bet_type == "low":
        if total < 7:
            multiplier = 2.2
            result_text = "🎉 Вы выиграли! Меньше 7!"
            user_data.wins += 1
        else:
            result_text = "😔 Вы проиграли! Не меньше 7."
            user_data.loses += 1
    elif bet_type == "equal":
        if total == 7:
            multiplier = 5.7
            result_text = "🎉 БИНГО! Выпало 7!"
            user_data.wins += 1
        else:
            result_text = "😔 Вы проиграли! Не 7."
            user_data.loses += 1
    
    # Расчет выигрыша
    win_amount = int(bet * multiplier) if multiplier > 1 else 0
    if win_amount > 0:
        user_data.balance += win_amount - bet
    else:
        user_data.balance -= bet
    
    # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            old_level = user_data.level
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
            
            level_up_text = (
                f"\n\n🎉 *НОВЫЙ УРОВЕНЬ!*\n\n"
                f"{get_emoji('level')} Теперь у вас {user_data.level} уровень!\n"
                f"{get_emoji('bonus')} Бонус: {format_number(level_bonus)}"
            )
        else:
            level_up_text = ""
    else:
        level_up_text = ""
    
    await db.save_user(user_data)
    
    text = (
        f"🎲 *РЕЗУЛЬТАТ КОСТЕЙ*\n\n"
        f"🎯 Ваш выбор: {bet_type}\n"
        f"🎲 Выпало: {dice1} + {dice2} = {total}\n"
        f"{result_text}\n\n"
        f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
    )
    
    if win_amount > 0:
        text += f"🎉 Выигрыш: {format_number(win_amount)} ({multiplier}x)\n"
    
    text += f"💰 Баланс: {format_number(user_data.balance)}"
    text += level_up_text
    
    keyboard = [[InlineKeyboardButton("🎲 Играть снова", callback_data="game_dice"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# Футбол
async def game_football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в футбол"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("⚽ ГОЛ (1.8x)", callback_data="football_goal"),
         InlineKeyboardButton("❌ МИМО (2.2x)", callback_data="football_miss")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="⚽ *ФУТБОЛ*\n\n"
             "Угадайте результат удара:\n"
             "• ГОЛ - мяч попадает в ворота (1.8x)\n"
             "• МИМО - мяч пролетает мимо (2.2x)\n\n"
             f"{get_emoji('money')} Минимальная ставка: 100",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def football_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ставка в футбол"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    bet_type = query.data.split("_")[1]
    
    await query.edit_message_text(
        text=f"⚽ *ФУТБОЛ - {bet_type.upper()}*\n\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "football"
    context.user_data["bet_type"] = bet_type

async def football_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в футбол с анимацией эмодзи"""
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
    
    bet_type = context.user_data.get("bet_type", "goal")
    
    # Анимация удара
    msg = await update.message.reply_text("⚽ Игрок готовится к удару...")
    
    # Анимация разбега
    for _ in range(3):
        await asyncio.sleep(0.3)
        await msg.edit_text("⚽ Игрок разбегается...")
        await asyncio.sleep(0.3)
        await msg.edit_text("⚽ Игрок бьет!")
    
    # Результат
    result = random.choice(["goal", "miss"])
    multiplier = 1.8 if result == "goal" else 2.2
    win = (bet_type == result)
    
    # Эмодзи для анимации
    if result == "goal":
        animation = ["⚽", "➡️", "➡️", "🥅", "🎉", "🎉", "🎉"]
        result_text = "⚽ ГОООООЛ! 🎉"
    else:
        animation = ["⚽", "➡️", "➡️", "❌", "😔", "😔", "😔"]
        result_text = "❌ МИМО... 😔"
    
    # Показываем анимацию
    for frame in animation:
        await asyncio.sleep(0.4)
        await msg.edit_text(frame)
    
    # Расчет выигрыша
    if win:
        win_amount = int(bet * multiplier)
        user_data.balance += win_amount - bet
        user_data.wins += 1
        win_text = f"🎉 Вы угадали! Выигрыш: {format_number(win_amount)} ({multiplier}x)"
    else:
        win_amount = 0
        user_data.balance -= bet
        user_data.loses += 1
        win_text = f"😔 Вы не угадали. Проигрыш: {format_number(bet)}"
    
    # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            old_level = user_data.level
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
            
            level_up_text = (
                f"\n\n🎉 *НОВЫЙ УРОВЕНЬ!*\n\n"
                f"{get_emoji('level')} Теперь у вас {user_data.level} уровень!\n"
                f"{get_emoji('bonus')} Бонус: {format_number(level_bonus)}"
            )
        else:
            level_up_text = ""
    else:
        level_up_text = ""
    
    await db.save_user(user_data)
    
    text = (
        f"⚽ *РЕЗУЛЬТАТ ФУТБОЛА*\n\n"
        f"🎯 Ваш выбор: {bet_type.upper()}\n"
        f"{result_text}\n"
        f"{win_text}\n\n"
        f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
        f"💰 Баланс: {format_number(user_data.balance)}"
        f"{level_up_text}"
    )
    
    keyboard = [[InlineKeyboardButton("⚽ Играть снова", callback_data="game_football"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    # Рулетка
async def game_roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рулетка"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("1-12 (3x)", callback_data="roulette_1_12"),
         InlineKeyboardButton("13-24 (3x)", callback_data="roulette_13_24"),
         InlineKeyboardButton("25-36 (3x)", callback_data="roulette_25_36")],
        [InlineKeyboardButton("Красное (2x)", callback_data="roulette_red"),
         InlineKeyboardButton("Черное (2x)", callback_data="roulette_black")],
        [InlineKeyboardButton("Четное (2x)", callback_data="roulette_even"),
         InlineKeyboardButton("Нечетное (2x)", callback_data="roulette_odd")],
        [InlineKeyboardButton("0-36 (36x)", callback_data="roulette_number"),
         InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="🎰 *РУЛЕТКА*\n\n"
             "Выберите тип ставки:\n"
             "• 1-12, 13-24, 25-36 (3x)\n"
             "• Красное/Черное (2x)\n"
             "• Четное/Нечетное (2x)\n"
             "• Конкретное число 0-36 (36x)\n\n"
             f"{get_emoji('money')} Минимальная ставка: 100",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def roulette_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ставка в рулетке"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    bet_data = query.data.split("_")[1:]
    context.user_data["roulette_type"] = bet_data[0]
    if len(bet_data) > 1:
        context.user_data["roulette_value"] = "_".join(bet_data[1:])
    
    await query.edit_message_text(
        text=f"🎰 *РУЛЕТКА*\n\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "roulette"

async def roulette_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в рулетку"""
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
    
    bet_type = context.user_data.get("roulette_type", "red")
    bet_value = context.user_data.get("roulette_value", "")
    
    # Анимация вращения рулетки
    msg = await update.message.reply_text("🎰 Крутим рулетку...")
    
    # Анимация чисел
    for i in range(5):
        await asyncio.sleep(0.3)
        random_num = random.randint(0, 36)
        await msg.edit_text(f"🎰 Выпадает: {random_num}")
    
    # Финальный результат
    number = random.randint(0, 36)
    is_red = number in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    is_black = number in [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
    is_even = number % 2 == 0 and number != 0
    
    # Определение выигрыша
    win = False
    multiplier = 1
    
    if bet_type == "red" and is_red:
        win = True
        multiplier = 2
    elif bet_type == "black" and is_black:
        win = True
        multiplier = 2
    elif bet_type == "even" and is_even:
        win = True
        multiplier = 2
    elif bet_type == "odd" and not is_even and number != 0:
        win = True
        multiplier = 2
    elif bet_type == "number":
        try:
            if number == int(bet_value):
                win = True
                multiplier = 36
        except:
            pass
    elif bet_type in ["1_12", "13_24", "25_36"]:
        ranges = {"1_12": (1, 12), "13_24": (13, 24), "25_36": (25, 36)}
        if bet_type in ranges:
            start, end = ranges[bet_type]
            if start <= number <= end:
                win = True
                multiplier = 3
    
    # Расчет
    if win:
        win_amount = int(bet * multiplier)
        user_data.balance += win_amount - bet
        user_data.wins += 1
        win_text = f"🎉 Вы выиграли! Выигрыш: {format_number(win_amount)}"
    else:
        win_amount = 0
        user_data.balance -= bet
        user_data.loses += 1
        win_text = f"😔 Вы проиграли. Проигрыш: {format_number(bet)}"
    
    # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            old_level = user_data.level
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
            
            level_up_text = (
                f"\n\n🎉 *НОВЫЙ УРОВЕНЬ!*\n\n"
                f"{get_emoji('level')} Теперь у вас {user_data.level} уровень!\n"
                f"{get_emoji('bonus')} Бонус: {format_number(level_bonus)}"
            )
        else:
            level_up_text = ""
    else:
        level_up_text = ""
    
    await db.save_user(user_data)
    
    # Описание числа
    color = "красное" if is_red else "черное" if is_black else "зеленое"
    parity = "четное" if is_even else "нечетное" if number != 0 else "ноль"
    
    text = (
        f"🎰 *РЕЗУЛЬТАТ РУЛЕТКИ*\n\n"
        f"🎯 Ваша ставка: {bet_type.replace('_', '-')}\n"
        f"📈 Выпало: {number} ({color}, {parity})\n"
        f"{win_text}\n\n"
        f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
    )
    
    if win_amount > 0:
        text += f"🎉 Выигрыш: {format_number(win_amount)}\n"
    
    text += f"💰 Баланс: {format_number(user_data.balance)}"
    text += level_up_text
    
    keyboard = [[InlineKeyboardButton("🎰 Играть снова", callback_data="game_roulette"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# Алмазы
async def game_diamonds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра Алмазы"""
    query = update.callback_query
    await query.answer()
    
    # Генерация позиции алмаза
    diamond_pos = random.randint(1, 16)
    context.user_data["diamond_position"] = diamond_pos
    context.user_data["diamond_opened"] = []
    context.user_data["diamond_level"] = 1
    context.user_data["game"] = "diamonds"
    
    keyboard = []
    for i in range(1, 17):
        if (i-1) % 4 == 0:
            keyboard.append([])
        keyboard[-1].append(InlineKeyboardButton("❓", callback_data=f"diamond_{i}"))
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="games_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="💎 *АЛМАЗЫ*\n\n"
             "Найдите алмаз среди 16 ячеек!\n"
             "Открывайте по одной ячейке на каждом уровне.\n"
             "Чем раньше найдете - тем больше выигрыш!\n\n"
             f"{get_emoji('money')} Уровень 1/16",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def diamond_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открытие ячейки в Алмазах"""
    query = update.callback_query
    await query.answer()
    
    cell_num = int(query.data.split("_")[1])
    diamond_pos = context.user_data.get("diamond_position", 1)
    opened = context.user_data.get("diamond_opened", [])
    level = context.user_data.get("diamond_level", 1)
    
    if cell_num in opened:
        return
    
    opened.append(cell_num)
    context.user_data["diamond_opened"] = opened
    
    # Проверка на алмаз
    if cell_num == diamond_pos:
        # Выигрыш
        multiplier = 1 + (17 - level) * 0.5  # 8.5x на 1 уровне, 1x на 16
        win_text = f"🎉 БИНГО! Вы нашли алмаз на уровне {level}!\nМножитель: {multiplier}x"
        context.user_data["diamond_win"] = True
        context.user_data["diamond_multiplier"] = multiplier
        context.user_data["diamond_final_level"] = level
        
        keyboard = [[InlineKeyboardButton("💰 Забрать выигрыш", callback_data="diamond_claim"),
                     InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    else:
        # Переход на следующий уровень
        level += 1
        context.user_data["diamond_level"] = level
        
        if level > 16:
            win_text = "😔 Вы не нашли алмаз!"
            context.user_data["diamond_win"] = False
            
            keyboard = [[InlineKeyboardButton("💎 Играть снова", callback_data="game_diamonds"),
                         InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
        else:
            win_text = f"💎 Неудача! Переходим на уровень {level}/16"
            
            # Обновляем клавиатуру
            keyboard = []
            for i in range(1, 17):
                if (i-1) % 4 == 0:
                    keyboard.append([])
                if i in opened:
                    keyboard[-1].append(InlineKeyboardButton("💣", callback_data=f"diamond_{i}"))
                else:
                    keyboard[-1].append(InlineKeyboardButton("❓", callback_data=f"diamond_{i}"))
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="games_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=f"💎 *АЛМАЗЫ*\n\n{win_text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def diamond_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Забрать выигрыш в Алмазах"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Запрос ставки
    await query.edit_message_text(
        text=f"💎 *АЛМАЗЫ*\n\n"
             f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}\n"
             f"🎯 Множитель: {context.user_data.get('diamond_multiplier', 1)}x\n\n"
             "Введите сумму ставки:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["game"] = "diamonds_claim"

async def diamond_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение игры Алмазы"""
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
    
    multiplier = context.user_data.get("diamond_multiplier", 1)
    win_amount = int(bet * multiplier)
    level = context.user_data.get("diamond_final_level", 1)
    
    user_data.balance += win_amount - bet
    user_data.wins += 1
    
    # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            old_level = user_data.level
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
            
            level_up_text = (
                f"\n\n🎉 *НОВЫЙ УРОВЕНЬ!*\n\n"
                f"{get_emoji('level')} Теперь у вас {user_data.level} уровень!\n"
                f"{get_emoji('bonus')} Бонус: {format_number(level_bonus)}"
            )
        else:
            level_up_text = ""
    else:
        level_up_text = ""
    
    await db.save_user(user_data)
    
    text = (
        f"💎 *АЛМАЗЫ - РЕЗУЛЬТАТ*\n\n"
        f"🎯 Уровень нахождения: {level}/16\n"
        f"🎉 Вы нашли алмаз! ({multiplier}x)\n\n"
        f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
        f"💰 Выигрыш: {format_number(win_amount)}\n"
        f"💎 Баланс: {format_number(user_data.balance)}"
        f"{level_up_text}"
    )
    
    keyboard = [[InlineKeyboardButton("💎 Играть снова", callback_data="game_diamonds"),
                 InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# Мины
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
    
        # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            old_level = user_data.level
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
            
            level_up_text = (
                f"\n\n🎉 *НОВЫЙ УРОВЕНЬ!*\n\n"
                f"{get_emoji('level')} Теперь у вас {user_data.level} уровень!\n"
                f"{get_emoji('bonus')} Бонус: {format_number(level_bonus)}"
            )
        else:
            level_up_text = ""
    else:
        level_up_text = ""
    
    await db.save_user(user_data)
    
    text = (
        f"💣 *МИНЫ - РЕЗУЛЬТАТ*\n\n"
        f"✅ Открыто ячеек: {len(context.user_data.get('mines_opened', []))}\n"
        f"🎯 Множитель: {multiplier}x\n"
        f"🎉 Вы успешно забрали выигрыш!\n\n"
        f"{get_emoji('money')} Ставка: {format_number(bet)}\n"
        f"💰 Выигрыш: {format_number(win_amount)}\n"
        f"💣 Баланс: {format_number(user_data.balance)}"
        f"{level_up_text}"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("💣 Играть снова", callback_data="game_mines"),
            InlineKeyboardButton("🔙 В меню", callback_data="games_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)


# Краш
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
            
            # Добавление EXP с шансом 50%
            if random.random() < 0.5:
                user_data.exp += 1
                # Проверка уровня
                if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
                    old_level = user_data.level
                    user_data.level += 1
                    user_data.exp = 0
                    level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
                    user_data.balance += level_bonus
            
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
    
    # Добавление EXP с шансом 50%
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

# Очко (21)
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
            
            # Добавление EXP с шансом 50%
            if random.random() < 0.5:
                user_data.exp += 1
                # Проверка уровня
                if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
                    old_level = user_data.level
                    user_data.level += 1
                    user_data.exp = 0
                    level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
                    user_data.balance += level_bonus
            
            await db.save_user(user_data)
            
            keyboard = [[InlineKeyboardButton("🃏 Играть снова", callback_data="game_blackjack"),
                         InlineKeyboardButton("🔙 В меню", callback_data="games_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

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
        
        # Добавление EXP с шансом 50%
        if random.random() < 0.5:
            user_data.exp += 1
            # Проверка уровня
            if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
                old_level = user_data.level
                user_data.level += 1
                user_data.exp = 0
                level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
                user_data.balance += level_bonus
        
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
    
    # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
        # Проверка уровня
        if user_data.exp >= LEVEL_EXP_REQUIREMENTS.get(user_data.level, 4):
            old_level = user_data.level
            user_data.level += 1
            user_data.exp = 0
            level_bonus = LEVEL_BONUS.get(user_data.level, 50000)
            user_data.balance += level_bonus
    
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
    # ========== БАНК ==========
async def bank_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню банка"""
    query = update.callback_query
    user = query.from_user if query else update.effective_user
    
    user_data = await get_or_create_user(user.id, user.username)
    
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('deposit')} Пополнить", callback_data="bank_deposit"),
         InlineKeyboardButton(f"{get_emoji('withdraw')} Снять", callback_data="bank_withdraw")],
        [InlineKeyboardButton(f"{get_emoji('transfer')} Перевести", callback_data="bank_transfer"),
         InlineKeyboardButton(f"{get_emoji('stats')} Статистика", callback_data="bank_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Расчет ежедневных процентов
    daily_interest = int(user_data.bank * 0.05)
    
    text = (
        f"{get_emoji('bank')} *БАНК*\n\n"
        f"{get_emoji('money')} *Наличные:* {format_number(user_data.balance)}\n"
        f"{get_emoji('bank')} *В банке:* {format_number(user_data.bank)}\n\n"
        f"{get_emoji('alert')} *Ежедневные проценты:* 5%\n"
        f"{get_emoji('money')} *Завтра получите:* +{format_number(daily_interest)}\n\n"
        f"Выберите действие:"
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
    context.user_data["bank_action"] = "deposit"

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
    context.user_data["bank_action"] = "withdraw"

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
    context.user_data["bank_action"] = "transfer"

async def bank_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика банка"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    # Расчет процентов
    daily_interest = int(user_data.bank * 0.05)
    weekly_interest = int(user_data.bank * 0.05 * 7)
    monthly_interest = int(user_data.bank * 0.05 * 30)
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="bank_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{get_emoji('stats')} *СТАТИСТИКА БАНКА*\n\n"
        f"{get_emoji('money')} *Наличные:* {format_number(user_data.balance)}\n"
        f"{get_emoji('bank')} *В банке:* {format_number(user_data.bank)}\n\n"
        f"{get_emoji('alert')} *Ежедневный процент:* 5%\n\n"
        f"{get_emoji('money')} *За день:* +{format_number(daily_interest)}\n"
        f"{get_emoji('money')} *За неделю:* +{format_number(weekly_interest)}\n"
        f"{get_emoji('money')} *За месяц:* +{format_number(monthly_interest)}\n\n"
        f"{get_emoji('alert')} Проценты начисляются каждый день\n"
        "в 00:00 по московскому времени."
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def handle_bank_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий банка"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    action = context.user_data.get("bank_action")
    
    if action == "deposit":
        try:
            amount = int(update.message.text)
            if amount < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма: 100")
                return
            if amount > user_data.balance:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств на балансе!")
                return
            
            user_data.balance -= amount
            user_data.bank += amount
            
            await db.save_user(user_data)
            
            text = (
                f"{get_emoji('check')} *СРЕДСТВА ПОПОЛНЕНЫ!*\n\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"{get_emoji('bank')} Теперь в банке: {format_number(user_data.bank)}\n"
                f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🏦 Еще операция", callback_data="bank_menu"),
                 InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            
        except ValueError:
            await update.message.reply_text(f"{get_emoji('alert')} Введите число!")
    
    elif action == "withdraw":
        try:
            amount = int(update.message.text)
            if amount < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма: 100")
                return
            if amount > user_data.bank:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств в банке!")
                return
            
            user_data.balance += amount
            user_data.bank -= amount
            
            await db.save_user(user_data)
            
            text = (
                f"{get_emoji('check')} *СРЕДСТВА СНЯТЫ!*\n\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"{get_emoji('bank')} Осталось в банке: {format_number(user_data.bank)}\n"
                f"{get_emoji('money')} Наличные: {format_number(user_data.balance)}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🏦 Еще операция", callback_data="bank_menu"),
                 InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            
        except ValueError:
            await update.message.reply_text(f"{get_emoji('alert')} Введите число!")
    
    elif action == "transfer":
        try:
            parts = update.message.text.split()
            if len(parts) != 2:
                await update.message.reply_text(f"{get_emoji('alert')} Неверный формат! Используйте: `ID СУММА`")
                return
            
            receiver_id = int(parts[0])
            amount = int(parts[1])
            
            if amount < 100:
                await update.message.reply_text(f"{get_emoji('alert')} Минимальная сумма перевода: 100")
                return
            if amount > user_data.balance:
                await update.message.reply_text(f"{get_emoji('cross')} Недостаточно средств!")
                return
            
            # Получаем получателя
            receiver_data = await get_or_create_user(receiver_id)
            
            # Проверяем, не пытается ли перевести сам себе
            if receiver_id == user.id:
                await update.message.reply_text(f"{get_emoji('cross')} Нельзя переводить самому себе!")
                return
            
            # Переводим средства
            user_data.balance -= amount
            receiver_data.balance += amount
            
            await db.save_user(user_data)
            await db.save_user(receiver_data)
            
            # Отправляем уведомление получателю
            try:
                await context.bot.send_message(
                    chat_id=receiver_id,
                    text=f"{get_emoji('gift')} *ВЫ ПОЛУЧИЛИ ПЕРЕВОД!*\n\n"
                         f"{get_emoji('user')} От: @{user.username if user.username else 'Аноним'}\n"
                         f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                         f"{get_emoji('money')} Ваш баланс: {format_number(receiver_data.balance)}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass  # Если не удалось отправить сообщение
            
            text = (
                f"{get_emoji('check')} *ПЕРЕВОД ВЫПОЛНЕН!*\n\n"
                f"{get_emoji('user')} Кому: ID {receiver_id}\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"{get_emoji('money')} Ваш баланс: {format_number(user_data.balance)}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔁 Еще перевод", callback_data="bank_transfer"),
                 InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            
        except ValueError:
            await update.message.reply_text(f"{get_emoji('alert')} Ошибка! Убедитесь, что ID и сумма - числа!")
        except Exception as e:
            await update.message.reply_text(f"{get_emoji('alert')} Ошибка перевода: {str(e)}")

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
        [InlineKeyboardButton(f"{get_emoji('stats')} Моя ферма", callback_data="farm_info"),
         InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Строим текст с информацией о ферме
    farm_text = f"{get_emoji('farm')} *ФЕРМА BTC*\n\n"
    
    if user_farm:
        farm_text += f"{get_emoji('btc')} *Доход в час:*\n"
        total_hourly = 0
        for farm in user_farm:
            gpu_info = GPU_TYPES.get(farm.gpu_type, {})
            hourly = gpu_info.get("income_per_hour", 0) * farm.quantity
            total_hourly += hourly
            farm_text += f"  {get_gpu_display_name(farm.gpu_type)} x{farm.quantity}: {hourly:.2f} BTC/ч\n"
        
        farm_text += f"\n{get_emoji('btc')} *Общий доход:* {total_hourly:.2f} BTC/ч\n"
        farm_text += f"{get_emoji('btc')} *Накоплено:* {btc_to_collect:.4f} BTC\n"
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
        
        current_farm = farm_dict.get(gpu_type, BTCFarm(query.from_user.id, gpu_type))
        current_quantity = current_farm.quantity
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

# ========== РАБОТА ==========
async def work_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню работы"""
    query = update.callback_query if update.callback_query else None
    user = query.from_user if query else update.effective_user
    
    user_data = await get_or_create_user(user.id, user.username)
    
    keyboard = []
    for job_type, job_info in JOBS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{get_job_display_name(job_type)}",
                callback_data=f"work_{job_type}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if user_data.job:
        current_job = JOBS.get(user_data.job, {})
        job_name = current_job.get("name", "Неизвестно")
        text = f"{get_emoji('job')} *РАБОТА*\n\nТекущая работа: *{job_name}*"
    else:
        text = f"{get_emoji('job')} *РАБОТА*\n\nВыберите работу:"
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

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
    
    user_data.job = job_type
    await db.save_user(user_data)
    
    text = (
        f"{get_emoji('check')} *ВЫ УСТРОИЛИСЬ НА РАБОТУ!*\n\n"
        f"{get_emoji('job')} Должность: {job_info['name']}\n"
        f"{get_emoji('alert')} Описание: {job_info['description']}\n"
        f"{get_emoji('money')} Зарплата: {format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])}\n"
        f"{get_emoji('time')} Перерыв: {job_info['cooldown']//60} мин\n"
        f"{get_emoji('btc')} Шанс BTC: {job_info['btc_chance']}%\n\n"
        f"Используйте /work или 'Работа' для выполнения задания."
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="work_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def work_perform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение работы"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    if not user_data.job:
        await update.message.reply_text(
            f"{get_emoji('cross')} У вас нет работы! Выберите работу в меню.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    job_info = JOBS.get(user_data.job, {})
    
    # Проверка кулдауна
    if user_data.last_work:
        cooldown = job_info.get("cooldown", 300)
        time_since = (datetime.datetime.now() - user_data.last_work).total_seconds()
        
        if time_since < cooldown:
            remaining = cooldown - int(time_since)
            minutes = remaining // 60
            seconds = remaining % 60
            
            await update.message.reply_text(
                f"{get_emoji('time')} *ОЖИДАНИЕ*\n\n"
                f"Вы уже работали недавно.\n"
                f"Осталось: {minutes} мин {seconds} сек",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    # Выполнение работы
    salary = random.randint(job_info.get("min_salary", 10000), job_info.get("max_salary", 50000))
    
    # Проверка на BTC с шансом 9%
    btc_found = random.random() * 100 < job_info.get("btc_chance", 9)
    btc_amount = random.uniform(0.0001, 0.001) if btc_found else 0
    
    # Начисление
    user_data.balance += salary
    if btc_found:
        user_data.btc += btc_amount
    
    user_data.last_work = datetime.datetime.now()
    
    # Добавление EXP с шансом 50%
    if random.random() < 0.5:
        user_data.exp += 1
    
    await db.save_user(user_data)
    
    # Формируем ответ
    text = f"{get_emoji('check')} *РАБОТА ВЫПОЛНЕНА!*\n\n"
    
    # Анимация процесса работы
    msg = await update.message.reply_text(f"{get_emoji('work')} Выполняем работу...")
    
    # Процесс работы в зависимости от типа
    if user_data.job == "digger":
        process = ["🔍 Ищем клады...", "⛏ Копаем...", "💰 Нашли сокровища!"]
    elif user_data.job == "hacker":
        process = ["💻 Взламываем систему...", "🔓 Обходим защиту...", "💾 Данные получены!"]
    elif user_data.job == "miner":
        process = ["⛏ Спускаемся в шахту...", "💎 Добываем криптовалюту...", "🪙 Нашли блок!"]
    elif user_data.job == "trader":
        process = ["📈 Анализируем рынок...", "💹 Совершаем сделки...", "💰 Успешная торговля!"]
    else:
        process = ["⚙ Выполняем работу...", "✅ Готово!"]
    
    for step in process:
        await asyncio.sleep(1)
        await msg.edit_text(f"{get_emoji('work')} {step}")
    
    await asyncio.sleep(1)
    
    text += f"{get_emoji('money')} *Зарплата:* {format_number(salary)}\n"
    
    if btc_found:
        text += f"{get_emoji('btc')} *Найден BTC:* {btc_amount:.6f} (~{format_number(int(btc_amount * btc_price))})\n"
    
    text += f"\n{get_emoji('money')} *Баланс:* {format_number(user_data.balance)}\n"
    
    if btc_found:
        text += f"{get_emoji('btc')} *BTC:* {user_data.btc:.6f}\n"
    
    text += f"\n{get_emoji('time')} Следующая работа через {job_info.get('cooldown', 300)//60} минут"
    
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

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
    context.user_data["market_action"] = "buy"

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
    context.user_data["market_action"] = "sell"

async def handle_market_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки/продажи BTC"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    action = context.user_data.get("market_action")
    
    try:
        if action == "buy":
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
            
        elif action == "sell":
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

# ========== БОНУСЫ ==========
async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню бонусов"""
    query = update.callback_query if update.callback_query else None
    user = query.from_user if query else update.effective_user
    
    user_data = await get_or_create_user(user.id, user.username)
    
    # Проверка ежедневного бонуса
    can_claim_daily = True
    daily_text = "🎁 *Ежедневный бонус* - доступен"
    
    if user_data.last_daily_bonus:
        time_since = (datetime.datetime.now() - user_data.last_daily_bonus).total_seconds()
        if time_since < 86400:  # 24 часа
            can_claim_daily = False
            hours_left = 24 - int(time_since // 3600)
            minutes_left = 60 - int((time_since % 3600) // 60)
            daily_text = f"⏰ *Ежедневный бонус* - через {hours_left}ч {minutes_left}м"
    
    keyboard = [
        [InlineKeyboardButton(daily_text, callback_data="daily_bonus" if can_claim_daily else "bonus_cooldown")],
        [InlineKeyboardButton(f"🏆 Бонус уровня ({format_number(LEVEL_BONUS.get(user_data.level, 50000))})", callback_data="level_bonus")],
        [InlineKeyboardButton(f"🎫 Промокод", callback_data="promo_code")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{get_emoji('bonus')} *БОНУСЫ*\n\n"
        f"Получайте награды за активность!\n\n"
        f"{get_emoji('level')} Текущий уровень: {user_data.level}\n"
        f"{get_emoji('bonus')} Бонус уровня: {format_number(LEVEL_BONUS.get(user_data.level, 50000))}"
    )
    
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
    
    # Проверка кулдауна
    if user_data.last_daily_bonus:
        time_since = (datetime.datetime.now() - user_data.last_daily_bonus).total_seconds()
        if time_since < 86400:  # 24 часа
            hours_left = 24 - int(time_since // 3600)
            minutes_left = 60 - int((time_since % 3600) // 60)
            await query.answer(f"Бонус будет доступен через {hours_left}ч {minutes_left}м", show_alert=True)
            return
    
    # Выдача бонуса
    bonus_amount = random.randint(1000, 50000)
    user_data.balance += bonus_amount
    user_data.last_daily_bonus = datetime.datetime.now()
    
    await db.save_user(user_data)
    
    text = (
        f"{get_emoji('gift')} *ЕЖЕДНЕВНЫЙ БОНУС!*\n\n"
        f"{get_emoji('money')} Вы получили: {format_number(bonus_amount)}\n"
        f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}\n\n"
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
    
    # Проверка, получал ли уже бонус за текущий уровень
    if user_data.last_bonus and user_data.last_bonus.date() == datetime.datetime.now().date():
        await query.answer(f"Вы уже получали бонус за уровень {user_data.level} сегодня", show_alert=True)
        return
    
    # Выдача бонуса
    bonus_amount = LEVEL_BONUS.get(user_data.level, 50000)
    user_data.balance += bonus_amount
    user_data.last_bonus = datetime.datetime.now()
    
    await db.save_user(user_data)
    
    text = (
        f"{get_emoji('gift')} *БОНУС УРОВНЯ!*\n\n"
        f"{get_emoji('level')} Уровень: {user_data.level}\n"
        f"{get_emoji('money')} Бонус: {format_number(bonus_amount)}\n"
        f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}\n\n"
        f"{get_emoji('alert')} Бонус можно получать раз в день"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="bonus")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод промокода"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text=f"{get_emoji('gift')} *ПРОМОКОД*\n\n"
             "Введите промокод для получения бонуса:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["action"] = "promo_code"

async def handle_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка промокода"""
    user = update.effective_user
    user_data = await get_or_create_user(user.id, user.username)
    
    promo = update.message.text.upper().strip()
    
    # Здесь можно добавить проверку промокодов из базы данных
    # Для примера, сделаем один рабочий промокод
    if promo == "WELCOME2026":
        bonus_amount = 25000
        
        # Проверяем, не использовал ли уже этот промокод
        if "used_promos" not in context.user_data:
            context.user_data["used_promos"] = []
        
        if promo in context.user_data["used_promos"]:
            await update.message.reply_text(
                f"{get_emoji('cross')} Вы уже использовали этот промокод!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        user_data.balance += bonus_amount
        context.user_data["used_promos"].append(promo)
        await db.save_user(user_data)
        
        text = (
            f"{get_emoji('gift')} *ПРОМОКОД АКТИВИРОВАН!*\n\n"
            f"🎫 Код: {promo}\n"
            f"{get_emoji('money')} Бонус: {format_number(bonus_amount)}\n"
            f"{get_emoji('money')} Баланс: {format_number(user_data.balance)}"
        )
    else:
        text = (
            f"{get_emoji('cross')} *ПРОМОКОД НЕДЕЙСТВИТЕЛЕН*\n\n"
            f"Промокод '{promo}' не найден или уже использован."
        )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="bonus")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реферальная система"""
    query = update.callback_query if update.callback_query else None
    user = query.from_user if query else update.effective_user
    
    user_data = await get_or_create_user(user.id, user.username)
    
    # Генерация реферальной ссылки
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_data.referral_code}"
    
    # Расчет доходов с рефералов
    level1_earnings = user_data.referral_earnings * 0.05
    level2_earnings = user_data.referral_earnings * 0.03
    level3_earnings = user_data.referral_earnings * 0.01
    
    text = (
        f"{get_emoji('referral')} *РЕФЕРАЛЬНАЯ СИСТЕМА*\n\n"
        f"{get_emoji('user')} Ваш реферальный код: `{user_data.referral_code}`\n"
        f"{get_emoji('link')} Ваша ссылка: `{referral_link}`\n\n"
        f"{get_emoji('people')} *Статистика:*\n"
        f"👥 Приглашено: {user_data.total_referrals}\n"
        f"💰 Заработано: {format_number(user_data.referral_earnings)}\n\n"
        f"{get_emoji('money')} *Бонусы за приглашение:*\n"
        f"1. Пригласивший получает {format_number(REFERRAL_BONUS)}\n"
        f"2. Вы получаете 5% с дохода 1 уровня\n"
        f"3. Вы получаете 3% с дохода 2 уровня\n"
        f"4. Вы получаете 1% с дохода 3 уровня\n\n"
        f"{get_emoji('alert')} Приглашайте друзей и зарабатывайте вместе!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📋 Скопировать ссылку", callback_data="copy_ref")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def copy_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Копирование реферальной ссылки"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_data = await get_or_create_user(user.id, user.username)
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_data.referral_code}"
    
    await query.answer(f"Ссылка скопирована: {referral_link}", show_alert=True)

# ========== АДМИН ПАНЕЛЬ ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer("У вас нет доступа к этой команде!", show_alert=True)
        else:
            await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика бота", callback_data="admin_stats"),
         InlineKeyboardButton("👤 Профиль игрока", callback_data="admin_user")],
        [InlineKeyboardButton("💰 Выдать деньги", callback_data="admin_give_money"),
         InlineKeyboardButton("❌ Забрать деньги", callback_data="admin_take_money")],
        [InlineKeyboardButton("₿ Выдать BTC", callback_data="admin_give_btc"),
         InlineKeyboardButton("🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton("📋 Логи", callback_data="admin_logs"),
         InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"{get_emoji('admin')} *АДМИН ПАНЕЛЬ*\n\n"
        f"Добро пожаловать, администратор {user.first_name}!\n"
        f"Выберите действие:"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика бота для админа"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    # Здесь можно добавить реальную статистику из БД
    # Для примеры, просто покажем базовую информацию
    
    text = (
        f"{get_emoji('stats')} *СТАТИСТИКА БОТА*\n\n"
        f"🕐 Время запуска: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"💎 Курс BTC: {format_number(btc_price)} ₽\n"
        f"⚙️ База данных: {'✅ Подключена' if db else '❌ Не подключена'}\n\n"
        f"{get_emoji('alert')} *Для просмотра детальной статистики:*\n"
        f"Используйте команду /stats в чате"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def admin_give_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача денег"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text=f"{get_emoji('money')} *ВЫДАЧА ДЕНЕГ*\n\n"
             "Введите в формате:\n"
             "`ID_игрока СУММА`\n\n"
             "Пример: `123456789 100000`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_money"

async def admin_take_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Забирание денег"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text=f"{get_emoji('money')} *ЗАБИРАНИЕ ДЕНЕГ*\n\n"
             "Введите в формате:\n"
             "`ID_игрока СУММА`\n\n"
             "Пример: `123456789 50000`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "take_money"

async def admin_give_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача BTC"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text=f"{get_emoji('btc')} *ВЫДАЧА BTC*\n\n"
             "Введите в формате:\n"
             "`ID_игрока КОЛИЧЕСТВО_BTC`\n\n"
             "Пример: `123456789 0.5`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_btc"

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бан/Разбан игрока"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text=f"{get_emoji('ban')} *БАН/РАЗБАН ИГРОКА*\n\n"
             "Введите в формате:\n"
             "`ID_игрока ПРИЧИНА`\n\n"
             "Пример: `123456789 Нарушение правил`\n\n"
             "Для разбана введите:\n"
             "`разбан ID_игрока`\n\n"
             "Пример: `разбан 123456789`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "ban"

async def admin_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр профиля игрока"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    await query.edit_message_text(
        text=f"{get_emoji('user')} *ПРОСМОТР ПРОФИЛЯ ИГРОКА*\n\n"
             "Введите ID игрока для просмотра профиля:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "view_user"

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр логов"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("У вас нет доступа!", show_alert=True)
        return
    
    # Здесь можно добавить логи из БД
    # Для примера, просто покажем последние транзакции
    
    text = (
        f"{get_emoji('logs')} *ЛОГИ СИСТЕМЫ*\n\n"
        f"🕐 Последнее обновление: {datetime.datetime.now().strftime('%H:%M:%S')}\n"
        f"📊 Всего игроков: (данные из БД)\n"
        f"💸 Общий оборот: (данные из БД)\n\n"
        f"{get_emoji('alert')} *Детальные логи:*\n"
        f"Для просмотра детальных логов используйте команды:\n"
        f"• /transactions - транзакции\n"
        f"• /users - список пользователей"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий админа"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа к этой команде!")
        return
    
    action = context.user_data.get("admin_action")
    text = update.message.text.strip()
    
    try:
        if action == "give_money":
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text(f"{get_emoji('alert')} Неверный формат! Используйте: `ID СУММА`")
                return
            
            receiver_id = int(parts[0])
            amount = int(parts[1])
            
            if amount <= 0:
                await update.message.reply_text(f"{get_emoji('alert')} Сумма должна быть положительной!")
                return
            
            receiver_data = await get_or_create_user(receiver_id)
            receiver_data.balance += amount
            await db.save_user(receiver_data)
            
            result_text = (
                f"{get_emoji('check')} *ДЕНЬГИ ВЫДАНЫ!*\n\n"
                f"👤 Игрок: ID {receiver_id}\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"💰 Новый баланс: {format_number(receiver_data.balance)}"
            )
            
        elif action == "take_money":
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text(f"{get_emoji('alert')} Неверный формат! Используйте: `ID СУММА`")
                return
            
            receiver_id = int(parts[0])
            amount = int(parts[1])
            
            if amount <= 0:
                await update.message.reply_text(f"{get_emoji('alert')} Сумма должна быть положительной!")
                return
            
            receiver_data = await get_or_create_user(receiver_id)
            
            if amount > receiver_data.balance:
                amount = receiver_data.balance
            
            receiver_data.balance -= amount
            await db.save_user(receiver_data)
            
            result_text = (
                f"{get_emoji('check')} *ДЕНЬГИ ЗАБРАНЫ!*\n\n"
                f"👤 Игрок: ID {receiver_id}\n"
                f"{get_emoji('money')} Сумма: {format_number(amount)}\n"
                f"💰 Новый баланс: {format_number(receiver_data.balance)}"
            )
            
        elif action == "give_btc":
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text(f"{get_emoji('alert')} Неверный формат! Используйте: `ID КОЛИЧЕСТВО_BTC`")
                return
            
            receiver_id = int(parts[0])
            btc_amount = float(parts[1])
            
            if btc_amount <= 0:
                await update.message.reply_text(f"{get_emoji('alert')} Количество должно быть положительным!")
                return
            
            receiver_data = await get_or_create_user(receiver_id)
            receiver_data.btc += btc_amount
            await db.save_user(receiver_data)
            
            result_text = (
                f"{get_emoji('check')} *BTC ВЫДАН!*\n\n"
                f"👤 Игрок: ID {receiver_id}\n"
                f"{get_emoji('btc')} Количество: {btc_amount:.6f} BTC\n"
                f"💰 Стоимость: ~{format_number(int(btc_amount * btc_price))}\n"
                f"₿ Теперь BTC: {receiver_data.btc:.6f}"
            )
            
        elif action == "ban":
            if text.lower().startswith("разбан"):
                parts = text.split()
                if len(parts) != 2:
                    await update.message.reply_text(f"{get_emoji('alert')} Неверный формат! Используйте: `разбан ID`")
                    return
                
                user_id = int(parts[1])
                user_data = await get_or_create_user(user_id)
                user_data.is_banned = False
                await db.save_user(user_data)
                
                result_text = (
                    f"{get_emoji('check')} *ИГРОК РАЗБАНЕН!*\n\n"
                    f"👤 Игрок: ID {user_id}\n"
                    f"📛 Статус: Активен"
                )
            else:
                parts = text.split(maxsplit=1)
                if len(parts) != 2:
                    await update.message.reply_text(f"{get_emoji('alert')} Неверный формат! Используйте: `ID ПРИЧИНА`")
                    return
                
                user_id = int(parts[0])
                reason = parts[1]
                user_data = await get_or_create_user(user_id)
                user_data.is_banned = True
                await db.save_user(user_data)
                
                result_text = (
                    f"{get_emoji('check')} *ИГРОК ЗАБАНЕН!*\n\n"
                    f"👤 Игрок: ID {user_id}\n"
                    f"📛 Причина: {reason}\n"
                    f"🚫 Статус: Забанен"
                )
        
        elif action == "view_user":
            user_id = int(text)
            user_data = await get_or_create_user(user_id)
            
            # Расчет статистики
            total_games = user_data.wins + user_data.loses
            win_rate = (user_data.wins / total_games * 100) if total_games > 0 else 0
            
            result_text = (
                f"{get_emoji('user')} *ПРОФИЛЬ ИГРОКА*\n\n"
                f"🆔 ID: {user_id}\n"
                f"👤 Username: @{user_data.username if user_data.username else 'Нет'}\n"
                f"📅 Регистрация: {user_data.registered.strftime('%d.%m.%Y')}\n\n"
                f"{get_emoji('stats')} *Статистика:*\n"
                f"💰 Баланс: {format_number(user_data.balance)}\n"
                f"₿ BTC: {user_data.btc:.6f}\n"
                f"🏦 В банке: {format_number(user_data.bank)}\n"
                f"🏆 Уровень: {user_data.level} ({user_data.exp} EXP)\n"
                f"🎮 Игр: {total_games}\n"
                f"🏅 Побед: {user_data.wins}\n"
                f"💔 Поражений: {user_data.loses}\n"
                f"📊 Винрейт: {win_rate:.1f}%\n\n"
                f"{get_emoji('referral')} *Рефералы:*\n"
                f"👥 Приглашено: {user_data.total_referrals}\n"
                f"💰 Заработано: {format_number(user_data.referral_earnings)}\n"
                f"🔗 Код: {user_data.referral_code}\n\n"
                f"🚫 Статус: {'Забанен' if user_data.is_banned else 'Активен'}"
            )
        
        else:
            await update.message.reply_text(f"{get_emoji('alert')} Неизвестное действие!")
            return
        
        keyboard = [[InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        
    except ValueError as e:
        await update.message.reply_text(f"{get_emoji('alert')} Ошибка ввода данных: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"{get_emoji('alert')} Ошибка: {str(e)}")

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
    elif data == "profile_detailed":
        await profile_detailed(update, context)
    
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
    
    # Биржа
    elif data == "market":
        await market(update, context)
    elif data == "market_buy":
        await market_buy(update, context)
    elif data == "market_sell":
        await market_sell(update, context)
    
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
    
    # Работа
    elif data == "work_menu":
        await work_menu(update, context)
    elif data.startswith("work_"):
        if data == "work_perform":
            await work_perform(update, context)
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
    elif data == "bonus_cooldown":
        await query.answer("Бонус еще не доступен!", show_alert=True)
    
    # Рефералы
    elif data == "referral":
        await referral(update, context)
    elif data == "copy_ref":
        await copy_ref(update, context)
    
    # Админ-панель
    elif data == "admin_panel":
        await admin_panel(update, context)
    elif data == "admin_stats":
        await admin_stats(update, context)
    elif data == "admin_give_money":
        await admin_give_money(update, context)
    elif data == "admin_take_money":
        await admin_take_money(update, context)
    elif data == "admin_give_btc":
        await admin_give_btc(update, context)
    elif data == "admin_ban":
        await admin_ban(update, context)
    elif data == "admin_user":
        await admin_user(update, context)
    elif data == "admin_logs":
        await admin_logs(update, context)
    
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
    
    # Обработка действий банка/биржи/бонусов
    elif context.user_data.get("bank_action"):
        await handle_bank_action(update, context)
    elif context.user_data.get("market_action"):
        await handle_market_action(update, context)
    elif context.user_data.get("action") == "promo_code":
        await handle_promo_code(update, context)
    
    # Обработка админских действий
    elif context.user_data.get("admin_action"):
        await handle_admin_action(update, context)
    
    # Обработка команд без слеша (алиасы)
    elif text.lower() in ["профиль", "profile", "я"]:
        await profile(update, context)
    elif text.lower() in ["игры", "games"]:
        await games_menu(update, context)
    elif text.lower() in ["работа", "work"]:
        await work_perform(update, context)
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
    elif text.lower() in ["админ", "admin"] and user.id in ADMIN_IDS:
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
            context.user_data["bet_amount"] = amount

# ========== КОМАНДЫ ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    text = (
        f"{get_emoji('alert')} *ПОМОЩЬ ПО БОТУ*\n\n"
        f"*Основные команды:*\n"
        f"/start - Начать игру\n"
        f"/profile или 'Я' - Профиль\n"
        f"/balance или 'Баланс' - Баланс\n"
        f"/level или 'Уровень' - Уровень\n"
        f"/games или 'Игры' - Игры\n"
        f"/work или 'Работа' - Работа\n"
        f"/farm или 'Ферма' - Ферма BTC\n"
        f"/bank или 'Банк' - Банк\n"
        f"/market или 'Биржа' - Биржа BTC\n"
        f"/bonus или 'Бонус' - Бонусы\n"
        f"/referral или 'Рефералы' - Реферальная система\n\n"
        f"*Игры:*\n"
        f"🎲 Кости - угадайте результат\n"
        f"⚽ Футбол - гол или мимо\n"
        f"🎰 Рулетка - классическая рулетка\n"
        f"💎 Алмазы - найдите алмаз\n"
        f"💣 Мины - избегайте мин\n"
        f"💥 Краш - выведите до краха\n"
        f"🃏 Очко - наберите 21\n\n"
        f"{get_emoji('alert')} *Поддержка:*\n"
        f"По вопросам пишите: @support"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

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

# ========== ЕЖЕДНЕВНЫЕ ПРОЦЕНТЫ ==========
async def daily_interest_task(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное начисление процентов в банке"""
    if not db:
        return
    
    try:
        # Получаем всех пользователей с деньгами в банке
        # Для psycopg2 используем синхронный подход
        conn = db.pool.getconn()
        try:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            cursor.execute('SELECT * FROM users WHERE bank > 0')
            users = cursor.fetchall()
            
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
        finally:
            db.pool.putconn(conn)
            
    except Exception as e:
        print(f"❌ Ошибка при начислении процентов: {e}")

import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ==================== Основная функция ====================
async def main():
    print("🤖 Бот запускается...")

    # Создаем приложение
    app = Application.builder().token(TOKEN).build()

    # ---------------- Командные обработчики ----------------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("level", level_command))
    app.add_handler(CommandHandler("games", games_menu))
    app.add_handler(CommandHandler("job", work_menu))
    app.add_handler(CommandHandler("work", work_perform))
    app.add_handler(CommandHandler("farm", farm_menu))
    app.add_handler(CommandHandler("bank", bank_menu))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("bonus", bonus))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("admin", admin_panel))

    # ---------------- Callback-запросы ----------------
    app.add_handler(CallbackQueryHandler(callback_handler))

    # ---------------- Текстовые сообщения ----------------
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # ---------------- Подключение к базе (не блокирует) ----------------
    if db:
        async def connect_db():
            try:
                await db.connect()
                print("✅ Обнаружено подключение к Supabase")
            except Exception as e:
                print(f"❌ Ошибка подключения к БД: {e}")

        # создаём задачу, чтобы бот не ждал подключения
        asyncio.create_task(connect_db())

    print("✅ Все хэндлеры добавлены. Стартуем polling...")

    # ---------------- Запуск бота ----------------
    await app.run_polling()
    print("✅ Бот остановлен")
