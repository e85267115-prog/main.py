import asyncio
import os
import logging
import random
import json
import io
import time
import aiohttp
from datetime import datetime, timedelta
from pytz import timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiohttp import web
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN") 
# Вставьте сюда ваш ID, чтобы работали админ-команды
ADMIN_IDS = [1997428703] 
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'
BOT_USERNAME = "GalacticSHBOT" # Используем имя из вашего запроса для ссылок

# Каналы для обязательной подписки
REQUIRED_CHANNELS = [
    {"username": "@chatvibee_bet", "link": "https://t.me/chatvibee_bet"},
    {"username": "@nvibee_bet", "link": "https://t.me/nvibee_bet"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Хранилище в памяти
users = {}
promos = {}
active_games = {} 

# --- НАСТРОЙКИ ФЕРМЫ ---
FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.00001, "scale": 1.2},
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.00004, "scale": 1.2},
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.00007, "scale": 1.3}
}
MAX_CARDS_PER_TYPE = 3  # Лимит карт одного типа

# --- НАСТРОЙКИ РАБОТЫ (КЛАДОИСКАТЕЛЬ) ---
WORK_CONFIG = {
    "shovel_price": 5000,
    "detector_price": 25000,
    "cooldown": 600, # 10 минут
    "rewards": [1000, 5000] # Мин/макс база
}

