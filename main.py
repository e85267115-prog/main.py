import asyncio
import os
import logging
import random
import json
import io
import aiohttp
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Библиотеки Google
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW"
CREDENTIALS_FILE = 'credentials.json'

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

# ⚠️ ВПИШИ СЮДА СВОЙ TELEGRAM ID (числом), ЧТОБЫ РАБОТАЛА АДМИНКА
ADMIN_IDS = [123456789, 987654321] 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

users = {}

# --- GOOGLE DRIVE & DB ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE):
        logging.error("❌ Файл credentials.json не найден!")
        return None
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

def load_data():
    global users
    service = get_drive_service()
    if not service: return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        content = fh.read().decode('utf-8').strip()
        if content:
            users = json.loads(content)
            users = {int(k): v for k, v in users.items()}
            logging.info("✅ БД загружена")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки БД: {e}")
        users = {}

def save_data():
    service = get_drive_service()
    if not service: return
    try:
        with open("temp_db.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("temp_db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения: {e}")

# --- UTIL FUNCTIONS ---
async def get_btc_price_usd():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                return float(data['price'])
        except:
            return 95000.0

def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        elif num < 1_000_000:
            val = num / 1000
            return f"{val:.2f}к".replace(".00", "")
        elif num < 1_000_000_000:
            val = num / 1_000_000
            return f"{val:.2f}кк".replace(".00", "")
        elif num < 1_000_000_000_000:
            val = num / 1_000_000_000
            return f"{val:.2f}ккк".replace(".00", "")
        else:
            val = num / 1_000_000_000_000
            return f"{val:.2f}кккк".replace(".00", "")
    except: return "0"

def parse_amount(text, balance):
    if not text: return None
    text = str(text).lower().strip().replace(",", ".")
    if text in ["все", "всё", "all", "ва-банк"]: return int(balance)
    mults = {"ккк": 10**9, "кк": 10**6, "к": 1000, "m": 10**6, "k": 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try: return int(float(text.replace(m, "")) * v)
            except: pass
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 50000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "refs": 0,
            "reg": datetime.now().strftime("%d.%m.%Y"),
            "shovel": 0, "detector": 0, "last_work_time": 0,
            "banned": False # Добавлено поле бана
        }
        save_data()
    
    # Проверка полей
    required = ["shovel", "detector", "last_work_time", "bank", "btc", "xp", "lvl", "banned"]
    for field in required:
        if field not in users[uid]: 
            users[uid][field] = 0 if field != "banned" else False
            
    return users[uid]

async def check_subscription(user_id):
    try:
        m1 = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        m2 = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        valid = ['creator', 'administrator', 'member']
        return m1.status in valid and m2.status in valid
    except: return False # Для тестов можно вернуть True

def sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL), InlineKeyboardButton(text="💬 Чат", url=CHAT_URL)],
        [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")]
    ])

# --- БАНК ТАЙМЕР ---
async def bank_interest_task():
    logging.info("🕒 Выплата процентов...")
    for uid in users:
        if users[uid].get('bank', 0) > 0 and not users[uid].get('banned'):
            users[uid]['bank'] += int(users[uid]['bank'] * 0.10)
    save_data()

# --- MIDDLEWARE / CHECKERS ---
async def check_ban_and_sub(message: Message):
    u = get_user(message.from_user.id, message.from_user.first_name)
    if u['banned']:
        await message.answer("🚫 <b>Вы забанены администрацией!</b>")
        return False
    if not await check_subscription(message.from_user.id):
        await message.answer("🔒 Подпишись на каналы для игры!", reply_markup=sub_keyboard())
        return False
    return True

# --- START & PROFILE ---
@dp.message(F.text.lower().startswith("start") | (F.text == "/start"))
async def cmd_start(message: Message):
    # Обработка рефки
    args = message.text.split()
    user_id = message.from_user.id
    
    if len(args) > 1 and str(user_id) not in [str(k) for k in users.keys()]:
        try:
            ref_id = int(args[1])
            if ref_id != user_id and ref_id in users:
                users[ref_id]['balance'] += 250000
                users[ref_id]['refs'] += 1
                save_data()
                await bot.send_message(ref_id, "👤 Новый реферал! +250к $")
        except: pass

    u = get_user(user_id, message.from_user.first_name)
    if not await check_subscription(user_id):
        cap = f"👋 <b>Привет, {u['name']}!</b>\n👇 Подпишись, чтобы начать:"
        try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=cap, reply_markup=sub_keyboard())
        except: await message.answer(cap, reply_markup=sub_keyboard())
        return

    await cmd_profile(message)

