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
ADMIN_IDS = [1997428703] # ВАШ ID
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'
BOT_USERNAME = "GalacticSHBOT" 

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
market_state = {"price": 50000} # Начальная цена BTC

# --- НАСТРОЙКИ ---
FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.00001, "scale": 1.2},
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.00004, "scale": 1.2},
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.00007, "scale": 1.3}
}
MAX_CARDS_PER_TYPE = 3 

WORK_CONFIG = {
    "shovel_price": 50000,
    "detector_price": 100000,
    "cooldown": 600, 
    "rewards": [30000, 150000], 
    "btc_chance": 0.1, 
    "btc_drop": [0.001, 0.005] # Немного уменьшил для баланса с учетом цены 150к
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
    if text in ["все", "всё", "all", "вабанк", "max"]: return float(balance) # Возвращаем float для точности
    multipliers = {"кккк": 1e12, "ккк": 1e9, "кк": 1e6, "к": 1e3}
    for suff, mult in multipliers.items():
        if text.endswith(suff):
            try: return float(text[:-len(suff)]) * mult
            except: pass
    try: return float(text)
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 5000, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, "reg_status": False,
            "shovel": 0, "detector": 0, 
            "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
        asyncio.create_task(save_data())
    
    # Миграция полей
    if "farm" not in users[uid] or not isinstance(users[uid]["farm"], dict):
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    for key in FARM_CONFIG:
        if key not in users[uid]["farm"]: users[uid]["farm"][key] = 0
            
    if "shovel" not in users[uid]: users[uid]["shovel"] = 0
    if "detector" not in users[uid]: users[uid]["detector"] = 0
    if "reg_status" not in users[uid]: users[uid]["reg_status"] = False
    if "bank" in users[uid]: del users[uid]["bank"] # Удаляем банк
    
    return users[uid]

def check_level_up(u, added_xp=0):
    if u['lvl'] >= 100: return
    u['xp'] += added_xp
    req = u['lvl'] * 4 
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
        except Exception:
            return False 
    return True

# --- БИРЖА (РЫНОК BTC) ---
async def update_btc_price():
    price = random.randint(10000, 150000)
    market_state["price"] = price
    # Можно включить оповещение в лог
    logging.info(f"Новая цена BTC: {price}$")

# --- MIDDLEWARE ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def global_check(handler, event, data):
    if isinstance(event, Message):
        uid = event.from_user.id
        name = event.from_user.first_name
        text = event.text.lower() if event.text else ""
    elif isinstance(event, CallbackQuery):
        uid = event.from_user.id
        name = event.from_user.first_name
        text = ""
    else:
        return await handler(event, data)

    u = get_user(uid, name)
    
    if u.get('banned'): return 

    allowed_unreg = ["/start", "/рег", "/reg"]
    if isinstance(event, CallbackQuery) and event.data == "check_sub_reg":
        return await handler(event, data)

    if not u['reg_status']:
        if isinstance(event, Message) and not any(text.startswith(cmd) for cmd in allowed_unreg):
            await event.reply("⛔ <b>Вы не зарегистрированы!</b>\nВведите /рег для создания аккаунта.")
            return
    
    return await handler(event, data)

# ================= АДМИН КОМАНДЫ (С REPALY) =================
def get_admin_target(message: Message, command: CommandObject):
    # Если ответ на сообщение
    if message.reply_to_message:
        return message.reply_to_message.from_user.id, None
    # Если аргумент
    if command.args:
        try:
            args = command.args.split()
            return int(args[0]), args[1:] if len(args) > 1 else []
        except: pass
    return None, None

@dp.message(Command("hhh")) # Выдача денег
async def admin_give_coins(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    
    target_id, rest_args = get_admin_target(message, command)
    if not target_id: return await message.reply("⚠️ Ответьте на сообщение или введите ID!")
    
    try:
        # Если по реплаю, сумма в первом аргументе команды
        amount = int(rest_args[0]) if rest_args else int(command.args.split()[1])
    except:
        return await message.reply("📝 Формат: `/hhh [ID] СУММА` или `/hhh СУММА` (реплаем)")
        
    u = get_user(target_id)
    u['balance'] += amount
    await save_data()
    await message.reply(f"✅ Выдано <b>{format_num(amount)} $</b> игроку {target_id}")

@dp.message(Command("hhhh")) # Выдача BTC
async def admin_give_btc(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    
    target_id, rest_args = get_admin_target(message, command)
    if not target_id: return await message.reply("⚠️ Ответьте на сообщение или введите ID!")
    
    try:
        amount = float(rest_args[0]) if rest_args else float(command.args.split()[1])
    except:
        return await message.reply("📝 Формат: `/hhhh [ID] BTC` или `/hhhh BTC` (реплаем)")

    u = get_user(target_id)
    u['btc'] += amount
    await save_data()
    await message.reply(f"✅ Выдано <b>{amount} BTC</b> игроку {target_id}")

@dp.message(Command("exp"))
async def admin_give_exp(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id, rest_args = get_admin_target(message, command)
    if not target_id: return await message.reply("⚠️ ID?")
    try:
        val = int(rest_args[0]) if rest_args else int(command.args.split()[1])
        u = get_user(target_id)
        u['xp'] += val
        check_level_up(u)
        await save_data()
        await message.reply(f"✅ Выдано <b>{val} XP</b>")
    except: pass

@dp.message(Command("lvl"))
async def admin_set_lvl(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id, rest_args = get_admin_target(message, command)
    if not target_id: return await message.reply("⚠️ ID?")
    try:
        val = int(rest_args[0]) if rest_args else int(command.args.split()[1])
        u = get_user(target_id)
        u['lvl'] = val
        await save_data()
        await message.reply(f"✅ Установлен LVL <b>{val}</b>")
    except: pass

@dp.message(Command("ban"))
async def admin_ban(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id, _ = get_admin_target(message, command)
    if not target_id: return await message.reply("⚠️ Кого банить?")
    
    u = get_user(target_id)
    u['banned'] = True
    await save_data()
    await message.reply(f"⛔ Игрок {target_id} <b>ЗАБАНЕН!</b>")

@dp.message(Command("unban"))
async def admin_unban(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id, _ = get_admin_target(message, command)
    if not target_id: return await message.reply("⚠️ Кого разбанить?")
    
    u = get_user(target_id)
    u['banned'] = False
    await save_data()
    await message.reply(f"✅ Игрок {target_id} <b>РАЗБАНЕН!</b>")

# ================= РЕГИСТРАЦИЯ И СТАРТ =================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    args = command.args
    if args and args.startswith("promo_"):
        code = args.split("_")[1]
        await activate_promo(message, code)
        return

    txt = (
        "👋 <b>Добро Пожаловать в Galactic Bet!</b>\n"
        "Для начала игры нужна регистрация: /рег\n\n"
        "🎲 <b>Игры:</b> Кости, Футбол, Рулетка, Алмазы, Мины\n"
        "⛏️ <b>Заработок:</b> Работа, Ферма BTC, Биржа\n"
        "💊 <b>Помощь:</b> Список команд"
    )
    try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower().in_({"/reg", "/рег", "рег", "регистрация"}))
async def cmd_reg(message: Message):
    u = get_user(message.from_user.id)
    if u['reg_status']:
        return await message.reply("✅ <b>Вы уже зарегистрированы!</b>")
    
    kb = []
    for ch in REQUIRED_CHANNELS:
        kb.append([InlineKeyboardButton(text=f"Подписаться на {ch['username']}", url=ch['link'])])
    kb.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub_reg")])
    
    await message.reply("📝 <b>Регистрация</b>\nПодпишитесь на каналы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "check_sub_reg")
async def check_sub_reg_cb(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        u = get_user(call.from_user.id)
        u['reg_status'] = True
        await save_data()
        await call.message.delete()
        await call.message.answer("✅ <b>Регистрация успешна!</b>")
    else:
        await call.answer("❌ Подпишитесь на все каналы!", show_alert=True)

# ================= БИРЖА (КОМАНДЫ) =================
@dp.message(F.text.lower().in_({"биржа", "курс", "btc"}))
async def cmd_market(message: Message):
    price = market_state["price"]
    await message.reply(f"📊 <b>Биржа Bitcoin</b>\n\n💰 Курс: <b>{format_num(price)} $</b>\n🕒 Обновление каждый час (10к - 150к $)")

@dp.message(F.text.lower().startswith("купить биткоин"))
async def cmd_buy_btc(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        amount_usd = parse_amount(args[2], u['balance'])
        price = market_state["price"]
        
        if amount_usd < 1: return await message.reply("❌ Минимум 1$")
        if u['balance'] < amount_usd: return await message.reply("❌ Недостаточно средств!")
        
        btc_amount = amount_usd / price
        u['balance'] -= amount_usd
        u['btc'] += btc_amount
        await save_data()
        await message.reply(f"✅ Куплено <b>{btc_amount:.8f} BTC</b> за {format_num(amount_usd)}$")
    except: await message.reply("📝: <code>Купить биткоин [сумма $]</code>")

@dp.message(F.text.lower().startswith("продать биткоин"))
async def cmd_sell_btc(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        val = args[2].lower()
        price = market_state["price"]
        
        if val in ["все", "всё", "all"]:
            btc_to_sell = u['btc']
        else:
            btc_to_sell = float(val)
            
        if btc_to_sell <= 0: return await message.reply("❌ Нечего продавать")
        if u['btc'] < btc_to_sell: return await message.reply("❌ Недостаточно BTC")
        
        profit = int(btc_to_sell * price)
        u['btc'] -= btc_to_sell
        u['balance'] += profit
        await save_data()
        await message.reply(f"✅ Продано <b>{btc_to_sell:.8f} BTC</b> за {format_num(profit)}$")
    except: await message.reply("📝: <code>Продать биткоин [кол-во BTC/все]</code>")

# ================= РАБОТА И МАГАЗИН =================
@dp.message(F.text.lower() == "магазин")
async def cmd_shop_tools(message: Message):
    u = get_user(message.from_user.id)
    kb = []
    if not u['shovel']:
        kb.append([InlineKeyboardButton(text=f"🛒 Лопата — {format_num(WORK_CONFIG['shovel_price'])}$", callback_data="buy_tool_shovel")])
    if not u['detector']:
        kb.append([InlineKeyboardButton(text=f"📡 Металлоискатель — {format_num(WORK_CONFIG['detector_price'])}$", callback_data="buy_tool_detector")])
    if not kb:
        return await message.reply("✅ У вас куплены все инструменты!")
    await message.reply("🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_tool_"))
async def buy_tool_cb(call: CallbackQuery):
    item = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    price = WORK_CONFIG[f"{item}_price"]
    if u['balance'] < price: return await call.answer("❌ Нет денег!", show_alert=True)
    
    u['balance'] -= price
    u[item] = 1
    await save_data()
    await call.answer("✅ Куплено!")
    await call.message.delete()

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    if not u['shovel'] or not u['detector']:
        return await message.reply("❌ Купите Лопату и Металлоискатель в /магазин!")

    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']:
        rem = int(WORK_CONFIG['cooldown'] - (now - u['last_work']))
        return await message.reply(f"⏳ Отдых: {rem // 60} мин {rem % 60} сек")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕳 Сектор A", callback_data="work_dig_1"),
         InlineKeyboardButton(text="🕳 Сектор B", callback_data="work_dig_2")]
    ])
    await message.reply("👷 <b>ГДЕ КОПАЕМ?</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("work_dig_"))
async def work_dig_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']: return await call.answer("⏳ Рано!")
    
    u['last_work'] = now
    reward = random.randint(WORK_CONFIG['rewards'][0], WORK_CONFIG['rewards'][1])
    u['balance'] += reward
    xp = random.randint(1, 5)
    
    txt = f"⚱️ <b>УСПЕХ!</b>\n💰 {format_num(reward)} $\n⭐ +{xp} XP"
    
    if random.random() < WORK_CONFIG['btc_chance']:
        drop = random.uniform(*WORK_CONFIG['btc_drop'])
        u['btc'] += drop
        txt += f"\n🪙 <b>Найдено {drop:.4f} BTC!</b>"
        
    check_level_up(u, xp)
    await save_data()
    await call.message.edit_text(txt)

# ================= ИГРЫ (REPLY + FIXES) =================
@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    valid_bets = ["к", "крас", "красный", "ч", "черн", "черный", "з", "зел", "зеленый", "чет", "нечет"]
    try:
        if len(args) < 3: raise ValueError
        bet = int(parse_amount(args[1], u['balance']))
        choice = args[2]
        if not choice.isdigit() and choice not in valid_bets: raise ValueError
        if bet < 10 or bet > u['balance']: return await message.reply("❌ Ставка/Баланс?")
        
        u['balance'] -= bet
        n = random.randint(0, 36)
        color = "зеленый" if n==0 else ("красный" if n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный")
        parity = "четное" if n!=0 and n%2==0 else "нечетное"
        
        win = 0
        if choice in ["к", "крас", "красный"] and color == "красный": win = bet*2
        elif choice in ["ч", "черн", "черный"] and color == "черный": win = bet*2
        elif choice in ["з", "зел", "зеленый"] and color == "зеленый": win = bet*14
        elif choice.isdigit() and int(choice) == n: win = bet*36
        elif choice in ["чет"] and parity == "четное": win = bet*2
        elif choice in ["нечет"] and parity == "нечетное": win = bet*2
        
        u['balance'] += win
        res = f"🎉 <b>+{format_num(win)}$</b>" if win>0 else "❌ <b>Проигрыш</b>"
        await message.reply(f"🎰 <b>Рулетка:</b> {n} ({color})\n{res}")
        await save_data()
    except: await message.reply("❌ Ставьте: кр, чер, зел, чет, нечет или число")

@dp.message(F.text.lower().startswith("кости"))
async def game_dice(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    valid = {"равно": ["=", "равно", "7"], "больше": [">", "больше", "б"], "меньше": ["<", "меньше", "м"]}
    try:
        if len(args) < 3: raise ValueError
        bet = int(parse_amount(args[1], u['balance']))
        out = args[2]
        type_ = next((k for k,v in valid.items() if out in v), None)
        if not type_: raise ValueError
        if bet < 10 or bet > u['balance']: return await message.reply("❌ Ставка/Баланс?")

        u['balance'] -= bet
        msg = await message.answer_dice("🎲"); await asyncio.sleep(3.5)
        val = msg.dice.value
        
        # Для 1 кубика (aiogram dice) значения 1-6. 7 невозможно.
        # Адаптируем под 1 кубик: 3.5 среднее.
        # Или бросим 2 раза. Сделаем 2 дайса для
        # ... (продолжение логики костей)
        # Бросаем два кубика для классической игры в "7"
        msg2 = await message.answer_dice("🎲")
        await asyncio.sleep(3.5)
        total = val + msg2.dice.value
        
        win = 0
        if type_ == "равно" and total == 7: win = bet * 5.8
        elif type_ == "больше" and total > 7: win = bet * 2.3
        elif type_ == "меньше" and total < 7: win = bet * 2.3
        
        win = int(win)
        u['balance'] += win
        res = f"🎉 <b>Выигрыш: {format_num(win)} $</b>" if win > 0 else "❌ <b>Проигрыш</b>"
        
        await message.reply(
            f"🎲 <b>Кости</b>\n"
            f"📊 Выпало: {val} + {msg2.dice.value} = <b>{total}</b>\n"
            f"{res}\n"
            f"💰 Баланс: {format_num(u['balance'])} $"
        )
        await save_data()
    except:
        await message.reply("📝 Пример: <code>Кости 1к больше</code>")

# --- ФУТБОЛ (ЭМОДЗИ-ИГРА) ---
@dp.message(F.text.lower().startswith("футбол"))
async def game_football(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = int(parse_amount(message.text.split()[1], u['balance']))
        if bet < 10 or bet > u['balance']: return await message.reply("❌ Ставка?")
        
        u['balance'] -= bet
        msg = await message.answer_dice("⚽")
        # В футболе значения 3, 4, 5 — это гол
        is_goal = msg.dice.value in [3, 4, 5]
        
        win = bet * 2 if is_goal else 0
        u['balance'] += win
        
        await asyncio.sleep(3.5)
        res = f"⚽ <b>ГОООЛ! Выигрыш: {format_num(win)}$</b>" if is_goal else "🧤 <b>Мимо/Вратарь вытащил!</b>"
        await message.reply(f"{res}\n💰 Баланс: {format_num(u['balance'])}$")
        await save_data()
    except:
        await message.reply("📝: <code>Футбол [сумма]</code>")

# --- ПРОФИЛЬ И ТОП (ID ВМЕСТО ИМЕН) ---
@dp.message(F.text.lower().in_({"профиль", "я", "стата"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    # Считаем доход в час для профиля
    btc_h = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    
    txt = (
        f"👤 <b>ВАШ ПРОФИЛЬ</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💳 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.8f} BTC</b>\n"
        f"📈 Уровень: <b>{u['lvl']}</b> ({u['xp']} XP)\n"
        f"⚒ Инструменты: {'🪓' if u['shovel'] else '❌'} {'📡' if u['detector'] else '❌'}\n"
        f"⚡ Ферма: <b>{btc_h:.6f} BTC/ч</b>"
    )
    await message.reply(txt)

@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    # Сортировка по балансу
    top_users = sorted(users.items(), key=lambda x: x[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ (по ID):</b>\n\n"
    for i, (uid, u_data) in enumerate(top_users):
        txt += f"{i+1}. <code>{uid}</code> — <b>{format_num(u_data['balance'])} $</b>\n"
    await message.reply(txt)

# --- ПЕРЕВОДЫ ---
@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        target_id = int(args[1])
        amount = int(parse_amount(args[2], u['balance']))
        
        if amount <= 0 or u['balance'] < amount:
            return await message.reply("❌ Недостаточно средств или неверная сумма!")
        if target_id == message.from_user.id:
            return await message.reply("❌ Нельзя переводить самому себе!")
            
        target_user = get_user(target_id)
        u['balance'] -= amount
        target_user['balance'] += amount
        
        await save_data()
        await message.reply(f"✅ Вы успешно перевели <b>{format_num(amount)}$</b> игроку <code>{target_id}</code>")
        # Уведомление получателю
        try:
            await bot.send_message(target_id, f"💰 Игрок <code>{message.from_user.id}</code> перевел вам <b>{format_num(amount)}$</b>")
        except: pass
    except:
        await message.reply("📝: <code>Перевести [ID] [Сумма]</code>")

# --- БОНУС ---
@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = time.time()
    if now - u['last_bonus'] < 3600:
        rem = int(3600 - (now - u['last_bonus']))
        return await message.reply(f"⏳ Бонус можно взять через {rem // 60} мин")
    
    reward = random.randint(5000, 20000)
    u['balance'] += reward
    u['last_bonus'] = now
    await save_data()
    await message.reply(f"🎁 Вы получили бонус: <b>{format_num(reward)} $</b>")

# --- УПРАВЛЕНИЕ ПРОМОКОДАМИ (АДМИН) ---
@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        code = args[2]
        reward = int(parse_amount(args[3], 999999999999))
        uses = int(args[4])
        
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        await message.reply(f"✅ Промокод <code>{code}</code> создан!\n💰 Награда: {format_num(reward)}$\n👥 Кол-во: {uses}")
    except:
        await message.reply("📝: <code>Создать промо [код] [сумма] [активации]</code>")

@dp.message(Command("pr"))
async def cmd_activate_promo(message: Message, command: CommandObject):
    if not command.args: return
    code = command.args.strip()
    u = get_user(message.from_user.id)
    
    if code not in promos:
        return await message.reply("❌ Такого промокода не существует!")
    if code in u['used_promos']:
        return await message.reply("❌ Вы уже активировали этот код!")
        
    u['balance'] += promos[code]['reward']
    u['used_promos'].append(code)
    promos[code]['uses'] -= 1
    
    if promos[code]['uses'] <= 0:
        del promos[code]
        
    await save_data()
    await message.reply(f"✅ Активировано! +<b>{format_num(u['used_promos'][-1])}$</b>")

# --- ГЛАВНЫЙ ЗАПУСК ---
async def main():
    # 1. Загрузка базы данных
    sync_load()
    
    # 2. Планировщик для рынка BTC (раз в час)
    scheduler.add_job(update_btc_price, 'interval', minutes=60)
    await update_btc_price() # Установить начальную цену
    scheduler.start()
    
    # 3. Веб-сервер (для хостингов)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    # 4. Поллинг бота
    logging.info("Бот успешно запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен")
