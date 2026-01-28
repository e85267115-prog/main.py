import os
import re
import json
import random
import asyncio
import logging
import datetime
import aiohttp
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
from contextlib import suppress

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [1997428703]  # Твой ID
CHANNEL_USERNAME = "@nvibee_bet"
CHAT_USERNAME = "@chatvibee_bet"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# ========== БАЗА ДАННЫХ ==========
users_db = {}
promo_codes = {}
transactions = []
btc_price = 45000.0
farm_production = {
    1: {"coins": 100, "btc_chance": 0.01},
    2: {"coins": 250, "btc_chance": 0.02},
    3: {"coins": 500, "btc_chance": 0.03}
}
# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_number(num: float) -> str:
    """Форматирует число с к, кк, ккк"""
    if num >= 1_000_000_000_000:
        return f"{num/1_000_000_000_000:.2f}кккк"
    elif num >= 1_000_000_000:
        return f"{num/1_000_000_000:.2f}ккк"
    elif num >= 1_000_000:
        return f"{num/1_000_000:.2f}кк"
    elif num >= 1_000:
        return f"{num/1_000:.2f}к"
    else:
        return f"{num:.2f}"

def parse_bet(text: str, user_id: int) -> Optional[float]:
    """Парсит ставку с к, кк, ккк"""
    text = text.lower().replace(" ", "")
    
    if text in ["все", "всё"]:
        user = users_db.get(user_id)
        return user.get("balance", 0) if user else 0
    
    multipliers = {"кккк": 1_000_000_000_000, "ккк": 1_000_000_000, 
                   "кк": 1_000_000, "к": 1_000}
    
    for suffix, mult in multipliers.items():
        if suffix in text:
            try:
                return float(text.replace(suffix, "")) * mult
            except:
                return None
    
    try:
        return float(text) if float(text) > 0 else None
    except:
        return None

def get_user(user_id: int) -> Dict:
    """Получает или создает пользователя"""
    if user_id not in users_db:
        users_db[user_id] = {
            "id": user_id,
            "balance": 10000.0,
            "deposit": 0.0,
            "btc": 0.0,
            "level": 1,
            "exp": 0,
            "exp_needed": 4,
            "wins": 0,
            "losses": 0,
            "shovel": 0,
            "detector": 0,
            "farm_cards": 0,
            "last_collect": None,
            "last_bonus": None,
            "last_work": None,
            "promos_used": [],
            "created": datetime.now().isoformat()
        }
    return users_db[user_id]

def add_exp(user_id: int) -> bool:
    """Добавляет опыт с шансом 50%"""
    if random.random() > 0.5:
        return False
    
    user = get_user(user_id)
    user["exp"] += 1
    
    if user["exp"] >= user["exp_needed"]:
        user["level"] += 1
        user["exp"] = 0
        user["exp_needed"] += 4
        return True
    return False