@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ Спасибо за подписку! Приятной игры.")
    else:
        await call.answer("❌ Подпишись на каналы!", show_alert=True)

@dp.message(F.text.lower().in_({"профиль", "я", "profile", "stats"}))
async def cmd_profile(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*5} XP)\n"
        f"💰 На руках: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Bitcoin: <b>{u['btc']:.6f} BTC</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 Рефералов: <b>{u['refs']}</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(text)

# --- БАНК ---
@dp.message(F.text.lower() == "банк")
async def cmd_bank_menu(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    text = (
        f"🏦 <b>VIBE BANK</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💵 Счет: <b>{format_num(u['bank'])} $</b>\n"
        f"📈 Ставка: <b>10%</b> (в 00:00 МСК)\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📥 Пополнить: <code>деп [сумма]</code>\n"
        f"📤 Снять: <code>снять [сумма]</code>\n"
        f"💸 Перевод: <code>перевести [id] [сумма]</code>"
    )
    await message.answer(text)

@dp.message(F.text.lower().startswith("деп"))
async def cmd_deposit(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    try: amount = parse_amount(message.text.split()[1], u['balance'])
    except: return await message.answer("❌ Пример: <code>деп 100к</code>")

    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['balance']: return await message.answer("❌ Недостаточно средств!")
    
    u['balance'] -= amount
    u['bank'] += amount
    save_data()
    await message.answer(f"🏦 Депозит: <b>+{format_num(amount)} $</b>")

@dp.message(F.text.lower().startswith("снять"))
async def cmd_withdraw(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    try: amount = parse_amount(message.text.split()[1], u['bank'])
    except: return await message.answer("❌ Пример: <code>снять 100к</code>")

    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['bank']: return await message.answer("❌ Недостаточно в банке!")
    
    u['bank'] -= amount
    u['balance'] += amount
    save_data()
    await message.answer(f"🏦 Снято: <b>{format_num(amount)} $</b>")

@dp.message(F.text.lower().startswith(("перевести", "перевод")))
async def cmd_pay(message: Message):
    if not await check_ban_and_sub(message): return
    u_sender = get_user(message.from_user.id)
    args = message.text.split()
    
    try:
        target_id = int(args[1])
        amount = parse_amount(args[2], u_sender['balance'])
    except: return await message.answer("❌ Формат: <code>перевести [ID] [сумма]</code>")
    
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u_sender['balance']: return await message.answer("❌ Мало денег!")
    if target_id not in users: return await message.answer("❌ Игрок не найден!")
    if target_id == message.from_user.id: return await message.answer("❌ Себе нельзя!")
    
    users[target_id]['balance'] += amount
    u_sender['balance'] -= amount
    save_data()
    await message.answer(f"💸 Перевод <b>{format_num(amount)} $</b> игроку {users[target_id]['name']}!")
    try: await bot.send_message(target_id, f"💸 Перевод: <b>+{format_num(amount)} $</b> от {u_sender['name']}")
    except: pass

# --- МАГАЗИН ---
@dp.message(F.text.lower().in_({"магазин", "шоп", "shop"}))
async def cmd_shop(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    
    count = 0
    if u['shovel'] > 0: count += 1
    if u['detector'] > 0: count += 1
    
    inv_text = f"Нету инструментов 0/2" if count == 0 else f"Инструменты {count}/2"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Лопата (100к)", callback_data="buy_shovel")],
        [InlineKeyboardButton(text="📟 Металлоискатель (150к)", callback_data="buy_detector")]
    ])
    
    text = (
        f"🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🎒 <b>{inv_text}</b>\n"
        f"⛏ Лопата: {u['shovel']}/5 ходок\n"
        f"📟 Детектор: {u['detector']}/5 ходок\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👇 Покупайте, чтобы работать!"
    )
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_tool_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    item = call.data.split("_")[1]
    price = 100000 if item == "shovel" else 150000
    name = "Лопата" if item == "shovel" else "Металлоискатель"
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    if u[item] > 0:
        return await call.answer(f"❌ {name} уже куплена! (Прочность: {u[item]}/5)", show_alert=True)
    
    u['balance'] -= price
    u[item] = 5
    save_data()
    await cmd_shop(call.message) 
    await call.answer("✅ Куплено!")

# --- РАБОТА ---
@dp.message(F.text.lower().in_({"работа", "work"}))
async def cmd_work(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    
    now_ts = datetime.now().timestamp()
    if now_ts - u['last_work_time'] < 7200: 
        rem = int(7200 - (now_ts - u['last_work_time']))
        h, m = divmod(divmod(rem, 60)[0], 60)
        return await message.answer(f"⏳ Перерыв! Отдых еще: <b>{int(h)}ч {int(m)}м</b>")

    if u['shovel'] <= 0 or u['detector'] <= 0:
        return await message.answer("🛠 <b>Инструментов нет или они сломаны!</b>\nЗайдите в 'магазин'")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌲 Сектор 1", callback_data="dig_1"),
         InlineKeyboardButton(text="🌲 Сектор 2", callback_data="dig_2"),
         InlineKeyboardButton(text="🌲 Сектор 3", callback_data="dig_3")]
    ])
    
    await message.answer("🗺 <b>КЛАДОИСКАТЕЛЬ</b>\nВыберите сектор:", reply_markup=kb)

