import os
import re
import json
import random
import asyncio
import logging
import datetime
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from telegram.constants import ParseMode

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [1997428703]
CHANNEL_USERNAME = "@nvibee_bet"
CHAT_USERNAME = "@chatvibee_bet"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
users_db = {}
promo_codes = {}
transactions = []
btc_price = 68000.0

def format_number(num):
    if num >= 1_000_000_000_000: return f"{num/1_000_000_000_000:.2f}кккк"
    elif num >= 1_000_000_000: return f"{num/1_000_000_000:.2f}ккк"
    elif num >= 1_000_000: return f"{num/1_000_000:.2f}кк"
    elif num >= 1_000: return f"{num/1_000:.2f}к"
    else: return f"{num:.2f}"

def parse_bet(text, user_id):
    text = str(text).lower().strip()
    
    if text in ["все", "всё"]:
        user = users_db.get(user_id, {})
        return user.get('balance', 0)
    
    # Убираем все нецифровые символы кроме k, к, м, .
    text = re.sub(r'[^0-9kкм.]', '', text)
    
    multiplier = 1
    if 'кккк' in text or 'kkkk' in text:
        multiplier = 1_000_000_000_000
        text = text.replace('кккк', '').replace('kkkk', '')
    elif 'ккк' in text or 'kkk' in text:
        multiplier = 1_000_000_000
        text = text.replace('ккк', '').replace('kkk', '')
    elif 'кк' in text or 'kk' in text:
        multiplier = 1_000_000
        text = text.replace('кк', '').replace('kk', '')
    elif 'к' in text or 'k' in text:
        multiplier = 1_000
        text = text.replace('к', '').replace('k', '')
    
    try:
        if '.' in text:
            amount = float(text) * multiplier
        else:
            amount = int(float(text)) * multiplier
        return amount if amount > 0 else None
    except:
        return None

def get_user(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            'id': user_id,
            'balance': 10000.0,
            'deposit': 0.0,
            'btc': 0.0,
            'level': 1,
            'exp': 0,
            'exp_needed': 4,
            'wins': 0,
            'losses': 0,
            # Убираем лишнее из профиля
            'shovel': 0,
            'detector': 0,
            'farm_cards': 0,
            'last_bonus': None,
            'last_work': None,
            'promos_used': [],
            'created': datetime.datetime.now().isoformat()
        }
    return users_db[user_id]

def add_exp(user_id):
    if random.random() > 0.5:
        return False
    user = get_user(user_id)
    user['exp'] += 1
    if user['exp'] >= user['exp_needed']:
        user['level'] += 1
        user['exp'] = 0
        user['exp_needed'] += 4
        return True
    return False
    