# ========== КОМАНДЫ ПРОФИЛЯ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда старт с проверкой подписки"""
    user = update.effective_user
    user_id = user.id
    
    # Проверка подписки
    check_keyboard = [
        [InlineKeyboardButton("📢 Канал", url=f"https://t.me/nvibee_bet")],
        [InlineKeyboardButton("💬 Чат", url=f"https://t.me/chatvibee_bet")],
        [InlineKeyboardButton("✅ Проверить", callback_data="check_sub")]
    ]
    
    await update.message.reply_photo(
        photo="https://i.imgur.com/start_img.jpg",
        caption=f"👋 Добро пожаловать в Vibe Bet, {user.first_name}!\n\n"
                f"🎲 Игры: 🎰 Рулетка, 📈 Краш, 🎲 Кости, ⚽ Футбол\n"
                f"💎 Алмазы, 💣 Мины, 💰 Банк\n\n"
                f"👇 Для начала подпишись на канал и чат:",
        reply_markup=InlineKeyboardMarkup(check_keyboard)
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Профиль игрока"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    profile_text = (
        f"👤 <b>Профиль {update.effective_user.first_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>\n"
        f"🏦 Депозит: <b>{format_number(user['deposit'])} $</b>\n"
        f"₿ BTC: <b>{user['btc']:.6f}</b> (${format_number(user['btc'] * btc_price)})\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"📊 EXP: <b>{user['exp']}/{user['exp_needed']}</b>\n"
        f"🏆 Побед/Поражений: <b>{user['wins']}/{user['losses']}</b>\n"
        f"⛏️ Инвентарь: Лопаты: {user['shovel']}, Детекторы: {user['detector']}\n"
        f"🖥️ Видеокарт: {user['farm_cards']}/3\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(profile_text, parse_mode="HTML")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Баланс игрока"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    balance_text = (
        f"💰 <b>Ваш баланс</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 На руках: <b>{format_number(user['balance'])} $</b>\n"
        f"🏦 В депозите: <b>{format_number(user['deposit'])} $</b>\n"
        f"₿ BTC: <b>{user['btc']:.6f}</b> (${format_number(user['btc'] * btc_price)})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Общий капитал: <b>{format_number(user['balance'] + user['deposit'] + user['btc'] * btc_price)} $</b>"
    )
    
    await update.message.reply_text(balance_text, parse_mode="HTML")
# ========== ИГРА РУЛЕТКА ==========
async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в рулетку"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "🎰 <b>Vibe Рулетка</b>\n\n"
            "📝 Формат: <code>рулетка [ставка] [ставка]</code>\n\n"
            "🎯 Ставки:\n"
            "• Число 0-36\n"
            "• <code>кр</code> - красный\n"
            "• <code>чер</code> - черный\n"
            "• <code>чет</code> - четное\n"
            "• <code>нечет</code> - нечетное\n"
            "• <code>1-12</code>, <code>13-24</code>, <code>25-36</code>\n\n"
            "Пример: <code>рулетка 1000 кр</code>",
            parse_mode="HTML"
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount > user["balance"]:
        await update.message.reply_text("❌ Неверная ставка!")
        return
    
    bet_type = args[1].lower()
    win_number = random.randint(0, 36)
    
    # Определяем цвет числа
    red_numbers = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    is_red = win_number in red_numbers and win_number != 0
    is_black = win_number not in red_numbers and win_number != 0
    
    # Проверяем выигрыш
    multiplier = 0
    win = False
    
    if bet_type.isdigit() and 0 <= int(bet_type) <= 36:
        # Ставка на число
        multiplier = 36 if int(bet_type) == win_number else 0
        win = int(bet_type) == win_number
    elif bet_type == "кр":
        multiplier = 2 if is_red else 0
        win = is_red
    elif bet_type == "чер":
        multiplier = 2 if is_black else 0
        win = is_black
    elif bet_type == "чет":
        multiplier = 2 if win_number % 2 == 0 and win_number != 0 else 0
        win = win_number % 2 == 0 and win_number != 0
    elif bet_type == "нечет":
        multiplier = 2 if win_number % 2 == 1 and win_number != 0 else 0
        win = win_number % 2 == 1 and win_number != 0
    elif bet_type in ["1-12", "13-24", "25-36"]:
        range_start = int(bet_type.split("-")[0])
        range_end = int(bet_type.split("-")[1])
        multiplier = 3 if range_start <= win_number <= range_end else 0
        win = range_start <= win_number <= range_end
    
    # Вычисляем результат
    win_amount = bet_amount * multiplier if win else 0
    user["balance"] += win_amount - bet_amount
    
    if win:
        user["wins"] += 1
        result_text = "🎉 ВЫИГРЫШ"
    else:
        user["losses"] += 1
        result_text = "❌ ПРОИГРЫШ"
    
    # Добавляем опыт
    if add_exp(user_id):
        await update.message.reply_text(
            f"⭐ Поздравляем! Вы повысили уровень до {user['level']}!\n"
            f"🎁 Бонус за уровень: {format_number(50000 + (user['level'] - 1) * 25000)} $"
        )
    
    # Формируем сообщение
    color = "красный" if is_red else "черный" if is_black else "зеленый"
    parity = "четное" if win_number % 2 == 0 else "нечетное" if win_number != 0 else "ноль"
    
    result_message = (
        f"🎰 <b>Vibe Рулетка</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Выпало: <b>{win_number}</b> ({color}, {parity})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
    )
    
    if win:
        result_message += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{multiplier})\n"
    
    result_message += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode="HTML")
# ========== ИГРА КОСТИ ==========
async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в кости"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "🎲 <b>Vibe Кости</b>\n\n"
            "📝 Формат: <code>кости [ставка] [ставка]</code>\n\n"
            "🎯 Ставки:\n"
            "• <code>больше</code> (>7) - x2.2\n"
            "• <code>меньше</code> (<7) - x2.2\n"
            "• <code>равно</code> (=7) - x5.7\n\n"
            "Пример: <code>кости 500 больше</code>",
            parse_mode="HTML"
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount > user["balance"]:
        await update.message.reply_text("❌ Неверная ставка!")
        return
    
    bet_type = args[1].lower()
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
    # Определяем результат
    win = False
    multiplier = 0
    
    if bet_type == "больше":
        win = total > 7
        multiplier = 2.2 if win else 0
    elif bet_type == "меньше":
        win = total < 7
        multiplier = 2.2 if win else 0
    elif bet_type == "равно":
        win = total == 7
        multiplier = 5.7 if win else 0
    else:
        await update.message.reply_text("❌ Неверный тип ставки!")
        return
    
    # Вычисляем результат
    win_amount = bet_amount * multiplier if win else 0
    user["balance"] += win_amount - bet_amount
    
    if win:
        user["wins"] += 1
        result_text = "🎉 ВЫИГРЫШ"
    else:
        user["losses"] += 1
        result_text = "❌ ПРОИГРЫШ"
    
    # Добавляем опыт
    add_exp(user_id)
    
    # Эмодзи для костей
    dice_emojis = {
        1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"
    }
    
    result_message = (
        f"🎲 <b>Vibe Кости</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 Выпало: {dice_emojis[dice1]} + {dice_emojis[dice2]} = <b>{total}</b>\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Выбор: <b>{bet_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
    )
    
    if win:
        result_message += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{multiplier})\n"
    
    result_message += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode="HTML")