@dp.callback_query(F.data.startswith("dig_"))
async def work_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if u['shovel'] <= 0 or u['detector'] <= 0:
        await call.message.delete()
        return await call.answer("🛠 Инструменты сломались!", show_alert=True)

    u['shovel'] -= 1
    u['detector'] -= 1
    
    if u['shovel'] == 0 or u['detector'] == 0:
        u['last_work_time'] = datetime.now().timestamp()
        broken_msg = "\n🧨 <b>Инструменты сломались!</b>\nКупите новые в магазине (кд 2 часа)."
    else:
        broken_msg = f"\n🔧 Остаток прочности: {u['shovel']}/5"

    rand = random.randint(1, 100)
    if rand <= 10: 
        btc_price = await get_btc_price_usd()
        found_btc = random.uniform(0.0001, 0.0005) 
        val_usd = int(found_btc * btc_price)
        u['balance'] += val_usd
        u['btc'] += found_btc
        res = f"💎 <b>ДЖЕКПОТ!</b> Найден BTC: <b>{found_btc:.6f}</b>\n💵 Продано на бирже за: <b>{format_num(val_usd)} $</b>"
    elif rand <= 70:
        money = random.randint(20000, 80000)
        u['balance'] += money
        res = f"⛏ Успех! Выкопано: <b>{format_num(money)} $</b>"
    else:
        res = "🗑 Вы нашли только старый ботинок... Пусто."

    save_data()
    await call.message.edit_text(res + broken_msg)

# --- ИГРЫ: РУЛЕТКА ---
@dp.message(F.text.lower().startswith(("рул", "рулетка")))
async def cmd_roulette(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    args = message.text.split()
    
    try:
        amount = parse_amount(args[1], u['balance'])
        bet_color = args[2].lower()
    except: return await message.answer("🎰 Формат: <code>рул [сумма] [кра/чер/зел]</code>")
    
    target = None
    if 'кра' in bet_color: target = 'red'
    elif 'чер' in bet_color: target = 'black'
    elif 'зел' in bet_color: target = 'green'
    else: return await message.answer("❌ Цвета: кра (🔴), чер (⚫), зел (🟢)")
    
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['balance']: return await message.answer("❌ Недостаточно средств!")
    
    u['balance'] -= amount
    
    # Генерация числа
    num = random.randint(0, 36)
    
    # Определение цвета и четности
    if num == 0:
        color = 'green'
        color_ru = 'зеленый'
        parity_ru = 'зеро'
        emoji = '🟢'
    else:
        if num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]:
            color = 'red'
            color_ru = 'красный'
            emoji = '🔴'
        else:
            color = 'black'
            color_ru = 'черный'
            emoji = '⚫'
        
        parity_ru = 'четное' if num % 2 == 0 else 'нечетное'

    is_win = (target == color)
    if is_win:
        coef = 14 if target == 'green' else 2
        win_amount = amount * coef
        u['balance'] += win_amount
        header = f"🎉 Выигрыш: {format_num(win_amount)} $"
    else:
        header = f"😔 Вы проиграли!"

    save_data()

    text = (
        f"💸 Ставка: {format_num(amount)} $\n"
        f"{header}\n"
        f"📈 Выпало: {num} {emoji} ({color_ru}, {parity_ru})\n"
        f"💰 Баланс: {format_num(u['balance'])} $"
    )
    await message.answer(text)