# --- DB & SYNC ---
def sync_load():
    global users, promos
    service = get_drive_service()
    if not service: return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8').strip()
        if content:
            data = json.loads(content)
            users = {int(k): v for k, v in data.get("users", {}).items()}
            promos = data.get("promos", {})
    except Exception as e:
        logging.error(f"Ошибка загрузки БД: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data_to_save = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e:
        logging.error(f"Ошибка сохранения БД: {e}")

async def save_data(): 
    await asyncio.to_thread(sync_save)

def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

# --- УТИЛИТЫ ---
def format_num(num):
    num = float(num)
    if num < 1000: return str(int(num))
    suffixes = [(1e12, "кккк"), (1e9, "ккк"), (1e6, "кк"), (1e3, "к")]
    for val, suff in suffixes:
        if num >= val:
            res = num / val
            return f"{int(res) if res == int(res) else round(res, 2)}{suff}"
    return str(int(num))

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all", "вабанк", "max"]: return int(balance)
    multipliers = {"кккк": 1e12, "ккк": 1e9, "кк": 1e6, "к": 1e3}
    for suff, mult in multipliers.items():
        if text.endswith(suff):
            try: return int(float(text[:-len(suff)]) * mult)
            except: pass
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 5000, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, 
            "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
        asyncio.create_task(save_data())
    
    # Миграция и проверка полей
    if "farm" not in users[uid] or not isinstance(users[uid]["farm"], dict):
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    
    # Убедимся, что все ключи карт существуют
    for key in FARM_CONFIG:
        if key not in users[uid]["farm"]:
            users[uid]["farm"][key] = 0
            
    if "shovel" not in users[uid]: users[uid]["shovel"] = 0
    if "detector" not in users[uid]: users[uid]["detector"] = 0
    if "last_work" not in users[uid]: users[uid]["last_work"] = 0
    if "xp" not in users[uid]: users[uid]["xp"] = 0
    if "lvl" not in users[uid]: users[uid]["lvl"] = 1
    
    # Удаляем банк, если он есть (Legacy cleanup)
    if "bank" in users[uid]: del users[uid]["bank"]
    
    return users[uid]

def check_level_up(u):
    if u['lvl'] >= 100: return
    req = u['lvl'] * 100 
    if u['xp'] >= req:
        u['xp'] -= req
        u['lvl'] += 1
        return True
    return False

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_subscription(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            # Пытаемся получить статус пользователя
            member = await bot.get_chat_member(chat_id=channel["username"], user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                return False
        except Exception as e:
            # Если ошибка (бот не админ или канал приватный без доступа), считаем False для безопасности
            logging.error(f"Ошибка проверки подписки {channel['username']}: {e}")
            return False 
    return True

# --- MIDDLEWARE (БАН + ПОДПИСКА) ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def global_check(handler, event, data):
    uid = event.from_user.id
    u = get_user(uid, event.from_user.first_name)
    
    if u.get('banned'):
        return 
        
    return await handler(event, data)

# --- START & HELP ---
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    is_sub = await check_subscription(message.from_user.id)
    
    if not is_sub:
        kb = []
        for ch in REQUIRED_CHANNELS:
            kb.append([InlineKeyboardButton(text=f"Подписаться на {ch['username']}", url=ch['link'])])
        kb.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub_start")])
        
        return await message.answer("🔒 <b>Для использования бота подпишитесь на наши каналы:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    # Обработка рефералов/промо
    args = command.args
    if args and args.startswith("promo_"):
        code = args.split("_")[1]
        await activate_promo(message, code)
        return

    txt = (
        "👋 <b>Добро Пожаловать в Vibe Bet!</b>\n"
        "Крути рулетку, рискуй в Краше, а также собирай свою ферму.\n\n"
        "🎲 <b>Игры:</b> 🎲 Кости, ⚽ Футбол, 🎰 Рулетка, 💎 Алмазы, 💣 Мины\n"
        "⛏️ <b>Заработок:</b> 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус\n\n"
        "👇 Жми <b>Помощь</b> для списка команд!"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Помощь", callback_data="help_menu")]
    ])
    
    try: 
        await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt, reply_markup=kb)
    except: 
        await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "check_sub_start")
async def check_sub_cb(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ <b>Спасибо за подписку!</b> Жмите /start")
    else:
        await call.answer("❌ Вы не подписались на все каналы!", show_alert=True)

@dp.callback_query(F.data == "help_menu")
async def help_cb(call: CallbackQuery):
    await cmd_help(call.message)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "💎 <b>ЦЕНТР ПОМОЩИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "🔹 <code>Рул [сумма] [число/цвет]</code> (кр, чер, зел)\n"
        "🔹 <code>Кости [сумма] [ставка]</code> (равно, больше, меньше)\n"
        "🔹 <code>Футбол [сумма] [ставка]</code> (гол, мимо)\n"
        "🔹 <code>Алмазы [сумма] [бомбы]</code> (1 или 2)\n"
        "🔹 <code>Мины [сумма]</code>\n\n"
        "⛏️ <b>ЗАРАБОТОК:</b>\n"
        "🔹 <code>Работа</code> — Копать клад (нужна лопата)\n"
        "🔹 <code>Ферма</code> — Майнинг биткоина\n"
        "🔹 <code>Бонус</code> — Ежечасная награда\n\n"
        "⚙️ <b>ПРОЧЕЕ:</b>\n"
        "🔹 <code>Профиль</code>, <code>Топ</code>\n"
        "🔹 <code>Перевести [ID] [Сумма]</code>\n"
        "🔹 <code>/pr [код]</code> — Активация промо\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    # Если это коллбек, то редактируем или новое сообщение
    try:
        await message.edit_text(txt)
    except:
        await message.answer(txt)

# --- АДМИН КОМАНДЫ ---
@dp.message(Command("hhh"))
async def admin_give_coins(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = command.args.split()
        target_id = int(args[0])
        amount = int(args[1])
        u = get_user(target_id)
        u['balance'] += amount
        await save_data()
        await message.answer(f"✅ Выдано <b>{format_num(amount)} $</b> игроку {target_id}")
    except: await message.answer("📝: `/hhh ID СУММА`")

@dp.message(Command("hhhh"))
async def admin_give_btc(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = command.args.split()
        target_id = int(args[0])
        amount = float(args[1])
        u = get_user(target_id)
        u['btc'] += amount
        await save_data()
        await message.answer(f"✅ Выдано <b>{amount} BTC</b> игроку {target_id}")
    except: await message.answer("📝: `/hhhh ID BTC`")

@dp.message(Command("lvl"))
async def admin_set_lvl(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = command.args.split()
        target_id = int(args[0])
        val = int(args[1])
        u = get_user(target_id)
        u['lvl'] = val
        await save_data()
        await message.answer(f"✅ Уровень игрока {target_id} установлен на <b>{val}</b>")
    except: await message.answer("📝: `/lvl ID LVL`")

# --- ПРОФИЛЬ, ТОП, БОНУС, ПЕРЕВОД ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    req_xp = u['lvl'] * 100
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.8f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{req_xp} XP)\n"
        f"🎒 Инструменты: {'✅' if u['shovel'] else '❌'} {'✅' if u['detector'] else '❌'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = time.time()
    if now - u['last_bonus'] < 3600:
        rem_sec = int(3600 - (now - u['last_bonus']))
        m, s = divmod(rem_sec, 60)
        return await message.answer(f"⏳ <b>Бонус доступен через: {m} мин {s} сек</b>")
    
    base = random.randint(10000, 50000)
    extra = u['lvl'] * 5000
    total = base + extra
    
    u['balance'] += total
    u['last_bonus'] = now
    u['xp'] += 10
    check_level_up(u)
    
    await save_data()
    await message.answer(f"🎁 <b>Почасовой бонус: {format_num(total)} $</b>\n(База: {format_num(base)} + Уровень: {format_num(extra)})")

@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    try:
        args = message.text.split()
        if len(args) < 3: raise ValueError
        target_id = int(args[1])
        amount = parse_amount(args[2], get_user(message.from_user.id)['balance'])
        
        sender = get_user(message.from_user.id)
        
        if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
        if amount > sender['balance']: return await message.answer("❌ Недостаточно средств!")
        if message.from_user.id == target_id: return await message.answer("❌ Себе нельзя!")
        if target_id not in users: return await message.answer("❌ Игрок не найден (пусть нажмет /start)!")
            
        receiver = get_user(target_id)
        sender['balance'] -= amount
        receiver['balance'] += amount
        
        await save_data()
        await message.answer(f"✅ Перевод <b>{format_num(amount)} $</b> игроку {receiver['name']} успешен!")
        try:
            await bot.send_message(target_id, f"💸 <b>Вам перевели {format_num(amount)} $</b> от {sender['name']}")
        except: pass
    except:
        await message.answer("📝 Формат: <code>Перевести [ID] [Сумма]</code>")

@dp.message(Command("pr"))
async def cmd_pr(message: Message, command: CommandObject):
    if not command.args: return await message.answer("📝 Введите код: `/pr CODE`")
    await activate_promo(message, command.args)

async def activate_promo(message: Message, code: str):
    u = get_user(message.from_user.id)
    if code not in promos: return await message.answer("❌ Промокод не найден или закончился!")
    if code in u['used_promos']: return await message.answer("❌ Вы уже активировали этот код!")
    
    promos[code]['uses'] -= 1
    reward = promos[code]['reward']
    u['balance'] += reward
    u['used_promos'].append(code)
    
    if promos[code]['uses'] <= 0: del promos[code]
    await save_data()
    await message.answer(f"✅ <b>Промокод активирован!</b>\nНачислено: <b>{format_num(reward)} $</b>")

@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS: 
        return # Игнор не админов

    try:
        args = message.text.split()
        if len(args) < 4: raise ValueError
        code = args[2]
        reward = parse_amount(args[3], 0)
        uses = int(args[4])
        
        if reward <= 0 or uses <= 0: return await message.answer("❌ Неверные значения!")
        if code in promos: return await message.answer("❌ Такой код уже есть!")
        
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        
        # Получаем имя бота для ссылки (или используем константу)
        bot_link = f"https://t.me/{BOT_USERNAME}?start=promo_{code}"
        
        txt = (
            f"Промокод {code} создан! ТЫК ДЛЯ АКТИВАЦИИ\n"
            f"Начисление: {format_num(reward)} монет\n"
            f"Активаций: {uses}\n\n"
            f"Чтобы активировать: /pr {code}\n"
            f"Или ссылка: {bot_link}"
        )
        await message.answer(txt)
    except: 
        await message.answer("📝 Формат: <code>Создать промо [КОД] [Сумма] [Кол-во]</code>")

# ================= РАБОТА (КЛАДОИСКАТЕЛЬ) =================

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    
    if u['shovel'] == 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🛒 Купить лопату ({format_num(WORK_CONFIG['shovel_price'])}$)", callback_data="work_buy_shovel")]
        ])
        return await message.answer("👷 <b>РАБОТА КЛАДОИСКАТЕЛЕМ</b>\n\n❌ У вас нет лопаты! Без нее копать нельзя.", reply_markup=kb)

    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']:
        rem = int(WORK_CONFIG['cooldown'] - (now - u['last_work']))
        m, s = divmod(rem, 60)
        return await message.answer(f"⏳ <b>Отдых!</b> Копать можно через: {m} мин {s} сек")
    
    txt = "👷 <b>ГДЕ БУДЕМ КОПАТЬ?</b>\nВыберите место раскопок:"
    if u['detector']:
        txt += "\n✅ <b>Металлоискатель активен!</b> Шанс найти клад выше."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🕳 Яма 1", callback_data="work_dig_1"),
            InlineKeyboardButton(text="🕳 Яма 2", callback_data="work_dig_2"),
            InlineKeyboardButton(text="🕳 Яма 3", callback_data="work_dig_3")
        ],
        [InlineKeyboardButton(text="🏪 Магазин инструментов", callback_data="work_shop")]
    ])
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "work_shop")
async def work_shop_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    kb = []
    if not u['shovel']:
        kb.append([InlineKeyboardButton(text=f"🛒 Лопата - {format_num(WORK_CONFIG['shovel_price'])}$", callback_data="work_buy_shovel")])
    if not u['detector']:
        kb.append([InlineKeyboardButton(text=f"📡 Металлоискатель - {format_num(WORK_CONFIG['detector_price'])}$", callback_data="work_buy_detector")])
    
    if not kb:
        return await call.answer("✅ У вас уже куплены все инструменты!", show_alert=True)
        
    await call.message.edit_text("🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("work_buy_"))
async def work_buy_cb(call: CallbackQuery):
    item = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    price = WORK_CONFIG[f"{item}_price"]
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    u['balance'] -= price
    u[item] = 1
    await save_data()
    await call.answer("✅ Инструмент куплен!", show_alert=True)
    await call.message.delete()
    await cmd_work(call.message)

@dp.callback_query(F.data.startswith("work_dig_"))
async def work_dig_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    
    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']:
        return await call.answer("⏳ Рано!", show_alert=True)

    u['last_work'] = now
    
    luck = random.random()
    threshold = 0.1 if u['detector'] else 0.3
    
    if luck < threshold:
        txt = "🍂 <b>Пусто...</b> В этой яме только грязь."
    else:
        base_reward = random.randint(WORK_CONFIG['rewards'][0], WORK_CONFIG['rewards'][1])
        if u['detector']:
            base_reward = int(base_reward * 1.5) 
        
        u['balance'] += base_reward
        u['xp'] += 5
        check_level_up(u)
        txt = f"⚱️ <b>КЛАД!</b> Вы откопали древнюю вазу.\nПродано за: <b>{format_num(base_reward)} $</b>"
    
    await save_data()
    await call.message.edit_text(txt)

# ================= ИГРЫ =================

# --- РУЛЕТКА ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    
    valid_bets = ["к", "крас", "красный", "ч", "черн", "черный", "з", "зел", "зеленый", "чет", "нечет"]
    
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        choice = args[2]

        # --- СТРОГАЯ ПРОВЕРКА ВВОДА (РУЛЕТКА) ---
        if not choice.isdigit() and choice not in valid_bets:
             return await message.answer("❌ Неверная ставка! Используйте: кр, чер, зел, чет, нечет или число 0-36")

        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        u['balance'] -= bet
        n = random.randint(0, 36)
        
        if n == 0: color = "зеленый"
        elif n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]: color = "красный"
        else: color = "черный"
        
        parity = "четное" if n!=0 and n%2==0 else "нечетное" if n!=0 else ""
        
        win = 0
        if choice in ["к", "крас", "красный"] and color == "красный": win = bet*2
        elif choice in ["ч", "черн", "черный"] and color == "черный": win = bet*2
        elif choice in ["з", "зел", "зеленый"] and color == "зеленый": win = bet*14
        elif choice.isdigit() and int(choice) == n: win = bet*36
        elif choice in ["чет"] and parity == "четное": win = bet*2
        elif choice in ["нечет"] and parity == "нечетное": win = bet*2
        
        u['balance'] += win
        res_line = f"🎉 <b>Выигрыш: {format_num(win)} $</b>" if win > 0 else "❌ <b>Проигрыш</b>"
            
        await message.answer(
            f"🎰 <b>Vibe Рулетка</b>\n"
            f"💸 Ставка: {format_num(bet)} $\n"
            f"{res_line}\n"
            f"📈 Выпало: <b>{n}</b> ({color}, {parity})\n"
            f"💰 Баланс: {format_num(u['balance'])} $"
        )
        await save_data()
    except: await message.answer("📝 Пример: <code>Рул 1к к</code> (к, ч, з, чет, нечет, 0-36)")

