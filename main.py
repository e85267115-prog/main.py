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
BOT_USERNAME = "VibeBetBot" 

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
            "name": name, "balance": 5000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, 
            "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
        asyncio.create_task(save_data())
    
    # Миграция и проверка полей
    if "farm" not in users[uid]:
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    if "shovel" not in users[uid]: users[uid]["shovel"] = 0
    if "detector" not in users[uid]: users[uid]["detector"] = 0
    if "last_work" not in users[uid]: users[uid]["last_work"] = 0
    if "xp" not in users[uid]: users[uid]["xp"] = 0
    if "lvl" not in users[uid]: users[uid]["lvl"] = 1
    
    return users[uid]

def check_level_up(u):
    if u['lvl'] >= 100: return
    req = u['lvl'] * 100 # Немного усложним: 100 XP на уровень
    if u['xp'] >= req:
        u['xp'] -= req
        u['lvl'] += 1
        return True
    return False

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_subscription(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["username"], user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                return False
        except Exception as e:
            logging.error(f"Ошибка проверки подписки: {e}")
            # Если бот не админ канала, он не увидит. Считаем, что подписан, чтобы не ломать,
            # либо верните False, если уверены, что бот админ.
            return True 
    return True

# --- MIDDLEWARE (БАН + ПОДПИСКА) ---
# Проверку подписки делаем только в /start для удобства, 
# либо жестко блокируем все сообщения. 
# Сделаем жесткую проверку в /start и мягкую в играх.

@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def global_check(handler, event, data):
    uid = event.from_user.id
    u = get_user(uid, event.from_user.first_name)
    
    if u.get('banned'):
        return # Игнор забаненных
        
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
        "⛏️ <b>Заработок:</b> 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус\n"
        "🏦 <b>Банк:</b> Храни деньги под процент!\n\n"
        "👇 Жми <b>Помощь</b> для списка команд!"
    )
    
    # Пытаемся отправить фото, если нет - текст
    try: 
        await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: 
        await message.answer(txt)