# ========== ИГРА ФУТБОЛ ==========
async def football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра футбол"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "⚽ <b>Vibe Футбол</b>\n\n"
            "📝 Формат: <code>футбол [ставка] [ставка]</code>\n\n"
            "🎯 Ставки:\n"
            "• <code>гол</code> - x1.8\n"
            "• <code>мимо</code> - x2.2\n\n"
            "Пример: <code>футбол 500 гол</code>",
            parse_mode="HTML"
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount > user["balance"]:
        await update.message.reply_text("❌ Неверная ставка!")
        return
    
    bet_type = args[1].lower()
    
    # Рандомный эмодзи для футбола
    field = ["⚽", "🥅", "👟", "🔄", "🎯", "❌", "✅", "🔥"]
    result_emoji = random.choice(field)
    
    # Определяем результат (60% шанс на гол)
    is_goal = random.random() < 0.6
    
    win = False
    multiplier = 0
    
    if bet_type == "гол":
        win = is_goal
        multiplier = 1.8 if win else 0
    elif bet_type == "мимо":
        win = not is_goal
        multiplier = 2.2 if win else 0
    else:
        await update.message.reply_text("❌ Неверный тип ставки!")
        return
    
    # Вычисляем результат
    win_amount = bet_amount * multiplier if win else 0
    user["balance"] += win_amount - bet_amount
    
    if win:
        user["wins"] += 1
        result_text = f"{result_emoji} ГОЛ!" if is_goal else f"{result_emoji} МИМО!"
    else:
        user["losses"] += 1
        result_text = f"{result_emoji} МИМО!" if is_goal else f"{result_emoji} ГОЛ!"
    
    # Добавляем опыт
    add_exp(user_id)
    
    result_message = (
        f"⚽ <b>Vibe Футбол</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Игрок бьет... {result_emoji}\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Выбор: <b>{bet_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
    )
    
    if win:
        result_message += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{multiplier})\n"
    
    result_message += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode="HTML")
# ========== ИГРА КРАШ ==========
async def crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра краш"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        await update.message.reply_text(
            "📈 <b>Vibe Краш</b>\n\n"
            "📝 Формат: <code>краш [ставка]</code>\n\n"
            "🎯 Как играть:\n"
            "1. Делаете ставку\n"
            "2. Множитель растет от 1.00\n"
            "3. Нужно вывести до краха\n"
            "4. Если не успели - проигрыш\n\n"
            "Пример: <code>краш 1000</code>",
            parse_mode="HTML"
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount > user["balance"]:
        await update.message.reply_text("❌ Неверная ставка!")
        return
    
    # Генерируем точку краха (1.00 - 10.00)
    crash_point = round(random.uniform(1.01, 5.00), 2)
    
    # Игрок выбирает множитель (симуляция)
    player_multiplier = round(random.uniform(1.10, crash_point - 0.01), 2) if crash_point > 1.10 else 1.00
    
    # Определяем выигрыш
    if player_multiplier < crash_point:
        # Игрок успел вывести
        win_amount = bet_amount * player_multiplier
        user["balance"] += win_amount - bet_amount
        user["wins"] += 1
        result_text = "🎉 ВЫИГРЫШ"
    else:
        # Краш раньше
        user["balance"] -= bet_amount
        user["losses"] += 1
        win_amount = 0
        result_text = "😔 ВЫ ПРОИГРАЛИ"
    
    # Добавляем опыт
    add_exp(user_id)
    
    result_message = (
        f"📈 <b>Vibe Краш</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📈 Точка краха: <b>{crash_point}x</b>\n"
        f"🎯 Ваш множитель: <b>{player_multiplier}x</b>\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
    )
    
    if player_multiplier < crash_point:
        result_message += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b>\n"
    
    result_message += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode="HTML")
