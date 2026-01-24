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

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN") 
# Admin ID
ADMIN_IDS = [1997428703] 
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'
BOT_USERNAME = "GalacticSHBOT" # Changed based on your request context

# Channels for mandatory subscription
REQUIRED_CHANNELS = [
    {"username": "@chatvibee_bet", "link": "https://t.me/chatvibee_bet"},
    {"username": "@nvibee_bet", "link": "https://t.me/nvibee_bet"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Memory Storage
users = {}
promos = {}
active_games = {} 

# --- FARM CONFIG ---
FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.00001, "scale": 1.2},
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.00004, "scale": 1.2},
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.00007, "scale": 1.3}
}
MAX_CARDS_PER_TYPE = 3

# --- WORK CONFIG ---
WORK_CONFIG = {
    "shovel_price": 5000,
    "detector_price": 25000,
    "cooldown": 600, # 10 minutes
    "rewards": [1000, 5000] 
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
            # Ensure keys are integers for IDs
            users = {int(k): v for k, v in data.get("users", {}).items()}
            promos = data.get("promos", {})
    except Exception as e:
        logging.error(f"Error loading DB: {e}")

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
        logging.error(f"Error saving DB: {e}")

async def save_data(): 
    await asyncio.to_thread(sync_save)

def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

# --- UTILS ---
def format_num(num):
    try:
        num = float(num)
    except: return "0"
    if num < 1000: return str(int(num))
    suffixes = [(1e12, "кккк"), (1e9, "ккк"), (1e6, "кк"), (1e3, "к")]
    for val, suff in suffixes:
        if num >= val:
            res = num / val
            return f"{int(res) if res == int(res) else round(res, 2)}{suff}"
    return str(int(num))

def parse_amount(text, balance):
    if not text: return None
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all", "вабанк", "max"]: return int(balance)
    multipliers = {"кккк": 1e12, "ккк": 1e9, "кк": 1e6, "к": 1e3}
    for suff, mult in multipliers.items():
        if text.endswith(suff):
            try: return int(float(text[:-len(suff)]) * mult)
            except: pass
    try: 
        val = int(float(text))
        return val if val > 0 else None
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
        # Save immediately to prevent data loss on new user
        asyncio.create_task(save_data())
    
    # Migration checks
    if "farm" not in users[uid] or not isinstance(users[uid]["farm"], dict):
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    
    # Ensure all keys exist
    defaults = {
        "balance": 5000, "btc": 0.0, "lvl": 1, "xp": 0, 
        "shovel": 0, "detector": 0, "last_work": 0, 
        "last_bonus": 0, "used_promos": []
    }
    for k, v in defaults.items():
        if k not in users[uid]: users[uid][k] = v

    return users[uid]

def check_level_up(u):
    if u['lvl'] >= 100: return
    req = u['lvl'] * 100 
    if u['xp'] >= req:
        u['xp'] -= req
        u['lvl'] += 1
        return True
    return False

# --- SUBSCRIPTION CHECK LOGIC ---
async def is_subscribed(user_id):
    # Admin bypass
    if user_id in ADMIN_IDS: return True
    
    for channel in REQUIRED_CHANNELS:
        try:
            chat_id = channel["username"]
            # We assume bot is admin in these channels
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                return False
        except Exception as e:
            # If bot can't check (not admin), we default to False to force fix
            logging.error(f"Sub check error for {chat_id}: {e}")
            return False 
    return True

async def check_sub_middleware(message: Message):
    """Returns True if subscribed, sends error message if not."""
    if not await is_subscribed(message.from_user.id):
        kb = []
        for ch in REQUIRED_CHANNELS:
            kb.append([InlineKeyboardButton(text=f"Подписаться на {ch['username']}", url=ch['link'])])
        kb.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub_re")])
        
        await message.answer("🔒 <b>Для использования бота подпишитесь на наши каналы:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return False
    return True

# --- GLOBAL HANDLER ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def global_check(handler, event, data):
    user = event.from_user
    if not user: return
    u = get_user(user.id, user.first_name)
    
    if u.get('banned'): return 
    return await handler(event, data)

# --- START & HELP ---
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    # Check subscription immediately
    if not await check_sub_middleware(message):
        return

    # Promo activation via link
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
        [InlineKeyboardButton(text="💎 Помощь", callback_data="cmd_help_cb")]
    ])

    try: 
        await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt, reply_markup=kb)
    except: 
        await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "check_sub_re")