# --- ИГРЫ: КРАШ ---
@dp.message(F.text.lower().startswith(("краш", "crash")))
async def cmd_crash(message: Message):
    if not await check_ban_and_sub(message): return
    u = get_user(message.from_user.id)
    args = message.text.split()
    
    try:
        amount = parse_amount(args[1], u['balance'])
        target_mult = float(args[2].replace(",", "."))
    except: return await message.answer("🚀 Формат: <code>краш [сумма] [кэф]</code>\nПример: <code>краш 100 2.5</code>")
    
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['balance']: return await message.answer("❌ Недостаточно средств!")
    if target_mult < 1.01: return await message.answer("❌ Минимальный кэф 1.01")
    
    u['balance'] -= amount

    # Алгоритм Краша (простой)
    # Шанс краша на 1.00 = 3%
    if random.randint(1, 100) <= 3:
        crash_point = 1.00
    else:
        # Генерируем число. Чем больше число, тем меньше шанс.
        # Формула E = 0.99 / (1 - random) - имитация реального краша
        # Для простоты сделаем рандом с весом
        crash_point = round(0.96 / (1 - random.random()), 2)
        if crash_point > 100: crash_point = round(random.uniform(100, 500), 2)
        if crash_point < 1.00: crash_point = 1.00

    if target_mult <= crash_point:
        win_amount = int(amount * target_mult)
        u['balance'] += win_amount
        header = "🎉 Вы выиграли!"
        res_emoji = "✅"
    else:
        header = "😔 Вы проиграли!"
        res_emoji = "❌"

    save_data()

    text = (
        f"{header}\n"
        f"📈 Точка краша: {crash_point:.2f}\n"
        f"🎯 Множитель: {target_mult:.2f} {res_emoji}\n"
        f"💸 Ставка: {format_num(amount)} $\n"
        f"💰 Баланс: {format_num(u['balance'])} $"
    )
    await message.answer(text)


# --- АДМИН ПАНЕЛЬ ---
def is_admin(uid):
    return uid in ADMIN_IDS

@dp.message(F.text.lower().startswith("бан"))
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        target_id = int(message.text.split()[1])
        if target_id not in users: return await message.answer("❌ Игрок не найден в БД")
        users[target_id]['banned'] = True
        save_data()
        await message.answer(f"⛔ Игрок {target_id} забанен!")
        logging.info(f"ADMIN: {message.from_user.id} забанил {target_id}")
    except: await message.answer("❌ Формат: бан [ID]")