# ========== РАБОТА ==========
async def work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Работа для заработка"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # Виды работ
    jobs = {
        "👷 Кладоискатель": {"min": 10000, "max": 50000, "btc_chance": 0.09, "tool": "shovel"},
        "💻 Хакер": {"min": 20000, "max": 100000, "btc_chance": 0.05, "tool": None},
        "🚚 Курьер": {"min": 5000, "max": 20000, "btc_chance": 0.02, "tool": None},
        "🍽 Официант": {"min": 3000, "max": 15000, "btc_chance": 0.01, "tool": None},
        "🏗 Строитель": {"min": 15000, "max": 80000, "btc_chance": 0.03, "tool": "shovel"}
    }
    
    # Выбираем случайную работу
    job_name, job_info = random.choice(list(jobs.items()))
    
    # Проверка инструмента
    if job_info["tool"] == "shovel" and user["shovel"] == 0:
        earnings = random.randint(1000, 5000)  # Без инструмента меньше
        tool_msg = "⛏ Без лопаты заработок меньше"
    else:
        earnings = random.randint(job_info["min"], job_info["max"])
        tool_msg = ""
    
    # Шанс найти BTC
    found_btc = 0
    if random.random() < job_info["btc_chance"]:
        found_btc = round(random.uniform(0.0001, 0.001), 6)
        user["btc"] += found_btc
    
    user["balance"] += earnings
    
    # Добавляем опыт
    if add_exp(user_id):
        await update.message.reply_text(
            f"⭐ Поздравляем! Вы повысили уровень до {user['level']}!"
        )
    
    result_message = (
        f"{job_name}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Заработано: <b>{format_number(earnings)} $</b>\n"
        f"{tool_msg}\n"
    )
    
    if found_btc > 0:
        result_message += f"₿ Найден BTC: <b>{found_btc:.6f}</b>\n"
    
    result_message += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>\n"
        f"₿ BTC: <b>{user['btc']:.6f}</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode="HTML")

# ========== ФЕРМА BTC ==========
async def farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ферма майнинга"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if "buy" in context.args:
        # Покупка видеокарты
        if user["farm_cards"] >= 3:
            await update.message.reply_text("❌ Лимит 3 видеокарты на человека!")
            return
        
        card_price = 50000
        if user["balance"] < card_price:
            await update.message.reply_text(f"❌ Недостаточно средств! Нужно {format_number(card_price)} $")
            return
        
        user["balance"] -= card_price
        user["farm_cards"] += 1
        
        await update.message.reply_text(
            f"🖥 <b>Видеокарта куплена!</b>\n\n"
            f"💸 Стоимость: {format_number(card_price)} $\n"
            f"📊 Всего карт: {user['farm_cards']}/3\n"
            f"💰 Баланс: {format_number(user['balance'])} $",
            parse_mode="HTML"
        )
        return
    
    if "collect" in context.args:
        # Сбор дохода
        if user["farm_cards"] == 0:
            await update.message.reply_text("❌ У вас нет видеокарт!")
            return
        
        # Вычисляем доход
        hours_passed = 1  # Упрощенная версия
        income_per_card = 1000
        total_income = user["farm_cards"] * income_per_card * hours_passed
        
        # Шанс на майнинг BTC
        btc_mined = 0
        btc_chance = 0.01 * user["farm_cards"]
        if random.random() < btc_chance:
            btc_mined = round(random.uniform(0.00001, 0.0001) * user["farm_cards"], 6)
            user["btc"] += btc_mined
        
        user["balance"] += total_income
        
        await update.message.reply_text(
            f"🖥 <b>Доход с фермы собран!</b>\n\n"
            f"📊 Видеокарт: {user['farm_cards']}\n"
            f"💰 Доход: {format_number(total_income)} $\n"
            f"{f'₿ Намайнено BTC: {btc_mined:.6f}' if btc_mined > 0 else ''}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: {format_number(user['balance'])} $\n"
            f"₿ BTC: {user['btc']:.6f}",
            parse_mode="HTML"
        )
        return
    
    # Информация о ферме
    farm_info = (
        f"🖥 <b>Ферма BTC</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Видеокарт: {user['farm_cards']}/3\n"
        f"💰 Доход с карты: 1к $/час\n"
        f"₿ Шанс на BTC: {user['farm_cards']}%/час\n\n"
        f"💸 Стоимость карты: 50к $\n\n"
        f"📝 Команды:\n"
        f"• <code>ферма купить</code> - купить видеокарту\n"
        f"• <code>ферма собрать</code> - собрать доход\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $\n"
        f"₿ BTC: {user['btc']:.6f}"
    )
    
    await update.message.reply_text(farm_info, parse_mode="HTML")