async def check_sub_cb_re(call: CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ <b>Спасибо за подписку!</b> Жмите /start")
    else:
        await call.answer("❌ Вы не подписались на все каналы!", show_alert=True)

@dp.callback_query(F.data == "cmd_help_cb")
async def help_callback(call: CallbackQuery):
    await cmd_help(call.message)
    await call.answer()

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "💎 <b>ЦЕНТР ПОМОЩИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "🔹 <code>Рул [сумма] [исход]</code> (кр, чер, зел)\n"
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
    await message.answer(txt)

# --- ADMIN COMMANDS ---
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
        await bot.send_message(target_id, f"💳 Администратор выдал вам <b>{format_num(amount)} $</b>")
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

# --- PROFILE, TOP, BONUS, TRANSFER ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    req_xp = u['lvl'] * 100
    txt = (
        f"👤 <b>ПРОФИЛЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.8f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{req_xp} XP)\n"
        f"🎒 Инструменты: {'✅' if u['shovel'] else '❌'} {'✅' if u['detector'] else '❌'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    if not await check_sub_middleware(message): return
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (uid, u) in enumerate(sorted_users):
        medal = medals.get(i, f"{i+1}.")
        # Showing ID instead of Name
        txt += f"{medal} ID: <code>{uid}</code> — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(txt)

@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    if not await check_sub_middleware(message): return
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
    if not await check_sub_middleware(message): return
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
        await message.answer(f"✅ Перевод <b>{format_num(amount)} $</b> на ID {target_id} успешен!")
        try:
            await bot.send_message(target_id, f"💸 <b>Вам перевели {format_num(amount)} $</b> от ID {message.from_user.id}")
        except: pass
    except:
        await message.answer("📝 Формат: <code>Перевести [ID] [Сумма]</code>")

# --- PROMO SYSTEM ---
@dp.message(Command("pr"))
async def cmd_pr(message: Message, command: CommandObject):
    if not await check_sub_middleware(message): return
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
    # Strictly Admin Only
    if message.from_user.id not in ADMIN_IDS: return 
    try:
        args = message.text.split()
        if len(args) < 5: raise ValueError
        code = args[2]
        reward = parse_amount(args[3], 0)
        uses = int(args[4])
        
        if reward <= 0 or uses <= 0: return await message.answer("❌ Неверные значения!")
        if code in promos: return await message.answer("❌ Такой код уже есть!")
        
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        
        bot_user = await bot.get_me()
        bot_link = f"https://t.me/{bot_user.username}?start=promo_{code}"
        
        # Exact requested format
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

# ================= WORK =================

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    if not await check_sub_middleware(message): return
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

# ================= GAMES =================

# --- ROULETTE ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    
    # Строгая валидация исходов
    valid_colors = ["к", "крас", "красный", "ч", "черн", "черный", "з", "зел", "зеленый"]
    
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        choice = args[2]
        
        # Проверяем: это число 0-36 ИЛИ валидный цвет?
        is_num = choice.isdigit() and 0 <= int(choice) <= 36
        is_color = choice in valid_colors
        
        if not (is_num or is_color):
            return await message.answer("❌ <b>Ошибка ставки!</b>\nИспользуйте цвета: `кр`, `чер`, `зел`\nИли число: `0-36`")

        if not bet or bet < 10: return await message.answer("❌ Минимальная ставка 10 $")
        if bet > u['balance']: return await message.answer("❌ Недостаточно средств!")
        
        u['balance'] -= bet
        n = random.randint(0, 36)
        
        # Определение цвета выпавшего числа
        if n == 0: color = "зеленый"
        elif n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]: color = "красный"
        else: color = "черный"
        
        win = 0
        # Логика победы
        if choice in ["к", "крас", "красный"] and color == "красный": win = bet*2
        elif choice in ["ч", "черн", "черный"] and color == "черный": win = bet*2
        elif choice in ["з", "зел", "зеленый"] and color == "зеленый": win = bet*14
        elif choice.isdigit() and int(choice) == n: win = bet*36
        
        u['balance'] += win
        res_line = f"🎉 <b>Выигрыш: {format_num(win)} $</b>" if win > 0 else "❌ <b>Проигрыш</b>"
            
        await message.answer(
            f"🎰 <b>Vibe Рулетка</b>\n"
            f"💸 Ставка: {format_num(bet)} $\n"
            f"{res_line}\n"
            f"📈 Выпало: <b>{n}</b> ({color})\n"
            f"💰 Баланс: {format_num(u['balance'])} $"
        )
        await save_data()
    except ValueError: await message.answer("📝 Пример: <code>Рул 1к к</code> (к, ч, з, 0-36)")

# --- DICE (КОСТИ) ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice_real(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    
    # Допустимые варианты ввода
    valid_outcomes = {
        "equal": ["равно", "=", "7", "семь"],
        "over": ["больше", "б", ">"],
        "under": ["меньше", "м", "<"]
    }
    
    try:
        bet = parse_amount(args[1], u['balance'])
        outcome_raw = args[2]
        
        outcome_type = None
        for k, v in valid_outcomes.items():
            if outcome_raw in v:
                outcome_type = k
                break
        
        if not outcome_type:
            return await message.answer("❌ <b>Ошибка ставки!</b>\nИспользуйте: `больше`, `меньше`, `равно`")

        if not bet or bet < 10: return await message.answer("❌ Минимальная ставка 10 $")
        if bet > u['balance']: return await message.answer("❌ Недостаточно средств!")
        
        u['balance'] -= bet
        
        # Бросаем 2 кубика
        msg1 = await message.answer_dice(emoji="🎲")
        msg2 = await message.answer_dice(emoji="🎲")
        await asyncio.sleep(3.5)
        
        total = msg1.dice.value + msg2.dice.value
        win_mult = 0
        
        # Коэффициенты
        if outcome_type == "equal" and total == 7: win_mult = 5.7
        elif outcome_type == "over" and total > 7: win_mult = 2.2
        elif outcome_type == "under" and total < 7: win_mult = 2.2
        
        win_val = int(bet * win_mult)
        res_txt = f"🎲 <b>КОСТИ: {msg1.dice.value} + {msg2.dice.value} = {total}</b>\n"
        
        if win_val > 0:
            u['balance'] += win_val
            res_txt += f"🎉 <b>Выигрыш: {format_num(win_val)} $</b> (x{win_mult})"
        else:
            res_txt += f"❌ <b>Проигрыш</b>"
        
        await message.answer(res_txt + f"\n💰 Баланс: {format_num(u['balance'])} $")
        await save_data()
    except IndexError: await message.answer("📝: <code>Кости 10к больше</code>")

# --- FOOTBALL ---
@dp.message(F.text.lower().startswith("футбол"))
async def game_football_real(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    
    valid_goals = ["гол", "goal", "g"]
    valid_miss = ["мимо", "miss", "m"]
    
    try:
        bet = parse_amount(args[1], u['balance'])
        outcome_raw = args[2]
        
        outcome_type = None
        if outcome_raw in valid_goals: outcome_type = "goal"
        elif outcome_raw in valid_miss: outcome_type = "miss"
        
        if not outcome_type: return await message.answer("❌ <b>Ошибка ставки!</b>\nИспользуйте: `гол` или `мимо`")
        if not bet or bet < 10: return await message.answer("❌ Минимальная ставка 10 $")
        if bet > u['balance']: return await message.answer("❌ Недостаточно средств!")
        
        u['balance'] -= bet
        msg = await message.answer_dice(emoji="⚽")
        await asyncio.sleep(3.5)
        
        # 3, 4, 5 = Гол. 1, 2 = Мимо/Штанга.
        is_goal = msg.dice.value in [3, 4, 5]
        win = 0
        
        if outcome_type == "goal" and is_goal: win = int(bet * 1.8)
        elif outcome_type == "miss" and not is_goal: win = int(bet * 2.2)
        
        if win > 0:
            u['balance'] += win
            txt = f"⚽ <b>ГООООЛ!</b>\n🎉 Выигрыш: {format_num(win)} $"
        else:
            txt = f"⚽ {'МИМО!' if not is_goal else 'ВРАТАРЬ СЕЙВ!'} \n❌ Проигрыш"
            
        await message.answer(txt + f"\n💰 Баланс: {format_num(u['balance'])} $")
        await save_data()
    except IndexError: await message.answer("📝: <code>Футбол 10к гол</code>")

# --- DIAMONDS (TOWER STYLE) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_dia_start(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        bet = parse_amount(args[1], u['balance'])
        bombs = 1 # Всегда 1 бомба, как в классическом режиме Tower
        if len(args) > 2:
            bombs = int(args[2])
        
        if bombs != 1: return await message.answer("❌ В этой версии доступна только 1 бомба!")
        if not bet or bet < 10: return await message.answer("❌ Мин. ставка 10")
        if bet > u['balance']: return await message.answer("❌ Недостаточно средств")
        
        u['balance'] -= bet
        gid = f"tw_{message.from_user.id}_{int(time.time())}"
        
        # Коэффициенты как на фото
        multipliers = [1.2, 1.54, 1.93, 2.41, 3.01, 3.76, 4.70, 5.88, 7.35]
        
        active_games[gid] = {
            "type": "tower", 
            "uid": message.from_user.id, 
            "bet": bet, 
            "step": 0, 
            "mults": multipliers
        }
        
        await message.answer(
            f"💎 <b>Алмазы</b>\n"
            f"Мин: 1\n"
            f"💸 Ставка: {format_num(bet)} $\n"
            f"📊 Множитель: x{multipliers[0]}\n",
            reply_markup=get_tower_kb(gid, 0)
        )
        await save_data()
    except: await message.answer("📝: <code>Алмазы [сумма]</code>")

def get_tower_kb(gid, step, finish_state=None):
    # finish_state = {'win': Bool, 'correct_idx': int, 'clicked_idx': int}
    
    kb = []
    
    # 3 Кнопки в ряд
    row_btns = []
    for i in range(1, 4):
        txt = "❓"
        cb = f"tw_go_{gid}_{i}"
        
        if finish_state:
            cb = "ignore"
            if i == finish_state['correct_idx']: txt = "💎"
            elif i == finish_state['clicked_idx'] and not finish_state['win']: txt = "💣"
            else: txt = "⬜"
            
        row_btns.append(InlineKeyboardButton(text=f"{txt} {i}", callback_data=cb))
    
    kb.append(row_btns)
    
    # Кнопка Забрать (если игра активна и прошли хотя бы 1 шаг)
    if not finish_state and step > 0:
        kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"tw_cash_{gid}")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("tw_"))