# --- КОСТИ (С ПРОВЕРКОЙ СЛОВ) ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice_real(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    
    valid_outcomes = {
        "equal": ["равно", "equal", "=", "7", "семь"],
        "over": ["больше", "б", "over", ">"],
        "under": ["меньше", "м", "under", "<"]
    }
    
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        outcome_raw = args[2]
        
        outcome_type = None
        for k, v in valid_outcomes.items():
            if outcome_raw in v:
                outcome_type = k
                break
        
        if not outcome_type:
            return await message.answer("❌ <b>Ошибка ввода!</b>\nСтавки: <code>равно</code>, <code>больше</code>, <code>меньше</code>")

        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        u['balance'] -= bet
        msg1 = await message.answer_dice(emoji="🎲")
        msg2 = await message.answer_dice(emoji="🎲")
        await asyncio.sleep(3.5)
        
        total = msg1.dice.value + msg2.dice.value
        win_mult = 0
        
        if outcome_type == "equal" and total == 7: win_mult = 5.8
        elif outcome_type == "over" and total > 7: win_mult = 2.3
        elif outcome_type == "under" and total < 7: win_mult = 2.3
        
        win_val = int(bet * win_mult)
        res_txt = f"🎲 <b>КОСТИ: {msg1.dice.value} + {msg2.dice.value} = {total}</b>\n"
        
        if win_val > 0:
            u['balance'] += win_val
            res_txt += f"🎉 <b>Выигрыш: {format_num(win_val)} $</b>"
        else:
            res_txt += f"❌ <b>Проигрыш</b>"
        
        await message.answer(res_txt + f"\n💰 Баланс: {format_num(u['balance'])} $")
        await save_data()
    except: await message.answer("📝: <code>Кости 10к больше</code>")

