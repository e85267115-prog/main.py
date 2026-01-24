import asyncio
import os
import logging
import random
import json
import io
import time
import math
import aiohttp
from datetime import datetime
from pytz import timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiohttp import web
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN") 
# Замените на свой ID, чтобы работали админ команды
ADMIN_IDS = [1997428703] 
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Хранилище в памяти
users = {}
promos = {}
# Временное хранилище для активных игр (Мины, Алмазы)
active_games = {} 

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
            # При загрузке конвертируем ключи в int
            users = {int(k): v for k, v in data.get("users", {}).items()}
            promos = data.get("promos", {})
    except Exception as e:
        logging.error(f"Ошибка загрузки БД: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        # Убираем временные поля перед сохранением если нужно, но здесь храним все важное
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
    """Форматирование чисел (к, кк, ккк, кккк)"""
    num = float(num)
    if num < 1000: return str(int(num))
    
    suffixes = [
        (1_000_000_000_000, "кккк"),
        (1_000_000_000, "ккк"),
        (1_000_000, "кк"),
        (1_000, "к")
    ]
    
    for val, suff in suffixes:
        if num >= val:
            res = num / val
            # Если число целое (например 5.00), убираем ноль, иначе 2 знака
            f_res = f"{int(res)}" if res == int(res) else f"{round(res, 2)}"
            return f"{f_res}{suff}"
    
    return str(int(num))

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all", "вабанк", "max"]: return int(balance)
    
    multipliers = {"кккк": 1_000_000_000_000, "ккк": 1_000_000_000, "кк": 1_000_000, "к": 1_000}
    
    for suff, mult in multipliers.items():
        if text.endswith(suff):
            try:
                base = text[:-len(suff)]
                return int(float(base) * mult)
            except: pass
            
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, 
            "balance": 5000, 
            "bank": 0, 
            "btc": 0.0, 
            "lvl": 1, 
            "xp": 0, 
            "banned": False, 
            "shovel": 0, 
            "detector": 0, 
            "last_work": 0, 
            "last_bonus": 0, 
            "used_promos": [],
            # Ферма
            "farm": {
                "rtx3060": 0, # Tier 1
                "rtx4070": 0, # Tier 2
                "rtx4090": 0, # Tier 3
                "last_collect": time.time()
            }
        }
        asyncio.create_task(save_data())
    
    # Миграция для старых юзеров (если добавили новые поля)
    if "farm" not in users[uid]:
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    
    return users[uid]

async def get_btc_price():
    # Заглушка, если API не работает, или реальный запрос
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return float(data['bitcoin']['usd'])
    except:
        return 98500.0 # Фолбек цена

# --- МИДЛВАРЬ (БАН) ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def ban_check(handler, event, data):
    user_id = event.from_user.id
    u = get_user(user_id, event.from_user.first_name)
    if u.get('banned'):
        if isinstance(event, Message):
            await event.answer("🚫 <b>Доступ заблокирован администрацией!</b>")
        else:
            await event.answer("🚫 Доступ заблокирован!", show_alert=True)
        return
    return await handler(event, data)

# --- START & HELP ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    txt = (
        "👋 <b>Добро Пожаловать в Vibe Bet!</b>\n"
        "Лучший бот для развлечений и заработка.\n\n"
        "🎮 <b>Игры:</b> Рулетка, Краш, Кости, Мины, Алмазы\n"
        "💻 <b>Майнинг:</b> Собери свою BTC ферму\n"
        "🏆 <b>Топ:</b> Соревнуйся с другими\n\n"
        "Жми <i>Помощь</i> или введи команду!"
    )
    try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "💎 <b>ЦЕНТР ПОМОЩИ VIBE BET</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>ОСНОВНОЕ:</b>\n"
        "└ <code>Профиль</code>, <code>Топ</code>, <code>Бонус</code>\n\n"
        "🎰 <b>ИГРЫ:</b>\n"
        "└ <code>Рул [сумма] [цвет/число]</code>\n"
        "└ <code>Краш [сумма] [кэф]</code>\n"
        "└ <code>Кости [сумма] [ставка]</code> (ставка: 7, больше, меньше)\n"
        "└ <code>Мины [сумма]</code>\n"
        "└ <code>Алмазы [сумма]</code>\n\n"
        "🖥 <b>МАЙНИНГ:</b>\n"
        "└ <code>Ферма</code> - управление видеокартами\n\n"
        "🏦 <b>ФИНАНСЫ:</b>\n"
        "└ <code>Банк</code>, <code>Рынок</code>\n"
        "└ <code>Деп [сумма]</code>, <code>Снять [сумма]</code>\n"
        "└ <code>Продать биткоин [кол-во/все]</code>\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(txt)