async def tower_act(call: CallbackQuery):
    p = call.data.split("_")
    action = p[1]
    gid = "_".join(p[2:])
    
    if action == "cash":
        gid = "_".join(p[2:]) # fix parsing
        g = active_games.get(gid)
        if not g: return await call.answer("Игра окончена")
        
        mult = g['mults'][g['step']-1]
        win = int(g['bet'] * mult)
        
        u = get_user(g['uid'])
        u['balance'] += win
        
        await call.message.edit_text(f"💰 <b>Вы забрали: {format_num(win)} $</b> (x{mult})")
        del active_games[gid]
        await save_data()
        return

    # Игрок выбрал ячейку
    if action == "go":
        col_idx = int(p[-1]) # 1, 2, 3
        gid = "_".join(p[2:-1])
        g = active_games.get(gid)
        if not g: return await call.answer("Игра окончена")
        
        # Логика: 1 бомба, 2 алмаза в ряду.
        # Генерируем, где бомба (1, 2 или 3)
        bomb_pos = random.randint(1,3)
        
        if bomb_pos == col_idx:
            # Попал на бомбу
            await call.message.edit_text(
                f"💣 <b>БАБАХ!</b>\nПроигрыш: {format_num(g['bet'])} $",
                reply_markup=get_tower_kb(gid, g['step'], {'win': False, 'correct_idx': -1, 'clicked_idx': col_idx})
            )
            del active_games[gid]
        else:
            # Угадал
            g['step'] += 1
            if g['step'] >= len(g['mults']):
                # Дошел до конца
                win = int(g['bet'] * g['mults'][-1])
                u = get_user(g['uid'])
                u['balance'] += win
                await call.message.edit_text(f"💎 <b>ПОБЕДА! Максимум!</b>\nВыигрыш: {format_num(win)} $")
                del active_games[gid]
            else:
                next_mult = g['mults'][g['step']]
                curr_mult = g['mults'][g['step']-1]
                curr_win = int(g['bet'] * curr_mult)
                
                # "Новое поле" - просто обновляем сообщение с новым кэфом
                await call.message.edit_text(
                    f"💎 <b>УГАДАЛ!</b>\n"
                    f"⬆️ Следующий ход: x{next_mult}\n"
                    f"💰 Можно забрать: {format_num(curr_win)} $",
                    reply_markup=get_tower_kb(gid, g['step'])
                )
        await save_data()