@dp.callback_query(F.data == "check_sub_start")
async def check_sub_cb(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ <b>Спасибо за подписку!</b> Жмите /start")
    else:
        await call.answer("❌ Вы не подписались на все каналы!", show_alert=True)

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
    await message.answer(txt)

# --- АДМИН КОМАНДЫ (НОВЫЕ) ---
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

@dp.message(Command("exp"))
async def admin_give_exp(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = command.args.split()
        target_id = int(args[0])
        val = int(args[1])
        u = get_user(target_id)
        u['xp'] += val
        check_level_up(u)
        await save_data()
        await message.answer(f"✅ Выдано <b>{val} XP</b> игроку {target_id}")
    except: await message.answer("📝: `/exp ID XP`")


# --- ПРОФИЛЬ, ТОП, БОНУС, ПЕРЕВОД ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    req_xp = u['lvl'] * 100
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🏦 В банке: <b>{format_num(u['bank'])} $</b>\n"
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
    # Только админ может создавать, если нужно - раскомментируйте проверку ID
    # if message.from_user.id not in ADMIN_IDS: return 
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
        
        bot_user = await bot.get_me()
        bot_link = f"https://t.me/{bot_user.username}?start=promo_{code}"
        
        txt = (
            f"✅ <b>Промокод создан!</b>\n"
            f"🔑 Код: <code>{code}</code>\n"
            f"💰 Сумма: <b>{format_num(reward)} $</b>\n"
            f"👥 Активаций: <b>{uses}</b>\n\n"
            f"🔗 <a href='{bot_link}'>Ссылка для друзей</a>"
        )
        await message.answer(txt)
    except: 
        await message.answer("📝 Формат: <code>Создать промо [КОД] [Сумма] [Кол-во]</code>")

# ================= РАБОТА (КЛАДОИСКАТЕЛЬ) =================

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    
    # Меню инструментов
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
    
    # Меню копания
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
    
    # Проверка КД еще раз
    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']:
        return await call.answer("⏳ Рано!", show_alert=True)

    # Логика копания
    u['last_work'] = now
    
    # Шанс найти ничего (30%), Клад (70%)
    # Если есть детектор, шанс найти клад 90% и сумма больше
    
    luck = random.random()
    threshold = 0.1 if u['detector'] else 0.3
    
    if luck < threshold:
        txt = "🍂 <b>Пусто...</b> В этой яме только грязь."
    else:
        base_reward = random.randint(WORK_CONFIG['rewards'][0], WORK_CONFIG['rewards'][1])
        if u['detector']:
            base_reward = int(base_reward * 1.5) # +50% дохода с детектором
        
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
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        choice = args[2]
        
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

# --- КОСТИ ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice_real(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    
    # "7" заменено на "равно" по запросу
    valid_outcomes = {
        "equal": ["равно", "equal", "=", "7", "семь"],
        "over": ["больше", "б", "over", ">"],
        "under": ["меньше", "м", "under", "<"]
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
    except IndexError: await message.answer("📝: <code>Кости 10к больше</code>")

# --- ФУТБОЛ ---
@dp.message(F.text.lower().startswith("футбол"))
async def game_football_real(message: Message):
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
    except IndexError: await message.answer("📝: <code>Футбол 10к гол</code>")

# --- АЛМАЗЫ ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_dia_start(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        bet = parse_amount(args[1], u['balance'])
        bombs = 1
        if len(args) > 2:
            bombs = int(args[2])
        
        if bombs not in [1, 2]: return await message.answer("❌ Можно выбрать 1 или 2 бомбы!")
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        
        u['balance'] -= bet
        gid = f"dm_{message.from_user.id}_{int(time.time())}"
        
        start_mult = 1.3 if bombs == 1 else 2.3
        
        active_games[gid] = {
            "type": "dm", 
            "uid": message.from_user.id, 
            "bet": bet, 
            "lvl": 0, 
            "mult": start_mult,
            "bombs_count": bombs
        }
        
        await message.answer(
            f"💎 <b>АЛМАЗЫ ({bombs} 💣)</b>\n"
            f"💰 Ставка: {format_num(bet)} $\n"
            f"👇 Выберите ячейку:", 
            reply_markup=get_dia_kb(gid)
        )
        await save_data()
    except: await message.answer("📝: <code>Алмазы [сумма] [бомбы 1-2]</code>")

def get_dia_kb(gid, finish_state=None):
    btns = []
    if finish_state:
        bomb_indices = finish_state['bomb_indices']
        for i in range(3):
            txt = "💀" if i in bomb_indices else "💎"
            btns.append(InlineKeyboardButton(text=txt, callback_data="ignore"))
        kb = [btns]
    else:
        btns = [InlineKeyboardButton(text="📦", callback_data=f"dm_g_{gid}_{i}") for i in range(3)]
        kb = [btns, [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"dm_c_{gid}")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("dm_"))
async def dia_act(call: CallbackQuery):
    p = call.data.split("_")
    if p[1] == 'c': # Cashout
        gid = "_".join(p[2:])
        g = active_games.get(gid)
        if not g: return await call.answer("Игра окончена")
        
        # FIX: Проверка, что игрок сделал хотя бы один ход
        if g['lvl'] == 0:
            return await call.answer("🚫 Сначала сделайте хотя бы один ход!", show_alert=True)
        
        w = int(g['bet'] * g['mult'])
        get_user(g['uid'])['balance'] += w
        del active_games[gid]
        await save_data()
        await call.message.edit_text(f"💰 <b>Вы забрали: {format_num(w)} $</b>")
        return

    gid = "_".join(p[2:-1])
    clicked_idx = int(p[-1])
    g = active_games.get(gid)
    if not g: return await call.answer("Игра окончена")

    all_indices = [0, 1, 2]
    bomb_indices = random.sample(all_indices, g['bombs_count'])
    
    if clicked_idx in bomb_indices:
        await call.message.edit_text(
            f"💀 <b>БАБАХ! Вы проиграли {format_num(g['bet'])} $</b>",
            reply_markup=get_dia_kb(gid, finish_state={'clicked': clicked_idx, 'bomb_indices': bomb_indices})
        )
        del active_games[gid]
    else:
        step_add = 0.3 if g['bombs_count'] == 1 else 0.5
        g['mult'] += step_add
        g['lvl'] += 1
        curr_win = int(g['bet'] * g['mult'])
        
        await call.message.edit_text(
            f"💎 <b>УГАДАЛ!</b> (x{g['mult']:.1f})\n"
            f"💰 Выигрыш сейчас: {format_num(curr_win)} $",
            reply_markup=get_dia_kb(gid) 
        )
    await save_data()

# --- ФЕРМА BTC ---
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
    income = (btc_per_hour / 3600) * seconds_passed
    return income, btc_per_hour, total_cards

@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    u = get_user(message.from_user.id)
    pending_btc, hourly_btc, total_cards = calculate_farm_income(u)
    
    txt = (
        f"🖥 <b>BTC ФЕРМА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Ваши видеокарты:</b>\n"
        f"🔹 RTX 3060: <b>{u['farm']['rtx3060']} шт.</b>\n"
        f"🔹 RTX 4070: <b>{u['farm']['rtx4070']} шт.</b>\n"
        f"🔹 RTX 4090: <b>{u['farm']['rtx4090']} шт.</b>\n\n"
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
        count = u['farm'][key]
        price = int(cfg['base_price'] * (cfg['scale'] ** count))
        btn_text = f"{cfg['name']} — {format_num(price)}$"
        kb_list.append([InlineKeyboardButton(text=btn_text, callback_data=f"farm_buy_{key}")])
        
    kb_list.append([InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")])
    await call.message.edit_text("🛍 <b>МАГАЗИН ВИДЕОКАРТ</b>\nКаждая покупка увеличивает цену следующей.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_cb(call: CallbackQuery):
    key = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    cfg = FARM_CONFIG[key]
    count = u['farm'][key]
    price = int(cfg['base_price'] * (cfg['scale'] ** count))
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    # Сбор дохода перед апгрейдом
    pending, _, _ = calculate_farm_income(u)
    u['btc'] += pending
    
    u['balance'] -= price
    u['farm'][key] += 1
    u['farm']['last_collect'] = time.time()
    
    await save_data()
    await call.answer(f"✅ Куплено: {cfg['name']}", show_alert=True)
    await farm_shop_cb(call)

@dp.callback_query(F.data == "farm_back")
async def farm_back_cb(call: CallbackQuery):
    await call.message.delete()
    await cmd_farm(call.message)

# --- МИНЫ ---
@dp.message(F.text.lower().startswith("мины"))
async def game_mines_start(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        
        u['balance'] -= bet
        grid = [False]*25
        mines = random.sample(range(25), 3)
        for m in mines: grid[m] = True
        
        gid = f"mn_{message.from_user.id}_{int(time.time())}"
        active_games[gid] = {"type":"mines", "uid":message.from_user.id, "bet":bet, "grid":grid, "opened":[False]*25, "mult":1.0}
        
        await message.answer(f"💣 <b>МИНЫ</b> (3 мины)\nСтавка: {format_num(bet)}$\nУдачи!", 
                             reply_markup=get_mines_kb(gid, [False]*25))
    except: await message.answer("📝: <code>Мины 1000</code>")

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

# --- ТОП ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (uid, u) in enumerate(sorted_users):
        medal = medals.get(i, f"{i+1}.")
        txt += f"{medal} {u['name']} — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(txt)

# --- ЗАПУСК ---
async def bank_interest():
    for u in users.values():
        if u.get('bank', 0) > 0: 
            u['bank'] += int(u['bank'] * 0.05) # 5% в сутки
    await save_data()

async def main():
    sync_load()
    scheduler.add_job(bank_interest, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
    scheduler.start()
    
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Active"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