# --- ПРОФИЛЬ ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🏦 В банке: <b>{format_num(u['bank'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*100} XP)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

# --- ТОП (LEADERBOARD) ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    # Сортируем пользователей по балансу
    sorted_users = sorted(users.items(), key=lambda item: item[1]['balance'], reverse=True)
    top_10 = sorted_users[:10]
    
    txt = "🏆 <b>Топ 10 игроков по балансу:</b>\n\n"
    
    medals = {1: "🐍", 2: "🎩", 3: "🥉", 4: "👑", 5: "", 6: "👑", 7: "", 8: "🤖", 9: "👑", 10: "🎰"}
    
    for i, (uid, u) in enumerate(top_10, 1):
        icon = medals.get(i, "")
        name = u['name']
        # Экранируем имя от тегов
        name = name.replace("<", "&lt;").replace(">", "&gt;")
        bal = format_num(u['balance'])
        txt += f"{i}) {name} {icon} — {bal}\n"
        
    await message.answer(txt)

# --- АДМИН КОМАНДЫ (ПОЛНОСТЬЮ ПЕРЕПИСАНЫ) ---
@dp.message(F.text.lower().startswith("выдать"))
async def admin_give(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        # Форматы:
        # выдать [сумма] (себе)
        # выдать [id] [сумма] (другому)
        # выдатьбтк [id] [сумма]
        
        cmd = args[0].lower()
        
        if cmd == "выдать":
            if len(args) == 2:
                target_id = message.from_user.id
                amount = parse_amount(args[1], 0)
            else:
                target_id = int(args[1])
                amount = parse_amount(args[2], 0)
            
            if amount:
                u = get_user(target_id)
                u['balance'] += amount
                await message.answer(f"✅ Выдано <b>{format_num(amount)}$</b> игроку {u['name']}")
                await bot.send_message(target_id, f"💰 <b>АДМИНИСТРАЦИЯ:</b> Вам начислено <b>{format_num(amount)} $</b>!")
                await save_data()

        elif cmd == "выдатьбтк":
            target_id = int(args[1])
            amount = float(args[2])
            u = get_user(target_id)
            u['btc'] += amount
            await message.answer(f"✅ Выдано <b>{amount} BTC</b> игроку {u['name']}")
            await bot.send_message(target_id, f"🎁 <b>АДМИНИСТРАЦИЯ:</b> Вам начислено <b>{amount} BTC</b>!")
            await save_data()
            
        elif cmd == "выдатьлвл":
            target_id = int(args[1])
            lvl = int(args[2])
            u = get_user(target_id)
            u['lvl'] = lvl
            await message.answer(f"✅ Уровень игрока {u['name']} установлен на {lvl}")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка команды: {e}\nПример: <code>Выдать 123456789 1кк</code>")

@dp.message(F.text.lower().startswith("бан") | F.text.lower().startswith("разбан"))
async def admin_ban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        cmd = args[0].lower()
        target_id = int(args[1])
        u = get_user(target_id)
        
        if cmd == "бан":
            u['banned'] = True
            await message.answer(f"🚫 Пользователь {target_id} заблокирован.")
            await bot.send_message(target_id, "🚫 <b>Ваш аккаунт заблокирован администратором.</b>")
        else:
            u['banned'] = False
            await message.answer(f"✅ Пользователь {target_id} разблокирован.")
            await bot.send_message(target_id, "✅ <b>Ваш аккаунт разблокирован!</b>")
        await save_data()
    except:
        await message.answer("❌ Пример: <code>Бан 123456789</code>")

# --- ЭКОНОМИКА: РЫНОК И ПРОДАЖА ---
@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    price = await get_btc_price()
    await message.answer(f"📊 <b>КРИПТО РЫНОК</b>\n━━━━━━━━━━━━━━━━━━\n🪙 Bitcoin (BTC): <b>{price:,.2f} $</b>\n━━━━━━━━━━━━━━━━━━\n<i>Чтобы продать: Продать биткоин [кол-во]</i>")

@dp.message(F.text.lower().startswith("продать биткоин"))
async def cmd_sell_btc(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        if len(args) < 3: raise ValueError
        amount_str = args[2].lower()
        
        if amount_str in ["все", "всё", "all"]:
            amount = u['btc']
        else:
            amount = float(amount_str)
            
        if amount <= 0 or amount > u['btc']:
            return await message.answer("❌ Недостаточно BTC!")
            
        price = await get_btc_price()
        total_usd = int(amount * price)
        
        u['btc'] -= amount
        u['balance'] += total_usd
        
        await message.answer(f"✅ <b>ПРОДАЖА УСПЕШНА</b>\n━━━━━━━━━━━━━━━━━━\n📤 Продано: <b>{amount:.6f} BTC</b>\n💰 Получено: <b>{format_num(total_usd)} $</b>\n💳 Баланс: <b>{format_num(u['balance'])} $</b>")
        await save_data()
        
    except:
        await message.answer("📝 Пример: <code>Продать биткоин 0.5</code> или <code>Продать биткоин все</code>")

# --- БАНК ---
@dp.message(F.text.lower().startswith("деп"))
async def cmd_bank_dep(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['balance'])
        if not amt or amt < 0: raise ValueError
        if u['balance'] < amt: return await message.answer("❌ Недостаточно средств!")
        u['balance'] -= amt
        u['bank'] += amt
        await message.answer(f"✅ В банк внесено: <b>{format_num(amt)} $</b>\n🏦 На счету: <b>{format_num(u['bank'])} $</b>")
        await save_data()
    except: await message.answer("📝 Пример: <code>Деп 1кк</code>")

@dp.message(F.text.lower().startswith("снять"))
async def cmd_bank_with(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['bank'])
        if not amt or amt < 0: raise ValueError
        if u['bank'] < amt: return await message.answer("❌ Недостаточно средств в банке!")
        u['bank'] -= amt
        u['balance'] += amt
        await message.answer(f"✅ Из банка снято: <b>{format_num(amt)} $</b>\n💰 Баланс: <b>{format_num(u['balance'])} $</b>")
        await save_data()
    except: await message.answer("📝 Пример: <code>Снять 1кк</code>")

@dp.message(F.text.lower() == "банк")
async def cmd_bank_info(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(f"🏦 <b>VIBE BANK</b>\n━━━━━━━━━━━━\n💰 На счету: <b>{format_num(u['bank'])} $</b>\n📈 Ставка: <b>10%</b> ежедневно в 00:00\n━━━━━━━━━━━━")

# --- БОНУС ---
@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = time.time()
    if now - u.get('last_bonus', 0) < 3600:
        rem = int(3600 - (now - u['last_bonus']))
        return await message.answer(f"⏳ Бонус доступен через <b>{rem // 60} мин.</b>")
    
    val = random.randint(5000, 50000) * u['lvl']
    u['balance'] += val
    u['last_bonus'] = now
    await message.answer(f"🎁 <b>БОНУС</b>\nПолучено: <b>{format_num(val)} $</b>")
    await save_data()

# ==========================================
#              ИГРЫ (ОБНОВЛЕННЫЕ)
# ==========================================

# --- РУЛЕТКА (ПО ШАБЛОНУ) ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roulette(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        choice = args[2].lower()
        
        if not bet or bet < 10 or bet > u['balance']:
            return await message.answer("❌ Неверная ставка!")
            
        u['balance'] -= bet
        
        # Логика рулетки
        num = random.randint(0, 36)
        color = "зеленый" if num == 0 else "черный" if num in [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35] else "красный"
        parity = "четное" if num != 0 and num % 2 == 0 else "нечетное" if num != 0 else ""
        
        # Множители
        win_amount = 0
        if choice in ["к", "красный", "red", "крас"] and color == "красный": win_amount = bet * 2
        elif choice in ["ч", "черный", "black", "черн"] and color == "черный": win_amount = bet * 2
        elif choice in ["з", "зеленый", "green", "зел"] and color == "зеленый": win_amount = bet * 14
        elif choice.isdigit() and int(choice) == num: win_amount = bet * 36
        elif choice in ["чет", "четное"] and parity == "четное": win_amount = bet * 2
        elif choice in ["нечет", "нечетное"] and parity == "нечетное": win_amount = bet * 2

        formatted_res = f"{num} ({color}{', ' + parity if parity else ''})"
        
        if win_amount > 0:
            u['balance'] += win_amount
            res_text = (
                f"💸 Ставка: {format_num(bet)} $\n"
                f"🎉 Выигрыш: {format_num(win_amount)} $\n"
                f"📈 Выпало: {formatted_res}\n"
                f"💰 Баланс: {format_num(u['balance'])} $"
            )
        else:
            res_text = (
                f"💸 Ставка: {format_num(bet)} $\n"
                f"🎉 Выигрыш: 0 $\n"
                f"📈 Выпало: {formatted_res}\n"
                f"💰 Баланс: {format_num(u['balance'])} $"
            )
        
        await message.answer(res_text)
        await save_data()

    except:
        await message.answer("📝 Пример: <code>Рул 1к красный</code> или <code>Рул 500 0</code>")

# --- КРАШ (ПО ШАБЛОНУ) ---
@dp.message(F.text.lower().startswith("краш"))
async def game_crash(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        target = float(args[2].replace(",", "."))
        
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        if target <= 1: return await message.answer("❌ Кэф должен быть больше 1!")
        
        u['balance'] -= bet
        
        # Генерация краша (смещенная вероятность для реализма)
        chance = random.random()
        if chance < 0.1: crash_point = random.uniform(1.0, 1.2) # Мгновенный краш
        elif chance < 0.6: crash_point = random.uniform(1.2, 2.5) # Средний
        else: crash_point = random.uniform(2.5, 5.0) # Высокий
        
        crash_point = round(crash_point, 2)
        
        if crash_point >= target:
            win = int(bet * target)
            u['balance'] += win
            msg = (
                "🤩 <b>Вы выиграли!</b>\n"
                f"📈 Точка краша: {crash_point}\n"
                f"🎯 Множитель: {target:.2f}\n"
                f"💸 Ставка: {format_num(bet)} $\n"
                f"💰 Баланс: {format_num(u['balance'])} $"
            )
        else:
            msg = (
                "😔 <b>Вы проиграли!</b>\n"
                f"📈 Точка краша: {crash_point}\n"
                f"🎯 Множитель: {target:.2f}\n"
                f"💸 Ставка: {format_num(bet)} $\n"
                f"💰 Баланс: {format_num(u['balance'])} $"
            )
        await message.answer(msg)
        await save_data()

    except:
        await message.answer("📝 Пример: <code>Краш 1к 1.5</code>")

# --- КОСТИ (НОВАЯ ИГРА) ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    # Кости [сумма] [ставка]
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        outcome = args[2].lower() # больше, меньше, 7
        
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        u['balance'] -= bet
        
        d1 = random.randint(1, 6)
        d2 = random.randint(1, 6)
        total = d1 + d2
        
        win_mult = 0
        if outcome in ["7", "семь", "seven"] and total == 7:
            win_mult = 5.8
        elif outcome in ["больше", "б", ">"] and total > 7:
            win_mult = 2.33
        elif outcome in ["меньше", "м", "<"] and total < 7:
            win_mult = 2.33
            win_val = int(bet * win_mult)
        
        res_txt = (
            f"🎲 <b>КОСТИ</b>\n"
            f"Выпало: <b>{d1} + {d2} = {total}</b>\n"
            f"Ваш выбор: <b>{outcome}</b>\n"
            f"💸 Ставка: {format_num(bet)} $\n"
        )
        
        if win_val > 0:
            u['balance'] += win_val
            res_txt += f"🎉 <b>Выигрыш: {format_num(win_val)} $</b>\n"
        else:
            res_txt += f"❌ <b>Проигрыш</b>\n"
            
        res_txt += f"💰 Баланс: {format_num(u['balance'])} $"
        await message.answer(res_txt)
        await save_data()
        
    except:
        await message.answer("📝 Пример: <code>Кости 10к больше</code> (или меньше, 7)")

# --- МИНЫ (НОВАЯ ИГРА - Inline) ---
@dp.message(F.text.lower().startswith("мины"))
async def game_mines_start(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        bet = parse_amount(args[1], u['balance'])
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        mines_count = 3 # Дефолт
        if len(args) > 2: mines_count = int(args[2])
        if mines_count < 1 or mines_count > 24: return await message.answer("❌ От 1 до 24 мин!")

        # Инициализация игры
        u['balance'] -= bet
        
        # Поле 5x5 (25 ячеек)
        grid = [False] * 25
        # Расставляем мины
        mine_indices = random.sample(range(25), mines_count)
        for idx in mine_indices: grid[idx] = True # True = Мина
        
        game_id = f"mines_{message.from_user.id}_{int(time.time())}"
        active_games[game_id] = {
            "type": "mines",
            "uid": message.from_user.id,
            "bet": bet,
            "mines": mines_count,
            "grid": grid, # True если мина
            "opened": [False]*25,
            "multiplier": 1.0,
            "step": 0
        }
        
        await message.answer(
            f"💣 <b>МИНЫ</b>\nСтавка: {format_num(bet)} $\nМин: {mines_count}\nОткрывай ячейки!", 
            reply_markup=get_mines_kb(game_id, [False]*25)
        )
        await save_data()
    except:
        await message.answer("📝 Пример: <code>Мины 1к</code> (по дефолту 3 мины)")

def get_mines_kb(gid, opened_mask, finish=False, grid_real=None):
    kb = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            text = "⬜️"
            cb = f"mn_{gid}_{idx}"
            
            if finish and grid_real:
                if grid_real[idx]: text = "💣"
                elif opened_mask[idx]: text = "💎"
                else: text = "▪️"
                cb = "ignore"
            elif opened_mask[idx]:
                text = "💎"
                cb = "ignore"
                
            row.append(InlineKeyboardButton(text=text, callback_data=cb))
        kb.append(row)
    
    if not finish:
        kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ ДЕНЬГИ", callback_data=f"mn_claim_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("mn_"))
async def mines_action(call: CallbackQuery):
    data = call.data.split("_")
    action = data[1] # gameid or claim
    
    if action == "claim":
        gid = "_".join(data[2:])
        game = active_games.get(gid)
        if not game: return await call.answer("Игра не найдена", show_alert=True)
        
        win = int(game['bet'] * game['multiplier'])
        u = get_user(game['uid'])
        u['balance'] += win
        del active_games[gid]
        await save_data()
        await call.message.edit_text(f"💰 <b>ВЫИГРЫШ: {format_num(win)} $</b>", reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        return

    gid = "_".join(data[1:-1])
    idx = int(data[-1])
    game = active_games.get(gid)
    
    if not game: return await call.answer("Игра устарела", show_alert=True)
    if game['uid'] != call.from_user.id: return await call.answer("Не твоя игра!", show_alert=True)
    
    if game['grid'][idx]: # Попал на мину
        del active_games[gid]
        await call.message.edit_text(f"💥 <b>БАБАХ! Вы проиграли {format_num(game['bet'])} $</b>", reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
    else:
        game['opened'][idx] = True
        game['step'] += 1
        # Простой расчет множителя
        safe_remaining = 25 - game['mines'] - (game['step'] - 1)
        if safe_remaining <= 0: safe_remaining = 1
        mult_step = 25 / safe_remaining
        game['multiplier'] *= (0.95 * mult_step) # 5% комиссии казино
        
        await call.message.edit_text(
            f"💎 <b>МИНЫ</b> | Множитель: x{game['multiplier']:.2f}\nВыигрыш сейчас: {format_num(int(game['bet']*game['multiplier']))} $",
            reply_markup=get_mines_kb(gid, game['opened'])
        )

# --- АЛМАЗЫ (НОВАЯ ИГРА - Упрощенная Inline башня) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_diamonds_start(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        u['balance'] -= bet
        gid = f"dm_{message.from_user.id}_{int(time.time())}"
        
        active_games[gid] = {
            "type": "diamonds",
            "uid": message.from_user.id,
            "bet": bet,
            "lvl": 0,
            "mult": 1.0
        }
        
        await message.answer(
            f"💎 <b>АЛМАЗЫ: Уровень 1/16</b>\n💰 Ставка: {format_num(bet)} $\nУгадай где алмаз!",
            reply_markup=get_diamonds_kb(gid)
        )
        await save_data()
    except: await message.answer("📝 Пример: <code>Алмазы 1к</code>")

def get_diamonds_kb(gid):
    # 3 кнопки выбора + забрать
    row = [
        InlineKeyboardButton(text="🔹", callback_data=f"dm_g_{gid}_0"),
        InlineKeyboardButton(text="🔹", callback_data=f"dm_g_{gid}_1"),
        InlineKeyboardButton(text="🔹", callback_data=f"dm_g_{gid}_2")
    ]
    cashout = [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"dm_c_{gid}")]
    return InlineKeyboardMarkup(inline_keyboard=[row, cashout])

@dp.callback_query(F.data.startswith("dm_"))
async def diamonds_action(call: CallbackQuery):
    parts = call.data.split("_")
    action = parts[1] # g (guess) or c (claim)
    gid = "_".join(parts[2:] if action == 'c' else parts[2:-1])
    
    game = active_games.get(gid)
    if not game: return await call.answer("Игра не найдена", show_alert=True)
    
    if action == "c":
        win = int(game['bet'] * game['mult'])
        get_user(game['uid'])['balance'] += win
        del active_games[gid]
        await save_data()
        await call.message.edit_text(f"💰 <b>Вы забрали: {format_num(win)} $</b>")
        return

    choice = int(parts[-1])
    # Шанс 1 к 3
    correct = random.randint(0, 2)
    
    if choice == correct:
        game['lvl'] += 1
        game['mult'] *= 2.0 # Жесткий множитель
        
        if game['lvl'] >= 16:
            win = int(game['bet'] * game['mult'])
            get_user(game['uid'])['balance'] += win
            del active_games[gid]
            await save_data()
            await call.message.edit_text(f"🏆 <b>ПОБЕДА! Вы прошли все уровни!\nВыигрыш: {format_num(win)} $</b>")
        else:
            await call.message.edit_text(
                f"✅ <b>Угадал! Уровень {game['lvl']+1}/16</b>\nТекущий выигрыш: {format_num(int(game['bet']*game['mult']))} $",
                reply_markup=get_diamonds_kb(gid)
            )
    else:
        del active_games[gid]
        await call.message.edit_text(f"❌ <b>Алмаз был в ячейке {correct+1}. Вы проиграли!</b>")

# ==========================================
#              ФЕРМА BTC (NVIDIA)
# ==========================================

FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.1, "scale": 1.20}, # +20%
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.4, "scale": 1.20}, # +20%
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.7, "scale": 1.30}  # +30%
}

def calculate_farm_income(u):
    now = time.time()
    last = u['farm']['last_collect']
    seconds = now - last
    
    total_hourly_income = (
        u['farm']['rtx3060'] * FARM_CONFIG['rtx3060']['income'] +
        u['farm']['rtx4070'] * FARM_CONFIG['rtx4070']['income'] +
        u['farm']['rtx4090'] * FARM_CONFIG['rtx4090']['income']
    )
    
    income_btc = (total_hourly_income / 3600) * seconds
    return income_btc, total_hourly_income

@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    u = get_user(message.from_user.id)
    pending_btc, hourly = calculate_farm_income(u)
    
    txt = (
        f"🖥 <b>BTC ФЕРМА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Ваши видеокарты:</b>\n"
        f"🔹 RTX 3060: <b>{u['farm']['rtx3060']} шт.</b>\n"
        f"🔹 RTX 4070: <b>{u['farm']['rtx4070']} шт.</b>\n"
        f"🔹 RTX 4090: <b>{u['farm']['rtx4090']} шт.</b>\n\n"
        f"📉 Доход в час: <b>{hourly:.2f} BTC</b>\n"
        f"💰 Намайнено: <b>{pending_btc:.6f} BTC</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать доход", callback_data="farm_collect")],
        [InlineKeyboardButton(text="🛍 Купить видеокарты", callback_data="farm_shop")]
    ])
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "farm_collect")
async def farm_collect_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    pending_btc, _ = calculate_farm_income(u)
    
    if pending_btc <= 0:
        return await call.answer("⚠️ Нечего собирать!", show_alert=True)
    
    u['btc'] += pending_btc
    u['farm']['last_collect'] = time.time()
    await save_data()
    
    await call.answer(f"✅ Собрано {pending_btc:.6f} BTC", show_alert=True)
    await cmd_farm(call.message) # Обновить сообщение