# --- FARM BTC ---
def calculate_farm_income(u):
    now = time.time()
    last_collect = u['farm'].get('last_collect', now)
    
    btc_per_hour = 0
    total_cards = 0
    for key, cfg in FARM_CONFIG.items():
        count = u['farm'].get(key, 0)
        btc_per_hour += count * cfg['income']
        total_cards += count
        
    seconds_passed = now - last_collect
    if seconds_passed < 0: seconds_passed = 0
    income = (btc_per_hour / 3600) * seconds_passed
    return income, btc_per_hour, total_cards

@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    pending_btc, hourly_btc, total_cards = calculate_farm_income(u)
    
    # Отображаем кол-во и лимит
    txt = (
        f"🖥 <b>BTC ФЕРМА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Ваши видеокарты:</b>\n"
        f"🔹 RTX 3060: <b>{u['farm'].get('rtx3060', 0)}</b> / {MAX_CARDS_PER_TYPE}\n"
        f"🔹 RTX 4070: <b>{u['farm'].get('rtx4070', 0)}</b> / {MAX_CARDS_PER_TYPE}\n"
        f"🔹 RTX 4090: <b>{u['farm'].get('rtx4090', 0)}</b> / {MAX_CARDS_PER_TYPE}\n\n"
    )
    
    if total_cards == 0:
        txt += "⚠️ <i>У вас пока нет видеокарт. Купите их в магазине!</i>\n\n"
    else:
        txt += f"📉 Доход: <b>{hourly_btc:.8f} BTC/ч</b>\n"
        txt += f"💰 Намайнено: <b>{pending_btc:.8f} BTC</b>\n"
        
    txt += f"━━━━━━━━━━━━━━━━━━"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать доход", callback_data="farm_collect")],
        [InlineKeyboardButton(text="🛍 Купить видеокарты", callback_data="farm_shop")]
    ])
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "farm_collect")
async def farm_collect_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    pending_btc, _, _ = calculate_farm_income(u)
    
    if pending_btc <= 0.00000001:
        return await call.answer("⚠️ Копить еще нечего!", show_alert=True)
    
    u['btc'] += pending_btc
    u['farm']['last_collect'] = time.time()
    await save_data()
    
    await call.answer(f"✅ Собрано {pending_btc:.8f} BTC", show_alert=True)
    await cmd_farm(call.message)