# --- ФУТБОЛ (С ПРОВЕРКОЙ СЛОВ) ---
@dp.message(F.text.lower().startswith("футбол"))
async def game_football_real(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    valid_goals = ["гол", "goal", "g"]
    valid_miss = ["мимо", "miss", "m"]
    
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        outcome_raw = args[2]
        
        outcome_type = None
        if outcome_raw in valid_goals: outcome_type = "goal"
        elif outcome_raw in valid_miss: outcome_type = "miss"
        
        if not outcome_type: return await message.answer("❌ Ставьте на: <code>гол</code> или <code>мимо</code>")
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        u['balance'] -= bet
        msg = await message.answer_dice(emoji="⚽")
        await asyncio.sleep(3.5)
        
        is_goal = msg.dice.value in [3, 4, 5]
        win = 0
        
        if outcome_type == "goal" and is_goal: win = int(bet * 1.8)
        elif outcome_type == "miss" and not is_goal: win = int(bet * 2.3)
        
        if win > 0:
            u['balance'] += win
            txt = f"⚽ <b>ГООООЛ!</b>\n🎉 Выигрыш: {format_num(win)} $"
        else:
            txt = f"⚽ {'МИМО!' if not is_goal else 'ВРАТАРЬ СЕЙВ!'} \n❌ Проигрыш"
            
        await message.answer(txt + f"\n💰 Баланс: {format_num(u['balance'])} $")
        await save_data()
    except: await message.answer("📝: <code>Футбол 10к гол</code>")

# --- АЛМАЗЫ (НОВАЯ ВИЗУАЛИЗАЦИЯ) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_dia_start(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        bet = parse_amount(args[1], u['balance'])
        bombs = 1
        if len(args) > 2: bombs = int(args[2])
        
        if bombs not in [1, 2]: return await message.answer("❌ Можно выбрать 1 или 2 бомбы!")
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        
        u['balance'] -= bet
        gid = f"dm_{message.from_user.id}_{int(time.time())}"
        
        grid = []
        for _ in range(10):
            row = [False] * 3
            b_indices = random.sample(range(3), bombs)
            for idx in b_indices: row[idx] = True
            grid.append(row)
        
        active_games[gid] = {
            "type": "dm", "uid": message.from_user.id, "bet": bet, 
            "grid": grid, "current_row": 0, "mult": 1.0, 
            "bombs_count": bombs, "history": []
        }
        
        await message.answer(
            f"💠 Игра началась!\n\n🧨 Мин: {bombs}\n💸 Ставка: {format_num(bet)}\n📊 Множитель: x1.00",
            reply_markup=get_tower_kb(gid)
        )
        await save_data()
    except: await message.answer("📝: <code>Алмазы [сумма] [бомбы 1-2]</code>")

def get_tower_kb(gid, finished=False, lost_at_col=None):
    g = active_games.get(gid)
    if not g and not finished: return None
    kb = []
    
    start_viz = max(0, g['current_row'] - 4)
    end_viz = min(10, start_viz + 8)
    
    for r in range(end_viz - 1, start_viz - 1, -1):
        row_btns = []
        is_current = (r == g['current_row']) and not finished
        is_passed = r < g['current_row']
        
        for c in range(3):
            txt = "▪️"
            cb = "ignore"
            if is_current:
                txt = "🟦"; cb = f"dm_go_{gid}_{c}"
            elif is_passed:
                txt = "💎" if c == g['history'][r] else "▪️"
            elif finished and r == g['current_row']:
                if lost_at_col is not None:
                    if g['grid'][r][c]: txt = "💣"
                    elif c == lost_at_col: txt = "💥"
                    else: txt = "▪️"
            else: txt = "▫️"
            row_btns.append(InlineKeyboardButton(text=txt, callback_data=cb))
        kb.append(row_btns)
        
    if not finished:
        kb.append([InlineKeyboardButton(text="💰 Забрать", callback_data=f"dm_cash_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- ФЕРМА (ИСПРАВЛЕННЫЙ СБОР И ЛИМИТ) ---
@dp.callback_query(F.data == "farm_collect")
async def farm_collect_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    pending_btc, _, _ = calculate_farm_income(u)
    
    if pending_btc <= 0.00000001:
        return await call.answer("⚠️ Копить еще нечего!", show_alert=True)
    
    u['btc'] += pending_btc
    # Исправлено: обновляем время, карты НЕ пропадают
    u['farm']['last_collect'] = time.time()
    await save_data()
    await call.answer(f"✅ Собрано {pending_btc:.8f} BTC", show_alert=True)
    await cmd_farm(call.message)

@dp.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_cb(call: CallbackQuery):
    key = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    cfg = FARM_CONFIG[key]
    
    # Исправлено: лимит 3 видеокарты
    if u['farm'][key] >= 3:
         return await call.answer("🚫 Достигнут лимит (3 шт)!", show_alert=True)
         
    price = int(cfg['base_price'] * (cfg['scale'] ** u['farm'][key]))
    if u['balance'] < price: return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    # Сбор перед покупкой
    pending, _, _ = calculate_farm_income(u)
    u['btc'] += pending
    
    u['balance'] -= price
    u['farm'][key] += 1
    u['farm']['last_collect'] = time.time()
    
    await save_data()
    await call.answer(f"✅ Куплено: {cfg['name']}", show_alert=True)
    await farm_shop_cb(call)

# --- ПРОМОКОДЫ (ФОРМАТ ПО ЗАПРОСУ) ---
@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        code = args[2]
        reward = parse_amount(args[3], 0)
        uses = int(args[4])
        
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        
        bot_link = f"https://t.me/{BOT_USERNAME}?start=promo_{code}"
        txt = (
            f"Промокод {code} создан! ТЫК ДЛЯ АКТИВАЦИИ\n"
            f"Начисление: {format_num(reward)} монет\n"
            f"Активаций: {uses}\n\n"
            f"Чтобы активировать: /pr {code}\n"
            f"Или ссылка: {bot_link}"
        )
        await message.answer(txt)
    except: await message.answer("📝: <code>Создать промо [КОД] [Сумма] [Кол-во]</code>")

# --- ТОП (ВМЕСТО НИКОВ - ID) ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    for i, (uid, u) in enumerate(sorted_users):
        # Маскируем ID для красоты: 123456...78
        masked_id = str(uid)[:4] + "..." + str(uid)[-2:]
        txt += f"{i+1}. ID: <code>{masked_id}</code> — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(txt)

# --- ПРОФИЛЬ (УБРАН БАНК) ---
@dp.message(F.text.lower().in_({"профиль", "я"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.8f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)
    # --- ТОП (ВМЕСТО НИКОВ — ID) ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (uid, u) in enumerate(sorted_users):
        medal = medals.get(i, f"{i+1}.")
        # Показываем только ID (можно скрыть часть цифр для приватности)
        masked_id = f"<code>{uid}</code>"
        txt += f"{medal} ID: {masked_id} — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(txt)

# --- РАБОТА (КЛАДОИСКАТЕЛЬ) ---
@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    if u['shovel'] == 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🛒 Купить лопату ({format_num(WORK_CONFIG['shovel_price'])}$)", callback_data="work_buy_shovel")]
        ])
        return await message.answer("👷 <b>РАБОТА</b>\n\n❌ У вас нет лопаты!", reply_markup=kb)

    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']:
        rem = int(WORK_CONFIG['cooldown'] - (now - u['last_work']))
        return await message.answer(f"⏳ Отдых! Еще {rem // 60} мин {rem % 60} сек")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕳 Яма 1", callback_data="work_dig_1"),
         InlineKeyboardButton(text="🕳 Яма 2", callback_data="work_dig_2"),
         InlineKeyboardButton(text="🕳 Яма 3", callback_data="work_dig_3")]
    ])
    await message.answer("👷 <b>ГДЕ БУДЕМ КОПАТЬ?</b>", reply_markup=kb)

# --- МИНЫ (ИСПРАВЛЕННЫЕ) ---
def get_mines_kb(gid, opened, finish=False, grid=None):
    kb = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5+c
            txt = "⬜️"
            if finish:
                if grid[idx]: txt = "💣"
                elif opened[idx]: txt = "💎"
                else: txt = "🔹"
            elif opened[idx]: txt = "💎"
            row.append(InlineKeyboardButton(text=txt, callback_data="ignore" if opened[idx] or finish else f"mn_click_{gid}_{idx}"))
        kb.append(row)
    if not finish:
        kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"mn_stop_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("mn_"))
async def mines_callback(call: CallbackQuery):
    data = call.data.split("_")
    # Обработка клика или стопа
    if data[1] == "click":
        gid = "_".join(data[2:-1])
        idx = int(data[-1])
    else:
        gid = "_".join(data[2:])
    
    game = active_games.get(gid)
    if not game: return await call.answer("Игра окончена")

    if data[1] == "stop":
        win = int(game['bet'] * game['mult'])
        u = get_user(game['uid'])
        u['balance'] += win
        await call.message.edit_text(f"💰 <b>ВЫИГРЫШ: {format_num(win)} $</b>", 
                                     reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]; await save_data(); return

    if game['grid'][idx]:
        await call.message.edit_text(f"💥 <b>БАБАХ! Проигрыш</b>", 
                                     reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]
    else:
        game['opened'][idx] = True
        game['mult'] += 0.3 # Коэффициент за каждый алмаз
        await call.message.edit_text(f"💎 <b>МИНЫ</b> | Множитель: x{game['mult']:.2f}", 
                                     reply_markup=get_mines_kb(gid, game['opened']))
    await save_data()

# --- ПРОВЕРКА ПОДПИСКИ (ФИКС) ---
async def check_subscription(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["username"], user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                return False
        except Exception:
            return False 
    return True

# --- ГЛАВНЫЙ ЗАПУСК (БЕЗ БАНКА) ---
async def main():
    sync_load() # Загрузка БД
    
    # Настройка веб-сервера для логов/мониторинга (опционально)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Active"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    # Запуск бота
    logging.info("Бот запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")

        