# ========== БАНК И ПЕРЕВОДЫ ==========
async def bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление банком"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    args = context.args
    
    if len(args) < 2:
        # Информация о банке
        daily_interest = user["deposit"] * 0.05  # 5% в день
        bank_info = (
            f"🏦 <b>Vibe Банк</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 На руках: {format_number(user['balance'])} $\n"
            f"🏦 В депозите: {format_number(user['deposit'])} $\n"
            f"📈 Ежедневные проценты: 5%\n"
            f"💸 Завтра получите: {format_number(daily_interest)} $\n\n"
            f"📝 Команды:\n"
            f"• <code>банк положить [сумма]</code>\n"
            f"• <code>банк снять [сумма]</code>\n"
            f"• <code>банк процент</code> - инфо о процентах\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎 Общая сумма: {format_number(user['balance'] + user['deposit'])} $"
        )
        await update.message.reply_text(bank_info, parse_mode="HTML")
        return
    
    action = args[0].lower()
    amount_str = args[1]
    
    if action == "процент":
        await update.message.reply_text(
            "🏦 <b>Проценты в банке</b>\n\n"
            "📈 Начисление: 5% ежедневно\n"
            "⏰ Время: 00:00 по МСК\n"
            "💸 Минимальный депозит: 1к $\n"
            "💰 Максимальный: без лимита",
            parse_mode="HTML"
        )
        return
    
    amount = parse_bet(amount_str, user_id)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Неверная сумма!")
        return
    
    if action == "положить":
        if user["balance"] < amount:
            await update.message.reply_text("❌ Недостаточно средств на балансе!")
            return
        
        user["balance"] -= amount
        user["deposit"] += amount
        
        await update.message.reply_text(
            f"✅ <b>Деньги положены в банк</b>\n\n"
            f"💸 Сумма: {format_number(amount)} $\n"
            f"💰 На руках: {format_number(user['balance'])} $\n"
            f"🏦 В банке: {format_number(user['deposit'])} $\n"
            f"📈 Завтра получите: {format_number(amount * 0.05)} $",
            parse_mode="HTML"
        )
    
    elif action == "снять":
        if user["deposit"] < amount:
            await update.message.reply_text("❌ Недостаточно средств в банке!")
            return
        
        user["deposit"] -= amount
        user["balance"] += amount
        
        await update.message.reply_text(
            f"✅ <b>Деньги сняты с банка</b>\n\n"
            f"💸 Сумма: {format_number(amount)} $\n"
            f"💰 На руках: {format_number(user['balance'])} $\n"
            f"🏦 В банке: {format_number(user['deposit'])} $",
            parse_mode="HTML"
        )

async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перевод денег другому игроку"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "💸 <b>Перевод денег</b>\n\n"
            "📝 Формат: <code>перевести [ID] [сумма]</code>\n\n"
            "Пример: <code>перевести 123456789 1000</code>\n\n"
            "⚠️ Переводы безвозвратны!\n"
            "🔍 ID можно узнать в профиле",
            parse_mode="HTML"
        )
        return
    
    try:
        target_id = int(args[0])
        amount_str = args[1]
    except:
        await update.message.reply_text("❌ Неверный формат команды!")
        return
    
    amount = parse_bet(amount_str, user_id)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Неверная сумма!")
        return
    
    if user["balance"] < amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    if target_id == user_id:
        await update.message.reply_text("❌ Нельзя перевести себе!")
        return
    
    # Переводим деньги
    user["balance"] -= amount
    
    target_user = get_user(target_id)
    target_user["balance"] += amount
    
    # Логируем транзакцию
    transactions.append({
        "from": user_id,
        "to": target_id,
        "amount": amount,
        "time": datetime.now().isoformat()
    })
    
    # Уведомляем получателя
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💰 <b>Вам перевели деньги!</b>\n\n"
                 f"👤 От: {user_id}\n"
                 f"💸 Сумма: {format_number(amount)} $\n"
                 f"💰 Ваш баланс: {format_number(target_user['balance'])} $",
            parse_mode="HTML"
        )
    except:
        pass  # Если пользователь заблокировал бота
    
    await update.message.reply_text(
        f"✅ <b>Перевод выполнен!</b>\n\n"
        f"👤 Кому: {target_id}\n"
        f"💸 Сумма: {format_number(amount)} $\n"
        f"💰 Ваш баланс: {format_number(user['balance'])} $",
        parse_mode="HTML"
    )
# ========== БОНУСЫ ==========
async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный бонус"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    now = datetime.now()
    
    # Проверяем время последнего бонуса
    if user.get("last_bonus"):
        last_bonus = datetime.fromisoformat(user["last_bonus"])
        if (now - last_bonus).total_seconds() < 3600:  # 1 час
            wait_time = 3600 - int((now - last_bonus).total_seconds())
            minutes = wait_time // 60
            seconds = wait_time % 60
            
            await update.message.reply_text(
                f"⏳ <b>Бонус уже получен</b>\n\n"
                f"🕐 Следующий через: {minutes}м {seconds}с\n"
                f"🎁 Уровень {user['level']} бонус: {format_number(50000 + (user['level'] - 1) * 25000)} $",
                parse_mode="HTML"
            )
            return
    
    # Выдаем бонус
    bonus_amount = 50000 + (user["level"] - 1) * 25000
    user["balance"] += bonus_amount
    user["last_bonus"] = now.isoformat()
    
    # Увеличиваем серию
    streak = user.get("bonus_streak", 0) + 1
    user["bonus_streak"] = streak
    
    # Дополнительный бонус за серию
    extra_bonus = 0
    if streak % 7 == 0:  # Каждые 7 дней
        extra_bonus = bonus_amount * 2
        user["balance"] += extra_bonus
    
    await update.message.reply_text(
        f"🎁 <b>Бонус получен!</b>\n\n"
        f"💰 Основной бонус: {format_number(bonus_amount)} $\n"
        f"{f'🎉 Дополнительный за серию: {format_number(extra_bonus)} $' if extra_bonus > 0 else ''}\n"
        f"🔥 Серия: {streak} дней\n"
        f"⭐ Уровень: {user['level']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode="HTML"
    )