@dp.callback_query(F.data == "farm_shop")
async def farm_shop_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    kb_list = []
    
    for key, cfg in FARM_CONFIG.items():
        count = u['farm'].get(key, 0)
        price = int(cfg['base_price'] * (cfg['scale'] ** count))
        
        # Если достигнут лимит, меняем кнопку
        if count >= MAX_CARDS_PER_TYPE:
            btn_text = f"{cfg['name']} (МАКС)"
            cb_data = "farm_full"
        else:
            btn_text = f"{cfg['name']} — {format_num(price)}$"
            cb_data = f"farm_buy_{key}"
            
        kb_list.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
        
    kb_list.append([InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")])
    await call.message.edit_text("🛍 <b>МАГАЗИН ВИДЕОКАРТ</b>\nЛимит: 3 шт каждого вида.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data == "farm_full")
async def farm_full_cb(call: CallbackQuery):
    await call.answer("❌ Достигнут лимит (3 шт) для этой карты!", show_alert=True)

@dp.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_cb(call: CallbackQuery):
    key = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    cfg = FARM_CONFIG[key]
    count = u['farm'].get(key, 0)
    
    if count >= MAX_CARDS_PER_TYPE:
         return await call.answer("❌ Максимум 3 таких карты!", show_alert=True)

    price = int(cfg['base_price'] * (cfg['scale'] ** count))
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    # Сначала собираем то, что намайнилось, чтобы не сбить таймер
    pending, _, _ = calculate_farm_income(u)
    u['btc'] += pending
    
    u['balance'] -= price
    u['farm'][key] = count + 1
    u['farm']['last_collect'] = time.time()
    
    await save_data()
    await call.answer(f"✅ Куплено: {cfg['name']}", show_alert=True)
    await farm_shop_cb(call)

@dp.callback_query(F.data == "farm_back")
async def farm_back_cb(call: CallbackQuery):
    await call.message.delete()
    await cmd_farm(call.message)

# --- MINES ---
@dp.message(F.text.lower().startswith("мины"))
async def game_mines_start(message: Message):
    if not await check_sub_middleware(message): return
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if bet < 10: return await message.answer("❌ Мин. ставка 10")
        if bet > u['balance']: return await message.answer("❌ Недостаточно средств")
        
        u['balance'] -= bet
        grid = [False]*25
        mines = random.sample(range(25), 3)
        for m in mines: grid[m] = True
        
        gid = f"mn_{message.from_user.id}_{int(time.time())}"
        active_games[gid] = {"type":"mines", "uid":message.from_user.id, "bet":bet, "grid":grid, "opened":[False]*25, "mult":1.0}
        
        await message.answer(f"💣 <b>МИНЫ</b> (3 мины)\nСтавка: {format_num(bet)}$\nУдачи!", 
                             reply_markup=get_mines_kb(gid, [False]*25))
        await save_data()
    except: await message.answer("📝: <code>Мины 1000</code>")

def get_mines_kb(gid, opened, finish=False, grid=None):
    kb = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5+c
            txt = "⬜️"
            cb = f"mn_click_{gid}_{idx}"
            if finish:
                cb = "ignore"
                if grid[idx]: txt = "💣"
                elif opened[idx]: txt = "💎"
                else: txt = "🔹"
            elif opened[idx]: 
                txt = "💎"
                cb = "ignore"
            row.append(InlineKeyboardButton(text=txt, callback_data=cb))
        kb.append(row)
    if not finish: kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"mn_stop_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("mn_"))
async def mines_callback(call: CallbackQuery):
    data = call.data.split("_")
    gid = "_".join(data[2:-1]) if data[1] == "click" else "_".join(data[2:])
    game = active_games.get(gid)
    if not game: return await call.answer("Игра окончена")

    if data[1] == "stop":
        win = int(game['bet'] * game['mult'])
        u = get_user(game['uid'])
        u['balance'] += win
        u['xp'] += 3
        check_level_up(u)
        await call.message.edit_text(f"💰 <b>ВЫИГРЫШ: {format_num(win)} $</b>", 
                                     reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]; await save_data(); return

    idx = int(data[-1])
    if game['grid'][idx]:
        await call.message.edit_text(f"💥 <b>БАБАХ! Проигрыш {format_num(game['bet'])} $</b>", 
                                     reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]
    else:
        game['opened'][idx] = True
        game['mult'] += 0.25
        await call.message.edit_text(f"💎 <b>МИНЫ</b> | Множитель: x{game['mult']:.2f}\nВыигрыш: {format_num(int(game['bet']*game['mult']))}$", 
                                     reply_markup=get_mines_kb(gid, game['opened']))
    await save_data()

# --- STARTUP ---
async def main():
    sync_load()
    scheduler.start()
    
    # Простой веб-сервер для Keep-Alive
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Active"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