@dp.message(F.text.lower().startswith("разбан"))
async def admin_unban(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        target_id = int(message.text.split()[1])
        if target_id not in users: return await message.answer("❌ Игрок не найден в БД")
        users[target_id]['banned'] = False
        save_data()
        await message.answer(f"✅ Игрок {target_id} разбанен!")
        logging.info(f"ADMIN: {message.from_user.id} разбанил {target_id}")
    except: await message.answer("❌ Формат: разбан [ID]")
        @dp.message(F.text.lower().startswith("выдатьбит"))
async def admin_give_btc(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        args = message.text.split()
        target_id = int(args[1])
        amount = float(args[2].replace(",", "."))
        if target_id not in users: return await message.answer("❌ Нет в БД")
        
        users[target_id]['btc'] += amount
        save_data()
        await message.answer(f"💳 Выдано {amount} BTC игроку {target_id}")
        await bot.send_message(target_id, f"💳 Администратор выдал вам <b>{amount} BTC</b>")
        logging.info(f"ADMIN: {message.from_user.id} выдал BTC {amount} игроку {target_id}")
    except: await message.answer("❌ Формат: выдатьбит [ID] [сумма]")

@dp.message(F.text.lower().startswith("выдать"))
async def admin_give_money(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        args = message.text.split()
        target_id = int(args[1])
        # Здесь нельзя использовать parse_amount с балансом юзера, так как админ выдает из воздуха
        # Парсим вручную
        txt = args[2].lower()
        mult = 1
        if txt.endswith("к"): mult = 1000; txt = txt[:-1]
        elif txt.endswith("кк"): mult = 10**6; txt = txt[:-2]
        elif txt.endswith("ккк"): mult = 10**9; txt = txt[:-3]
        
        amount = int(float(txt) * mult)
        
        if target_id not in users: return await message.answer("❌ Нет в БД")
        
        users[target_id]['balance'] += amount
        save_data()
        await message.answer(f"💳 Выдано {format_num(amount)} $ игроку {target_id}")
        await bot.send_message(target_id, f"💳 Администратор выдал вам <b>{format_num(amount)} $</b>")
        logging.info(f"ADMIN: {message.from_user.id} выдал {amount} игроку {target_id}")
    except Exception as e: await message.answer(f"❌ Формат: выдать [ID] [сумма] ({e})")

@dp.message(F.text.lower().startswith("забрать"))
async def admin_take_money(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        args = message.text.split()
        target_id = int(args[1])
        # Парсим сумму
        txt = args[2].lower()
        mult = 1
        if txt.endswith("к"): mult = 1000; txt = txt[:-1]
        elif txt.endswith("кк"): mult = 10**6; txt = txt[:-2]
        
        amount = int(float(txt) * mult)
        
        if target_id not in users: return await message.answer("❌ Нет в БД")
        
        users[target_id]['balance'] -= amount
        if users[target_id]['balance'] < 0: users[target_id]['balance'] = 0
        save_data()
        await message.answer(f"🗑 Забрано {format_num(amount)} $ у игрока {target_id}")
        await bot.send_message(target_id, f"🗑 Администратор забрал у вас <b>{format_num(amount)} $</b>")
        logging.info(f"ADMIN: {message.from_user.id} забрал {amount} у {target_id}")
    except: await message.answer("❌ Формат: забрать [ID] [сумма]")

@dp.message(F.text.lower() == "админ")
async def admin_help(message: Message):
    if not is_admin(message.from_user.id): return
    text = (
        "👮‍♂️ <b>АДМИН ПАНЕЛЬ</b>\n"
        "• <code>бан [ID]</code>\n"
        "• <code>разбан [ID]</code>\n"
        "• <code>выдать [ID] [сумма]</code>\n"
        "• <code>забрать [ID] [сумма]</code>\n"
        "• <code>выдатьбит [ID] [сумма]</code>\n"
        "Логи пишутся в консоль сервера."
    )
    await message.answer(text)

@dp.message(F.text.lower().in_({"помощь", "help", "команды"}))
async def cmd_help(message: Message):
    text = (
        "🎮 <b>СПИСОК КОМАНД:</b>\n\n"
        "💼 <b>РАБОТА:</b>\n"
        "• <code>работа</code> — Искать клад\n"
        "• <code>магазин</code> — Купить инструменты\n\n"
        "🏦 <b>ФИНАНСЫ:</b>\n"
        "• <code>банк</code> — Меню банка\n"
        "• <code>деп [сумма]</code> — Положить в банк\n"
        "• <code>снять [сумма]</code> — Снять из банка\n"
        "• <code>перевести [id] [сумма]</code> — Перевод игроку\n\n"
        "🎰 <b>ИГРЫ:</b>\n"
        "• <code>рул [сумма] [цвет]</code> — Рулетка (кра/чер/зел)\n"
        "• <code>краш [сумма] [кэф]</code> — Краш (мин кэф 1.01)\n\n"
        "👤 <b>Профиль</b> — Статистика"
    )
    await message.answer(text)

# --- SERVER ---
async def handle_ping(request): return web.Response(text="Bot Alive")

async def main():
    load_data()
    msk_tz = pytz.timezone('Europe/Moscow')
    scheduler.add_job(bank_interest_task, 'cron', hour=0, minute=0, timezone=msk_tz)
    scheduler.start()
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