# ========== ПРОМОКОДЫ ==========
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активация промокода"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        await update.message.reply_text(
            "🎫 <b>Промокоды</b>\n\n"
            "📝 Формат: <code>промо [код]</code>\n\n"
            "Пример: <code>промо WELCOME</code>\n\n"
            "🎁 Создать промокод: <code>создатьпромо [сумма] [активаций]</code>",
            parse_mode="HTML"
        )
        return
    
    promo_code = args[0].upper()
    
    if promo_code not in promo_codes:
        await update.message.reply_text("❌ Промокод не найден!")
        return
    
    promo_info = promo_codes[promo_code]
    
    # Проверяем лимиты
    if promo_info["activations"] >= promo_info["max_activations"]:
        await update.message.reply_text("❌ Лимит активаций исчерпан!")
        return
    
    if user_id in promo_info["used_by"]:
        await update.message.reply_text("❌ Вы уже активировали этот промокод!")
        return
    
    # Активируем промокод
    promo_info["activations"] += 1
    promo_info["used_by"].append(user_id)
    
    user["balance"] += promo_info["amount"]
    user["promos_used"].append(promo_code)
    
    await update.message.reply_text(
        f"🎉 <b>Промокод активирован!</b>\n\n"
        f"🎫 Код: {promo_code}\n"
        f"💰 Начислено: {format_number(promo_info['amount'])} $\n"
        f"📊 Активаций: {promo_info['activations']}/{promo_info['max_activations']}\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode="HTML"
    )

