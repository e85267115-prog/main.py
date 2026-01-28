# ===ИМПОРТЫ И НАСТРОЙКИ===
import os
import re
import json
import random
import asyncio
import logging
import datetime
from typing import Dict, List, Optional, Tuple
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
# ===ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ===
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
    # ===КОМАНДА START===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_data = get_user(user_id)  # Получаем данные пользователя
    
    # Проверка подписки на канал
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        channel_subscribed = chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        channel_subscribed = False
    
    # Проверка подписки на чат
    try:
        chat_member = await context.bot.get_chat_member(CHAT_USERNAME, user_id)
        chat_subscribed = chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        chat_subscribed = False
    
    if not channel_subscribed or not chat_subscribed:
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("💬 Вступить в чат", url=f"https://t.me/{CHAT_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")]
        ]
        
        await update.message.reply_photo(
            photo="https://raw.githubusercontent.com/e85267115-prog/main.py/main/start_img.jpg",
            caption=f"👋 Добро пожаловать в Vibe Bet, {user.first_name}!\n\n"
                    f"🎲 Игры: 🎰 Рулетка, 📈 Краш, 🎲 Кости, ⚽ Футбол\n"
                    f"💎 Алмазы, 💣 Мины\n"
                    f"⛏️ Заработок: 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус\n\n"
                    f"💰 Начальный баланс: {format_number(10000)} $\n\n"
                    f"⚠️ Для использования бота необходимо подписаться на канал и чат!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Начальный бонус 10к уже установлен в get_user(), просто приветствуем
    keyboard = [
        [InlineKeyboardButton("🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton("⛏️ Заработок", callback_data="earn_menu")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
    ]
    
    await update.message.reply_photo(
        photo="https://raw.githubusercontent.com/e85267115-prog/main.py/main/start_img.jpg",
        caption=f"👋 Привет, {user.first_name}!\n\n"
                f"✅ Вы успешно подписаны!\n"
                f"🎮 Добро пожаловать в Vibe Bet - лучший игровой бот!\n\n"
                f"💰 Текущий баланс: {format_number(user_data['balance'])} $",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
        )
    # ===ПРОФИЛЬ И БАЛАНС===
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    # ===ПОМОЩЬ И ОБРАБОТЧИК КНОПОК===
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎮 <b>Vibe Bet - Центр помощи</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "• /roulette [сумма] [ставка]\n"
        "• /dice [сумма] [больше/меньше]\n"
        "• /football [сумма] [гол/мимо]\n"
        "• /diamonds [сумма] [бомбы 3-8]\n"
        "• /mines [сумма] [мины 3-8]\n"
        "• /crash [сумма]\n\n"
        "⛏️ <b>ЗАРАБОТОК:</b>\n"
        "• /work — Работа (4 этапа)\n"
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_sub":
        # Проверяем подписку при нажатии кнопки
        user_id = query.from_user.id
        try:
            chat_member = await query.bot.get_chat_member(CHANNEL_USERNAME, user_id)
            channel_subscribed = chat_member.status in ['member', 'administrator', 'creator']
        except:
            channel_subscribed = False
            
        try:
            chat_member = await query.bot.get_chat_member(CHAT_USERNAME, user_id)
            chat_subscribed = chat_member.status in ['member', 'administrator', 'creator']
        except:
            chat_subscribed = False
        
        if channel_subscribed and chat_subscribed:
            keyboard = [
                [InlineKeyboardButton("🎮 Игры", callback_data="games_menu")],
                [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
            ]
            await query.edit_message_text(
                "✅ Отлично! Вы подписаны!\n\n"
                "🎮 Теперь можете использовать все функции бота!\n"
                "📝 Напишите /help для списка команд.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("💬 Вступить в чат", url=f"https://t.me/{CHAT_USERNAME[1:]}")],
                [InlineKeyboardButton("🔄 Проверить снова", callback_data="check_sub")]
            ]
            await query.edit_message_text(
                "❌ Вы еще не подписались на канал и/или чат!\n"
                "Пожалуйста, подпишитесь и нажмите кнопку проверки снова.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
        )
            # ===ИГРА РУЛЕТКА===
async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)

    if len(args) < 2:
        text = (
            "🎰 <b>Vibe Рулетка</b>\n\n"
            "📝 Формат: рул [сумма] [ставка]\n\n"
            "🎯 Ставки:\n"
            "• Число 0-36 (x36)\n"
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

    # Определяем цвет числа
    red_numbers = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    is_red = win_number in red_numbers and win_number != 0
    is_black = win_number not in red_numbers and win_number != 0
    is_even = win_number % 2 == 0 and win_number != 0
    is_odd = win_number % 2 == 1

    # Проверяем выигрыш
    multiplier = 0
    win = False

    if bet_type.isdigit() and 0 <= int(bet_type) <= 36:
        # Ставка на число - x36
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
        range_start = int(bet_type.split("-")[0])
        range_end = int(bet_type.split("-")[1])
        if range_start <= win_number <= range_end:
            multiplier = 3
            win = True
    else:
        await update.message.reply_text("❌ Неизвестный тип ставки!")
        return

    # Вычисляем результат
    win_amount = int(bet_amount * multiplier) if win else 0
    
    # Обновляем баланс
    user['balance'] += win_amount - bet_amount

    if win:
        user['wins'] += 1
        result_text = f"🎉 ВЫИГРЫШ! +{format_number(win_amount)} $ (x{multiplier})"
    else:
        user['losses'] += 1
        result_text = f"❌ ПРОИГРЫШ! -{format_number(bet_amount)} $"

    # Формируем сообщение
    color = "красный" if is_red else "черный" if is_black else "зеленый"
    parity = "четное" if is_even else "нечетное" if win_number != 0 else "ноль"

    result_message = (
        f"🎰 <b>Vibe Рулетка</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Выпало: <b>{win_number}</b> ({color}, {parity})\n"
        f"💰 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Ваш выбор: <b>{bet_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Баланс: <b>{format_number(user['balance'])} $</b>"
    )

    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML)
    
    # Добавляем опыт
    if add_exp(user_id):
        await update.message.reply_text(f"⭐ Уровень повышен! Теперь у вас {user['level']} уровень!")
        
# ===ИГРА В КОСТИ С АНИМАЦИЕЙ===
async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        text = (
            "🎲 <b>Vibe Кости</b>\n\n"
            "📝 Формат: кости [сумма] [ставка]\n\n"
            "🎯 Ставки:\n"
            "• <code>больше</code> - сумма >7 (x2.2)\n"
            "• <code>меньше</code> - сумма <7 (x2.2)\n"
            "• <code>7</code> - сумма =7 (x4)\n\n"
            "💎 Примеры:\n"
            "• кости 1000 больше\n"
            "• кости 500 меньше\n"
            "• кости 200 7"
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
    if bet_type not in ['больше', 'меньше', '7']:
        await update.message.reply_text("❌ Неверный тип ставки! Используйте: больше, меньше, 7")
        return
    
    # Снимаем ставку
    user['balance'] -= bet_amount
    
    # Отправляем анимацию игральных костей
    dice_message = await update.message.reply_dice(emoji="🎲")
    
    # Ждем 2 секунды для эффекта
    await asyncio.sleep(2)
    
    # Получаем результат (Telegram Dice дает число от 1 до 6, но нам нужно от 2 до 12)
    dice_value = dice_message.dice.value
    
    # Создаем вторую кость для реалистичности
    dice2 = random.randint(1, 6)
    total = dice_value + dice2
    
    # Определяем результат
    multiplier = 0
    win = False
    
    if bet_type == 'больше':
        if total > 7:
            multiplier = 2.2
            win = True
    elif bet_type == 'меньше':
        if total < 7:
            multiplier = 2.2
            win = True
    elif bet_type == '7':
        if total == 7:
            multiplier = 4
            win = True
    
    # Вычисляем выигрыш
    win_amount = int(bet_amount * multiplier) if win else 0
    user['balance'] += win_amount
    
    if win:
        user['wins'] += 1
        result_text = f"🎉 ВЫИГРЫШ! +{format_number(win_amount)} $ (x{multiplier})"
    else:
        user['losses'] += 1
        result_text = f"❌ ПРОИГРЫШ! -{format_number(bet_amount)} $"
    
    result_message = (
        f"🎲 <b>Vibe Кости</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Выпало: <b>{dice_value} + {dice2} = {total}</b>\n"
        f"💰 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Ваш выбор: <b>{bet_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML)
    
    if add_exp(user_id):
        await update.message.reply_text(f"⭐ Уровень повышен! Теперь у вас {user['level']} уровень!")
# ===РАБОТА С ЭТАПАМИ===
async def work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # Виды работ с этапами и зарплатой
    jobs = {
        "👷 Строитель": {
            "stages": [
                "🚗 Выезжаю на строительную площадку...",
                "🧱 Закладываю фундамент...",
                "🏗️ Возвожу стены...",
                "🎨 Завершаю отделку..."
            ],
            "min_salary": 8000,
            "max_salary": 25000,
            "btc_chance": 0.03
        },
        "🔧 Механик": {
            "stages": [
                "🚗 Принимаю автомобиль в ремонт...",
                "🔧 Диагностирую неисправность...",
                "🛠️ Заменяю детали...",
                "🧼 Делаю чистку и настройку..."
            ],
            "min_salary": 12000,
            "max_salary": 35000,
            "btc_chance": 0.05
        },
        "⛏️ Кладоискатель": {
            "stages": [
                "🗺️ Ищу место для раскопок...",
                "⛏️ Начинаю копать...",
                "💎 Нахожу артефакты...",
                "💰 Продаю находки..."
            ],
            "min_salary": 15000,
            "max_salary": 50000,
            "btc_chance": 0.1
        },
        "🍽️ Официант": {
            "stages": [
                "🧹 Подготавливаю зал...",
                "📝 Принимаю заказы...",
                "🍽️ Обслуживаю клиентов...",
                "💰 Получаю чаевые..."
            ],
            "min_salary": 5000,
            "max_salary": 15000,
            "btc_chance": 0.02
        }
    }
    
    # Если работа уже идет, продолжаем этапы
    if 'current_job' in user and user['current_job'].get('in_progress', False):
        job_data = user['current_job']
        current_stage = job_data.get('stage', 0)
        
        if current_stage < len(job_data['stages']):
            # Показываем текущий этап
            stage_msg = job_data['stages'][current_stage]
            progress_bar = "█" * (current_stage + 1) + "░" * (len(job_data['stages']) - current_stage - 1)
            
            keyboard = [[InlineKeyboardButton("➡️ Следующий этап", callback_data=f"work_next_{current_stage}")]]
            
            await update.message.reply_text(
                f"{job_data['job_name']}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Этап {current_stage + 1}/{len(job_data['stages'])}\n"
                f"⏳ {stage_msg}\n"
                f"📈 Прогресс: [{progress_bar}]\n\n"
                f"💰 Потенциальный заработок: {format_number(job_data['salary'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return
    
    # Начинаем новую работу
    job_name = random.choice(list(jobs.keys()))
    job_info = jobs[job_name]
    
    # Генерируем зарплату
    salary = random.randint(job_info['min_salary'], job_info['max_salary'])
    
    # Сохраняем информацию о работе
    user['current_job'] = {
        'job_name': job_name,
        'stages': job_info['stages'],
        'salary': salary,
        'btc_chance': job_info['btc_chance'],
        'stage': 0,
        'in_progress': True,
        'start_time': datetime.datetime.now().isoformat()
    }
    
    # Показываем первый этап
    keyboard = [[InlineKeyboardButton("➡️ Начать работать", callback_data="work_next_0")]]
    
    await update.message.reply_text(
        f"💼 <b>Новая работа: {job_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 Описание: {' → '.join(job_info['stages'])}\n"
        f"💰 Потенциальный заработок: {format_number(salary)} $\n"
        f"₿ Шанс найти BTC: {job_info['btc_chance']*100}%\n\n"
        f"Нажмите кнопку ниже чтобы начать работу:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
            )
    # ===ОБРАБОТЧИК РАБОТЫ===
async def work_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("work_next_"):
        user_id = query.from_user.id
        user = get_user(user_id)
        
        if 'current_job' not in user:
            await query.edit_message_text("❌ Работа не найдена! Начните новую через /work")
            return
        
        job_data = user['current_job']
        stage_num = int(query.data.split("_")[2])
        
        # Переходим к следующему этапу
        job_data['stage'] = stage_num + 1
        
        if job_data['stage'] < len(job_data['stages']):
            # Показываем следующий этап
            stage_msg = job_data['stages'][job_data['stage']]
            progress_bar = "█" * (job_data['stage'] + 1) + "░" * (len(job_data['stages']) - job_data['stage'] - 1)
            
            keyboard = [[InlineKeyboardButton("➡️ Следующий этап", callback_data=f"work_next_{job_data['stage']}")]]
            
            await query.edit_message_text(
                f"{job_data['job_name']}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Этап {job_data['stage'] + 1}/{len(job_data['stages'])}\n"
                f"⏳ {stage_msg}\n"
                f"📈 Прогресс: [{progress_bar}]\n\n"
                f"💰 Потенциальный заработок: {format_number(job_data['salary'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        else:
            # Работа завершена - выплата
            salary = job_data['salary']
            
            # Бонус за лопату
            if user.get('shovel', 0) > 0:
                salary = int(salary * 1.5)
            
            # Шанс найти BTC
            btc_found = 0
            if random.random() < job_data['btc_chance']:
                btc_found = round(random.uniform(0.00001, 0.0001), 6)
                user['btc'] += btc_found
            
            # Начисляем зарплату
            user['balance'] += salary
            
            # Добавляем опыт
            add_exp(user_id)
            
            # Формируем результат
            btc_text = f"₿ Найден BTC: {btc_found:.6f}\n" if btc_found > 0 else ""
            
            result_text = (
                f"🎉 <b>Работа завершена!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💼 {job_data['job_name']}\n"
                f"💰 Заработано: {format_number(salary)} $\n"
                f"{btc_text}"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Баланс: {format_number(user['balance'])} $\n"
                f"₿ BTC: {user['btc']:.6f}"
            )
            
            # Удаляем информацию о работе
            del user['current_job']
            
            keyboard = [
                [InlineKeyboardButton("💼 Новая работа", callback_data="new_work")],
                [InlineKeyboardButton("🎮 Игры", callback_data="games_menu")]
            ]
            
            await query.edit_message_text(
                result_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
        )
            # ===ИГРА ФУТБОЛ С АНИМАЦИЕЙ===
async def football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        text = (
            "⚽ <b>Vibe Футбол</b>\n\n"
            "📝 Формат: футбол [сумма] [ставка]\n\n"
            "🎯 Ставки:\n"
            "• <code>гол</code> - игрок забьет гол (x1.8)\n"
            "• <code>мимо</code> - игрок промахнется (x2.2)\n\n"
            "💎 Примеры:\n"
            "• футбол 1000 гол\n"
            "• футбол 500 мимо\n"
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
    if bet_type not in ['гол', 'мимо']:
        await update.message.reply_text("❌ Неверный тип ставки! Используйте: гол, мимо")
        return
    
    # Снимаем ставку
    user['balance'] -= bet_amount
    
    # Отправляем анимацию футбола
    await update.message.reply_text("⚽ Игрок готовится к удару...")
    await asyncio.sleep(1)
    
    # Отправляем анимацию (Telegram имеет встроенные анимации для футбола)
    animation_message = await update.message.reply_animation(
        animation="CgACAgQAAxkBAAIBAAAB4iL2uFqGYjLeGwf4jFgAAcKz3ygAAv8DAAJ3jXhSWYPN3jA8RMEwBA"  # ID футбольной анимации
    )
    
    # Ждем завершения анимации
    await asyncio.sleep(3)
    
    # Определяем результат (60% шанс на гол)
    is_goal = random.random() < 0.6
    
    # Проверяем выигрыш
    multiplier = 0
    win = False
    
    if bet_type == 'гол' and is_goal:
        multiplier = 1.8
        win = True
    elif bet_type == 'мимо' and not is_goal:
        multiplier = 2.2
        win = True
    
    # Вычисляем выигрыш
    win_amount = int(bet_amount * multiplier) if win else 0
    user['balance'] += win_amount
    
    if win:
        user['wins'] += 1
        result_text = f"🎉 ВЫИГРЫШ! +{format_number(win_amount)} $ (x{multiplier})"
        # Анимация гола
        await update.message.reply_animation(
            animation="CgACAgQAAxkBAAIBAAAC4iL2uFqGYjLeGwf4jFgAAcKz3ygAAv8DAAJ3jXhSWYPN3jA8RMEwBA",
            caption="⚽ ГООООЛ! 🎉"
        )
    else:
        user['losses'] += 1
        result_text = f"❌ ПРОИГРЫШ! -{format_number(bet_amount)} $"
        # Анимация промаха
        await update.message.reply_text("❌ Мяч улетел мимо ворот!")
    
    result_message = (
        f"⚽ <b>Vibe Футбол</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Результат: <b>{'ГОЛ! ⚽' if is_goal else 'МИМО! ❌'}</b>\n"
        f"💰 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        f"🎯 Ваш выбор: <b>{bet_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Баланс: <b>{format_number(user['balance'])} $</b>"
    )
    
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML)
    
    if add_exp(user_id):
        await update.message.reply_text(f"⭐ Уровень повышен! Теперь у вас {user['level']} уровень!")
        # ===ИГРА МИНЫ (ПОЛЕ 5x5)===
async def mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        text = (
            "💣 <b>Vibe Мины</b>\n\n"
            "📝 Формат: мины [сумма] [количество мин 3-8]\n\n"
            "🎯 Правила:\n"
            "• Игровое поле 5x5 (25 клеток)\n"
            "• Выбирайте количество мин от 3 до 8\n"
            "• Открывайте клетки, избегая мин\n"
            "• За каждую безопасную клетку: x1.1\n"
            "• Можно забрать выигрыш в любой момент\n\n"
            "💎 Примеры:\n"
            "• мины 1000 5\n"
            "• мины 5000 3\n"
            "• мины все 8"
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
    
    # Количество мин (по умолчанию 5)
    mines_count = 5
    if len(args) >= 2:
        try:
            mines_count = int(args[1])
            if mines_count < 3 or mines_count > 8:
                await update.message.reply_text("❌ Количество мин должно быть от 3 до 8!")
                return
        except:
            await update.message.reply_text("❌ Неверное количество мин!")
            return
    
    # Снимаем ставку
    user['balance'] -= bet_amount
    
    # Создаем игровое поле 5x5
    total_cells = 25
    mine_positions = random.sample(range(total_cells), mines_count)
    
    # Сохраняем игру в контексте пользователя
    context.user_data['mines_game'] = {
        'bet_amount': bet_amount,
        'mines_count': mines_count,
        'mine_positions': mine_positions,
        'opened_cells': [],
        'multiplier': 1.0,
        'user_id': user_id
    }
    
    # Создаем клавиатуру с полем 5x5
    keyboard = []
    for row in range(5):
        row_buttons = []
        for col in range(5):
            cell_num = row * 5 + col
            row_buttons.append(InlineKeyboardButton("🟦", callback_data=f"mines_open_{cell_num}"))
        keyboard.append(row_buttons)
    
    keyboard.append([
        InlineKeyboardButton("💰 Забрать выигрыш", callback_data="mines_cashout"),
        InlineKeyboardButton("🔄 Новая игра", callback_data="mines_new")
    ])
    
    await update.message.reply_text(
        f"💣 <b>Vibe Мины</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: {format_number(bet_amount)} $\n"
        f"💣 Мин на поле: {mines_count}\n"
        f"🎯 Открыто клеток: 0\n"
        f"📈 Множитель: x1.0\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Выберите клетку для открытия:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    # ===ОБРАБОТЧИК ИГРЫ МИНЫ (5x5)===
async def mines_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    if query.data.startswith("mines_open_"):
        cell_num = int(query.data.split("_")[2])
        
        if 'mines_game' not in context.user_data:
            await query.edit_message_text("❌ Игра не найдена! Начните новую через /mines")
            return
        
        game_data = context.user_data['mines_game']
        
        if cell_num in game_data['opened_cells']:
            await query.answer("❌ Эта клетка уже открыта!", show_alert=True)
            return
        
        # Проверяем, не мина ли это
        if cell_num in game_data['mine_positions']:
            # Игрок наступил на мину
            user['losses'] += 1
            
            # Создаем финальное поле со всеми минами
            keyboard = []
            for row in range(5):
                row_buttons = []
                for col in range(5):
                    cell_idx = row * 5 + col
                    if cell_idx in game_data['mine_positions']:
                        row_buttons.append(InlineKeyboardButton("💥", callback_data="mines_lost"))
                    elif cell_idx == cell_num:  # Текущая клетка, на которую наступили
                        row_buttons.append(InlineKeyboardButton("💣", callback_data="mines_lost"))
                    elif cell_idx in game_data['opened_cells']:
                        row_buttons.append(InlineKeyboardButton("✅", callback_data="mines_lost"))
                    else:
                        row_buttons.append(InlineKeyboardButton("🟦", callback_data="mines_lost"))
                keyboard.append(row_buttons)
            
            keyboard.append([
                InlineKeyboardButton("🔄 Новая игра", callback_data="mines_new"),
                InlineKeyboardButton("🎮 Другие игры", callback_data="games_menu")
            ])
            
            await query.edit_message_text(
                f"💣 <b>Vibe Мины</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💥 <b>ВЗРЫВ!</b> Вы наступили на мину!\n"
                f"💰 Потеряно: {format_number(game_data['bet_amount'])} $\n"
                f"🎯 Открыто клеток: {len(game_data['opened_cells'])}\n"
                f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Баланс: {format_number(user['balance'])} $\n"
                f"🏆 Побед/Поражений: {user['wins']}/{user['losses']}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            # Удаляем игру
            del context.user_data['mines_game']
            return
        
        # Клетка безопасна
        game_data['opened_cells'].append(cell_num)
        game_data['multiplier'] = round(game_data['multiplier'] * 1.1, 2)  # Увеличиваем множитель на 10%
        
        # Считаем количество мин вокруг (для отображения)
        safe_cells_opened = len(game_data['opened_cells'])
        total_safe_cells = 25 - game_data['mines_count']
        
        # Обновляем клавиатуру
        keyboard = []
        for row in range(5):
            row_buttons = []
            for col in range(5):
                cell_idx = row * 5 + col
                if cell_idx in game_data['opened_cells']:
                    # Считаем мины вокруг этой клетки
                    mines_around = 0
                    for dr in [-1, 0, 1]:
                        for dc in [-1, 0, 1]:
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = row + dr, col + dc
                            if 0 <= nr < 5 and 0 <= nc < 5:
                                neighbor_idx = nr * 5 + nc
                                if neighbor_idx in game_data['mine_positions']:
                                    mines_around += 1
                    
                    if mines_around > 0:
                        row_buttons.append(InlineKeyboardButton(f"{mines_around}", callback_data=f"mines_open_{cell_idx}"))
                    else:
                        row_buttons.append(InlineKeyboardButton("✅", callback_data=f"mines_open_{cell_idx}"))
                else:
                    row_buttons.append(InlineKeyboardButton("🟦", callback_data=f"mines_open_{cell_idx}"))
            keyboard.append(row_buttons)
        
        # Проверяем, все ли безопасные клетки открыты
        if safe_cells_opened == total_safe_cells:
            # ПОБЕДА! Все безопасные клетки открыты
            win_amount = int(game_data['bet_amount'] * game_data['multiplier'])
            user['balance'] += win_amount
            user['wins'] += 1
            
            keyboard = []
            for row in range(5):
                row_buttons = []
                for col in range(5):
                    cell_idx = row * 5 + col
                    if cell_idx in game_data['mine_positions']:
                        row_buttons.append(InlineKeyboardButton("💣", callback_data="mines_won"))
                    else:
                        row_buttons.append(InlineKeyboardButton("✅", callback_data="mines_won"))
                keyboard.append(row_buttons)
            
            keyboard.append([
                InlineKeyboardButton("🔄 Новая игра", callback_data="mines_new"),
                InlineKeyboardButton("💰 Забрать выигрыш", callback_data="mines_cashout")
            ])
            
            await query.edit_message_text(
                f"💣 <b>Vibe Мины</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎉 <b>ПОБЕДА!</b> Все безопасные клетки открыты!\n"
                f"💰 Ставка: {format_number(game_data['bet_amount'])} $\n"
                f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
                f"💰 Выигрыш: {format_number(win_amount)} $\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Баланс: {format_number(user['balance'])} $\n"
                f"🏆 Побед/Поражений: {user['wins']}/{user['losses']}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            del context.user_data['mines_game']
            return
        
        # Добавляем кнопки управления
        keyboard.append([
            InlineKeyboardButton("💰 Забрать выигрыш", callback_data="mines_cashout"),
            InlineKeyboardButton("🔄 Новая игра", callback_data="mines_new")
        ])
        
        current_win = int(game_data['bet_amount'] * game_data['multiplier'])
        
        await query.edit_message_text(
            f"💣 <b>Vibe Мины</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Ставка: {format_number(game_data['bet_amount'])} $\n"
            f"💣 Мин на поле: {game_data['mines_count']}\n"
            f"🎯 Открыто клеток: {safe_cells_opened}/{total_safe_cells}\n"
            f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
            f"💰 Текущий выигрыш: {format_number(current_win)} $\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Выберите следующую клетку:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    
    elif query.data == "mines_cashout":
        if 'mines_game' not in context.user_data:
            await query.answer("❌ Нет активной игры!", show_alert=True)
            return
        
        game_data = context.user_data['mines_game']
        
        if len(game_data['opened_cells']) == 0:
            await query.answer("❌ Вы еще не открыли ни одной клетки!", show_alert=True)
            return
        
        win_amount = int(game_data['bet_amount'] * game_data['multiplier'])
        user['balance'] += win_amount
        user['wins'] += 1
        
        # Показываем финальное поле
        keyboard = []
        for row in range(5):
            row_buttons = []
            for col in range(5):
                cell_idx = row * 5 + col
                if cell_idx in game_data['mine_positions']:
                    row_buttons.append(InlineKeyboardButton("💣", callback_data="mines_cashed"))
                elif cell_idx in game_data['opened_cells']:
                    row_buttons.append(InlineKeyboardButton("✅", callback_data="mines_cashed"))
                else:
                    row_buttons.append(InlineKeyboardButton("🟦", callback_data="mines_cashed"))
            keyboard.append(row_buttons)
        
        keyboard.append([InlineKeyboardButton("🔄 Новая игра", callback_data="mines_new")])
        
        await query.edit_message_text(
            f"💣 <b>Vibe Мины</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Вы забрали выигрыш!</b>\n"
            f"🎯 Открыто клеток: {len(game_data['opened_cells'])}\n"
            f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
            f"💰 Выигрыш: {format_number(win_amount)} $\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 Баланс: {format_number(user['balance'])} $\n"
            f"🏆 Побед/Поражений: {user['wins']}/{user['losses']}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
        del context.user_data['mines_game']
    
    elif query.data == "mines_new":
        # Очищаем старую игру
        if 'mines_game' in context.user_data:
            del context.user_data['mines_game']
        
        await query.edit_message_text(
            "💣 Начните новую игру командой:\n"
            "<code>/mines [ставка] [количество мин]</code>\n\n"
            "Примеры:\n"
            "• <code>/mines 1000 5</code>\n"
            "• <code>/mines все 3</code>\n"
            "• <code>/mines 5к 8</code>",
            parse_mode=ParseMode.HTML
            )
        # ===ИГРА АЛМАЗЫ (ПОЛЕ 3x1)===
async def diamonds_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 2:
        text = (
            "💎 <b>Vibe Алмазы</b>\n\n"
            "📝 Формат: алмазы [сумма] [количество бомб 1-2]\n\n"
            "🎯 Правила:\n"
            "• Игровое поле 3x1 (3 клетки)\n"
            "• Выбирайте количество бомб от 1 до 2\n"
            "• Находите 3 алмаза, избегая бомб\n"
            "• За каждый алмаз: x1.5\n"
            "• После каждого хода поле обновляется снизу\n"
            "• Можно забрать выигрыш в любой момент\n\n"
            "💎 Примеры:\n"
            "• алмазы 1000 1\n"
            "• алмазы 5000 2\n"
            "• алмазы все 1"
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
    
    # Количество бомб (по умолчанию 1)
    bombs_count = 1
    if len(args) >= 2:
        try:
            bombs_count = int(args[1])
            if bombs_count < 1 or bombs_count > 2:
                await update.message.reply_text("❌ Количество бомб должно быть от 1 до 2!")
                return
        except:
            await update.message.reply_text("❌ Неверное количество бомб!")
            return
    
    # Снимаем ставку
    user['balance'] -= bet_amount
    
    # Создаем игровое поле 3x1
    total_cells = 3
    bomb_positions = random.sample(range(total_cells), bombs_count)
    diamond_positions = [i for i in range(total_cells) if i not in bomb_positions]
    
    # Сохраняем игру в контексте пользователя
    context.user_data['diamonds_game'] = {
        'bet_amount': bet_amount,
        'bombs_count': bombs_count,
        'bomb_positions': bomb_positions,
        'diamond_positions': diamond_positions,
        'opened_cells': [],
        'found_diamonds': 0,
        'multiplier': 1.0,
        'user_id': user_id
    }
    
    # Создаем клавиатуру с полем 3x1
    keyboard = create_diamonds_field_3x1([], bomb_positions, diamond_positions)
    
    await update.message.reply_text(
        f"💎 <b>Vibe Алмазы</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: {format_number(bet_amount)} $\n"
        f"💣 Бомб на поле: {bombs_count}\n"
        f"💎 Алмазов: {3 - bombs_count}\n"
        f"🎯 Найдено алмазов: 0\n"
        f"📈 Множитель: x1.0\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Выберите клетку для открытия:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

def create_diamonds_field_3x1(opened_cells, bomb_positions, diamond_positions):
    """Создает поле 3x1 для игры в алмазы"""
    keyboard = []
    
    # Первая строка: текущее поле
    row_buttons = []
    for cell_num in range(3):
        if cell_num in opened_cells:
            if cell_num in bomb_positions:
                row_buttons.append(InlineKeyboardButton("💣", callback_data=f"diamonds_open_{cell_num}"))
            elif cell_num in diamond_positions:
                row_buttons.append(InlineKeyboardButton("💎", callback_data=f"diamonds_open_{cell_num}"))
            else:
                row_buttons.append(InlineKeyboardButton("⬜", callback_data=f"diamonds_open_{cell_num}"))
        else:
            row_buttons.append(InlineKeyboardButton("🟦", callback_data=f"diamonds_open_{cell_num}"))
    keyboard.append(row_buttons)
    
    # Вторая строка: новое поле (для обновления снизу)
    row_buttons = []
    for cell_num in range(3):
        row_buttons.append(InlineKeyboardButton("❓", callback_data=f"diamonds_new_{cell_num}"))
    keyboard.append(row_buttons)
    
    keyboard.append([
        InlineKeyboardButton("💰 Забрать выигрыш", callback_data="diamonds_cashout"),
        InlineKeyboardButton("🔄 Новая игра", callback_data="diamonds_new")
    ])
    
    return keyboard
    # ===ОБРАБОТЧИК АЛМАЗОВ 3x1===
async def diamonds_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    if query.data.startswith("diamonds_open_"):
        cell_num = int(query.data.split("_")[2])
        
        if 'diamonds_game' not in context.user_data:
            await query.edit_message_text("❌ Игра не найдена! Начните новую через /diamonds")
            return
        
        game_data = context.user_data['diamonds_game']
        
        if cell_num in game_data['opened_cells']:
            await query.answer("❌ Эта клетка уже открыта!", show_alert=True)
            return
        
        # Проверяем, не бомба ли это
        if cell_num in game_data['bomb_positions']:
            # Игрок нашел бомбу
            user['losses'] += 1
            
            # Показываем результат
            keyboard = []
            row_buttons = []
            for cell_idx in range(3):
                if cell_idx in game_data['bomb_positions']:
                    row_buttons.append(InlineKeyboardButton("💣", callback_data="diamonds_lost"))
                elif cell_idx in game_data['diamond_positions']:
                    row_buttons.append(InlineKeyboardButton("💎", callback_data="diamonds_lost"))
                else:
                    row_buttons.append(InlineKeyboardButton("⬜", callback_data="diamonds_lost"))
            keyboard.append(row_buttons)
            
            # Вторая строка: новое поле
            row_buttons = []
            for _ in range(3):
                row_buttons.append(InlineKeyboardButton("💣", callback_data="diamonds_lost"))
            keyboard.append(row_buttons)
            
            keyboard.append([InlineKeyboardButton("🔄 Новая игра", callback_data="diamonds_new")])
            
            await query.edit_message_text(
                f"💎 <b>Vibe Алмазы</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💣 БУМ! Вы нашли бомбу!\n"
                f"💰 Потеряно: {format_number(game_data['bet_amount'])} $\n"
                f"🎯 Найдено алмазов: {game_data['found_diamonds']}\n"
                f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Баланс: {format_number(user['balance'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            # Удаляем игру
            del context.user_data['diamonds_game']
            return
        
        # Игрок нашел алмаз
        game_data['opened_cells'].append(cell_num)
        game_data['found_diamonds'] += 1
        game_data['multiplier'] *= 1.5  # Увеличиваем множитель на 1.5 за каждый алмаз
        
        # Проверяем, все ли алмазы найдены
        all_diamonds_found = all(cell in game_data['opened_cells'] for cell in game_data['diamond_positions'])
        
        if all_diamonds_found:
            # Все алмазы найдены - победа!
            win_amount = int(game_data['bet_amount'] * game_data['multiplier'])
            user['balance'] += win_amount
            user['wins'] += 1
            
            keyboard = []
            row_buttons = []
            for cell_idx in range(3):
                if cell_idx in game_data['bomb_positions']:
                    row_buttons.append(InlineKeyboardButton("💣", callback_data="diamonds_won"))
                else:
                    row_buttons.append(InlineKeyboardButton("💎", callback_data="diamonds_won"))
            keyboard.append(row_buttons)
            
            # Вторая строка: новое поле
            row_buttons = []
            for _ in range(3):
                row_buttons.append(InlineKeyboardButton("💎", callback_data="diamonds_won"))
            keyboard.append(row_buttons)
            
            keyboard.append([InlineKeyboardButton("🔄 Новая игра", callback_data="diamonds_new")])
            
            await query.edit_message_text(
                f"💎 <b>Vibe Алмазы</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎉 ПОБЕДА! Все алмазы найдены!\n"
                f"💰 Выигрыш: {format_number(win_amount)} $\n"
                f"🎯 Найдено алмазов: {game_data['found_diamonds']}\n"
                f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Баланс: {format_number(user['balance'])} $",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            del context.user_data['diamonds_game']
            return
        
        # Обновляем поле
        keyboard = create_diamonds_field_3x1(game_data['opened_cells'], game_data['bomb_positions'], game_data['diamond_positions'])
        
        await query.edit_message_text(
            f"💎 <b>Vibe Алмазы</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Ставка: {format_number(game_data['bet_amount'])} $\n"
            f"💣 Бомб на поле: {game_data['bombs_count']}\n"
            f"💎 Найдено алмазов: {game_data['found_diamonds']}\n"
            f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Отличная работа! Продолжайте искать алмазы!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    
    elif query.data == "diamonds_cashout":
        if 'diamonds_game' not in context.user_data:
            await query.answer("❌ Нет активной игры!", show_alert=True)
            return
        
        game_data = context.user_data['diamonds_game']
        
        if game_data['found_diamonds'] == 0:
            await query.answer("❌ Вы еще не нашли ни одного алмаза!", show_alert=True)
            return
        
        win_amount = int(game_data['bet_amount'] * game_data['multiplier'])
        user['balance'] += win_amount
        user['wins'] += 1
        
        await query.edit_message_text(
            f"💎 <b>Vibe Алмазы</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Вы забрали выигрыш!\n"
            f"🎯 Найдено алмазов: {game_data['found_diamonds']}\n"
            f"📈 Множитель: x{game_data['multiplier']:.2f}\n"
            f"💰 Выигрыш: {format_number(win_amount)} $\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
        
        del context.user_data['diamonds_game']
    
    elif query.data == "diamonds_new":
        # Очищаем старую игру и предлагаем начать новую
        if 'diamonds_game' in context.user_data:
            del context.user_data['diamonds_game']
        
        await query.edit_message_text(
            "💎 Начните новую игру командой /diamonds [сумма] [количество бомб]",
            parse_mode=ParseMode.HTML
        )
# ===ИГРА КРАШ===
async def crash_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        text = (
            "📈 <b>Vibe Краш</b>\n\n"
            "📝 Формат: краш [сумма]\n\n"
            "🎯 Правила:\n"
            "• Ставьте сумму и смотрите за растущим множителем\n"
            "• Заберите выигрыш до того, как график 'крашнется'\n"
            "• Множитель может вырасти до 100x\n"
            "• Чем позже заберете - тем больше выигрыш\n"
            "• Но если не успеете - потеряете ставку\n\n"
            "💎 Примеры:\n"
            "• краш 1000\n"
            "• краш 5000\n"
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
    
    # Снимаем ставку
    user['balance'] -= bet_amount
    
    # Генерируем точку краха (от 1.1x до 10x)
    crash_point = round(random.uniform(1.1, 10.0), 2)
    
    # Сохраняем игру
    context.user_data['crash_game'] = {
        'bet_amount': bet_amount,
        'crash_point': crash_point,
        'current_multiplier': 1.0,
        'crashed': False,
        'user_id': user_id
    }
    
    keyboard = [[
        InlineKeyboardButton("💰 Забрать выигрыш", callback_data="crash_cashout"),
        InlineKeyboardButton("🚀 Продолжить", callback_data="crash_continue")
    ]]
    
    await update.message.reply_text(
        f"📈 <b>Vibe Краш</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: {format_number(bet_amount)} $\n"
        f"🎯 Текущий множитель: x1.0\n"
        f"📊 Максимальный множитель: ???\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"График начинает расти...",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    # Запускаем анимацию роста
    asyncio.create_task(crash_animation(update, context, crash_point))

async def crash_animation(update: Update, context: ContextTypes.DEFAULT_TYPE, crash_point: float):
    """Анимация роста множителя в краше"""
    game_data = context.user_data.get('crash_game')
    if not game_data:
        return
    
    multiplier = 1.0
    step = 0.05
    
    while multiplier < crash_point and game_data.get('crashed', False) == False:
        await asyncio.sleep(0.5)  # Обновление каждые 0.5 секунды
        
        if 'crash_game' not in context.user_data:
            break
            
        multiplier = min(multiplier + step, crash_point)
        game_data['current_multiplier'] = multiplier
        
        # Обновляем сообщение
        try:
            keyboard = [[
                InlineKeyboardButton("💰 Забрать выигрыш", callback_data="crash_cashout"),
                InlineKeyboardButton("🚀 Продолжить", callback_data="crash_continue")
            ]]
            
            # Создаем визуализацию графика
            progress = int((multiplier - 1.0) / (crash_point - 1.0) * 10)
            graph = "█" * progress + "░" * (10 - progress)
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id + 1,
                text=(
                    f"📈 <b>Vibe Краш</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Ставка: {format_number(game_data['bet_amount'])} $\n"
                    f"🎯 Текущий множитель: x{multiplier:.2f}\n"
                    f"📊 Прогресс: [{graph}]\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"График растет..."
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
        except Exception as e:
            break
    
    # Если не забрали вовремя - краш
    if multiplier >= crash_point and game_data.get('crashed', False) == False:
        game_data['crashed'] = True
        user_id = game_data['user_id']
        user = get_user(user_id)
        user['losses'] += 1
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id + 1,
            text=(
                f"📈 <b>Vibe Краш</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💥 КРАШ! График упал на x{crash_point:.2f}\n"
                f"💰 Потеряно: {format_number(game_data['bet_amount'])} $\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Баланс: {format_number(user['balance'])} $"
            ),
            parse_mode=ParseMode.HTML
        )
        
        if 'crash_game' in context.user_data:
            del context.user_data['crash_game']
            # ===ОБРАБОТЧИК КРАША===
async def crash_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    if query.data == "crash_cashout":
        if 'crash_game' not in context.user_data:
            await query.answer("❌ Нет активной игры!", show_alert=True)
            return
        
        game_data = context.user_data['crash_game']
        
        if game_data.get('crashed', False):
            await query.answer("❌ Уже слишком поздно! График крашнулся.", show_alert=True)
            return
        
        multiplier = game_data['current_multiplier']
        win_amount = int(game_data['bet_amount'] * multiplier)
        
        user['balance'] += win_amount
        user['wins'] += 1
        game_data['crashed'] = True
        
        await query.edit_message_text(
            f"📈 <b>Vibe Краш</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎉 Вы успели забрать выигрыш!\n"
            f"💰 Ставка: {format_number(game_data['bet_amount'])} $\n"
            f"🎯 Множитель: x{multiplier:.2f}\n"
            f"💰 Выигрыш: {format_number(win_amount)} $\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
        
        if 'crash_game' in context.user_data:
            del context.user_data['crash_game']
    
    elif query.data == "crash_continue":
        if 'crash_game' not in context.user_data:
            await query.answer("❌ Нет активной игры!", show_alert=True)
            return
        
        await query.answer("Продолжаем наблюдать за графиком...")
        # ===БАНК И ПЕРЕВОДЫ===
async def bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(context.args) == 0:
        # Показываем информацию о банке
        keyboard = [
            [InlineKeyboardButton("💰 Положить на депозит", callback_data="bank_deposit"),
             InlineKeyboardButton("💵 Снять с депозита", callback_data="bank_withdraw")],
            [InlineKeyboardButton("📊 Процентная ставка", callback_data="bank_interest")]
        ]
        
        await update.message.reply_text(
            f"🏦 <b>Vibe Банк</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 На руках: {format_number(user['balance'])} $\n"
            f"💰 В депозите: {format_number(user['deposit'])} $\n"
            f"📈 Процентная ставка: 5% в день\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Выберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Обработка команд банка
    if len(context.args) >= 2:
        action = context.args[0].lower()
        amount_str = context.args[1]
        
        amount = parse_bet(amount_str, user_id)
        if not amount or amount <= 0:
            await update.message.reply_text("❌ Неверная сумма!")
            return
        
        if action == "положить":
            if user['balance'] < amount:
                await update.message.reply_text("❌ Недостаточно средств на руках!")
                return
            
            user['balance'] -= amount
            user['deposit'] += amount
            
            await update.message.reply_text(
                f"✅ Успешно положено на депозит!\n"
                f"💰 Сумма: {format_number(amount)} $\n"
                f"💵 На руках: {format_number(user['balance'])} $\n"
                f"🏦 В депозите: {format_number(user['deposit'])} $",
                parse_mode=ParseMode.HTML
            )
        
        elif action == "снять":
            if user['deposit'] < amount:
                await update.message.reply_text("❌ Недостаточно средств на депозите!")
                return
            
            user['deposit'] -= amount
            user['balance'] += amount
            
            await update.message.reply_text(
                f"✅ Успешно снято с депозита!\n"
                f"💰 Сумма: {format_number(amount)} $\n"
                f"💵 На руках: {format_number(user['balance'])} $\n"
                f"🏦 В депозите: {format_number(user['deposit'])} $",
                parse_mode=ParseMode.HTML
            )

async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(context.args) < 2:
        text = (
            "💸 <b>Vibe Перевод</b>\n\n"
            "📝 Формат: перевести [ID] [сумма]\n\n"
            "🎯 Правила:\n"
            "• Переводите деньги другим игрокам\n"
            "• Комиссия: 1% от суммы перевода\n"
            "• Минимальная сумма: 100 $\n\n"
            "💎 Пример:\n"
            "• перевести 123456789 1000\n"
            "• перевести 987654321 все"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        amount_str = context.args[1]
        
        amount = parse_bet(amount_str, user_id)
        if not amount or amount < 100:
            await update.message.reply_text("❌ Неверная сумма! Минимум 100 $")
            return
        
        if user['balance'] < amount:
            await update.message.reply_text("❌ Недостаточно средств!")
            return
        
        # Комиссия 1%
        commission = int(amount * 0.01)
        transfer_amount = amount - commission
        
        # Получатель
        target_user = get_user(target_id)
        
        # Проверяем, существует ли получатель
        if target_user['id'] == user_id:
            await update.message.reply_text("❌ Нельзя переводить себе!")
            return
        
        # Совершаем перевод
        user['balance'] -= amount
        target_user['balance'] += transfer_amount
        
        # Добавляем в историю транзакций
        transactions.append({
            'from': user_id,
            'to': target_id,
            'amount': amount,
            'transfer_amount': transfer_amount,
            'commission': commission,
            'time': datetime.datetime.now().isoformat()
        })
        
        await update.message.reply_text(
            f"✅ Перевод выполнен успешно!\n"
            f"👤 Получатель ID: {target_id}\n"
            f"💰 Сумма перевода: {format_number(amount)} $\n"
            f"💸 Комиссия (1%): {format_number(commission)} $\n"
            f"🎯 Получено получателем: {format_number(transfer_amount)} $\n"
            f"💵 Ваш баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный ID получателя!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при переводе: {str(e)}")
        # ===ФЕРМА===
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

        # ===БОНУС===
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
    
    # Добавляем опыт
    if add_exp(user_id):
        await update.message.reply_text(
            f"⭐ Поздравляем! Вы повысили уровень до {user['level']}!\n"
            f"🎁 Бонус за уровень: {format_number(50000 + (user['level'] - 1) * 25000)} $"
        )
    
    await update.message.reply_text(
        f"🎁 <b>Бонус получен!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Основной бонус: {format_number(bonus_amount)} $\n"
        f"{f'🎉 Дополнительный за серию: {format_number(extra_bonus)} $' if extra_bonus > 0 else ''}\n"
        f"🔥 Серия: {streak} дней\n"
        f"⭐ Уровень: {user['level']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode=ParseMode.HTML
    )
        # ===ПРОМОКОДЫ===
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активация промокода"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        await update.message.reply_text(
            "🎫 <b>Промокоды</b>\n\n"
            "📝 Формат: промо [код]\n\n"
            "Пример: промо WELCOME\n\n"
            "🎁 Создать промокод: создатьпромо [сумма] [активаций]",
            parse_mode=ParseMode.HTML
        )
        return
    
    promo_code = args[0].upper()
    
    # Заглушка - всегда выигрышный промокод
    bonus_amount = 5000
    user['balance'] += bonus_amount
    
    await update.message.reply_text(
        f"🎉 <b>Промокод активирован!</b>\n\n"
        f"🎫 Код: {promo_code}\n"
        f"💰 Начислено: {format_number(bonus_amount)} $\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode=ParseMode.HTML
    )

async def create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода"""
    args = context.args
    user_id = update.effective_user.id
    
    if len(args) < 2:
        await update.message.reply_text(
            "🎫 <b>Создание промокода</b>\n\n"
            "📝 Формат: создатьпромо [сумма] [активаций]\n\n"
            "Пример: создатьпромо 1000 5",
            parse_mode=ParseMode.HTML
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
    
    await update.message.reply_text(
        f"🎫 <b>Промокод создан!</b>\n\n"
        f"🔑 Код: <code>{promo_code}</code>\n"
        f"💰 Начисление: {format_number(amount)} $\n"
        f"📊 Активаций: {max_activations}\n\n"
        f"📝 Для активации:\n"
        f"<code>промо {promo_code}</code>",
        parse_mode=ParseMode.HTML
        )
    
        # ===АДМИН КОМАНДЫ===
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Эта команда только для админов!")
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Выдать деньги", callback_data="admin_give_money")],
        [InlineKeyboardButton("⭐ Изменить уровень", callback_data="admin_change_level")],
        [InlineKeyboardButton("👥 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🎫 Создать промокод", callback_data="admin_create_promo")]
    ]
    
    await update.message.reply_text(
        "👑 <b>Админ-панель Vibe Bet</b>\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def admin_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Эта команда только для админов!")
        return
    
    if len(context.args) < 2:
        text = (
            "💰 <b>Выдача денег</b>\n\n"
            "📝 Формат: /hhh [ID] [сумма]\n\n"
            "💎 Примеры:\n"
            "• /hhh 123456789 10000\n"
            "• /hhh 987654321 500к\n"
            "• /hhh 123456789 1.5кк"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        amount_str = context.args[1]
        
        # Парсим сумму с поддержкой к/кк/ккк
        amount = parse_bet(amount_str, target_id)
        if not amount or amount <= 0:
            await update.message.reply_text("❌ Неверная сумма!")
            return
        
        target_user = get_user(target_id)
        target_user['balance'] += amount
        
        await update.message.reply_text(
            f"✅ Деньги успешно выданы!\n"
            f"👤 ID получателя: {target_id}\n"
            f"💰 Сумма: {format_number(amount)} $\n"
            f"💵 Баланс получателя: {format_number(target_user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def admin_give_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Эта команда только для админов!")
        return
    
    if len(context.args) < 2:
        text = (
            "₿ <b>Выдача BTC</b>\n\n"
            "📝 Формат: /hhhh [ID] [количество BTC]\n\n"
            "💎 Примеры:\n"
            "• /hhhh 123456789 0.001\n"
            "• /hhhh 987654321 0.01\n"
            "• /hhhh 123456789 1"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        btc_amount = float(context.args[1])
        
        if btc_amount <= 0:
            await update.message.reply_text("❌ Неверное количество BTC!")
            return
        
        target_user = get_user(target_id)
        target_user['btc'] += btc_amount
        
        usd_value = btc_amount * btc_price
        
        await update.message.reply_text(
            f"✅ BTC успешно выданы!\n"
            f"👤 ID получателя: {target_id}\n"
            f"₿ BTC: {btc_amount:.6f}\n"
            f"💰 В долларах: {format_number(usd_value)} $\n"
            f"₿ Всего BTC у получателя: {target_user['btc']:.6f}",
            parse_mode=ParseMode.HTML
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверные данные!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def admin_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Эта команда только для админов!")
        return
    
    if len(context.args) < 2:
        text = (
            "⭐ <b>Изменение уровня</b>\n\n"
            "📝 Формат: /lvl [ID] [уровень]\n\n"
            "💎 Примеры:\n"
            "• /lvl 123456789 10\n"
            "• /lvl 987654321 50\n"
            "• /lvl 123456789 1"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        new_level = int(context.args[1])
        
        if new_level < 1 or new_level > 100:
            await update.message.reply_text("❌ Уровень должен быть от 1 до 100!")
            return
        
        target_user = get_user(target_id)
        target_user['level'] = new_level
        target_user['exp'] = 0
        target_user['exp_needed'] = 4 * new_level
        
        await update.message.reply_text(
            f"✅ Уровень успешно изменен!\n"
            f"👤 ID пользователя: {target_id}\n"
            f"⭐ Новый уровень: {new_level}\n"
            f"📊 Требуется EXP для след. уровня: {target_user['exp_needed']}",
            parse_mode=ParseMode.HTML
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверные данные!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def admin_exp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Эта команда только для админов!")
        return
    
    if len(context.args) < 2:
        text = (
            "📊 <b>Изменение опыта</b>\n\n"
            "📝 Формат: /exp [ID] [количество опыта]\n\n"
            "💎 Примеры:\n"
            "• /exp 123456789 100\n"
            "• /exp 987654321 500\n"
            "• /exp 123456789 1000"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        exp_amount = int(context.args[1])
        
        if exp_amount < 0:
            await update.message.reply_text("❌ Количество опыта не может быть отрицательным!")
            return
        
        target_user = get_user(target_id)
        target_user['exp'] = exp_amount
        
        # Проверяем, не нужно ли повысить уровень
        while target_user['exp'] >= target_user['exp_needed']:
            target_user['level'] += 1
            target_user['exp'] -= target_user['exp_needed']
            target_user['exp_needed'] += 4
        
        await update.message.reply_text(
            f"✅ Опыт успешно изменен!\n"
            f"👤 ID пользователя: {target_id}\n"
            f"📊 Опыт: {target_user['exp']}\n"
            f"⭐ Уровень: {target_user['level']}\n"
            f"📈 Требуется до след. уровня: {target_user['exp_needed'] - target_user['exp']}",
            parse_mode=ParseMode.HTML
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверные данные!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        # ===ТОП ИГРОКОВ===
async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сортируем игроков по балансу
    sorted_users = sorted(users_db.values(), key=lambda x: x['balance'] + x['deposit'] + (x['btc'] * btc_price), reverse=True)
    
    top_text = "🏆 <b>Топ игроков Vibe Bet</b>\n━━━━━━━━━━━━━━━━━━\n"
    
    for i, user in enumerate(sorted_users[:10], 1):
        total_wealth = user['balance'] + user['deposit'] + (user['btc'] * btc_price)
        
        # Получаем имя пользователя (если есть)
        try:
            chat_member = await context.bot.get_chat_member(user['id'], user['id'])
            username = chat_member.user.first_name
        except:
            username = f"Игрок {user['id']}"
        
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        
        top_text += f"{medal} {username}\n"
        top_text += f"   💰 Капитал: {format_number(total_wealth)} $\n"
        top_text += f"   ⭐ Уровень: {user['level']} | 🏆 Побед: {user['wins']}\n"
        
        if i < len(sorted_users[:10]):
            top_text += "━━━━━━━━━━━━━━━━━━\n"
    
    top_text += "\n📊 Всего игроков: " + str(len(users_db))
    
    await update.message.reply_text(top_text, parse_mode=ParseMode.HTML)
    # ===МАГАЗИН (ПОЛНАЯ ВЕРСИЯ)===
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # Обработка покупки через команду
    if len(context.args) >= 1:
        item_name = context.args[0].lower()
        
        items = {
            'лопата': {'price': 5000, 'field': 'shovel', 'emoji': '⛏️', 'name': 'Лопата'},
            'детектор': {'price': 20000, 'field': 'detector', 'emoji': '🔍', 'name': 'Металлоискатель'},
            'видеокарта': {'price': 50000, 'field': 'farm_cards', 'emoji': '🖥️', 'name': 'Видеокарта'}
        }
        
        if item_name in items:
            item = items[item_name]
            
            # Проверка ограничений
            if item_name == 'видеокарта' and user.get('farm_cards', 0) >= 3:
                await update.message.reply_text("❌ Максимум 3 видеокарты на человека!")
                return
            
            if user['balance'] < item['price']:
                await update.message.reply_text(f"❌ Недостаточно средств! Нужно {format_number(item['price'])} $")
                return
            
            # Покупка
            user['balance'] -= item['price']
            if item_name == 'видеокарта':
                user['farm_cards'] = user.get('farm_cards', 0) + 1
            else:
                user[item['field']] = user.get(item['field'], 0) + 1
            
            await update.message.reply_text(
                f"{item['emoji']} <b>{item['name']} куплена!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💸 Цена: {format_number(item['price'])} $\n"
                f"📦 Всего {item['name'].lower()}ов: {user.get(item['field'], 0)}\n"
                f"💰 Баланс: {format_number(user['balance'])} $",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Показ магазина с кнопками
    keyboard = [
        [InlineKeyboardButton("⛏️ Купить лопату (5,000 $)", callback_data="shop_buy_shovel")],
        [InlineKeyboardButton("🔍 Купить детектор (20,000 $)", callback_data="shop_buy_detector")],
        [InlineKeyboardButton("🖥️ Купить видеокарту (50,000 $)", callback_data="shop_buy_gpu")],
        [InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
    ]
    
    shop_text = (
        f"🛒 <b>Vibe Магазин</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Доступные товары:</b>\n\n"
        f"⛏️ <b>Лопата</b> - 5,000 $\n"
        f"• Увеличивает доход с работ на 50%\n"
        f"• Шанс найти BTC +2%\n"
        f"📦 У вас: {user.get('shovel', 0)}\n\n"
        f"🔍 <b>Металлоискатель</b> - 20,000 $\n"
        f"• Увеличивает шанс найти BTC в 2 раза\n"
        f"• Особенно полезен для кладоискателя\n"
        f"📦 У вас: {user.get('detector', 0)}\n\n"
        f"🖥️ <b>Видеокарта</b> - 50,000 $\n"
        f"• Для майнинг фермы\n"
        f"• Максимум 3 карты на человека\n"
        f"• Каждая дает 1,000 $/час\n"
        f"📦 У вас: {user.get('farm_cards', 0)}/3\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ваш баланс: {format_number(user['balance'])} $\n\n"
        f"📝 <i>Используйте: /shop [название]</i>\n"
        f"Пример: <code>/shop лопата</code>"
    )
    
    await update.message.reply_text(
        shop_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

# ========== ОБРАБОТЧИК ВСЕХ КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    data = query.data
    
    print(f"🖱️ Нажата кнопка: {data} от {user_id}")
    
    # ========== ПРОВЕРКА ПОДПИСКИ ==========
    if data == "check_sub":
        await query.edit_message_text(
            "✅ Отлично! Вы подписаны!\n\n"
            "🎮 Теперь можете использовать все функции бота!\n"
            "📝 Напишите /help для списка команд.",
            parse_mode=ParseMode.HTML
        )
        return
    
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
            
        elif item == "detector":
            price = 20000
            if user['balance'] < price:
                await query.answer(f"❌ Недостаточно средств! Нужно {format_number(price)} $", show_alert=True)
                return
            
            user['balance'] -= price
            user['detector'] += 1
            await query.answer(f"✅ Металлоискатель куплен за {format_number(price)} $", show_alert=True)
        
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
    
    # ========== АЛМАЗЫ ==========
    elif data.startswith("diamond_"):
        parts = data.split("_")
        
        if len(parts) >= 2 and parts[1] == "cashout":
            # Забрать выигрыш в алмазах
            bet_amount = float(parts[2]) if len(parts) > 2 else 1000
            win_amount = bet_amount * 2.0
            
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
        
        # Простая игра в алмазы
        bet_amount = 1000
        if user['balance'] < bet_amount:
            await query.answer("❌ Недостаточно средств!", show_alert=True)
            return
        
        user['balance'] -= bet_amount
        
        # 70% шанс выигрыша
        if random.random() < 0.7:
            win_amount = bet_amount * 2
            user['balance'] += win_amount
            user['wins'] += 1
            result = "💎 Найден алмаз!"
        else:
            win_amount = 0
            user['losses'] += 1
            result = "💣 Попали на бомбу!"
        
        add_exp(user_id)
        
        await query.edit_message_text(
            f"💎 <b>Vibe Алмазы</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💸 Ставка: {format_number(bet_amount)} $\n"
            f"💣 Бомб: 2\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{result}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
    
    # ========== МИНЫ ==========
    elif data.startswith("mine_"):
        parts = data.split("_")
        
        if len(parts) >= 2 and parts[1] == "cashout":
            # Забрать выигрыш в минах
            bet_amount = float(parts[2]) if len(parts) > 2 else 1000
            win_amount = bet_amount * 3.5
            
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
        
        # Простая игра в мины
        bet_amount = 1000
        if user['balance'] < bet_amount:
            await query.answer("❌ Недостаточно средств!", show_alert=True)
            return
        
        user['balance'] -= bet_amount
        
        # 60% шанс выигрыша
        if random.random() < 0.6:
            win_amount = bet_amount * 3
            user['balance'] += win_amount
            user['wins'] += 1
            result = "✅ Безопасная клетка!"
        else:
            win_amount = 0
            user['losses'] += 1
            result = "💥 МИНА! Вы проиграли"
        
        add_exp(user_id)
        
        await query.edit_message_text(
            f"💣 <b>Vibe Мины</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💸 Ставка: {format_number(bet_amount)} $\n"
            f"💣 Мин: 5\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{result}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: {format_number(user['balance'])} $",
            parse_mode=ParseMode.HTML
        )
    
    # ========== КРАШ ==========
    elif data.startswith("crash_"):
        bet_amount = 1000
        if user['balance'] < bet_amount:
            await query.answer("❌ Недостаточно средств!", show_alert=True)
            return
        
        user['balance'] -= bet_amount
        
        crash_point = round(random.uniform(1.01, 5.00), 2)
        player_multiplier = round(random.uniform(1.10, crash_point - 0.01), 2) if crash_point > 1.10 else 1.00
        
        win = player_multiplier < crash_point
        
        if win:
            win_amount = round(bet_amount * player_multiplier, 2)
            user['balance'] += win_amount
            user['wins'] += 1
            result_text = "🎉 ВЫИГРЫШ"
        else:
            win_amount = 0
            user['losses'] += 1
            result_text = "😔 ВЫ ПРОИГРАЛИ"
        
        add_exp(user_id)
        
        text = (
            f"📈 <b>Vibe Краш</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💸 Ставка: <b>{format_number(bet_amount)} $</b>\n"
        )
        
        if not win:
            text += f"📈 Точка краха: <b>{crash_point}x</b>\n"
            text += f"🎯 Ваш множитель: <b>{player_multiplier}x</b>\n"
        
        text += f"{result_text}\n"
        
        if win:
            text += f"💰 Выигрыш: <b>{format_number(win_amount)} $</b> (x{player_multiplier})\n"
        
        text += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: <b>{format_number(user['balance'])} $</b>"
        )
        
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    
    # ========== РАБОТА ==========
    elif data.startswith("work_"):
        # Простая работа
        earnings = random.randint(5000, 20000)
        user['balance'] += earnings
        add_exp(user_id)
        
        jobs = ["👷 Кладоискатель", "💻 Хакер", "🚚 Курьер", "🍽 Официант", "🏗 Строитель"]
        job = random.choice(jobs)
        
        await query.edit_message_text(
            f"{job}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Заработано: <b>{format_number(earnings)} $</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: <b>{format_number(user['balance'])} $</b>",
            parse_mode=ParseMode.HTML
        )
    
    # ========== НЕИЗВЕСТНАЯ КНОПКА ==========
    else:
        await query.answer("ℹ️ Эта кнопка пока не активна", show_alert=True)    
        
# Глобальная база промокодов
promo_codes = {}

async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активация промокода"""
    args = context.args
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if len(args) < 1:
        await update.message.reply_text(
            "🎫 <b>Промокоды</b>\n\n"
            "📝 Формат: промо [код]\n\n"
            "Пример: промо WELCOME",
            parse_mode=ParseMode.HTML
        )
        return
    
    promo_code = args[0].upper().strip()
    
    # Проверяем существует ли промокод
    if promo_code not in promo_codes:
        await update.message.reply_text("❌ Промокод не найден!")
        return
    
    promo_info = promo_codes[promo_code]
    
    # Проверяем лимит активаций
    if promo_info['activations'] >= promo_info['max_activations']:
        await update.message.reply_text("❌ Лимит активаций исчерпан!")
        return
    
    # Проверяем использовал ли пользователь уже этот промокод
    if user_id in promo_info['used_by']:
        await update.message.reply_text("❌ Вы уже активировали этот промокод!")
        return
    
    # Активируем промокод
    bonus_amount = promo_info['amount']
    user['balance'] += bonus_amount
    user['promos_used'].append(promo_code)
    
    promo_info['activations'] += 1
    promo_info['used_by'].append(user_id)
    
    await update.message.reply_text(
        f"🎉 <b>Промокод активирован!</b>\n\n"
        f"🎫 Код: {promo_code}\n"
        f"💰 Начислено: {format_number(bonus_amount)} $\n"
        f"📊 Активаций: {promo_info['activations']}/{promo_info['max_activations']}\n"
        f"💰 Баланс: {format_number(user['balance'])} $",
        parse_mode=ParseMode.HTML
    )

async def create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода"""
    args = context.args
    user_id = update.effective_user.id
    
    if len(args) < 2:
        await update.message.reply_text(
            "🎫 <b>Создание промокода</b>\n\n"
            "📝 Формат: создатьпромо [сумма] [активаций]\n\n"
            "Пример: создатьпромо 1000 5",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        amount = float(args[0])
        max_activations = int(args[1])
        
        if amount <= 0 or max_activations <= 0:
            await update.message.reply_text("❌ Сумма и активации должны быть больше 0!")
            return
        
        # Генерируем уникальный промокод
        import string
        import time
        
        # Используем время для уникальности
        timestamp = int(time.time())
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        promo_code = f"VIBE{timestamp % 10000}{random_part}"
        
        # Сохраняем промокод
        promo_codes[promo_code] = {
            'amount': amount,
            'max_activations': max_activations,
            'activations': 0,
            'used_by': [],
            'created_by': user_id,
            'created_at': datetime.datetime.now().isoformat()
        }
        
        await update.message.reply_text(
            f"🎫 <b>Промокод создан!</b>\n\n"
            f"🔑 Код: <code>{promo_code}</code>\n"
            f"💰 Начисление: {format_number(amount)} $\n"
            f"📊 Активаций: {max_activations}\n\n"
            f"📝 Для активации:\n"
            f"<code>промо {promo_code}</code>\n\n"
            f"🔗 Ссылка: t.me/{(await context.bot.getMe()).username}?start=promo_{promo_code}",
            parse_mode=ParseMode.HTML
        )
        
    except:
        await update.message.reply_text("❌ Неверный формат!")
    
# ========== ОБРАБОТЧИК РУССКИХ КОМАНД БЕЗ / ==========
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

# ========== ГЛАВНЫЙ ЗАПУСК ДЛЯ RENDER ==========
def main() -> None:
    """Запуск бота для Render.com"""
    print("=" * 50)
    print("🚀 Vibe Bet Bot запускается на Render.com")
    print("=" * 50)
    
    # Получаем порт от Render (важно!)
    port = int(os.environ.get("PORT", 8443))
    print(f"📡 Порт: {port}")
    
    # Проверка токена
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен не найден!")
        print("Добавьте переменную TOKEN в Render:")
        print("1. Dashboard -> Your Service -> Environment")
        print("2. Add Environment Variable: Key=TOKEN, Value=ваш_токен")
        print("3. Manual Deploy -> Clear build cache & deploy")
        return
    
    print(f"✅ Токен получен: {TOKEN[:10]}...")
    
    try:
        # Создаем приложение с увеличенными таймаутами для Render
        request = HTTPXRequest(
            connect_timeout=60.0,
            read_timeout=60.0,
            write_timeout=60.0,
        )
        
        app = Application.builder().token(TOKEN).request(request).build()
        
        # ========== РЕГИСТРАЦИЯ ВСЕХ КОМАНД ==========
        print("📝 Регистрация команд...")
        
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
        app.add_handler(CommandHandler("crash", crash_game))
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
        
        # Обработка callback-запросов (кнопок)
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(CallbackQueryHandler(work_handler, pattern="^work_"))
        app.add_handler(CallbackQueryHandler(mines_handler, pattern="^mines_"))
        app.add_handler(CallbackQueryHandler(diamonds_handler, pattern="^diamonds_"))
        app.add_handler(CallbackQueryHandler(crash_handler, pattern="^crash_"))
        
        # Обработчик русских команд без /
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

        #универс обработ
        app.add_handler(CallbackQueryHandler(button_handler))
        
        print("✅ Все обработчики зарегистрированы")
        print("=" * 50)
        print("🤖 Бот успешно запущен на Render!")
        print(f"👑 Админы: {ADMIN_IDS}")
        print("⏳ Ожидание сообщений...")
        print("📞 Отправьте /start в Telegram")
        print("=" * 50)
        
        # ЗАПУСК БОТА - polling для Render
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False,
            poll_interval=1.0,
            timeout=30
        )
        
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        traceback.print_exc()

# ========== ТОЧКА ВХОДА ==========
if __name__ == "__main__":
    main()