@dp.callback_query(F.data == "farm_shop")
async def farm_shop_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    
    kb_list = []
    for key, cfg in FARM_CONFIG.items():
        count = u['farm'][key]
        if count >= 3:
            btn_text = f"{cfg['name']} (МАКС)"
            cb = "ignore"
        else:
            # Динамическая цена
            price = int(cfg['base_price'] * (cfg['scale'] ** count))
            btn_text = f"{cfg['name']} - {format_num(price)}$ (+{cfg['income']} BTC/ч)"
            cb = f"farm_buy_{key}"
        
        kb_list.append([InlineKeyboardButton(text=btn_text, callback_data=cb)])
        
    kb_list.append([InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")])
    
    await call.message.edit_text("🛍 <b>МАГАЗИН ВИДЕОКАРТ</b>\nЛимит: 3 шт. каждой модели.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_cb(call: CallbackQuery):
    key = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    cfg = FARM_CONFIG[key]
    
    count = u['farm'][key]
    if count >= 3: return await call.answer("❌ Максимум 3 карты этого типа!", show_alert=True)
    
    price = int(cfg['base_price'] * (cfg['scale'] ** count))
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    # Перед покупкой собираем старый доход, чтобы не сбросился таймер
    pending, _ = calculate_farm_income(u)
    u['btc'] += pending
    u['farm']['last_collect'] = time.time()
    
    u['balance'] -= price
    u['farm'][key] += 1
    
    await save_data()
    await call.answer(f"✅ Куплено: {cfg['name']}", show_alert=True)
    await farm_shop_cb(call) # Обновить магазин

@dp.callback_query(F.data == "farm_back")
async def farm_back_cb(call: CallbackQuery):
    await call.message.delete()
    await cmd_farm(call.message)

@dp.callback_query(F.data == "ignore")
async def ignore_cb(call: CallbackQuery):
    await call.answer()

# --- BACKGROUND JOBS ---
async def bank_interest():
    for u in users.values():
        if u['bank'] > 0: u['bank'] += int(u['bank'] * 0.10)
    await save_data()

async def main():
    sync_load()
    # Запускаем планировщик для банка (каждую полночь)
    scheduler.add_job(bank_interest, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
    scheduler.start()
    
    # Web server для хостинга
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    # Запуск бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

            