# ← Функция add_exp закончилась, новая функция должна начинаться с того же уровня

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Создаем клавиатуру для проверки подписки
    keyboard = [
        [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
        [InlineKeyboardButton("💬 Вступить в чат", url=f"https://t.me/{CHAT_USERNAME[1:]}")],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")]
    ]
    
    await update.message.reply_text(
        f"👋 Добро пожаловать в Vibe Bet, {user.first_name}!\n\n"
        f"🎲 Игры: 🎰 Рулетка, 📈 Краш, 🎲 Кости, ⚽ Футбол\n"
        f"💎 Алмазы, 💣 Мины\n"
        f"⛏️ Заработок: 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус\n\n"
        f"👇 Для начала подпишись на канал и чат:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
        )
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_sub":
        # В реальном боте нужно проверять подписку через getChatMember
        # Здесь заглушка для примера
        await query.edit_message_text(
            "✅ Отлично! Вы подписаны!\n\n"
            "🎮 Теперь можете использовать все функции бота!\n"
            "📝 Напишите /help для списка команд.",
            parse_mode=ParseMode.HTML
        )
    
    elif query.data.startswith("farm_"):
        action = query.data.split("_")[1]
        user_id = query.from_user.id
        user = get_user(user_id)
        
        if action == "buy":
            if user['farm_cards'] >= 3:
                await query.answer("❌ Лимит 3 видеокарты!", show_alert=True)
                return
            
            price = 50000
            if user['balance'] < price:
                await query.answer(f"❌ Недостаточно средств! Нужно {format_number(price)} $", show_alert=True)
                return
            
            user['balance'] -= price
            user['farm_cards'] += 1
            
            keyboard = [
                [InlineKeyboardButton("🛒 Купить видеокарту (50к $)", callback_data="farm_buy")],
                [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")]
            ]
            
            await query.edit_message_text(
                f"🖥 <b>Ферма BTC</b>\n\n"
                f"📊 Видеокарт: {user['farm_cards']}/3\n"
                f"💰 Доход с карты: 1к $/час\n"
                f"₿ Шанс на BTC: {user['farm_cards']}%/час\n\n"
                f"💰 Баланс: {format_number(user['balance'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
        elif action == "collect":
            if user['farm_cards'] == 0:
                await query.answer("❌ У вас нет видеокарт!", show_alert=True)
                return
            
            # Расчет дохода (упрощенно)
            income = user['farm_cards'] * 1000
            user['balance'] += income
            
            keyboard = [
                [InlineKeyboardButton("🛒 Купить видеокарту (50к $)", callback_data="farm_buy")],
                [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")]
            ]
            
            await query.edit_message_text(
                f"🖥 <b>Ферма BTC</b>\n\n"
                f"📊 Видеокарт: {user['farm_cards']}/3\n"
                f"💰 Собрано: {format_number(income)} $\n"
                f"₿ Всего BTC: {user['btc']:.6f}\n\n"
                f"💰 Баланс: {format_number(user['balance'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            # ========== КОМАНДЫ ПРОФИЛЯ ==========
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Профиль игрока - только основные данные"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    profile_text = (
        f"👤 <b>Профиль {update.effective_user.first_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"📊 EXP: <b>{user['exp']}/{user['exp_needed']}</b>\n"
        f"🏆 Побед/Поражений: <b>{user['wins']}/{user['losses']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(profile_text, parse_mode=ParseMode.HTML)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Баланс игрока"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    balance_text = (
        f"💰 <b>Ваш баланс</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 На руках: <b>{format_number(user['balance'])} $</b>\n"
        f"🏦 В депозите: <b>{format_number(user['deposit'])} $</b>\n"
        f"₿ BTC: <b>{user['btc']:.6f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Общий капитал: <b>{format_number(user['balance'] + user['deposit'] + user['btc'] * btc_price)} $</b>"
    )
    
    await update.message.reply_text(balance_text, parse_mode=ParseMode.HTML)
    
#помощь

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎮 <b>Vibe Bet - Центр помощи</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "• /roulette [сумма] [ставка]\n"
        "• /dice [сумма] [ставка]\n"
        "• /football [сумма] [ставка]\n"
        "• /diamonds [сумма] [бомбы]\n"
        "• /mines [сумма]\n"
        "• /crash [сумма]\n\n"
        "⛏️ <b>ЗАРАБОТОК:</b>\n"
        "• /work — Работа\n"
        "• /farm — Ферма BTC\n"
        "• /bonus — Бонус\n\n"
        "⚙️ <b>ПРОЧЕЕ:</b>\n"
        "• /profile — Профиль\n"
        "• /balance — Баланс\n"
        "• /bank — Банк\n"
        "• /transfer — Перевод\n"
        "• /promo — Промокод\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💎 Русские команды тоже работают!"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        text = (
            "🎰 <b>Vibe Рулетка</b>\n\n"
            "📝 Формат: рул [сумма] [ставка]\n\n"
            "🎯 Ставки:\n"
            "• Число 0-36\n"
            "• кр — красный (x2)\n"
            "• чер — черный (x2)\n"
            "• чет — четное (x2)\n"
            "• нечет — нечетное (x2)\n"
            "• 1-12, 13-24, 25-36 (x3)\n\n"
            "💎 Примеры:\n"
            "• рул 1000 кр\n"
            "• рул 5к 17\n"
            "• рул все чер"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount <= 0:
        await update.message.reply_text("❌ Неверная сумма ставки!")
        return
    
    if user['balance'] < bet_amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    bet_type = args[1].lower()
    win_number = random.randint(0, 36)
    
    # Определяем выигрыш
    reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    is_red = win_number in reds
    is_black = win_number not in reds and win_number != 0
    is_even = win_number % 2 == 0 and win_number != 0
    is_odd = win_number % 2 == 1 and win_number != 0
    
    multiplier = 0
    win = False
    
    # Проверяем ставку
    if bet_type.isdigit() and 0 <= int(bet_type) <= 36:
        if int(bet_type) == win_number:
            multiplier = 36
            win = True
    elif bet_type == "кр":
        if is_red:
            multiplier = 2
            win = True
    elif bet_type == "чер":
        if is_black:
            multiplier = 2
            win = True
    elif bet_type == "чет":
        if is_even:
            multiplier = 2
            win = True
    elif bet_type == "нечет":
        if is_odd:
            multiplier = 2
            win = True
    elif bet_type in ["1-12", "13-24", "25-36"]:
        start, end = map(int, bet_type.split("-"))
        if start <= win_number <= end:
            multiplier = 3
            win = True
    else:
        await update.message.reply_text("❌ Неверный тип ставки!")
        return
    
    # Обрабатываем результат
    user['balance'] -= bet_amount
    
    if win:
        win_amount = bet_amount * multiplier
        user['balance'] += win_amount
        user['wins'] += 1
        result_emoji = "🎉"
        result_text = "ВЫИГРЫШ"
    else:
        win_amount = 0
        user['losses'] += 1
        result_emoji = "❌"
        result_text = "ПРОИГРЫШ"
    
    add_exp(user_id)
    
    # Формируем сообщение
    color = "красный" if is_red else "черный" if is_black else "зеленый"
    parity = "четное" if is_even else "нечетное" if is_odd else "ноль"
    
    text = (
        f"🎰 <b>Vibe Рулетка</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"{result_emoji} <b>{result_text}</b>\n"
        f"📈 Выпало: <b>{win_number}</b> ({color}, {parity})\n"
    )
    
    if win:
        text += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{multiplier})\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        text = (
            "🎲 <b>Vibe Кости</b>\n\n"
            "📝 Формат: кости [сумма] [ставка]\n\n"
            "🎯 Ставки:\n"
            "• равно (=7) — x5.7\n"
            "• больше (>7) — x2.2\n"
            "• меньше (<7) — x2.2\n\n"
            "💎 Примеры:\n"
            "• кости 1000 больше\n"
            "• кости 5к равно\n"
            "• кости все меньше"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount <= 0:
        await update.message.reply_text("❌ Неверная сумма ставки!")
        return
    
    if user['balance'] < bet_amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    bet_type = args[1].lower()
    if bet_type not in ["равно", "больше", "меньше"]:
        await update.message.reply_text("❌ Неверный тип ставки!")
        return
    
    # Отправляем анимацию кубика
    msg = await update.message.reply_dice(emoji="🎲")
    dice_value = msg.dice.value
    
    # Ждем 2 секунды для анимации
    await asyncio.sleep(2)
    
    # Определяем результат
    total = dice_value
    win = False
    multiplier = 0
    
    if bet_type == "равно":
        if total == 7:
            multiplier = 5.7
            win = True
    elif bet_type == "больше":
        if total > 7:
            multiplier = 2.2
            win = True
    elif bet_type == "меньше":
        if total < 7:
            multiplier = 2.2
            win = True
    
    # Обрабатываем результат
    user['balance'] -= bet_amount
    
    if win:
        win_amount = bet_amount * multiplier
        user['balance'] += win_amount
        user['wins'] += 1
        result_emoji = "🎉"
        result_text = "ВЫИГРЫШ"
    else:
        win_amount = 0
        user['losses'] += 1
        result_emoji = "❌"
        result_text = "ПРОИГРЫШ"
    
    add_exp(user_id)
    
    # Формируем результат
    text = (
        f"🎲 <b>Vibe Кости</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 Выпало: <b>{total}</b>\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Выбор: <b>{bet_type}</b>\n"
        f"{result_emoji} <b>{result_text}</b>\n"
    )
    
    if win:
        text += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{multiplier})\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    async def football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        text = (
            "⚽ <b>Vibe Футбол</b>\n\n"
            "📝 Формат: футбол [сумма] [ставка]\n\n"
            "🎯 Ставки:\n"
            "• гол — x1.8\n"
            "• мимо — x2.2\n\n"
            "💎 Примеры:\n"
            "• футбол 1000 гол\n"
            "• футбол 5к мимо\n"
            "• футбол все гол"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount <= 0:
        await update.message.reply_text("❌ Неверная сумма ставки!")
        return
    
    if user['balance'] < bet_amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    bet_type = args[1].lower()
    if bet_type not in ["гол", "мимо"]:
        await update.message.reply_text("❌ Неверный тип ставки!")
        return
    
    # Отправляем анимацию футбола
    msg = await update.message.reply_dice(emoji="⚽")
    dice_value = msg.dice.value
    
    # Ждем 2 секунды для анимации
    await asyncio.sleep(2)
    
    # Определяем результат (1-3 гол, 4-6 мимо)
    is_goal = dice_value <= 3
    win = False
    multiplier = 0
    
    if bet_type == "гол" and is_goal:
        multiplier = 1.8
        win = True
    elif bet_type == "мимо" and not is_goal:
        multiplier = 2.2
        win = True
    
    # Обрабатываем результат
    user['balance'] -= bet_amount
    
    if win:
        win_amount = bet_amount * multiplier
        user['balance'] += win_amount
        user['wins'] += 1
        result_emoji = "🥅"
        result_text = "ГОООЛ!"
    else:
        win_amount = 0
        user['losses'] += 1
        result_emoji = "❌"
        result_text = "МИМО!"
    
    add_exp(user_id)
    
    # Формируем результат
    text = (
        f"⚽ <b>Vibe Футбол</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Выбор: <b>{bet_type}</b>\n"
        f"{result_emoji} <b>{result_text}</b>\n"
    )
    
    if win:
        text += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{multiplier})\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    async def crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        text = (
            "📈 <b>Vibe Краш</b>\n\n"
            "📝 Формат: краш [сумма]\n\n"
            "🎯 Правила:\n"
            "1. Делаете ставку\n"
            "2. Множитель растет от 1.00x\n"
            "3. Нужно успеть вывести\n"
            "4. Если не успели — проигрыш\n\n"
            "💎 Примеры:\n"
            "• краш 1000\n"
            "• краш 5к\n"
            "• краш все"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount <= 0:
        await update.message.reply_text("❌ Неверная сумма ставки!")
        return
    
    if user['balance'] < bet_amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    # Генерируем точку краха (1.01 - 5.00)
    crash_point = round(random.uniform(1.01, 5.00), 2)
    
    # Игрок выбирает множитель (симуляция)
    # В реальном краше игрок сам выбирает когда выводить
    player_multiplier = round(random.uniform(1.10, crash_point - 0.01), 2) if crash_point > 1.10 else 1.00
    
    # Определяем выигрыш
    win = player_multiplier < crash_point
    
    # Обрабатываем результат
    user['balance'] -= bet_amount
    
    if win:
        win_amount = round(bet_amount * player_multiplier, 2)
        user['balance'] += win_amount
        user['wins'] += 1
        result_emoji = "🎉"
        result_text = "ВЫИГРЫШ"
    else:
        win_amount = 0
        user['losses'] += 1
        result_emoji = "😔"
        result_text = "ВЫ ПРОИГРАЛИ"
    
    add_exp(user_id)
    
    # Формируем сообщение
    text = (
        f"📈 <b>Vibe Краш</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
    )
    
    if not win:
        text += f"📈 Точка краха: <b>{crash_point}x</b>\n"
        text += f"🎯 Ваш множитель: <b>{player_multiplier}x</b>\n"
    
    text += f"{result_emoji} <b>{result_text}</b>\n"
    
    if win:
        text += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{player_multiplier})\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    async def farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🛒 Купить видеокарту (50к $)", callback_data="farm_buy")],
        [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")]
    ]
    
    text = (
        f"🖥 <b>Ферма BTC</b>\n\n"
        f"📊 Видеокарт: {user['farm_cards']}/3\n"
        f"💰 Доход с карты: 1к $/час\n"
        f"₿ Шанс на BTC: {user['farm_cards']}%/час\n\n"
        f"💸 Стоимость карты: 50к $\n\n"
        f"💰 Баланс: {format_number(user['balance'])} $"
    )
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    async def work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # Выбираем случайную работу
    jobs = [
        {"name": "👷 Кладоискатель", "min": 10000, "max": 50000, "btc_chance": 0.09, "stages": 3},
        {"name": "💻 Хакер", "min": 20000, "max": 100000, "btc_chance": 0.05, "stages": 4},
        {"name": "🚚 Курьер", "min": 5000, "max": 20000, "btc_chance": 0.02, "stages": 2},
        {"name": "🍽 Официант", "min": 3000, "max": 15000, "btc_chance": 0.01, "stages": 3},
        {"name": "🏗 Строитель", "min": 15000, "max": 80000, "btc_chance": 0.03, "stages": 3}
    ]
    
    job = random.choice(jobs)
    
    # Симуляция этапов работы
    stages_completed = random.randint(1, job["stages"])
    base_earnings = random.randint(job["min"], job["max"])
    earnings = base_earnings * stages_completed // job["stages"]
    
    # Шанс найти BTC
    found_btc = 0
    if random.random() < job["btc_chance"]:
        found_btc = round(random.uniform(0.0001, 0.001), 6)
        user['btc'] += found_btc
    
    user['balance'] += earnings
    add_exp(user_id)
    
    text = (
        f"{job['name']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Этапы: {stages_completed}/{job['stages']}\n"
        f"💰 Заработано: <b>{format_number(earnings)} $</b>\n"
    )
    
    if found_btc > 0:
        text += f"₿ Найден BTC: <b>{found_btc:.6f}</b>\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    async def admin_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещен!")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 Формат: /hhh [ID] [сумма]\nПример: /hhh 123456789 100к")
        return
    
    try:
        target_id = int(args[0])
        amount_str = args[1]
        
        # Парсим сумму
        amount = parse_bet(amount_str, user_id)
        if not amount or amount <= 0:
            await update.message.reply_text("❌ Неверная сумма!")
            return
        
        target_user = get_user(target_id)
        target_user['balance'] += amount
        
        await update.message.reply_text(
            f"✅ <b>Деньги выданы!</b>\n\n"
            f"👤 Игрок: {target_id}\n"
            f"💰 Сумма: {format_number(amount)} $\n"
            f"💸 Новый баланс: {format_number(target_user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def admin_give_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше 0!")
            return
        
        target_user = get_user(target_id)
        target_user['btc'] += amount
        
        await update.message.reply_text(
            f"✅ <b>BTC выдан!</b>\n\n"
            f"👤 Игрок: {target_id}\n"
            f"₿ Количество: {amount:.6f}\n"
            f"💰 Стоимость: {format_number(amount * btc_price)} $\n"
            f"💸 Всего BTC: {target_user['btc']:.6f}",
            parse_mode=ParseMode.HTML
        )
    except:
        await update.message.reply_text("❌ Неверный формат!")
        
        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text# ========== ОБРАБОТЧИК РУССКИХ КОМАНД БЕЗ / ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений (команды без /)"""
    text = update.message.text.lower().strip()
    user_id = update.effective_user.id
    
    print(f"📨 Получен текст: '{text}' от {user_id}")
    
    # Разделяем команду и аргументы
    parts = text.split()
    if not parts:
        return
    
    command = parts[0]
    args = parts[1:] if len(parts) > 1 else []
    
    # Передаем аргументы в контекст
    context.args = args
    
    # Основные команды без аргументов
    if command == "профиль":
        await profile(update, context)
    elif command == "баланс":
        await balance(update, context)
    elif command == "уровень":
        await level_command(update, context)
    elif command == "топ":
        await top_players(update, context)
    elif command == "помощь":
        await help_command(update, context)
    elif command in ["старт", "start"]:
        await start(update, context)
    
    # Игры (с аргументами)
    elif command in ["рул", "рулетка"]:
        await roulette(update, context)
    elif command == "кости":
        await dice_game(update, context)
    elif command == "футбол":
        await football(update, context)
    elif command == "краш":
        await crash(update, context)
    elif command == "алмазы":
        await diamonds_game(update, context)
    elif command == "мины":
        await mines_game(update, context)
    
    # Экономика
    elif command == "работа":
        await work(update, context)
    elif command == "ферма":
        await farm(update, context)
    elif command == "бонус":
        await bonus(update, context)
    elif command == "банк":
        await bank_command(update, context)
    elif command == "перевести":
        await transfer(update, context)
    elif command == "магазин":
        await shop(update, context)
    
    # Промокоды
    elif command == "промо":
        await promo(update, context)
    elif command == "создатьпромо":
        await create_promo(update, context)
    
    # Админ команды
    elif command in ["выдать", "дать"] and user_id in ADMIN_IDS:
        await admin_give(update, context)
    elif command in ["забрать", "забрал"] and user_id in ADMIN_IDS:
        await admin_take(update, context)
    elif command in ["выдатьбит", "датьбит"] and user_id in ADMIN_IDS:
        await admin_give_btc(update, context)
    elif command in ["уровеньадмин", "уровеньадм"] and user_id in ADMIN_IDS:
        await admin_level(update, context)
    elif command in ["опытадмин", "опытадм"] and user_id in ADMIN_IDS:
        await admin_exp(update, context)
    elif command in ["админ", "admin"] and user_id in ADMIN_IDS:
        await admin(update, context)
    
    # Если команда не распознана
    else:
        await update.message.reply_text(
            "🤖 Я не понимаю эту команду.\n"
            "📝 Напиши /help для списка команд."
        )
        # ========== ПОЛНЫЕ РЕАЛИЗАЦИИ ФУНКЦИЙ ==========
async def diamonds_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "💎 <b>Vibe Алмазы</b>\n\n"
            "📝 Формат: алмазы [ставка] [бомбы]\n\n"
            "🎯 Правила:\n"
            "• Поле 3x3\n"
            "• 1-2 бомбы на поле\n"
            "• Выбирайте клетки без бомб\n"
            "• За алмаз +100% к ставке\n"
            "• За бомбу - проигрыш\n\n"
            "💎 Примеры:\n"
            "• алмазы 1000 1\n"
            "• алмазы 5к 2\n"
            "• алмазы все 1",
            parse_mode=ParseMode.HTML
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount <= 0:
        await update.message.reply_text("❌ Неверная сумма ставки!")
        return
    
    if user['balance'] < bet_amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    try:
        bombs = int(args[1])
        if bombs not in [1, 2]:
            await update.message.reply_text("❌ Бомб может быть только 1 или 2!")
            return
    except:
        await update.message.reply_text("❌ Неверное количество бомб!")
        return
    
    # Снимаем ставку сразу
    user['balance'] -= bet_amount
    
    # Создаем клавиатуру поля 3x3
    keyboard = []
    for i in range(0, 9, 3):
        row = []
        for j in range(3):
            btn_num = i + j
            row.append(InlineKeyboardButton("💠", callback_data=f"diamond_{btn_num}_{bombs}_{bet_amount}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("💰 Забрать", callback_data=f"diamond_cashout_{bet_amount}")])
    
    await update.message.reply_text(
        f"💎 <b>Vibe Алмазы</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"💣 Бомб: <b>{bombs}</b>\n"
        f"📈 Множитель: <b>1.0x</b>\n"
        f"💰 Текущий выигрыш: <b>{format_number(bet_amount)} $</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Выбери первую клетку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        await update.message.reply_text(
            "💣 <b>Vibe Мины</b>\n\n"
            "📝 Формат: мины [ставка]\n\n"
            "🎯 Правила:\n"
            "• Поле 5x5\n"
            "• 5 мин на поле\n"
            "• Выбирайте безопасные клетки\n"
            "• Множитель растет с каждой клеткой\n"
            "• На мине - проигрыш\n\n"
            "💎 Примеры:\n"
            "• мины 1000\n"
            "• мины 5к\n"
            "• мины все",
            parse_mode=ParseMode.HTML
        )
        return
    
    bet_amount = parse_bet(args[0], user_id)
    if not bet_amount or bet_amount <= 0:
        await update.message.reply_text("❌ Неверная сумма ставки!")
        return
    
    if user['balance'] < bet_amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    # Снимаем ставку
    user['balance'] -= bet_amount
    
    # Создаем поле 5x5 с 5 минами
    keyboard = []
    for i in range(0, 25, 5):
        row = []
        for j in range(5):
            btn_num = i + j
            row.append(InlineKeyboardButton("🟦", callback_data=f"mine_{btn_num}_{bet_amount}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("💰 Забрать", callback_data=f"mine_cashout_{bet_amount}")])
    
    await update.message.reply_text(
        f"💣 <b>Vibe Мины</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"💣 Мин: <b>5</b>\n"
        f"📈 Множитель: <b>1.0x</b>\n"
        f"💰 Текущий выигрыш: <b>{format_number(bet_amount)} $</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Выбери первую клетку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный бонус"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    now = datetime.datetime.now()
    
    # Проверяем время последнего бонуса
    if user.get('last_bonus'):
        last_bonus = datetime.datetime.fromisoformat(user['last_bonus'])
        hours_since = (now - last_bonus).total_seconds() / 3600
        
        if hours_since < 1:
            minutes_left = int(60 - (hours_since * 60))
            await update.message.reply_text(
                f"⏳ <b>Бонус уже получен</b>\n\n"
                f"🕐 Следующий через: {minutes_left} минут\n"
                f"🎁 Уровень {user['level']} бонус: {format_number(50000 + (user['level'] - 1) * 25000)} $",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Выдаем бонус
    bonus_amount = 50000 + (user['level'] - 1) * 25000
    user['balance'] += bonus_amount
    user['last_bonus'] = now.isoformat()
    
    # Увеличиваем серию
    streak = user.get('bonus_streak', 0) + 1
    user['bonus_streak'] = streak
    
    # Дополнительный бонус за серию
    extra_bonus = 0
    if streak % 7 == 0:  # Каждые 7 дней
        extra_bonus = bonus_amount * 2
        user['balance'] += extra_bonus
    
    await update.message.reply_text(
        f"🎁 <b>Бонус получен!</b>\n\n"
        f"💰 Основной бонус: {format_number(bonus_amount)} $\n"
        f"{f'🎉 Дополнительный за серию: {format_number(extra_bonus)} $' if extra_bonus > 0 else ''}\n"
        f"🔥 Серия: {streak} дней\n"
        f"⭐ Уровень: {user['level']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode=ParseMode.HTML
    )

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление банком"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not args:
        # Показываем информацию о банке
        daily_interest = user['deposit'] * 0.05
        bank_info = (
            f"🏦 <b>Vibe Банк</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 На руках: {format_number(user['balance'])} $\n"
            f"🏦 В депозите: {format_number(user['deposit'])} $\n"
            f"📈 Проценты: 5% в день\n"
            f"💸 Завтра получите: {format_number(daily_interest)} $\n\n"
            f"📝 Команды:\n"
            f"• банк положить [сумма]\n"
            f"• банк снять [сумма]\n"
            f"• банк информация\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎 Общая сумма: {format_number(user['balance'] + user['deposit'])} $"
        )
        await update.message.reply_text(bank_info, parse_mode=ParseMode.HTML)
        return
    
    action = args[0].lower()
    
    if action == "информация":
        await update.message.reply_text(
            "🏦 <b>Информация о банке</b>\n\n"
            "📈 Начисление: 5% ежедневно\n"
            "⏰ Время начисления: 00:00 по МСК\n"
            "💸 Минимальный депозит: 1,000 $\n"
            "💰 Максимальный: без лимита\n"
            "⚠️ Проценты начисляются только на депозит",
            parse_mode=ParseMode.HTML
        )
        return
    
    if len(args) < 2:
        await update.message.reply_text("❌ Укажите сумму!")
        return
    
    amount = parse_bet(args[1], user_id)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Неверная сумма!")
        return
    
    if action == "положить":
        if user['balance'] < amount:
            await update.message.reply_text("❌ Недостаточно средств на балансе!")
            return
        
        user['balance'] -= amount
        user['deposit'] += amount
        
        await update.message.reply_text(
            f"✅ <b>Деньги положены в банк</b>\n\n"
            f"💸 Сумма: {format_number(amount)} $\n"
            f"💰 На руках: {format_number(user['balance'])} $\n"
            f"🏦 В банке: {format_number(user['deposit'])} $\n"
            f"📈 Завтра получите: {format_number(amount * 0.05)} $",
            parse_mode=ParseMode.HTML
        )
    
    elif action == "снять":
        if user['deposit'] < amount:
            await update.message.reply_text("❌ Недостаточно средств в банке!")
            return
        
        user['deposit'] -= amount
        user['balance'] += amount
        
        await update.message.reply_text(
            f"✅ <b>Деньги сняты с банка</b>\n\n"
            f"💸 Сумма: {format_number(amount)} $\n"
            f"💰 На руках: {format_number(user['balance'])} $\n"
            f"🏦 В банке: {format_number(user['deposit'])} $",
            parse_mode=ParseMode.HTML
        )
    
    else:
        await update.message.reply_text("❌ Неизвестная команда банка!")

async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перевод денег"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        await update.message.reply_text(
            "💸 <b>Перевод денег</b>\n\n"
            "📝 Формат: перевести [ID] [сумма]\n\n"
            "Пример: перевести 123456789 1000\n\n"
            "⚠️ Переводы безвозвратны!\n"
            "🔍 ID можно узнать в профиле",
            parse_mode=ParseMode.HTML
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
    
    if user['balance'] < amount:
        await update.message.reply_text("❌ Недостаточно средств!")
        return
    
    if target_id == user_id:
        await update.message.reply_text("❌ Нельзя перевести себе!")
        return
    
    # Переводим деньги
    user['balance'] -= amount
    
    target_user = get_user(target_id)
    target_user['balance'] += amount
    
    # Логируем транзакцию
    transactions.append({
        'from': user_id,
        'to': target_id,
        'amount': amount,
        'time': datetime.datetime.now().isoformat()
    })
    
    # Уведомляем получателя (если возможно)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💰 <b>Вам перевели деньги!</b>\n\n"
                 f"👤 От: {user_id}\n"
                 f"💸 Сумма: {format_number(amount)} $\n"
                 f"💰 Ваш баланс: {format_number(target_user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
    except:
        pass  # Пользователь заблокировал бота
    
    await update.message.reply_text(
        f"✅ <b>Перевод выполнен!</b>\n\n"
        f"👤 Кому: {target_id}\n"
        f"💸 Сумма: {format_number(amount)} $\n"
        f"💰 Ваш баланс: {format_number(user['balance'])} $",
        parse_mode=ParseMode.HTML
    )

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Магазин товаров"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not args:
        # Показываем магазин
        shop_text = (
            "🛒 <b>Vibe Магазин</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "1. ⛏️ Лопата - 5,000 $\n"
            "   • Увеличивает доход с работ в 1.5 раза\n\n"
            "2. 🔍 Металлоискатель - 20,000 $\n"
            "   • +30% к шансу найти BTC\n\n"
            "3. 🛠️ Комплект - 22,000 $\n"
            "   • Лопата + Металлоискатель (скидка)\n\n"
            "📝 Покупка:\n"
            "• магазин лопата\n"
            "• магазин детектор\n"
            "• магазин комплект\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: {format_number(user['balance'])} $\n"
            f"⛏️ Лопат: {user['shovel']} | 🔍 Детекторов: {user['detector']}"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("⛏️ Лопата (5к $)", callback_data="shop_shovel"),
                InlineKeyboardButton("🔍 Детектор (20к $)", callback_data="shop_detector")
            ],
            [InlineKeyboardButton("🛠️ Комплект (22к $)", callback_data="shop_kit")]
        ]
        
        await update.message.reply_text(
            shop_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return
    
    item = args[0].lower()
    
    if item == "лопата":
        price = 5000
        if user['balance'] < price:
            await update.message.reply_text(f"❌ Недостаточно средств! Нужно {format_number(price)} $")
            return
        
        user['balance'] -= price
        user['shovel'] += 1
        
        await update.message.reply_text(
            f"✅ <b>Лопата куплена!</b>\n\n"
            f"⛏️ Теперь у вас: {user['shovel']} лопат\n"
            f"💸 Стоимость: {format_number(price)} $\n"
            f"💰 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
    
    elif item == "детектор":
        price = 20000
        if user['balance'] < price:
            await update.message.reply_text(f"❌ Недостаточно средств! Нужно {format_number(price)} $")
            return
        
        user['balance'] -= price
        user['detector'] += 1
        
        await update.message.reply_text(
            f"✅ <b>Металлоискатель куплен!</b>\n\n"
            f"🔍 Теперь у вас: {user['detector']} детекторов\n"
            f"💸 Стоимость: {format_number(price)} $\n"
            f"💰 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
    
    elif item == "комплект":
        price = 22000
        if user['balance'] < price:
            await update.message.reply_text(f"❌ Недостаточно средств! Нужно {format_number(price)} $")
            return
        
        user['balance'] -= price
        user['shovel'] += 1
        user['detector'] += 1
        
        await update.message.reply_text(
            f"✅ <b>Комплект куплен!</b>\n\n"
            f"⛏️ Лопат: {user['shovel']}\n"
            f"🔍 Детекторов: {user['detector']}\n"
            f"💸 Стоимость: {format_number(price)} $\n"
            f"💰 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
    
    else:
        await update.message.reply_text("❌ Товар не найден! Доступно: лопата, детектор, комплект")

async def admin_take(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Забрать деньги (админ)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещен!")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 Формат: забрать [ID] [сумма]")
        return
    
    try:
        target_id = int(args[0])
        amount_str = args[1]
        
        amount = parse_bet(amount_str, user_id)
        if not amount or amount <= 0:
            await update.message.reply_text("❌ Неверная сумма!")
            return
        
        target_user = get_user(target_id)
        
        if target_user['balance'] < amount:
            amount = target_user['balance']  # Забираем все что есть
        
        target_user['balance'] -= amount
        
        await update.message.reply_text(
            f"✅ <b>Деньги забраны!</b>\n\n"
            f"👤 Игрок: {target_id}\n"
            f"💰 Сумма: {format_number(amount)} $\n"
            f"💸 Новый баланс: {format_number(target_user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        # ========== ОБРАБОТЧИК КНОПОК (ВСЕ ИГРЫ) ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    data = query.data
    
    # ========== АЛМАЗЫ ==========
    if data.startswith("diamond_"):
        parts = data.split("_")
        
        if len(parts) == 4 and parts[1] == "cashout":
            # Забрать выигрыш в алмазах
            bet_amount = float(parts[3])
            win_amount = bet_amount * 2.0  # Пример: множитель 2x
            
            user['balance'] += win_amount
            user['wins'] += 1
            add_exp(user_id)
            
            await query.edit_message_text(
                f"💎 <b>Vibe Алмазы - Игра завершена</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎉 Вы забрали выигрыш!\n"
                f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
                f"📈 Финальный множитель: <b>2.0x</b>\n"
                f"💰 Выигрыш: <b>{format_number(win_amount)} $</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 Баланс: <b>{format_number(user['balance'])} $</b>",
                parse_mode=ParseMode.HTML
            )
            return
        
        elif len(parts) == 4:
            # Выбор клетки в алмазах
            cell_num = int(parts[1])
            bombs = int(parts[2])
            bet_amount = float(parts[3])
            
            # Генерируем позиции бомб (если еще нет)
            if 'diamond_game' not in context.user_data:
                context.user_data['diamond_game'] = {
                    'bombs': random.sample(range(9), bombs),
                    'opened': [],
                    'multiplier': 1.0,
                    'bet': bet_amount
                }
            
            game = context.user_data['diamond_game']
            
            if cell_num in game['opened']:
                await query.answer("❌ Эта клетка уже открыта!", show_alert=True)
                return
            
            game['opened'].append(cell_num)
            
            # Проверяем, попал ли на бомбу
            if cell_num in game['bombs']:
                # БОМБА - проигрыш
                user['losses'] += 1
                
                # Показываем все бомбы
                keyboard = []
                for i in range(0, 9, 3):
                    row = []
                    for j in range(3):
                        btn_num = i + j
                        if btn_num in game['bombs']:
                            row.append(InlineKeyboardButton("💣", callback_data="none"))
                        elif btn_num in game['opened']:
                            row.append(InlineKeyboardButton("💎", callback_data="none"))
                        else:
                            row.append(InlineKeyboardButton("💠", callback_data="none"))
                    keyboard.append(row)
                
                await query.edit_message_text(
                    f"💎 <b>Vibe Алмазы</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💣 <b>БОМБА!</b> Вы проиграли\n"
                    f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
                    f"💰 Выигрыш: <b>0 $</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Баланс: <b>{format_number(user['balance'])} $</b>",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                del context.user_data['diamond_game']
                return
            
            # АЛМАЗ - увеличиваем множитель
            game['multiplier'] += 0.5
            
            # Создаем новое поле с дополнительными клетками внизу
            keyboard = []
            
            # Основное поле 3x3
            for i in range(0, 9, 3):
                row = []
                for j in range(3):
                    btn_num = i + j
                    if btn_num in game['opened']:
                        row.append(InlineKeyboardButton("💎", callback_data=f"diamond_{btn_num}_{bombs}_{bet_amount}"))
                    elif btn_num == cell_num:
                        row.append(InlineKeyboardButton("✨", callback_data=f"diamond_{btn_num}_{bombs}_{bet_amount}"))
                    else:
                        row.append(InlineKeyboardButton("💠", callback_data=f"diamond_{btn_num}_{bombs}_{bet_amount}"))
                keyboard.append(row)
            
            # Разделитель
            keyboard.append([InlineKeyboardButton("━━━━━━━━━━", callback_data="none")])
            
            # Новые клетки снизу (3 штуки)
            new_cells = []
            available = [i for i in range(9) if i not in game['opened'] and i not in game['bombs']]
            if len(available) >= 3:
                new_cells = random.sample(available, 3)
                new_row = []
                for pos in new_cells:
                    new_row.append(InlineKeyboardButton("🔷", callback_data=f"diamond_{pos}_{bombs}_{bet_amount}"))
                keyboard.append(new_row)
            
            # Кнопка забрать
            keyboard.append([InlineKeyboardButton("💰 Забрать", callback_data=f"diamond_cashout_{bet_amount}")])
            
            current_win = bet_amount * game['multiplier']
            
            await query.edit_message_text(
                f"💎 <b>Vibe Алмазы</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎉 Найден алмаз!\n"
                f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
                f"📈 Множитель: <b>{game['multiplier']}x</b>\n"
                f"💰 Текущий выигрыш: <b>{format_number(current_win)} $</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Выбери следующую клетку:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
    
    # ========== МИНЫ ==========
    elif data.startswith("mine_"):
        parts = data.split("_")
        
        if len(parts) == 3 and parts[1] == "cashout":
            # Забрать выигрыш в минах
            bet_amount = float(parts[2])
            win_amount = bet_amount * 3.5  # Пример: множитель 3.5x
            
            user['balance'] += win_amount
            user['wins'] += 1
            add_exp(user_id)
            
            await query.edit_message_text(
                f"💣 <b>Vibe Мины - Игра завершена</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎉 Вы забрали выигрыш!\n"
                f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
                f"📈 Финальный множитель: <b>3.5x</b>\n"
                f"💰 Выигрыш: <b>{format_number(win_amount)} $</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 Баланс: <b>{format_number(user['balance'])} $</b>",
                parse_mode=ParseMode.HTML
            )
            return
        
        elif len(parts) == 3:
            # Выбор клетки в минах
            cell_num = int(parts[1])
            bet_amount = float(parts[2])
            
            # Инициализируем игру мин
            if 'mine_game' not in context.user_data:
                mines = 5
                context.user_data['mine_game'] = {
                    'mines': random.sample(range(25), mines),
                    'opened': [],
                    'multiplier': 1.0,
                    'bet': bet_amount
                }
            
            game = context.user_data['mine_game']
            
            if cell_num in game['opened']:
                await query.answer("❌ Эта клетка уже открыта!", show_alert=True)
                return
            
            game['opened'].append(cell_num)
            
            # Проверяем, попал ли на мину
            if cell_num in game['mines']:
                # МИНА - проигрыш
                user['losses'] += 1
                
                # Показываем все мины
                keyboard = []
                for i in range(0, 25, 5):
                    row = []
                    for j in range(5):
                        btn_num = i + j
                        if btn_num in game['mines']:
                            row.append(InlineKeyboardButton("💣", callback_data="none"))
                        elif btn_num in game['opened']:
                            row.append(InlineKeyboardButton("💰", callback_data="none"))
                        else:
                            row.append(InlineKeyboardButton("🟦", callback_data="none"))
                    keyboard.append(row)
                
                await query.edit_message_text(
                    f"💣 <b>Vibe Мины</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💥 <b>МИНА!</b> Вы проиграли\n"
                    f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
                    f"📈 Открыто клеток: <b>{len(game['opened'])-1}</b>\n"
                    f"💰 Выигрыш: <b>0 $</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Баланс: <b>{format_number(user['balance'])} $</b>",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                del context.user_data['mine_game']
                return
            
            # Безопасная клетка - увеличиваем множитель
            game['multiplier'] += 0.25
            
            # Обновляем поле
            keyboard = []
            for i in range(0, 25, 5):
                row = []
                for j in range(5):
                    btn_num = i + j
                    if btn_num in game['opened']:
                        row.append(InlineKeyboardButton("💰", callback_data=f"mine_{btn_num}_{bet_amount}"))
                    elif btn_num == cell_num:
                        row.append(InlineKeyboardButton("✨", callback_data=f"mine_{btn_num}_{bet_amount}"))
                    else:
                        row.append(InlineKeyboardButton("🟦", callback_data=f"mine_{btn_num}_{bet_amount}"))
                keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("💰 Забрать", callback_data=f"mine_cashout_{bet_amount}")])
            
            current_win = bet_amount * game['multiplier']
            
            await query.edit_message_text(
                f"💣 <b>Vibe Мины</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ Безопасная клетка!\n"
                f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
                f"💣 Мин: <b>5</b>\n"
                f"📈 Множитель: <b>{game['multiplier']:.2f}x</b>\n"
                f"💰 Текущий выигрыш: <b>{format_number(current_win)} $</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Выбери следующую клетку:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
    
    # ========== ФЕРМА ==========
    elif data.startswith("farm_"):
        action = data.split("_")[1]
        
        if action == "buy":
            if user['farm_cards'] >= 3:
                await query.answer("❌ Лимит 3 видеокарты!", show_alert=True)
                return
            
            price = 50000
            if user['balance'] < price:
                await query.answer(f"❌ Недостаточно средств! Нужно {format_number(price)} $", show_alert=True)
                return
            
            user['balance'] -= price
            user['farm_cards'] += 1
            
            keyboard = [
                [InlineKeyboardButton("🛒 Купить видеокарту (50к $)", callback_data="farm_buy")],
                [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")]
            ]
            
            await query.edit_message_text(
                f"🖥 <b>Ферма BTC</b>\n\n"
                f"📊 Видеокарт: {user['farm_cards']}/3\n"
                f"💰 Доход с карты: 1к $/час\n"
                f"₿ Шанс на BTC: {user['farm_cards']}%/час\n\n"
                f"💰 Баланс: {format_number(user['balance'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
        elif action == "collect":
            if user['farm_cards'] == 0:
                await query.answer("❌ У вас нет видеокарт!", show_alert=True)
                return
            
            # Расчет дохода
            income = user['farm_cards'] * 1000
            
            # Шанс найти BTC
            btc_chance = user['farm_cards'] * 0.01
            found_btc = 0
            if random.random() < btc_chance:
                found_btc = round(random.uniform(0.00001, 0.0001), 6)
                user['btc'] += found_btc
            
            user['balance'] += income
            
            keyboard = [
                [InlineKeyboardButton("🛒 Купить видеокарту (50к $)", callback_data="farm_buy")],
                [InlineKeyboardButton("💰 Собрать доход", callback_data="farm_collect")]
            ]
            
            text = f"🖥 <b>Ферма BTC</b>\n\n"
            text += f"📊 Видеокарт: {user['farm_cards']}/3\n"
            text += f"💰 Собрано: {format_number(income)} $\n"
            
            if found_btc > 0:
                text += f"₿ Намайнено BTC: {found_btc:.6f}\n\n"
            
            text += f"💰 Баланс: {format_number(user['balance'])} $\n"
            text += f"₿ Всего BTC: {user['btc']:.6f}"
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
    
    # ========== МАГАЗИН ==========
    elif data.startswith("shop_"):
        item = data.split("_")[1]
        
        if item == "shovel":
            price = 5000
            if user['balance'] < price:
                await query.answer(f"❌ Недостаточно средств! Нужно {format_number(price)} $", show_alert=True)
                return
            
            user['balance'] -= price
            user['shovel'] += 1
            
            await query.answer(f"✅ Лопата куплена за {format_number(price)} $", show_alert=True)
            
            # Обновляем сообщение магазина
            keyboard = [
                [
                    InlineKeyboardButton("⛏️ Лопата (5к $)", callback_data="shop_shovel"),
                    InlineKeyboardButton("🔍 Детектор (20к $)", callback_data="shop_detector")
                ],
                [InlineKeyboardButton("🛠️ Комплект (22к $)", callback_data="shop_kit")]
            ]
            
            shop_text = (
                f"🛒 <b>Vibe Магазин</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"1. ⛏️ Лопата - 5,000 $\n"
                f"2. 🔍 Металлоискатель - 20,000 $\n"
                f"3. 🛠️ Комплект - 22,000 $\n\n"
                f"💰 Баланс: {format_number(user['balance'])} $\n"
                f"⛏️ Лопат: {user['shovel']} | 🔍 Детекторов: {user['detector']}"
            )
            
            await query.edit_message_text(
                shop_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        
        elif item == "detector":
            price = 20000
            if user['balance'] < price:
                await query.answer(f"❌ Недостаточно средств! Нужно {format_number(price)} $", show_alert=True)
                return
            
            user['balance'] -= price
            user['detector'] += 1
            
            await query.answer(f"✅ Металлоискатель куплен за {format_number(price)} $", show_alert=True)
            
            # Обновляем сообщение магазина
            keyboard = [
                [
                    InlineKeyboardButton("⛏️ Лопата (5к $)", callback_data="shop_shovel"),
                    InlineKeyboardButton("🔍 Детектор (20к $)", callback_data="shop_detector")
                ],
                [InlineKeyboardButton("🛠️ Комплект (22к $)", callback_data="shop_kit")]
            ]
            
            shop_text = (
                f"🛒 <b>Vibe Магазин</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"1. ⛏️ Лопата - 5,000 $\n"
                f"2. 🔍 Металлоискатель - 20,000 $\n"
                f"3. 🛠️ Комплект - 22,000 $\n\n"
                f"💰 Баланс: {format_number(user['balance'])} $\n"
                f"⛏️ Лопат: {user['shovel']} | 🔍 Детекторов: {user['detector']}"
            )
            
            await query.edit_message_text(
                shop_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        
        elif item == "kit":
            price = 22000
            if user['balance'] < price:
                await query.answer(f"❌ Недостаточно средств! Нужно {format_number(price)} $", show_alert=True)
                return
            
            user['balance'] -= price
            user['shovel'] += 1
            user['detector'] += 1
            
            await query.answer(f"✅ Комплект куплен за {format_number(price)} $", show_alert=True)
            
            # Обновляем сообщение магазина
            keyboard = [
                [
                    InlineKeyboardButton("⛏️ Лопата (5к $)", callback_data="shop_shovel"),
                    InlineKeyboardButton("🔍 Детектор (20к $)", callback_data="shop_detector")
                ],
                [InlineKeyboardButton("🛠️ Комплект (22к $)", callback_data="shop_kit")]
            ]
            
            shop_text = (
                f"🛒 <b>Vibe Магазин</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"1. ⛏️ Лопата - 5,000 $\n"
                f"2. 🔍 Металлоискатель - 20,000 $\n"
                f"3. 🛠️ Комплект - 22,000 $\n\n"
                f"💰 Баланс: {format_number(user['balance'])} $\n"
                f"⛏️ Лопат: {user['shovel']} | 🔍 Детекторов: {user['detector']}"
            )
            
            await query.edit_message_text(
                shop_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
    
    # ========== ПРОВЕРКА ПОДПИСКИ ==========
    elif data == "check_sub":
        # Здесь должна быть реальная проверка через getChatMember
        # Пока просто подтверждаем
        await query.edit_message_text(
            "✅ Отлично! Вы подписаны!\n\n"
            "🎮 Теперь можете использовать все функции бота!\n"
            "📝 Напишите /help для списка команд.",
            parse_mode=ParseMode.HTML
    )
        # ========== ЗАПУСК БОТА ==========
def main():
    """Запуск основного приложения бота"""
    print("🤖 ЗАПУСК БОТА VIBE BET...")
    print(f"📱 Токен: {'✅ Установлен' if TOKEN else '❌ ОТСУТСТВУЕТ!'}")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"📢 Канал: {CHANNEL_USERNAME}")
    print(f"💬 Чат: {CHAT_USERNAME}")
    print("=" * 50)
    
    if not TOKEN:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен бота не установлен!")
        print("👉 Добавьте переменную окружения TELEGRAM_BOT_TOKEN в Railway")
        return
    
    # Создаем приложение с увеличенными таймаутами для Railway
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )
    
    app = Application.builder() \
        .token(TOKEN) \
        .request(request) \
        .build()
    
    # ========== РЕГИСТРАЦИЯ ВСЕХ КОМАНД ==========
    
    # Основные команды (отдельно английские и русские)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("старт", start))
    
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("профиль", profile))
    
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("баланс", balance))
    
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("помощь", help_command))
    
    app.add_handler(CommandHandler("top", top_players))
    app.add_handler(CommandHandler("топ", top_players))
    
    app.add_handler(CommandHandler("level", level_command))
    app.add_handler(CommandHandler("уровень", level_command))
    
    # Игры (отдельно английские и русские)
    app.add_handler(CommandHandler("roulette", roulette))
    app.add_handler(CommandHandler("рулетка", roulette))
    app.add_handler(CommandHandler("рул", roulette))
    
    app.add_handler(CommandHandler("dice", dice_game))
    app.add_handler(CommandHandler("кости", dice_game))
    
    app.add_handler(CommandHandler("football", football))
    app.add_handler(CommandHandler("футбол", football))
    
    app.add_handler(CommandHandler("crash", crash))
    app.add_handler(CommandHandler("краш", crash))
    
    app.add_handler(CommandHandler("diamonds", diamonds_game))
    app.add_handler(CommandHandler("алмазы", diamonds_game))
    
    app.add_handler(CommandHandler("mines", mines_game))
    app.add_handler(CommandHandler("мины", mines_game))
    
    # Экономика
    app.add_handler(CommandHandler("work", work))
    app.add_handler(CommandHandler("работа", work))
    
    app.add_handler(CommandHandler("farm", farm))
    app.add_handler(CommandHandler("ферма", farm))
    
    app.add_handler(CommandHandler("bonus", bonus))
    app.add_handler(CommandHandler("бонус", bonus))
    
    app.add_handler(CommandHandler("bank", bank_command))
    app.add_handler(CommandHandler("банк", bank_command))
    
    app.add_handler(CommandHandler("transfer", transfer))
    app.add_handler(CommandHandler("перевести", transfer))
    
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("магазин", shop))
    
    # Промокоды
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("промо", promo))
    
    app.add_handler(CommandHandler("createpromo", create_promo))
    app.add_handler(CommandHandler("создатьпромо", create_promo))
    
    # Админ команды
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("админ", admin))
    
    app.add_handler(CommandHandler("hhh", admin_give))
    app.add_handler(CommandHandler("выдать", admin_give))
    
    app.add_handler(CommandHandler("hhhh", admin_give_btc))
    app.add_handler(CommandHandler("выдатьбит", admin_give_btc))
    
    app.add_handler(CommandHandler("lvl", admin_level))
    app.add_handler(CommandHandler("уровеньадмин", admin_level))
    
    app.add_handler(CommandHandler("exp", admin_exp))
    app.add_handler(CommandHandler("опытадмин", admin_exp))
    
    app.add_handler(CommandHandler("забрать", admin_take))
    app.add_handler(CommandHandler("take", admin_take))
    
    # Обработчик inline-кнопок (ВСЕ ИГРЫ)
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик русских команд БЕЗ / (только текст)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # ========== ЗАПУСК ==========
    print("✅ Все обработчики зарегистрированы")
    print("📡 Запускаю polling...")
    print("=" * 50)
    
    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False,
            timeout=30,
            pool_timeout=30
        )
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()

# ========== ТОЧКА ВХОДА ==========
if __name__ == "__main__":
    main()
    
