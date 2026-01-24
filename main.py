import asyncio
import os
import logging
import random
import json
import io
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiohttp import web

# Библиотеки Google
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN") # Или вставь токен сюда в кавычках
ADMIN_IDS = [1997428703] # Твой ID
PORT = int(os.getenv("PORT", 8080))

# Настройки Google Drive
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'

# Настройки каналов для подписки (ID или юзернеймы)
REQUIRED_CHANNELS = [
    {"username": "@nvibee_bet", "url": "https://t.me/nvibee_bet", "name": "Канал Vibe Bet"},
    {"username": "@chatvibee_bet", "url": "https://t.me/chatvibee_bet", "name": "Чат Vibe Bet"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
users = {}

# --- GOOGLE DRIVE (АСИНХРОННО) ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

def sync_load():
    global users
    service = get_drive_service()
    if not service: 
        logging.warning("Нет файла credentials.json!")
        return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8').strip()
        if content:
            data = json.loads(content)
            users = {int(k): v for k, v in data.items()}
            logging.info("✅ База данных загружена из Google Drive")
    except Exception as e: logging.error(f"Ошибка загрузки БД: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(users, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: logging.error(f"Ошибка сохранения БД: {e}")

async def save_data():
    # Сохраняем в отдельном потоке, чтобы бот летал
    await asyncio.to_thread(sync_save)

# --- ПРОВЕРКА ПОДПИСКИ (MIDDLEWARE) ---
async def check_subscription(user_id):
    not_subbed = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["username"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_subbed.append(channel)
        except Exception as e:
            # Если бот не админ, он не сможет проверить. Считаем, что не подписан, или логируем ошибку
            logging.error(f"Ошибка проверки подписки {channel['username']}: {e}")
            not_subbed.append(channel)
    return not_subbed

@dp.message.outer_middleware()
async def sub_middleware(handler, event: Message, data):
    # Пропускаем команду старт, чтобы показать приветствие, но блокируем действия
    if event.text and event.text.startswith("/start"):
        return await handler(event, data)
    
    # Исключаем админов из проверки, чтобы ты мог тестить спокойно
    if event.from_user.id in ADMIN_IDS:
        return await handler(event, data)

    not_subbed = await check_subscription(event.from_user.id)
    
    if not_subbed:
        # Генерируем клавиатуру
        keyboard = []
        for ch in not_subbed:
            keyboard.append([InlineKeyboardButton(text=f"👉 Подписаться: {ch['name']}", url=ch['url'])])
        
        # Кнопка проверки
        keyboard.append([InlineKeyboardButton(text="✅ Я ПОДПИСАЛСЯ", callback_data="check_sub_btn")])
        
        await event.answer(
            "🔒 <b>ДОСТУП ЗАКРЫТ!</b>\n\n"
            "Для игры в <b>Vibe Bet</b> необходимо быть подписанным на наши ресурсы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        return # Прерываем обработку
    
    return await handler(event, data)

@dp.callback_query(F.data == "check_sub_btn")
async def callback_check_sub(call: CallbackQuery):
    not_subbed = await check_subscription(call.from_user.id)
    if not not_subbed:
        await call.message.delete()
        await call.message.answer("✅ <b>Спасибо! Доступ открыт.</b>\nЖми /start или пиши <b>Профиль</b>")
    else:
        await call.answer("❌ Вы подписались не на все каналы!", show_alert=True)

# --- UTILS ---
def get_user(uid, name="Игрок"):
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 10000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, "last_work": 0, "last_bonus": 0
        }
        asyncio.create_task(save_data())
    return users[uid]

def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        if num < 1_000_000: return f"{num/1000:.1f}к"
        if num < 1_000_000_000: return f"{num/1_000_000:.1f}кк"
        return f"{num/1_000_000_000:.1f}ккк"
    except: return "0"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    m = {"к": 1000, "кк": 1000000, "ккк": 1000000000}
    for k, v in m.items():
        if text.endswith(k):
            try: return int(float(text.replace(k, "")) * v)
            except: return None
    try: return int(float(text))
    except: return None

async def add_xp_logic(message, u, amount):
    u['xp'] += amount
    needed = u['lvl'] * 10
    if u['xp'] >= needed:
        u['lvl'] += 1; u['xp'] = 0
        await message.answer(f"🆙 <b>LEVEL UP!</b>\nТеперь у тебя <b>{u['lvl']} уровень</b>!")

# --- COMMANDS ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    # Сначала проверяем подписку, даже на старте
    if message.from_user.id not in ADMIN_IDS:
        not_subbed = await check_subscription(message.from_user.id)
        if not_subbed:
            keyboard = [[InlineKeyboardButton(text=f"👉 {ch['name']}", url=ch['url'])] for ch in not_subbed]
            keyboard.append([InlineKeyboardButton(text="✅ Я ПОДПИСАЛСЯ", callback_data="check_sub_btn")])
            return await message.answer("👋 Привет! Чтобы начать, подпишись на нас:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    u = get_user(message.from_user.id, message.from_user.first_name)
    
    # Работа с картинкой
    photo_file = FSInputFile("start_img.jpg")
    
    caption_text = (
        f"👋 <b>Добро Пожаловать в Vibe Bet!</b>\n\n"
        f"Игровой телеграм бот. Играй, веселись, все это ТУТ!\n\n"
        f"👤 Игрок: <b>{u['name']}</b>\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n\n"
        f"👇 <b>Меню команд:</b>\n"
        f"• <code>Профиль</code> — Твоя статистика\n"
        f"• <code>Работа</code> — Заработать денег\n"
        f"• <code>Рул [сумма] [цвет]</code> — Рулетка\n"
        f"• <code>Краш [сумма] [кэф]</code> — Краш\n"
        f"• <code>Магазин</code> — Купить инструменты"
    )
    
    try:
        await message.answer_photo(photo=photo_file, caption=caption_text)
    except Exception as e:
        await message.answer(caption_text) # Если фото не нашли, шлем текст
        logging.error(f"Не удалось отправить фото: {e}")

@dp.message(F.text.lower().in_({"профиль", "стата", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id, message.from_user.first_name)
    needed = u['lvl'] * 10
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ: {u['name']}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💵 Деньги: <b>{format_num(u['balance'])} $</b>\n"
        f"🏦 В банке: <b>{format_num(u['bank'])} $</b>\n"
        f"🪙 Crypto: <b>{u['btc']:.6f} BTC</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"📊 Опыт: <b>{u['xp']} / {needed} XP</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(text)

@dp.message(F.text.lower().startswith("рул"))
async def cmd_roulette(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    
    if len(args) < 3:
        return await message.answer("⚠️ <b>Использование:</b>\n<code>рул 100к черный</code>\n<code>рул все красный</code>")
    
    try:
        amt = parse_amount(args[1], u['balance'])
        col = args[2].lower()
        if amt is None or amt <= 0 or amt > u['balance']: raise ValueError
    except:
        return await message.answer("❌ <b>Ошибка!</b> Неверная сумма или недостаточно средств.")

    u['balance'] -= amt
    res_num = random.randint(0, 36)
    
    # Определение цвета выпавшего числа
    if res_num == 0: win_col = "зеленый"
    elif res_num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]: win_col = "красный"
    else: win_col = "черный"
    
    win_amt = 0
    # Логика выигрыша
    if (col.startswith("чер") and win_col == "черный") or (col.startswith("кра") and win_col == "красный"):
        win_amt = amt * 2
    elif col.startswith("зел") and win_col == "зеленый":
        win_amt = amt * 14

    u['balance'] += win_amt
    
    xp_text = ""
    # 30% ШАНС НА ОПЫТ
    if random.random() < 0.30:
        await add_xp_logic(message, u, 1)
        xp_text = "\n🔥 <b>+1 XP</b>"
    
    asyncio.create_task(save_data())
    
    if win_amt > 0:
        res_text = f"✅ <b>ПОБЕДА!</b>\n💸 Выиграно: <b>{format_num(win_amt)} $</b>"
    else:
        res_text = f"❌ <b>ПРОИГРЫШ...</b>"

    await message.answer(
        f"🎰 <b>VIBE CASINO</b>\n"
        f"🎲 Выпало: <b>{res_num} {win_col.upper()}</b>\n"
        f"{res_text}\n"
        f"💰 Баланс: <b>{format_num(u['balance'])}$</b>{xp_text}"
    )

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    
    if len(args) < 3:
        return await message.answer("⚠️ <b>Использование:</b>\n<code>краш 50к 1.5</code>")
        
    try:
        amt = parse_amount(args[1], u['balance'])
        target_mult = float(args[2].replace(",", "."))
        if amt is None or amt <= 0 or amt > u['balance']: raise ValueError
        if target_mult < 1.01: return await message.answer("❌ Минимальный кэф 1.01")
    except:
        return await message.answer("❌ Неверные данные.")

    u['balance'] -= amt
    # Генерируем краш (имитация)
    crash_point = round(random.uniform(1.0, 5.0), 2)
    if random.random() < 0.1: crash_point = round(random.uniform(1.0, 1.15), 2) # Часто бреем на низких
    
    win_amt = 0
    if target_mult <= crash_point:
        win_amt = int(amt * target_mult)
        u['balance'] += win_amt
        res_text = f"🚀 <b>ЗАБРАЛ!</b> (x{target_mult})\n💸 Приз: <b>{format_num(win_amt)} $</b>"
    else:
        res_text = f"💥 <b>КРАШНУЛОСЬ!</b>"

    xp_text = ""
    if random.random() < 0.30:
        await add_xp_logic(message, u, 1)
        xp_text = "\n🔥 <b>+1 XP</b>"

    asyncio.create_task(save_data())
    await message.answer(
        f"📉 <b>CRASH GAME</b>\n"
        f"🛑 Стоп: <b>{crash_point}x</b>\n"
        f"{res_text}\n"
        f"💰 Баланс: <b>{format_num(u['balance'])}$</b>{xp_text}"
    )

@dp.message(F.text.lower().in_({"работа", "work"}))
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    now = datetime.now().timestamp()
    
    if now - u.get('last_work', 0) < 600:
        rem_min = int((600 - (now - u['last_work'])) // 60)
        rem_sec = int((600 - (now - u['last_work'])) % 60)
        return await message.answer(f"⏳ <b>Устал?</b> Отдохни еще {rem_min} мин {rem_sec} сек.")
    
    if u['shovel'] <= 0 or u['detector'] <= 0:
        return await message.answer("🛠 <b>Нет инструментов!</b>\nКупи лопату и детектор в <code>Магазин</code>")

    u['shovel'] -= 1; u['detector'] -= 1
    u['last_work'] = now
    
    money = random.randint(5000, 25000) * u['lvl'] # Чем выше лвл, тем больше денег
    u['balance'] += money
    
    msg = f"⛏ <b>РАБОТА ЗАВЕРШЕНА</b>\n💰 Заработано: <b>{format_num(money)} $</b>\n📉 Инструменты потрачены."
    
    # 30% шанс на опыт
    if random.random() < 0.30:
        xp = random.randint(1, 3)
        await add_xp_logic(message, u, xp)
        msg += f"\n🔥 Получено: <b>+{xp} XP</b>"

    asyncio.create_task(save_data())
    await message.answer(msg)

@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Лопата (50к)", callback_data="buy_shovel")],
        [InlineKeyboardButton(text="📡 Детектор (100к)", callback_data="buy_detector")]
    ])
    await message.answer("🏪 <b>VIBE SHOP</b>\nИнструменты нужны для работы.", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_item(call: CallbackQuery):
    u = get_user(call.from_user.id)
    item = call.data.split("_")[1]
    
    price = 50000 if item == "shovel" else 100000
    name = "Лопату" if item == "shovel" else "Детектор"
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
        
    u['balance'] -= price
    u[item] = u.get(item, 0) + 5 # Даем 5 зарядов
    asyncio.create_task(save_data())
    
    await call.message.edit_text(f"✅ Вы купили <b>{name}</b> (5 шт.)\n💰 Остаток: {format_num(u['balance'])}")

# --- АДМИН ПАНЕЛЬ ---
@dp.message(F.text.lower().startswith("выдать"))
async def adm_give(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        # Формат: выдать ID СУММА
        parts = message.text.split()
        target_id = int(parts[1])
        amount = parse_amount(parts[2], 0)
        
        user = get_user(target_id)
        user['balance'] += amount
        asyncio.create_task(save_data())
        
        await message.answer(f"✅ Админ {message.from_user.first_name} выдал {format_num(amount)}$ игроку {target_id}")
        # Опционально: уведомить игрока
        try: await bot.send_message(target_id, f"🎁 <b>АДМИН ПОПОЛНИЛ ВАШ БАЛАНС:</b> +{format_num(amount)}$")
        except: pass
    except Exception as e:
        await message.answer(f"❌ Ошибка команды: {e}")

@dp.message(F.text.lower().startswith("бан"))
async def adm_ban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        target_id = int(message.text.split()[1])
        get_user(target_id)['banned'] = True
        asyncio.create_task(save_data())
        await message.answer(f"🚫 Игрок {target_id} забанен.")
    except: pass

# --- WEB SERVER ---
async def handle_ping(request): return web.Response(text="Vibe Bet Bot is Alive!")

async def main():
    # Предзагрузка базы
    await asyncio.to_thread(sync_load)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
