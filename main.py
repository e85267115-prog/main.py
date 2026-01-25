# bot_complete.py - ПОЛНЫЙ КОД VIBE BET БОТА
# ЧАСТЬ 1/6

import logging
import json
import random
import asyncio
import datetime
import os
from typing import Dict, List, Tuple, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
import pytz

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TOKEN", "ВАШ_ТОКЕН_БОТА")
ADMIN_IDS = json.loads(os.environ.get("ADMIN_IDS", "[123456789]"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@nvibee_bet")
CHAT_USERNAME = os.environ.get("CHAT_USERNAME", "@chatvibee_bet")

# ========== НАСТРОЙКИ ==========
LEVEL_EXP_REQUIREMENTS = {1: 4, 2: 8, 3: 12, 4: 16, 5: 20}
LEVEL_BONUS = {1: 50000, 2: 75000, 3: 100000, 4: 125000, 5: 150000}

# ========== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ==========
USERS_FILE = "users.json"
BTC_FARM_FILE = "btc_farm.json"

# ========== НАСТРОЙКИ ВИДЕОКАРТ ==========
GPU_TYPES = {
    "low": {
        "name": "🎮 GeForce GTX 1650",
        "base_price": 150000,
        "price_increase": 1.2,
        "income_per_hour": 0.1,
        "max_quantity": 3
    },
    "medium": {
        "name": "💻 GeForce RTX 4060",
        "base_price": 220000,
        "price_increase": 1.2,
        "income_per_hour": 0.4,
        "max_quantity": 3
    },
    "high": {
        "name": "🚀 GeForce RTX 4090",
        "base_price": 350000,
        "price_increase": 1.3,
        "income_per_hour": 0.7,
        "max_quantity": 3
    }
}

# ========== РАБОТЫ ==========
JOBS = {
    "digger": {
        "name": "⛏️ Кладоискатель",
        "description": "Ищешь клады по всему миру",
        "min_salary": 10000,
        "max_salary": 50000,
        "btc_chance": 9
    },
    "hacker": {
        "name": "💻 Хакер",
        "description": "Взламываешь защищенные системы",
        "min_salary": 50000,
        "max_salary": 200000,
        "btc_chance": 9
    },
    "miner": {
        "name": "🔨 Майнер",
        "description": "Добываешь криптовалюту в шахтах",
        "min_salary": 30000,
        "max_salary": 100000,
        "btc_chance": 9
    },
    "trader": {
        "name": "📈 Трейдер",
        "description": "Торгуешь на бирже криптовалют",
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

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
users: Dict[int, 'User'] = {}
btc_farm = None
btc_price = random.randint(10000, 150000)

# ========== КЛАСС USER ==========
class User:
    def __init__(self, user_id: int, username: str = ""):
        self.user_id = user_id
        self.username = username
        self.balance = 10000
        self.bank = 0
        self.btc = 0.0
        self.level = 1
        self.exp = 0
        self.wins = 0
        self.loses = 0
        self.job = None
        self.last_work = None
        self.last_bonus = None
        self.registered = datetime.datetime.now()
        self.last_daily_bonus = None
        
    def to_dict(self):
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
            "last_daily_bonus": self.last_daily_bonus.isoformat() if self.last_daily_bonus else None
        }
    
    @classmethod
    def from_dict(cls, data):
        user = cls(data["user_id"], data.get("username", ""))
        user.balance = data.get("balance", 10000)
        user.bank = data.get("bank", 0)
        user.btc = data.get("btc", 0.0)
        user.level = data.get("level", 1)
        user.exp = data.get("exp", 0)
        user.wins = data.get("wins", 0)
        user.loses = data.get("loses", 0)
        user.job = data.get("job", None)
        
        if data.get("last_work"):
            user.last_work = datetime.datetime.fromisoformat(data["last_work"])
        if data.get("last_bonus"):
            user.last_bonus = datetime.datetime.fromisoformat(data["last_bonus"])
        if data.get("registered"):
            user.registered = datetime.datetime.fromisoformat(data["registered"])
        if data.get("last_daily_bonus"):
            user.last_daily_bonus = datetime.datetime.fromisoformat(data["last_daily_bonus"])
        
        return user

# ========== КЛАСС BTCFARM ==========
class BTCFarm:
    def __init__(self):
        self.gpus = {}
        self.last_collected = {}
        
    def add_gpu(self, user_id: int, gpu_type: str):
        if user_id not in self.gpus:
            self.gpus[user_id] = {}
        if gpu_type not in self.gpus[user_id]:
            self.gpus[user_id][gpu_type] = 0
        self.gpus[user_id][gpu_type] += 1
        
    def get_user_gpus(self, user_id: int):
        return self.gpus.get(user_id, {})
    
    def to_dict(self):
        return {
            "gpus": self.gpus,
            "last_collected": {uid: dt.isoformat() for uid, dt in self.last_collected.items()}
        }
    
    @classmethod
    def from_dict(cls, data):
        farm = cls()
        farm.gpus = data.get("gpus", {})
        last_collected = data.get("last_collected", {})
        farm.last_collected = {
            int(uid): datetime.datetime.fromisoformat(dt) 
            for uid, dt in last_collected.items()
        }
        return farm

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_number(num: float) -> str:
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

def calculate_gpu_income(user_id: int) -> float:
    if btc_farm is None:
        return 0.0
    
    user_gpus = btc_farm.get_user_gpus(user_id)
    total_income = 0.0
    
    for gpu_type, quantity in user_gpus.items():
        if gpu_type in GPU_TYPES:
            total_income += GPU_TYPES[gpu_type]["income_per_hour"] * quantity
    
    if user_id in btc_farm.last_collected:
        time_passed = datetime.datetime.now() - btc_farm.last_collected[user_id]
        hours_passed = time_passed.total_seconds() / 3600
        return total_income * hours_passed
    return 0.0

def add_exp(user: User) -> bool:
    if random.random() < 0.5:
        user.exp += 1
        exp_needed = LEVEL_EXP_REQUIREMENTS.get(user.level, 4 * user.level)
        if user.exp >= exp_needed:
            user.level += 1
            user.exp = 0
            return True
    return False

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
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
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# ========== ФУНКЦИИ СОХРАНЕНИЯ/ЗАГРУЗКИ ==========
def save_data():
    try:
        users_data = {uid: user.to_dict() for uid, user in users.items()}
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
        
        if btc_farm:
            with open(BTC_FARM_FILE, 'w', encoding='utf-8') as f:
                json.dump(btc_farm.to_dict(), f, ensure_ascii=False, indent=2)
        
        logging.info("Данные сохранены")
    except Exception as e:
        logging.error(f"Ошибка сохранения данных: {e}")

def load_data():
    global users, btc_farm, btc_price
    
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                users = {int(uid): User.from_dict(data) for uid, data in users_data.items()}
    except Exception as e:
        logging.error(f"Ошибка загрузки пользователей: {e}")
        users = {}
    
    try:
        if os.path.exists(BTC_FARM_FILE):
            with open(BTC_FARM_FILE, 'r', encoding='utf-8') as f:
                farm_data = json.load(f)
                btc_farm = BTCFarm.from_dict(farm_data)
        else:
            btc_farm = BTCFarm()
    except Exception as e:
        logging.error(f"Ошибка загрузки фермы: {e}")
        btc_farm = BTCFarm()
    
    btc_price = random.randint(10000, 150000)
    logging.info(f"Загружено {len(users)} пользователей")

# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    welcome_text = """
🎰 *Добро Пожаловать в Vibe Bet!*
Крути рулетку, рискуй в Краше, а также собирай свою ферму.

🎲 *Игры:* 🎲 Кости, ⚽ Футбол, 🎰 Рулетка, 💎 Алмазы, 💣 Мины
⛏️ *Заработок:* 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус
"""
    
    try:
        photo_url = "https://raw.githubusercontent.com/ваш-username/репозиторий/main/start_img.jpg"
        await update.message.reply_photo(
            photo=photo_url,
            caption=welcome_text,
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
    
    if user_id not in users:
        keyboard = [[InlineKeyboardButton("📝 Зарегистрироваться", callback_data="register")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "📝 Для начала игры необходимо зарегистрироваться!",
            reply_markup=reply_markup
        )
    else:
        await show_main_menu(update, context)

async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in users:
        await query.edit_message_text("✅ Вы уже зарегистрированы!")
        return
    
    if not await check_subscription(user_id, context):
        keyboard = [
            [InlineKeyboardButton("✅ Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ Подписаться на чат", url=f"https://t.me/{CHAT_USERNAME[1:]}")],
            [InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📢 Для регистрации необходимо подписаться на наш канал и чат!\n\n"
            f"Канал: {CHANNEL_USERNAME}\n"
            f"Чат: {CHAT_USERNAME}",
            reply_markup=reply_markup
        )
        return
    
    users[user_id] = User(user_id, query.from_user.username)
    save_data()
    
    await query.edit_message_text(
        "🎉 *Регистрация успешна!*\n\n"
        f"💰 Ваш стартовый баланс: {format_number(10000)}\n"
        "🎮 Используйте /menu для доступа к играм",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
         InlineKeyboardButton("🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton("💰 Банк", callback_data="bank_menu"),
         InlineKeyboardButton("⛏️ Работа", callback_data="jobs_menu")],
        [InlineKeyboardButton("🖥 Ферма BTC", callback_data="farm_menu"),
         InlineKeyboardButton("🎁 Бонус", callback_data="bonus")],
        [InlineKeyboardButton("📊 Биржа BTC", callback_data="btc_market")]
    ]
    
    if update.effective_user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🏠 *Главное меню Vibe Bet*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🏠 *Главное меню Vibe Bet*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    total_won = user.balance + user.bank - 10000
    
    profile_text = f"""
👤 *ПРОФИЛЬ ИГРОКА*

🆔 ID: `{user.user_id}`
👤 Имя: @{user.username if user.username else "Нет"}
💰 Баланс: *{format_number(user.balance)}*
🏦 Банк: *{format_number(user.bank)}*
₿ BTC: *{user.btc:.4f}*

🏆 Уровень: *{user.level}*
📊 EXP: *{user.exp}/{LEVEL_EXP_REQUIREMENTS.get(user.level, 4*user.level)}*
🎯 Побед: *{user.wins}*
💔 Поражений: *{user.loses}*
📈 Общий выигрыш: *{format_number(total_won)}*

📅 Регистрация: {user.registered.strftime('%d.%m.%Y')}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        profile_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎰 Рулетка", callback_data="roulette_menu"),
         InlineKeyboardButton("💣 Мины", callback_data="mines_game")],
        [InlineKeyboardButton("⚽ Футбол", callback_data="football_game"),
         InlineKeyboardButton("🎲 Кости", callback_data="dice_game")],
        [InlineKeyboardButton("💎 Алмазы", callback_data="diamonds_game"),
         InlineKeyboardButton("📈 Краш", callback_data="crash_game")],
        [InlineKeyboardButton("🃏 Очко (21)", callback_data="blackjack_menu")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎮 *ВЫБЕРИТЕ ИГРУ*\n\n"
        "Все игры с реальными ставками и высокими коэффициентами!",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# Продолжение следует...
# bot_complete.py - ПОЛНЫЙ КОД VIBE BET БОТА
# ЧАСТЬ 2/6

async def roulette_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    keyboard = [
        [InlineKeyboardButton("1-12 (x3)", callback_data="roulette_1_12"),
         InlineKeyboardButton("13-24 (x3)", callback_data="roulette_13_24"),
         InlineKeyboardButton("25-36 (x3)", callback_data="roulette_25_36")],
        [InlineKeyboardButton("🔴 Красное (x2)", callback_data="roulette_red"),
         InlineKeyboardButton("⚫ Черное (x2)", callback_data="roulette_black")],
        [InlineKeyboardButton("0-36 (x36)", callback_data="roulette_single")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎰 *РУЛЕТКА*\n\n"
        f"Ваш баланс: *{format_number(user.balance)}*\n\n"
        "Выберите тип ставки:\n"
        "• 1-12, 13-24, 25-36 - коэффициент x3\n"
        "• Красное/Черное - коэффициент x2\n"
        "• Конкретное число (0-36) - коэффициент x36",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def roulette_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    bet_type = query.data
    context.user_data["roulette_type"] = bet_type
    
    await query.edit_message_text(
        f"🎰 *РУЛЕТКА*\n\n"
        f"Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def process_roulette_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    
    result = random.randint(0, 36)
    is_red = result in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    is_black = result in [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
    is_even = result % 2 == 0
    color = "🔴" if is_red else "⚫" if is_black else "🟢"
    
    won = False
    multiplier = 0
    
    if bet_type == "roulette_1_12" and 1 <= result <= 12:
        won = True
        multiplier = 3
    elif bet_type == "roulette_13_24" and 13 <= result <= 24:
        won = True
        multiplier = 3
    elif bet_type == "roulette_25_36" and 25 <= result <= 36:
        won = True
        multiplier = 3
    elif bet_type == "roulette_red" and is_red:
        won = True
        multiplier = 2
    elif bet_type == "roulette_black" and is_black:
        won = True
        multiplier = 2
    elif bet_type == "roulette_single":
        number_bet = random.randint(0, 36)
        if result == number_bet:
            won = True
            multiplier = 36
    
    if won:
        win_amount = bet_amount * multiplier
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        
        result_text = f"""
🎰 *РУЛЕТКА - ПОБЕДА!*

💸 Ставка: *{format_number(bet_amount)}*
🎉 Выигрыш: *{format_number(win_amount)}*
📈 Выпало: {result} {color} ({'красное' if is_red else 'черное' if is_black else 'зеленое'}, {'четное' if is_even else 'нечетное'})
💰 Баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
    else:
        user.loses += 1
        result_text = f"""
🎰 *РУЛЕТКА - ПРОИГРЫШ*

💸 Ставка: *{format_number(bet_amount)}*
📈 Выпало: {result} {color} ({'красное' if is_red else 'черное' if is_black else 'зеленое'}, {'четное' if is_even else 'нечетное'})
💰 Баланс: *{format_number(user.balance)}*
"""
    
    save_data()
    await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)

async def football_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    keyboard = [
        [InlineKeyboardButton("⚽ ГОЛ (x1.8)", callback_data="football_goal"),
         InlineKeyboardButton("❌ МИМО (x2.2)", callback_data="football_miss")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚽ *ФУТБОЛ*\n\n"
        f"Ваш баланс: *{format_number(user.balance)}*\n\n"
        "Угадайте исход удара:\n"
        "• ⚽ ГОЛ - коэффициент x1.8\n"
        "• ❌ МИМО - коэффициент x2.2",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def process_football_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    bet_type = query.data
    context.user_data["football_type"] = bet_type
    
    await query.edit_message_text(
        "⚽ *ФУТБОЛ*\n\n"
        "Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def play_football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    
    message = await update.message.reply_text("⚽")
    await asyncio.sleep(2)
    
    is_goal = random.random() < 0.5
    
    won = False
    if (bet_type == "football_goal" and is_goal) or (bet_type == "football_miss" and not is_goal):
        won = True
    
    if won:
        multiplier = 1.8 if bet_type == "football_goal" else 2.2
        win_amount = int(bet_amount * multiplier)
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        
        result_emoji = "⚽🥅 ГООООЛ!!!" if is_goal else "❌ МИМО!"
        result_text = f"""
⚽ *ФУТБОЛ - ПОБЕДА!*

{result_emoji}
💸 Ставка: *{format_number(bet_amount)}*
🎉 Выигрыш: *{format_number(win_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
    else:
        user.loses += 1
        result_emoji = "⚽🥅 ГООООЛ!!!" if is_goal else "❌ МИМО!"
        result_text = f"""
⚽ *ФУТБОЛ - ПРОИГРЫШ*

{result_emoji}
💸 Ставка: *{format_number(bet_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
    
    save_data()
    await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)

async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    keyboard = [
        [InlineKeyboardButton("🎲 БОЛЬШЕ 7 (x2.2)", callback_data="dice_more"),
         InlineKeyboardButton("🎲 МЕНЬШЕ 7 (x2.2)", callback_data="dice_less")],
        [InlineKeyboardButton("🎲 РАВНО 7 (x5.7)", callback_data="dice_equal")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎲 *КОСТИ*\n\n"
        f"Ваш баланс: *{format_number(user.balance)}*\n\n"
        "Угадайте сумму двух кубиков:\n"
        "• 🎲 БОЛЬШЕ 7 (8-12) - x2.2\n"
        "• 🎲 МЕНЬШЕ 7 (2-6) - x2.2\n"
        "• 🎲 РАВНО 7 - x5.7",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def process_dice_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    bet_type = query.data
    context.user_data["dice_type"] = bet_type
    
    await query.edit_message_text(
        "🎲 *КОСТИ*\n\n"
        "Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def play_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    
    message = await update.message.reply_text("🎲")
    await asyncio.sleep(2)
    
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
    won = False
    multiplier = 0
    
    if bet_type == "dice_more" and total > 7:
        won = True
        multiplier = 2.2
    elif bet_type == "dice_less" and total < 7:
        won = True
        multiplier = 2.2
    elif bet_type == "dice_equal" and total == 7:
        won = True
        multiplier = 5.7
    
    if won:
        win_amount = int(bet_amount * multiplier)
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        
        result_text = f"""
🎲 *КОСТИ - ПОБЕДА!*

🎲 Выпало: {dice1} + {dice2} = *{total}*
💸 Ставка: *{format_number(bet_amount)}*
🎉 Выигрыш: *{format_number(win_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
    else:
        user.loses += 1
        result_text = f"""
🎲 *КОСТИ - ПРОИГРЫШ*

🎲 Выпало: {dice1} + {dice2} = *{total}*
💸 Ставка: *{format_number(bet_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
    
    save_data()
    await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)

async def crash_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        "📈 *КРАШ*\n\n"
        "Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_crash_bet"] = True

async def play_crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    
    crash_point = 1.0
    while random.random() < 0.95:
        crash_point += random.uniform(0.01, 0.2)
        if crash_point >= 10.0:
            break
    
    message = await update.message.reply_text("📈 График растет: 1.00x")
    
    current_multiplier = 1.00
    steps = 0
    while current_multiplier < crash_point and steps < 30:
        await asyncio.sleep(0.3)
        steps += 1
        current_multiplier += random.uniform(0.05, 0.2)
        if current_multiplier >= crash_point:
            break
        try:
            await message.edit_text(f"📈 График растет: {current_multiplier:.2f}x")
        except:
            pass
    
    player_cashed_out = random.random() < 0.3
    
    if player_cashed_out and current_multiplier > 1.1:
        win_amount = int(bet_amount * current_multiplier)
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        
        result_text = f"""
📈 *КРАШ - ПОБЕДА!*

🎯 Вы успели вывести на: *{current_multiplier:.2f}x*
💸 Ставка: *{format_number(bet_amount)}*
🎉 Выигрыш: *{format_number(win_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
    else:
        user.loses += 1
        result_text = f"""
😔 *КРАШ - ПРОИГРЫШ!*

📈 Точка краша: *{crash_point:.2f}x*
🎯 Множитель: *{current_multiplier:.2f}x*
💸 Ставка: *{format_number(bet_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
    
    save_data()
    await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)

# Продолжение следует...
# bot_complete.py - ПОЛНЫЙ КОД VIBE BET БОТА
# ЧАСТЬ 3/6

async def diamonds_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        "💎 *АЛМАЗЫ*\n\n"
        "Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_diamonds_bet"] = True
    context.user_data["diamonds_game"] = {
        "level": 1,
        "diamond_position": random.randint(1, 5),
        "opened": [],
        "multiplier": 1.0
    }

async def play_diamonds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    game_data = context.user_data["diamonds_game"]
    game_data["bet_amount"] = bet_amount
    
    await show_diamonds_board(update, context)

async def show_diamonds_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game_data = context.user_data["diamonds_game"]
    level = game_data["level"]
    
    if level > 16:
        win_amount = int(game_data["bet_amount"] * game_data["multiplier"])
        user_id = update.effective_user.id
        user = users.get(user_id)
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        save_data()
        
        result_text = f"""
💎 *АЛМАЗЫ - ПОБЕДА!*

🎮 Пройдено уровней: 16
🎉 Множитель: *{game_data['multiplier']:.1f}x*
💰 Выигрыш: *{format_number(win_amount)}*
💸 Ставка: *{format_number(game_data['bet_amount'])}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
        
        await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    keyboard = []
    for i in range(5):
        if i+1 in game_data["opened"]:
            if i+1 == game_data["diamond_position"]:
                button = InlineKeyboardButton("💎", callback_data=f"diamond_{i+1}")
            else:
                button = InlineKeyboardButton("📦", callback_data=f"diamond_{i+1}")
        else:
            button = InlineKeyboardButton("❓", callback_data=f"diamond_{i+1}")
        
        if len(keyboard) == 0 or len(keyboard[-1]) == 5:
            keyboard.append([button])
        else:
            keyboard[-1].append(button)
    
    keyboard.append([InlineKeyboardButton("🏆 Забрать выигрыш", callback_data="diamond_cashout")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
💎 *АЛМАЗЫ - Уровень {level}/16*

Множитель: *{game_data['multiplier']:.1f}x*
Открыто ячеек: {len(game_data['opened'])}/5

Выберите ячейку:
"""
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def process_diamond_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    game_data = context.user_data.get("diamonds_game")
    
    if not game_data:
        await query.edit_message_text("❌ Игра не найдена!")
        return
    
    if "cashout" in query.data:
        user = users.get(user_id)
        win_amount = int(game_data["bet_amount"] * game_data["multiplier"])
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        save_data()
        
        result_text = f"""
💎 *АЛМАЗЫ - ВЫИГРЫШ!*

🎮 Пройдено уровней: {game_data['level']-1}
🎉 Множитель: *{game_data['multiplier']:.1f}x*
💰 Выигрыш: *{format_number(win_amount)}*
💸 Ставка: *{format_number(game_data['bet_amount'])}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
        
        await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    cell_num = int(query.data.split("_")[1])
    
    if cell_num in game_data["opened"]:
        await query.answer("Эта ячейка уже открыта!", show_alert=True)
        return
    
    game_data["opened"].append(cell_num)
    
    if cell_num == game_data["diamond_position"]:
        game_data["level"] += 1
        game_data["multiplier"] += 0.5
        game_data["diamond_position"] = random.randint(1, 5)
        game_data["opened"] = []
        
        await query.edit_message_text(f"💎 *АЛМАЗ НАЙДЕН!*\n\nПереход на уровень {game_data['level']}!")
        await asyncio.sleep(2)
        await show_diamonds_board_from_query(query, context)
    else:
        await query.edit_message_text(f"📦 *Алмаза нет здесь!*\n\nПродолжайте искать...")
        await asyncio.sleep(1)
        await show_diamonds_board_from_query(query, context)

async def show_diamonds_board_from_query(query, context):
    game_data = context.user_data["diamonds_game"]
    level = game_data["level"]
    
    if level > 16:
        win_amount = int(game_data["bet_amount"] * game_data["multiplier"])
        user_id = query.from_user.id
        user = users.get(user_id)
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        save_data()
        
        result_text = f"""
💎 *АЛМАЗЫ - ПОБЕДА!*

🎮 Пройдено уровней: 16
🎉 Множитель: *{game_data['multiplier']:.1f}x*
💰 Выигрыш: *{format_number(win_amount)}*
💸 Ставка: *{format_number(game_data['bet_amount'])}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
        
        await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    keyboard = []
    for i in range(5):
        if i+1 in game_data["opened"]:
            if i+1 == game_data["diamond_position"]:
                button = InlineKeyboardButton("💎", callback_data=f"diamond_{i+1}")
            else:
                button = InlineKeyboardButton("📦", callback_data=f"diamond_{i+1}")
        else:
            button = InlineKeyboardButton("❓", callback_data=f"diamond_{i+1}")
        
        if len(keyboard) == 0 or len(keyboard[-1]) == 5:
            keyboard.append([button])
        else:
            keyboard[-1].append(button)
    
    keyboard.append([InlineKeyboardButton("🏆 Забрать выигрыш", callback_data="diamond_cashout")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
💎 *АЛМАЗЫ - Уровень {level}/16*

Множитель: *{game_data['multiplier']:.1f}x*
Открыто ячеек: {len(game_data['opened'])}/5

Выберите ячейку:
"""
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        "💣 *МИНЫ*\n\n"
        "Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_mines_bet"] = True
    context.user_data["mines_game"] = {
        "mines": [],
        "opened": [],
        "multiplier": 1.0
    }

async def play_mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    game_data = context.user_data["mines_game"]
    game_data["bet_amount"] = bet_amount
    
    all_cells = list(range(1, 26))
    game_data["mines"] = random.sample(all_cells, 3)
    
    await show_mines_board(update, context)

async def show_mines_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game_data = context.user_data["mines_game"]
    
    keyboard = []
    for row in range(5):
        row_buttons = []
        for col in range(5):
            cell_num = row * 5 + col + 1
            if cell_num in game_data["opened"]:
                if cell_num in game_data["mines"]:
                    button = InlineKeyboardButton("💣", callback_data=f"mine_{cell_num}")
                else:
                    button = InlineKeyboardButton("✅", callback_data=f"mine_{cell_num}")
            else:
                button = InlineKeyboardButton("🟦", callback_data=f"mine_{cell_num}")
            row_buttons.append(button)
        keyboard.append(row_buttons)
    
    keyboard.append([InlineKeyboardButton("🏆 Забрать выигрыш", callback_data="mine_cashout")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    opened_safe = len([c for c in game_data["opened"] if c not in game_data["mines"]])
    multiplier = 1.0 + (opened_safe * 0.3)
    game_data["multiplier"] = multiplier
    
    text = f"""
💣 *МИНЫ*

Открыто безопасных ячеек: {opened_safe}
Множитель: *{multiplier:.1f}x*
Мин на поле: 3

Выберите ячейку:
"""
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def process_mine_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    game_data = context.user_data.get("mines_game")
    user = users.get(user_id)
    
    if not game_data or not user:
        await query.edit_message_text("❌ Ошибка игры!")
        return
    
    if "cashout" in query.data:
        opened_safe = len([c for c in game_data["opened"] if c not in game_data["mines"]])
        multiplier = 1.0 + (opened_safe * 0.3)
        win_amount = int(game_data["bet_amount"] * multiplier)
        user.balance += win_amount
        user.wins += 1
        
        level_up = add_exp(user)
        save_data()
        
        result_text = f"""
💣 *МИНЫ - ВЫИГРЫШ!*

🎮 Открыто безопасных ячеек: {opened_safe}
🎉 Множитель: *{multiplier:.1f}x*
💰 Выигрыш: *{format_number(win_amount)}*
💸 Ставка: *{format_number(game_data['bet_amount'])}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
        
        await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    cell_num = int(query.data.split("_")[1])
    
    if cell_num in game_data["opened"]:
        await query.answer("Эта ячейка уже открыта!", show_alert=True)
        return
    
    game_data["opened"].append(cell_num)
    
    if cell_num in game_data["mines"]:
        user.loses += 1
        save_data()
        
        keyboard = []
        for row in range(5):
            row_buttons = []
            for col in range(5):
                cell_num_display = row * 5 + col + 1
                if cell_num_display in game_data["mines"]:
                    button = InlineKeyboardButton("💣", callback_data="none")
                elif cell_num_display == cell_num:
                    button = InlineKeyboardButton("💥", callback_data="none")
                elif cell_num_display in game_data["opened"]:
                    button = InlineKeyboardButton("✅", callback_data="none")
                else:
                    button = InlineKeyboardButton("🟦", callback_data="none")
                row_buttons.append(button)
            keyboard.append(row_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"""
💥 *МИНЫ - ПРОИГРЫШ!*

Вы наступили на мину!
💸 Ставка: *{format_number(game_data['bet_amount'])}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        await query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        opened_safe = len([c for c in game_data["opened"] if c not in game_data["mines"]])
        multiplier = 1.0 + (opened_safe * 0.3)
        game_data["multiplier"] = multiplier
        
        keyboard = []
        for row in range(5):
            row_buttons = []
            for col in range(5):
                cell_num_display = row * 5 + col + 1
                if cell_num_display in game_data["opened"]:
                    if cell_num_display in game_data["mines"]:
                        button = InlineKeyboardButton("💣", callback_data=f"mine_{cell_num_display}")
                    else:
                        button = InlineKeyboardButton("✅", callback_data=f"mine_{cell_num_display}")
                else:
                    button = InlineKeyboardButton("🟦", callback_data=f"mine_{cell_num_display}")
                row_buttons.append(button)
            keyboard.append(row_buttons)
        
        keyboard.append([InlineKeyboardButton("🏆 Забрать выигрыш", callback_data="mine_cashout")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""
💣 *МИНЫ*

Открыто безопасных ячеек: {opened_safe}
Множитель: *{multiplier:.1f}x*
Мин на поле: 3

Выберите ячейку:
"""
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# Продолжение следует...
# bot_complete.py - ПОЛНЫЙ КОД VIBE BET БОТА
# ЧАСТЬ 4/6

async def blackjack_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        "🃏 *ОЧКО (21)*\n\n"
        "Введите сумму ставки (мин. 100):\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["awaiting_blackjack_bet"] = True

async def play_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
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
    
    user.balance -= bet_amount
    
    context.user_data["blackjack_game"] = {
        "bet": bet_amount,
        "player_cards": [],
        "dealer_cards": [],
        "player_score": 0,
        "dealer_score": 0,
        "game_over": False
    }
    
    game = context.user_data["blackjack_game"]
    
    game["player_cards"] = [draw_card(), draw_card()]
    game["dealer_cards"] = [draw_card(), draw_card()]
    
    game["player_score"] = calculate_score(game["player_cards"])
    game["dealer_score"] = calculate_score([game["dealer_cards"][0]])
    
    if game["player_score"] == 21:
        win_amount = int(bet_amount * 2.5)
        user.balance += win_amount + bet_amount
        user.wins += 1
        
        level_up = add_exp(user)
        save_data()
        
        result_text = f"""
🃏 *ОЧКО - БЛЭКДЖЕК!*

Ваши карты: {format_cards(game['player_cards'])} ({game['player_score']})
Карты дилера: {format_cards(game['dealer_cards'])} ({calculate_score(game['dealer_cards'])})

💸 Ставка: *{format_number(bet_amount)}*
🎉 Выигрыш: *{format_number(win_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        if level_up:
            result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
        
        await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    await show_blackjack_board(update, context)

def draw_card():
    cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    return random.choice(cards)

def calculate_score(cards):
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
    
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    
    return score

def format_cards(cards):
    suits = ['♠️', '♥️', '♦️', '♣️']
    formatted = []
    for card in cards:
        suit = random.choice(suits)
        formatted.append(f"{card}{suit}")
    return ' '.join(formatted)

async def show_blackjack_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = context.user_data.get("blackjack_game")
    
    if not game:
        await update.message.reply_text("❌ Игра не найдена!")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Еще карту", callback_data="blackjack_hit"),
         InlineKeyboardButton("✋ Хватит", callback_data="blackjack_stand")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    dealer_cards_display = f"{game['dealer_cards'][0]}? ?"
    player_cards_display = format_cards(game["player_cards"])
    
    text = f"""
🃏 *ОЧКО (21)*

Карты дилера: {dealer_cards_display}
Ваши карты: {player_cards_display}
Ваши очки: *{game['player_score']}*

Выберите действие:
"""
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def process_blackjack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    game = context.user_data.get("blackjack_game")
    
    if not game or not user:
        await query.edit_message_text("❌ Ошибка игры!")
        return
    
    action = query.data
    
    if action == "blackjack_hit":
        game["player_cards"].append(draw_card())
        game["player_score"] = calculate_score(game["player_cards"])
        
        if game["player_score"] > 21:
            game["game_over"] = True
            user.loses += 1
            save_data()
            
            result_text = f"""
🃏 *ОЧКО - ПЕРЕБОР!*

Ваши карты: {format_cards(game['player_cards'])} ({game['player_score']})

💸 Ставка: *{format_number(game['bet'])}*
💰 Баланс: *{format_number(user.balance)}*
"""
            
            await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)
            return
        
        await show_blackjack_board_from_query(query, context)
    
    elif action == "blackjack_stand":
        game["dealer_score"] = calculate_score(game["dealer_cards"])
        
        while game["dealer_score"] < 17:
            game["dealer_cards"].append(draw_card())
            game["dealer_score"] = calculate_score(game["dealer_cards"])
        
        dealer_score = game["dealer_score"]
        player_score = game["player_score"]
        
        if dealer_score > 21 or player_score > dealer_score:
            win_amount = game["bet"] * 2
            user.balance += win_amount
            user.wins += 1
            
            level_up = add_exp(user)
            save_data()
            
            result_text = f"""
🃏 *ОЧКО - ПОБЕДА!*

Ваши карты: {format_cards(game['player_cards'])} ({player_score})
Карты дилера: {format_cards(game['dealer_cards'])} ({dealer_score})

💸 Ставка: *{format_number(game['bet'])}*
🎉 Выигрыш: *{format_number(win_amount)}*
💰 Баланс: *{format_number(user.balance)}*
"""
            
            if level_up:
                result_text += f"\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
        
        elif player_score < dealer_score:
            user.loses += 1
            save_data()
            
            result_text = f"""
🃏 *ОЧКО - ПРОИГРЫШ!*

Ваши карты: {format_cards(game['player_cards'])} ({player_score})
Карты дилера: {format_cards(game['dealer_cards'])} ({dealer_score})

💸 Ставка: *{format_number(game['bet'])}*
💰 Баланс: *{format_number(user.balance)}*
"""
        else:
            user.balance += game["bet"]
            save_data()
            
            result_text = f"""
🃏 *ОЧКО - НИЧЬЯ!*

Ваши карты: {format_cards(game['player_cards'])} ({player_score})
Карты дилера: {format_cards(game['dealer_cards'])} ({dealer_score})

💸 Ставка возвращена: *{format_number(game['bet'])}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)

async def show_blackjack_board_from_query(query, context):
    game = context.user_data.get("blackjack_game")
    
    keyboard = [
        [InlineKeyboardButton("➕ Еще карту", callback_data="blackjack_hit"),
         InlineKeyboardButton("✋ Хватит", callback_data="blackjack_stand")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    dealer_cards_display = f"{game['dealer_cards'][0]}? ?"
    player_cards_display = format_cards(game["player_cards"])
    
    text = f"""
🃏 *ОЧКО (21)*

Карты дилера: {dealer_cards_display}
Ваши карты: {player_cards_display}
Ваши очки: *{game['player_score']}*

Выберите действие:
"""
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def bank_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    daily_income = int(user.bank * 0.05)
    
    keyboard = [
        [InlineKeyboardButton("💰 Положить в банк", callback_data="bank_deposit"),
         InlineKeyboardButton("💳 Снять с банка", callback_data="bank_withdraw")],
        [InlineKeyboardButton("📤 Перевод по ID", callback_data="bank_transfer")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    bank_text = f"""
🏦 *БАНК*

💰 На счету: *{format_number(user.bank)}*
💵 Баланс: *{format_number(user.balance)}*

📈 Ежедневный доход (5%): *{format_number(daily_income)}*
⏰ Начисление: каждый день в 00:00 по МСК

📤 Переводы доступны по ID пользователя
"""
    
    await query.edit_message_text(
        bank_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def bank_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        f"🏦 *ВНЕСЕНИЕ В БАНК*\n\n"
        f"Введите сумму для внесения:\n"
        f"Ваш баланс: *{format_number(user.balance)}*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["bank_action"] = "deposit"

async def bank_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        f"🏦 *СНЯТИЕ С БАНКА*\n\n"
        f"Введите сумму для снятия:\n"
        f"В банке: *{format_number(user.bank)}*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["bank_action"] = "withdraw"

async def bank_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        f"📤 *ПЕРЕВОД ПО ID*\n\n"
        f"Введите ID получателя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["bank_action"] = "transfer_id"

async def process_bank_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        amount = int(update.message.text)
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной!")
            return
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число!")
        return
    
    action = context.user_data.get("bank_action")
    
    if action == "deposit":
        if amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств на балансе!")
            return
        
        user.balance -= amount
        user.bank += amount
        
        result_text = f"""
✅ *СРЕДСТВА ВНЕСЕНЫ В БАНК*

💸 Сумма: *{format_number(amount)}*
🏦 В банке: *{format_number(user.bank)}*
💰 На балансе: *{format_number(user.balance)}*

📈 Ежедневный доход увеличился на *{format_number(int(amount * 0.05))}*
"""
    
    elif action == "withdraw":
        if amount > user.bank:
            await update.message.reply_text("❌ Недостаточно средств в банке!")
            return
        
        user.bank -= amount
        user.balance += amount
        
        result_text = f"""
✅ *СРЕДСТВА СНЯТЫ С БАНКА*

💸 Сумма: *{format_number(amount)}*
🏦 В банке: *{format_number(user.bank)}*
💰 На балансе: *{format_number(user.balance)}*
"""
    
    elif action == "transfer_id":
        try:
            receiver_id = int(amount)
            if receiver_id == user_id:
                await update.message.reply_text("❌ Нельзя переводить самому себе!")
                return
            
            context.user_data["transfer_receiver"] = receiver_id
            await update.message.reply_text(
                f"📤 *ПЕРЕВОД ПО ID*\n\n"
                f"Получатель: `{receiver_id}`\n"
                f"Введите сумму перевода:",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        except:
            await update.message.reply_text("❌ Введите корректный ID!")
            return
    
    elif action == "transfer_amount":
        receiver_id = context.user_data.get("transfer_receiver")
        receiver = users.get(receiver_id)
        
        if not receiver:
            await update.message.reply_text("❌ Пользователь с таким ID не найден!")
            return
        
        if amount > user.balance:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
        
        user.balance -= amount
        receiver.balance += amount
        
        try:
            await context.bot.send_message(
                chat_id=receiver_id,
                text=f"""
📥 *ВАМ ПЕРЕВЕЛИ ДЕНЬГИ!*

От: @{user.username if user.username else f"ID: {user_id}"}
💸 Сумма: *{format_number(amount)}*
💰 Ваш баланс: *{format_number(receiver.balance)}*
"""
            )
        except:
            pass
        
        result_text = f"""
✅ *ПЕРЕВОД ВЫПОЛНЕН!*

👤 Получатель: `{receiver_id}`
💸 Сумма: *{format_number(amount)}*
💰 Ваш баланс: *{format_number(user.balance)}*
"""
        
        context.user_data.pop("transfer_receiver", None)
        context.user_data.pop("bank_action", None)
    
    else:
        await update.message.reply_text("❌ Неизвестное действие!")
        return
    
    save_data()
    await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)

# Продолжение следует...
# bot_complete.py - ПОЛНЫЙ КОД VIBE BET БОТА
# ЧАСТЬ 5/6

async def jobs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    keyboard = []
    for job_id, job_info in JOBS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{job_info['name']} ({format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])})",
                callback_data=f"job_{job_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    jobs_text = """
👷 *РАБОТЫ*

Выберите профессию:
⛏️ Кладоискатель - поиск сокровищ
💻 Хакер - взлом систем
🔨 Майнер - добыча криптовалюты
📈 Трейдер - торговля на бирже

🎁 Шанс найти BTC при работе: 9%
"""
    
    await query.edit_message_text(
        jobs_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    job_id = query.data.split("_")[1]
    job_info = JOBS.get(job_id)
    
    if not job_info:
        await query.edit_message_text("❌ Работа не найдена!")
        return
    
    user.job = job_id
    save_data()
    
    await query.edit_message_text(
        f"""
✅ *ВЫ УСТРОИЛИСЬ НА РАБОТУ!*

{job_info['name']}
📝 {job_info['description']}

💰 Зарплата: *{format_number(job_info['min_salary'])}-{format_number(job_info['max_salary'])}*
🎁 Шанс BTC: *{job_info['btc_chance']}%*

💼 Используйте /work для выполнения работы
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    if not user.job:
        await update.message.reply_text("❌ Сначала выберите работу в меню!")
        return
    
    job_info = JOBS.get(user.job)
    if not job_info:
        await update.message.reply_text("❌ Информация о работе не найдена!")
        return
    
    if user.last_work:
        time_since = datetime.datetime.now() - user.last_work
        if time_since.total_seconds() < 300:
            minutes_left = int((300 - time_since.total_seconds()) / 60)
            await update.message.reply_text(
                f"⏳ Вы уже работали недавно!\n"
                f"Отдохните еще {minutes_left} минут"
            )
            return
    
    work_message = await update.message.reply_text(f"💼 {job_info['name']}...")
    
    processes = {
        "digger": ["🔍 Ищем место для раскопок...", "⛏️ Копаем...", "💰 Нашли сундук!", "🎯 Открываем..."],
        "hacker": ["💻 Подключаемся к серверу...", "🔓 Взламываем защиту...", "📁 Ищем данные...", "💾 Скачиваем информацию..."],
        "miner": ["⛏️ Спускаемся в шахту...", "🔨 Добываем руду...", "🔥 Плавим...", "💰 Получаем криптовалюту..."],
        "trader": ["📈 Анализируем рынок...", "💹 Покупаем акции...", "📊 Следим за курсом...", "💰 Продаем с прибылью..."]
    }
    
    process_steps = processes.get(user.job, ["Работаем...", "Продолжаем...", "Завершаем..."])
    
    for step in process_steps:
        await asyncio.sleep(1)
        try:
            await work_message.edit_text(f"💼 {step}")
        except:
            pass
    
    salary = random.randint(job_info["min_salary"], job_info["max_salary"])
    user.balance += salary
    
    btc_found = 0.0
    if random.random() < job_info["btc_chance"] / 100:
        btc_found = random.uniform(0.001, 0.01)
        user.btc += btc_found
    
    level_up = add_exp(user)
    
    user.last_work = datetime.datetime.now()
    save_data()
    
    result_text = f"""
✅ *РАБОТА ВЫПОЛНЕНА!*

💼 Профессия: {job_info['name']}
💰 Зарплата: *{format_number(salary)}*
💰 Баланс: *{format_number(user.balance)}*
"""
    
    if btc_found > 0:
        result_text += f"\n🎉 *ВЫ НАШЛИ BTC!* +{btc_found:.4f} ₿"
    
    if level_up:
        result_text += f"\n\n🎊 *Уровень повышен!* Теперь у вас {user.level} уровень!"
    
    await work_message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)

async def farm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    btc_income = calculate_gpu_income(user_id)
    
    keyboard = [
        [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")],
        [InlineKeyboardButton("🖥 Купить видеокарты", callback_data="farm_buy")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user_gpus = btc_farm.get_user_gpus(user_id) if btc_farm else {}
    gpu_info = ""
    
    for gpu_type, quantity in user_gpus.items():
        if quantity > 0 and gpu_type in GPU_TYPES:
            gpu_data = GPU_TYPES[gpu_type]
            gpu_info += f"\n{gpu_data['name']}: {quantity} шт. (+{gpu_data['income_per_hour'] * quantity:.1f} BTC/час)"
    
    farm_text = f"""
🖥 *ФЕРМА BTC*

💰 Накоплено: *{btc_income:.4f} BTC*
₿ Всего BTC: *{user.btc:.4f}*

{gpu_info if gpu_info else "📭 У вас нет видеокарт"}

💵 Баланс: *{format_number(user.balance)}*
"""
    
    await query.edit_message_text(
        farm_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    btc_income = calculate_gpu_income(user_id)
    
    if btc_income <= 0:
        await query.answer("❌ Нет накопленного дохода!", show_alert=True)
        return
    
    user.btc += btc_income
    if btc_farm:
        btc_farm.last_collected[user_id] = datetime.datetime.now()
    save_data()
    
    await query.edit_message_text(
        f"""
✅ *ДОХОД СОБРАН!*

💰 Собрано: *{btc_income:.4f} BTC*
₿ Всего BTC: *{user.btc:.4f}*

💰 В денежном эквиваленте: *{format_number(int(btc_income * btc_price))}*
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def farm_buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    keyboard = []
    
    for gpu_type, gpu_data in GPU_TYPES.items():
        user_gpus = btc_farm.get_user_gpus(user_id) if btc_farm else {}
        quantity = user_gpus.get(gpu_type, 0)
        
        price = int(gpu_data["base_price"] * (gpu_data["price_increase"] ** quantity))
        
        button_text = f"{gpu_data['name']} - {format_number(price)}"
        callback_data = f"buy_gpu_{gpu_type}"
        
        if quantity >= gpu_data["max_quantity"]:
            button_text += " (MAX)"
            callback_data = "none"
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="farm_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    farm_text = """
🖥 *ПОКУПКА ВИДЕОКАРТ*

Выберите видеокарту:
🎮 GeForce GTX 1650 - базовая, дешевая
💻 GeForce RTX 4060 - средняя, оптимальная
🚀 GeForce RTX 4090 - мощная, дорогая

⚠️ Цена увеличивается с каждой покупкой!
"""
    
    await query.edit_message_text(
        farm_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def buy_gpu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    gpu_type = query.data.split("_")[2]
    gpu_data = GPU_TYPES.get(gpu_type)
    
    if not gpu_data:
        await query.edit_message_text("❌ Видеокарта не найдена!")
        return
    
    user_gpus = btc_farm.get_user_gpus(user_id) if btc_farm else {}
    quantity = user_gpus.get(gpu_type, 0)
    
    if quantity >= gpu_data["max_quantity"]:
        await query.answer("❌ Достигнут лимит покупки!", show_alert=True)
        return
    
    price = int(gpu_data["base_price"] * (gpu_data["price_increase"] ** quantity))
    
    if price > user.balance:
        await query.answer("❌ Недостаточно средств!", show_alert=True)
        return
    
    user.balance -= price
    if btc_farm:
        btc_farm.add_gpu(user_id, gpu_type)
    save_data()
    
    await query.edit_message_text(
        f"""
✅ *ВИДЕОКАРТА КУПЛЕНА!*

{gpu_data['name']}
💰 Стоимость: *{format_number(price)}*
📈 Доходность: +{gpu_data['income_per_hour']} BTC/час
📊 Всего таких карт: {quantity + 1}

💰 Баланс: *{format_number(user.balance)}*
₿ Общий доход с фермы: +{(quantity + 1) * gpu_data['income_per_hour']:.1f} BTC/час
""",
        parse_mode=ParseMode.MARKDOWN
    )

async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    user_id = update.effective_user.id if update.effective_user else update.message.from_user.id
    user = users.get(user_id)
    
    if not user:
        if query:
            await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        else:
            await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    current_time = datetime.datetime.now()
    can_claim = True
    
    if user.last_bonus:
        time_since = current_time - user.last_bonus
        if time_since.total_seconds() < 86400:
            can_claim = False
            hours_left = 24 - int(time_since.total_seconds() / 3600)
    
    bonus_amount = LEVEL_BONUS.get(user.level, 50000 + (user.level - 1) * 25000)
    
    if can_claim:
        user.balance += bonus_amount
        user.last_bonus = current_time
        save_data()
        
        bonus_text = f"""
🎁 *БОНУС ПОЛУЧЕН!*

🏆 Уровень: {user.level}
💰 Бонус: *{format_number(bonus_amount)}*
💰 Баланс: *{format_number(user.balance)}*

⏳ Следующий бонус через 24 часа
"""
    else:
        bonus_text = f"""
⏳ *БОНУС ЕЩЕ НЕ ДОСТУПЕН*

🏆 Уровень: {user.level}
💰 Бонус: *{format_number(bonus_amount)}*

⏰ Доступно через: {hours_left} часов
"""
    
    if query:
        await query.edit_message_text(bonus_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(bonus_text, parse_mode=ParseMode.MARKDOWN)

async def btc_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    global btc_price
    
    keyboard = [
        [InlineKeyboardButton("💰 Купить BTC", callback_data="btc_buy"),
         InlineKeyboardButton("💸 Продать BTC", callback_data="btc_sell")],
        [InlineKeyboardButton("🔄 Обновить курс", callback_data="btc_market")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    market_text = f"""
📊 *БИРЖА BTC*

💰 Текущий курс: *1 BTC = {format_number(btc_price)}*
₿ Ваш баланс BTC: *{user.btc:.4f}*
💵 Ваш баланс: *{format_number(user.balance)}*

📈 Курс обновляется каждый час
💹 Диапазон: 10,000 - 150,000
"""
    
    await query.edit_message_text(
        market_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def btc_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        f"""
💰 *ПОКУПКА BTC*

Текущий курс: 1 BTC = {format_number(btc_price)}
Ваш баланс: *{format_number(user.balance)}*

Введите сумму для покупки BTC:
1. Сумму в BTC (например: 0.01)
2. Сумму в деньгах (например: 1000)
""",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["btc_action"] = "buy"

async def btc_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = users.get(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь!")
        return
    
    await query.edit_message_text(
        f"""
💸 *ПРОДАЖА BTC*

Текущий курс: 1 BTC = {format_number(btc_price)}
Ваш баланс BTC: *{user.btc:.4f}*

Введите сумму для продажи BTC:
1. Сумму в BTC (например: 0.01)
2. Сумму в деньгах (например: 1000)
""",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["btc_action"] = "sell"

async def process_btc_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    
    if not user:
        await update.message.reply_text("❌ Сначала зарегистрируйтесь!")
        return
    
    try:
        amount = update.message.text
        
        btc_amount = 0.0
        money_amount = 0
        
        if "." in amount:
            try:
                btc_amount = float(amount)
                money_amount = int(btc_amount * btc_price)
            except:
                await update.message.reply_text("❌ Введите корректное число!")
                return
        else:
            try:
                money_amount = int(amount)
                btc_amount = money_amount / btc_price
            except:
                await update.message.reply_text("❌ Введите корректное число!")
                return
        
        action = context.user_data.get("btc_action")
        
        if action == "buy":
            if money_amount > user.balance:
                await update.message.reply_text("❌ Недостаточно средств!")
                return
            
            user.balance -= money_amount
            user.btc += btc_amount
            
            result_text = f"""
✅ *BTC КУПЛЕН!*

💰 Куплено: *{btc_amount:.4f} BTC*
💸 Потрачено: *{format_number(money_amount)}*
₿ Баланс BTC: *{user.btc:.4f}*
💰 Баланс: *{format_number(user.balance)}*
"""
        
        elif action == "sell":
            if btc_amount > user.btc:
                await update.message.reply_text("❌ Недостаточно BTC!")
                return
            
            user.btc -= btc_amount
            user.balance += money_amount
            
            result_text = f"""
✅ *BTC ПРОДАН!*

💰 Продано: *{btc_amount:.4f} BTC*
💸 Получено: *{format_number(money_amount)}*
₿ Баланс BTC: *{user.btc:.4f}*
💰 Баланс: *{format_number(user.balance)}*
"""
        else:
            await update.message.reply_text("❌ Неизвестное действие!")
            return
        
        save_data()
        await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Продолжение следует...
# bot_complete.py - ПОЛНЫЙ КОД VIBE BET БОТА
# ЧАСТЬ 6/6

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    keyboard = [
        [InlineKeyboardButton("👤 Поиск пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton("💰 Выдать деньги", callback_data="admin_give_money"),
         InlineKeyboardButton("💸 Забрать деньги", callback_data="admin_take_money")],
        [InlineKeyboardButton("₿ Выдать BTC", callback_data="admin_give_btc")],
        [InlineKeyboardButton("🚫 Забанить", callback_data="admin_ban"),
         InlineKeyboardButton("✅ Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👑 *АДМИН ПАНЕЛЬ*\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_find_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
        "👤 *ПОИСК ПОЛЬЗОВАТЕЛЯ*\n\n"
        "Введите ID пользователя или @username:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "find_user"

async def admin_give_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
        "💰 *ВЫДАЧА ДЕНЕГ*\n\n"
        "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_money_id"

async def admin_take_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
        "💸 *ЗАБИРАНИЕ ДЕНЕГ*\n\n"
        "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "take_money_id"

async def admin_give_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
        "₿ *ВЫДАЧА BTC*\n\n"
        "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "give_btc_id"

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
        "🚫 *БАН ПОЛЬЗОВАТЕЛЯ*\n\n"
        "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "ban_user"

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    await query.edit_message_text(
        "✅ *РАЗБАН ПОЛЬЗОВАТЕЛЯ*\n\n"
        "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["admin_action"] = "unban_user"

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав администратора!")
        return
    
    total_users = len(users)
    total_balance = sum(user.balance for user in users.values())
    total_bank = sum(user.bank for user in users.values())
    total_btc = sum(user.btc for user in users.values())
    total_wins = sum(user.wins for user in users.values())
    total_loses = sum(user.loses for user in users.values())
    
    stats_text = f"""
📊 *СТАТИСТИКА БОТА*

👥 Всего пользователей: *{total_users}*
💰 Общий баланс: *{format_number(total_balance)}*
🏦 Общий банк: *{format_number(total_bank)}*
₿ Общий BTC: *{total_btc:.4f}*

🎯 Всего побед: *{total_wins}*
💔 Всего поражений: *{total_loses}*

📈 Курс BTC: *{format_number(btc_price)}*
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def process_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора!")
        return
    
    action = context.user_data.get("admin_action")
    text = update.message.text
    
    if action == "find_user":
        try:
            target_id = int(text)
            user = users.get(target_id)
        except ValueError:
            target_id = None
            for uid, u in users.items():
                if u.username and text.lower() in u.username.lower():
                    target_id = uid
                    user = u
                    break
        
        if not target_id or not user:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
        
        profile_text = f"""
👑 *ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ*

🆔 ID: `{user.user_id}`
👤 Имя: @{user.username if user.username else "Нет"}
💰 Баланс: *{format_number(user.balance)}*
🏦 Банк: *{format_number(user.bank)}*
₿ BTC: *{user.btc:.4f}*

🏆 Уровень: *{user.level}*
📊 EXP: *{user.exp}*
🎯 Побед: *{user.wins}*
💔 Поражений: *{user.loses}*

📅 Регистрация: {user.registered.strftime('%d.%m.%Y %H:%M')}
"""
        
        keyboard = [
            [InlineKeyboardButton("💰 Выдать деньги", callback_data=f"admin_give_{target_id}"),
             InlineKeyboardButton("💸 Забрать деньги", callback_data=f"admin_take_{target_id}")],
            [InlineKeyboardButton("₿ Выдать BTC", callback_data=f"admin_givebtc_{target_id}"),
             InlineKeyboardButton("🚫 Забанить", callback_data=f"admin_ban_{target_id}")]
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
                await update.message.reply_text("✅ Пользователь разбанен!")
                context.user_data.clear()
        
        except ValueError:
            await update.message.reply_text("❌ Введите корректный ID!")

async def process_admin_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора!")
        return
    
    action = context.user_data.get("admin_action")
    target_id = context.user_data.get("admin_target_id")
    text = update.message.text
    
    if not target_id:
        await update.message.reply_text("❌ Ошибка! Начните заново.")
        return
    
    if action == "give_money_amount":
        try:
            amount = int(text)
            target_user = users.get(target_id)
            if target_user:
                target_user.balance += amount
                save_data()
                await update.message.reply_text(
                    f"✅ Деньги выданы!\n"
                    f"Пользователю {target_id} выдано {format_number(amount)}\n"
                    f"Новый баланс: {format_number(target_user.balance)}"
                )
            else:
                await update.message.reply_text("❌ Пользователь не найден!")
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "take_money_amount":
        try:
            amount = int(text)
            target_user = users.get(target_id)
            if target_user:
                if target_user.balance >= amount:
                    target_user.balance -= amount
                    save_data()
                    await update.message.reply_text(
                        f"✅ Деньги изъяты!\n"
                        f"У пользователя {target_id} изъято {format_number(amount)}\n"
                        f"Новый баланс: {format_number(target_user.balance)}"
                    )
                else:
                    await update.message.reply_text("❌ У пользователя недостаточно средств!")
            else:
                await update.message.reply_text("❌ Пользователь не найден!")
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "give_btc_amount":
        try:
            btc_amount = float(text)
            target_user = users.get(target_id)
            if target_user:
                target_user.btc += btc_amount
                save_data()
                await update.message.reply_text(
                    f"✅ BTC выданы!\n"
                    f"Пользователю {target_id} выдано {btc_amount:.4f} BTC\n"
                    f"Новый баланс BTC: {target_user.btc:.4f}"
                )
            else:
                await update.message.reply_text("❌ Пользователь не найден!")
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число!")
    
    elif action == "ban_reason":
        target_user = users.get(target_id)
        if target_user:
            users.pop(target_id, None)
            save_data()
            await update.message.reply_text(
                f"✅ Пользователь {target_id} забанен!\n"
                f"Причина: {text}"
            )
        else:
            await update.message.reply_text("❌ Пользователь не найден!")
    
    context.user_data.clear()

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if "football_type" in context.user_data:
        await play_football(update, context)
        context.user_data.pop("football_type", None)
    
    elif "dice_type" in context.user_data:
        await play_dice(update, context)
        context.user_data.pop("dice_type", None)
    
    elif "awaiting_crash_bet" in context.user_data:
        await play_crash(update, context)
        context.user_data.pop("awaiting_crash_bet", None)
    
    elif "roulette_type" in context.user_data:
        await process_roulette_bet(update, context)
        context.user_data.pop("roulette_type", None)
    
    elif "awaiting_diamonds_bet" in context.user_data:
        await play_diamonds(update, context)
        context.user_data.pop("awaiting_diamonds_bet", None)
    
    elif "awaiting_mines_bet" in context.user_data:
        await play_mines(update, context)
        context.user_data.pop("awaiting_mines_bet", None)
    
    elif "awaiting_blackjack_bet" in context.user_data:
        await play_blackjack(update, context)
        context.user_data.pop("awaiting_blackjack_bet", None)
    
    elif "bank_action" in context.user_data:
        await process_bank_action(update, context)
    
    elif "btc_action" in context.user_data:
        await process_btc_trade(update, context)
        context.user_data.pop("btc_action", None)
    
    elif "admin_action" in context.user_data:
        action = context.user_data["admin_action"]
        if action in ["give_money_amount", "take_money_amount", "give_btc_amount", "ban_reason"]:
            await process_admin_amount(update, context)
        else:
            await process_admin_action(update, context)
    
    else:
        user_id = update.effective_user.id
        if user_id in users:
            await update.message.reply_text(
                "Для начала игры используйте /menu или выберите команду из меню.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ])
            )
        else:
            await update.message.reply_text(
                "Добро пожаловать! Для начала игры нажмите /start",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Начать", callback_data="start")]
                ])
            )

def main():
    """Главная функция запуска бота"""
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    load_data()
    
    # Для версии 13.x используем другой подход
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Команды
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("menu", show_main_menu))
    dispatcher.add_handler(CommandHandler("bonus", bonus_command))
    dispatcher.add_handler(CommandHandler("work", work_command))
    dispatcher.add_handler(CommandHandler("profile", show_profile))
    
    # Callback handlers
    dispatcher.add_handler(CallbackQueryHandler(register_callback, pattern="^register$"))
    dispatcher.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    dispatcher.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
    dispatcher.add_handler(CallbackQueryHandler(show_games_menu, pattern="^games_menu$"))
    
    # Футбол
    dispatcher.add_handler(CallbackQueryHandler(football_game, pattern="^football_game$"))
    dispatcher.add_handler(CallbackQueryHandler(process_football_bet, pattern="^football_(goal|miss)$"))
    
    # Кости
    dispatcher.add_handler(CallbackQueryHandler(dice_game, pattern="^dice_game$"))
    dispatcher.add_handler(CallbackQueryHandler(process_dice_bet, pattern="^dice_(more|less|equal)$"))
    
    # Рулетка
    dispatcher.add_handler(CallbackQueryHandler(roulette_menu, pattern="^roulette_menu$"))
    dispatcher.add_handler(CallbackQueryHandler(roulette_bet, pattern="^roulette_"))
    
    # Краш
    dispatcher.add_handler(CallbackQueryHandler(crash_game, pattern="^crash_game$"))
    
    # Обработчики текстовых сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_messages))
    
    # Запуск бота
    logging.info("Бот запускается...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