async def create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода"""
    args = context.args
    user_id = update.effective_user.id
    
    if len(args) < 2:
        await update.message.reply_text(
            "🎫 <b>Создание промокода</b>\n\n"
            "📝 Формат: <code>создатьпромо [сумма] [активаций]</code>\n\n"
            "Пример: <code>создатьпромо 1000 5</code>\n\n"
            "⚠️ Создавать промокоды могут все!",
            parse_mode="HTML"
        )
        return
    
    try:
        amount = float(args[0])
        max_activations = int(args[1])
    except:
        await update.message.reply_text("❌ Неверный формат!")
        return
    
    if amount <= 0 or max_activations <= 0:
        await update.message.reply_text("❌ Сумма и активации должны быть больше 0!")
        return
    
    # Генерируем промокод
    import string
    promo_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    # Сохраняем промокод
    promo_codes[promo_code] = {
        "amount": amount,
        "max_activations": max_activations,
        "activations": 0,
        "used_by": [],
        "created_by": user_id,
        "created_at": datetime.now().isoformat()
    }
    
    await update.message.reply_text(
        f"🎫 <b>Промокод создан!</b>\n\n"
        f"🔑 Код: <code>{promo_code}</code>\n"
        f"💰 Начисление: {format_number(amount)} $\n"
        f"📊 Активаций: {max_activations}\n\n"
        f"🔗 Ссылка для активации:\n"
        f"<code>t.me/{(await context.bot.getMe()).username}?start=promo_{promo_code}</code>\n\n"
        f"📝 Для активации:\n"
        f"<code>промо {promo_code}</code>",
        parse_mode="HTML"
    )
# ========== АДМИН ПАНЕЛЬ ==========
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещен!")
        return
    
    admin_menu = (
        "👑 <b>Админ панель Vibe Bet</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 Статистика:\n"
        f"• Игроков: {len(users_db)}\n"
        f"• Промокодов: {len(promo_codes)}\n"
        f"• Транзакций: {len(transactions)}\n\n"
        "🔧 Команды:\n"
        "• <code>бан [ID] [причина]</code>\n"
        "• <code>разбан [ID]</code>\n"
        "• <code>выдать [ID] [сумма]</code>\n"
        "• <code>забрать [ID] [сумма]</code>\n"
        "• <code>выдатьбит [ID] [количество]</code>\n"
        "• <code>уровень [ID] [уровень]</code>\n"
        "• <code>опыт [ID] [опыт]</code>\n"
        "• <code>игрок [ID]</code> - просмотр\n"
        "• <code>транзакции</code> - логи\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(admin_menu, parse_mode="HTML")

async def admin_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача денег (админ)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 Формат: /hhh [ID] [сумма]")
        return
    
    try:
        target_id = int(args[0])
        amount = float(args[1])
    except:
        await update.message.reply_text("❌ Неверный формат!")
        return
    
    target_user = get_user(target_id)
    target_user["balance"] += amount
    
    await update.message.reply_text(
        f"✅ <b>Деньги выданы!</b>\n\n"
        f"👤 Игрок: {target_id}\n"
        f"💰 Сумма: {format_number(amount)} $\n"
        f"💸 Новый баланс: {format_number(target_user['balance'])} $",
        parse_mode="HTML"
    )

async def admin_give_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача BTC (админ)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 Формат: /hhhh [ID] [количество]")
        return
    
    try:
        target_id = int(args[0])
        amount = float(args[1])
    except:
        await update.message.reply_text("❌ Неверный формат!")
        return
    
    target_user = get_user(target_id)
    target_user["btc"] += amount
    
    await update.message.reply_text(
        f"✅ <b>BTC выдан!</b>\n\n"
        f"👤 Игрок: {target_id}\n"
        f"₿ Количество: {amount:.6f}\n"
        f"💰 Стоимость: {format_number(amount * btc_price)} $\n"
        f"💸 Всего BTC: {target_user['btc']:.6f}",
        parse_mode="HTML"
    )

async def admin_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача уровня (админ)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 Формат: /lvl [ID] [уровень]")
        return
    
    try:
        target_id = int(args[0])
        level = int(args[1])
    except:
        await update.message.reply_text("❌ Неверный формат!")
        return
    
    target_user = get_user(target_id)
    target_user["level"] = max(1, level)
    target_user["exp"] = 0
    target_user["exp_needed"] = 4 + (level - 1) * 4
    
    await update.message.reply_text(
        f"✅ <b>Уровень изменен!</b>\n\n"
        f"👤 Игрок: {target_id}\n"
        f"⭐ Новый уровень: {level}\n"
        f"📊 EXP: 0/{target_user['exp_needed']}",
        parse_mode="HTML"
    )

async def admin_exp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача опыта (админ)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 Формат: /exp [ID] [опыт]")
        return
    
    try:
        target_id = int(args[0])
        exp = int(args[1])
    except:
        await update.message.reply_text("❌ Неверный формат!")
        return
    
    target_user = get_user(target_id)
    target_user["exp"] = exp
    
    await update.message.reply_text(
        f"✅ <b>Опыт изменен!</b>\n\n"
        f"👤 Игрок: {target_id}\n"
        f"📊 EXP: {exp}/{target_user['exp_needed']}",
        parse_mode="HTML"
    )
    # ========== НЕДОСТАЮЩИЕ ФУНКЦИИ ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка по командам"""
    help_text = (
        "🎮 <b>Vibe Bet - Центр помощи</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "• рул [сумма] [число/цвет] (кр, чер, зел)\n"
        "• кости [сумма] [ставка] (равно, больше, меньше)\n"
        "• футбол [сумма] [ставка] (гол, мимо)\n"
        "• алмазы [сумма] [бомбы] (1 или 2)\n"
        "• мины [сумма]\n\n"
        "⛏️ <b>ЗАРАБОТОК:</b>\n"
        "• работа — Копать клад (нужна лопата)\n"
        "• ферма — Майнинг биткоина\n"
        "• бонус — Ежечасная награда\n\n"
        "⚙️ <b>ПРОЧЕЕ:</b>\n"
        "• профиль, топ\n"
        "• перевести [ID] [Сумма]\n"
        "• промо [код] — Активация промо\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📞 Поддержка: @d066q"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ игроков"""
    if not users_db:
        await update.message.reply_text("📊 Пока нет игроков в рейтинге!")
        return
    
    # Сортируем по балансу
    sorted_users = sorted(users_db.values(), key=lambda x: x["balance"], reverse=True)[:10]
    
    top_text = "🏆 <b>Топ игроков по балансу</b>\n━━━━━━━━━━━━━━━━━━\n"
    
    for i, user in enumerate(sorted_users, 1):
        top_text += f"{i}. ID {user['id']}: {format_number(user['balance'])} $\n"
    
    top_text += "━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(top_text, parse_mode="HTML")

async def diamonds_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра Алмазы"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "💎 <b>Vibe Алмазы</b>\n\n"
            "📝 Формат: <code>алмазы [ставка] [бомбы]</code>\n\n"
            "🎯 Правила:\n"
            "• 1-2 бомбы на поле\n"
            "• Выбирайте клетки без бомб\n"
            "• За алмаз x2 ставки\n"
            "• За бомбу - проигрыш\n\n"
            "Пример: <code>алмазы 1000 1</code>",
            parse_mode="HTML"
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount > user["balance"]:
        await update.message.reply_text("❌ Неверная ставка!")
        return
    
    try:
        bombs = int(args[1])
        if bombs not in [1, 2]:
            await update.message.reply_text("❌ Бомб может быть 1 или 2!")
            return
    except:
        await update.message.reply_text("❌ Неверное количество бомб!")
        return
    
    # Простая реализация
    user["balance"] -= bet_amount
    if random.random() > 0.3:  # 70% шанс выигрыша
        win_amount = bet_amount * 2
        user["balance"] += win_amount
        user["wins"] += 1
        result = f"💎 Найден алмаз! Выигрыш: {format_number(win_amount)} $"
    else:
        user["losses"] += 1
        result = "💣 Попали на бомбу! Проигрыш"
    
    add_exp(user_id)
    
    await update.message.reply_text(
        f"💎 <b>Vibe Алмазы</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: {format_number(bet_amount)} $\n"
        f"💣 Бомб: {bombs}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode="HTML"
    )

async def mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра Мины"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        await update.message.reply_text(
            "💣 <b>Vibe Мины</b>\n\n"
            "📝 Формат: <code>мины [ставка]</code>\n\n"
            "🎯 Правила:\n"
            "• Поле 5x5\n"
            "• 5 мин на поле\n"
            "• Открывайте клетки\n"
            "• За каждую клетку x1.5\n"
            "• На мине - проигрыш\n\n"
            "Пример: <code>мины 1000</code>",
            parse_mode="HTML"
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount > user["balance"]:
        await update.message.reply_text("❌ Неверная ставка!")
        return
    
    # Простая реализация
    user["balance"] -= bet_amount
    cells_opened = random.randint(1, 5)
    
    if cells_opened < 5:  # Не попали на мину
        win_amount = bet_amount * (1 + cells_opened * 0.5)
        user["balance"] += win_amount
        user["wins"] += 1
        result = f"✅ Открыто {cells_opened} клеток! Выигрыш: {format_number(win_amount)} $"
    else:
        user["losses"] += 1
        result = "💣 Попали на мину! Проигрыш"
    
    add_exp(user_id)
    
    await update.message.reply_text(
        f"💣 <b>Vibe Мины</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: {format_number(bet_amount)} $\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode="HTML"
    )

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Магазин"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    shop_text = (
        "🛒 <b>Vibe Магазин</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⛏️ Лопата: 5,000 $\n"
        "• Увеличивает доход с работ\n\n"
        "🔍 Металлоискатель: 20,000 $\n"
        "• Увеличивает шанс найти BTC\n\n"
        "🖥 Видеокарта: 50,000 $\n"
        "• Для фермы (макс. 3)\n\n"
        "📝 Покупка:\n"
        "• <code>купить лопата</code>\n"
        "• <code>купить детектор</code>\n"
        "• <code>ферма купить</code>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $"
    )
    
    await update.message.reply_text(shop_text, parse_mode="HTML")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_sub":
        if check_subscription(query.from_user.id):
            await query.edit_message_text(
                "✅ Отлично! Вы подписаны!\n\n"
                "🎮 Теперь можете использовать все функции бота!\n"
                "📝 Напишите <code>помощь</code> для списка команд.",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                "❌ Вы не подписаны на канал или чат!\n\n"
                "Пожалуйста, подпишитесь и нажмите проверку снова.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Канал", url="https://t.me/nvibee_bet")],
                    [InlineKeyboardButton("💬 Чат", url="https://t.me/chatvibee_bet")],
                    [InlineKeyboardButton("✅ Проверить", callback_data="check_sub")]
                ])
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    text = update.message.text.lower()
    
    if text in ["привет", "hi", "hello"]:
        await update.message.reply_text("👋 Привет! Напиши /start для начала!")
    elif "купить" in text:
        await shop(update, context)
    else:
        await update.message.reply_text(
            "🤖 Я не понимаю эту команду.\n"
            "📝 Напиши <code>помощь</code> для списка команд.",
            parse_mode="HTML"
    )
# ========== ЗАПУСК БОТА ==========
def main() -> None:
    """Запуск бота"""
    # Создаем приложение с увеличенными таймаутами
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )
    
    app = Application.builder().token(TOKEN).request(request).build()
    
    # Регистрируем обработчики команд
    # Основные команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("top", top_players))
    
    # Игры
    app.add_handler(CommandHandler("roulette", roulette))
    app.add_handler(CommandHandler("dice", dice_game))
    app.add_handler(CommandHandler("football", football))
    app.add_handler(CommandHandler("crash", crash))
    app.add_handler(CommandHandler("diamonds", diamonds_game))
    app.add_handler(CommandHandler("mines", mines_game))
    
    # Экономика
    app.add_handler(CommandHandler("work", work))
    app.add_handler(CommandHandler("farm", farm))
    app.add_handler(CommandHandler("bonus", bonus))
    app.add_handler(CommandHandler("bank", bank))
    app.add_handler(CommandHandler("transfer", transfer))
    app.add_handler(CommandHandler("shop", shop))
    
    # Промокоды
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("createpromo", create_promo))
    
    # Админ команды
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("hhh", admin_give))
    app.add_handler(CommandHandler("hhhh", admin_give_btc))
    app.add_handler(CommandHandler("lvl", admin_level))
    app.add_handler(CommandHandler("exp", admin_exp))
    
    # Обработка callback-запросов
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработка текстовых сообщений (здесь можно оставить русский текст)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 Бот запускается...")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"📢 Канал: {CHANNEL_USERNAME}")
    print(f"💬 Чат: {CHAT_USERNAME}")
    
    # Запускаем бота
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
