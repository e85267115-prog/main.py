import asyncio
import os
import logging
import random
import json
import io
import aiohttp
from datetime import datetime
from pytz import timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiohttp import web
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN") 
ADMIN_IDS = [1997428703]
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'

REQUIRED_CHANNELS = [
    {"username": "@nvibee_bet", "url": "https://t.me/nvibee_bet", "name": "Канал Vibe Bet"},
    {"username": "@chatvibee_bet", "url": "https://t.me/chatvibee_bet", "name": "Чат Vibe Bet"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Глобальные данные
users = {}
promos = {}

# --- GOOGLE DRIVE SYNC ---
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
            logging.info("✅ БД и Промокоды загружены")
    except Exception as e: logging.error(f"DB Load Error: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data_to_save = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: logging.error(f"Save Error: {e}")

async def save_data(): await asyncio.to_thread(sync_save)

def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        if num < 1_000_000: return f"{num/1000:.2f}к"
        if num < 1_000_000_000: return f"{num/1_000_000:.2f}кк"
        if num < 1_000_000_000_000: return f"{num/1_000_000_000:.2f}ккк"
        return f"{num/1_000_000_000_000:.2f}кккк"
    except: return "0"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    m = {"к": 1000, "кк": 1000000, "ккк": 1000000000, "кккк": 1000000000000}
    for k, v in m.items():
        if text.endswith(k):
            try: return int(float(text.replace(k, "")) * v)
            except: return None
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 10000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, "last_work": 0, "last_bonus": 0, "used_promos": []
        }
        asyncio.create_task(save_data())
    return users[uid]

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data['bitcoin']['usd']
    except: return 98000

# --- МИДЛВАРЬ (БАН И ПОДПИСКА) ---
@dp.message.outer_middleware()
async def check_access_msg(handler, event: Message, data):
    if not event.text: return await handler(event, data)
    u = get_user(event.from_user.id, event.from_user.first_name)
    if u.get('banned'):
        return await event.answer("🚫 <b>Ваш доступ заблокирован администрацией.</b>")
    if event.from_user.id not in ADMIN_IDS and not event.text.startswith("/start"):
        for ch in REQUIRED_CHANNELS:
            try:
                m = await bot.get_chat_member(chat_id=ch["username"], user_id=event.from_user.id)
                if m.status in ["left", "kicked"]:
                    kb = [[InlineKeyboardButton(text=f"👉 {c['name']}", url=c['url'])] for c in REQUIRED_CHANNELS]
                    kb.append([InlineKeyboardButton(text="✅ ПРОВЕРИТЬ", callback_data="check_sub")])
                    return await event.answer("🔒 <b>Подпишитесь для доступа:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            except: pass
    return await handler(event, data)

@dp.callback_query.outer_middleware()
async def check_access_kb(handler, event: CallbackQuery, data):
    u = get_user(event.from_user.id)
    if u.get('banned'):
        return await event.answer("🚫 Доступ заблокирован!", show_alert=True)
    return await handler(event, data)

# --- КОМАНДЫ АККАУНТА ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    txt = "👋 <b>Добро Пожаловать в Vibe Bet!</b>\nИгровой бот с биткоинами, бандами и кладами."
    try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📚 <b>СПИСОК КОМАНД:</b>\n\n"
        "👤 <b>Аккаунт:</b> <code>Профиль</code>, <code>Топ</code>, <code>Топ бтк</code>\n"
        "💸 <b>Доход:</b> <code>Работа</code>, <code>Бонус</code>, <code>Магазин</code>\n"
        "🏦 <b>Банк:</b> <code>Банк</code>, <code>Деп [сумма]</code>, <code>Снять [сумма]</code>\n"
        "🪙 <b>BTC:</b> <code>Рынок</code>, <code>Продать биткоин [кол-во]</code>\n"
        "🎁 <b>Промо:</b> <code>Создать промо [код] [сумма] [кол-во]</code>, <code>Промо [код]</code>\n"
        "🔄 <b>Перевод:</b> <code>Перевести [ID] [сумма]</code>"
    )

@dp.message(F.text.lower().in_({"профиль", "я"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    c = (1 if u['shovel'] > 0 else 0) + (1 if u['detector'] > 0 else 0)
    await message.answer(
        f"👤 <b>ПРОФИЛЬ</b>\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*10} XP)\n"
        f"🎒 Инструменты: <b>{c}/2</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )

@dp.message(F.text.lower().startswith("топ"))
async def cmd_tops(message: Message):
    is_btc = "бтк" in message.text.lower()
    if is_btc:
        sorted_users = sorted(users.items(), key=lambda x: x[1].get('btc', 0), reverse=True)[:10]
        title = "🏆 <b>ТОП-10 ПО BTC</b>"
    else:
        sorted_users = sorted(users.items(), key=lambda x: x[1].get('balance', 0), reverse=True)[:10]
        title = "🏆 <b>ТОП-10 ПО БАЛАНСУ</b>"

    txt = f"{title}\n\n"
    for i, (uid, u) in enumerate(sorted_users, 1):
        val = f"{u['btc']:.4f} BTC" if is_btc else f"{format_num(u['balance'])} $"
        txt += f"{i}. {u.get('name', 'Игрок')} — <b>{val}</b>\n"
    await message.answer(txt)

# --- СИСТЕМА БОНУСОВ И ПРОМО ---
@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = datetime.now().timestamp()
    if now - u.get('last_bonus', 0) < 3600:
        rem = int(3600 - (now - u['last_bonus']))
        return await message.answer(f"⏳ Бонус будет через {rem // 60} мин.")
    
    amount = 50000 + (u['lvl'] - 1) * 25000
    u['balance'] += amount
    u['last_bonus'] = now
    await save_data()
    await message.answer(f"🎁 Бонус <b>{format_num(amount)} $</b> зачислен!")

@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    u = get_user(message.from_user.id)
    try:
        _, _, code, reward_str, uses_str = message.text.split()
        reward = parse_amount(reward_str, u['balance'])
        uses = int(uses_str)
        if u['balance'] < reward * uses: return await message.answer("❌ Нет денег.")
        if code.upper() in promos: return await message.answer("❌ Уже есть.")
        
        u['balance'] -= (reward * uses)
        promos[code.upper()] = {"reward": reward, "uses": uses}
        await save_data()
        await message.answer(f"✅ Промо <code>{code.upper()}</code> на {uses} симв. создан!")
    except: await message.answer("📝: <code>Создать промо КОД СУММА КОЛВО</code>")

@dp.message(F.text.lower().startswith("промо"))
async def cmd_use_promo(message: Message):
    if "создать" in message.text.lower(): return
    u = get_user(message.from_user.id)
    try:
        code = message.text.split()[1].upper()
        if code not in promos or promos[code]["uses"] <= 0: return await message.answer("❌ Промо не найден.")
        if code in u.get("used_promos", []): return await message.answer("❌ Уже юзал.")
        
        reward = promos[code]["reward"]
        u['balance'] += reward
        u.setdefault("used_promos", []).append(code)
        promos[code]["uses"] -= 1
        if promos[code]["uses"] <= 0: del promos[code]
        await save_data()
        await message.answer(f"✅ Получено <b>{format_num(reward)} $</b>")
    except: await message.answer("📝: <code>Промо КОД</code>")

# --- КЛАДОИСКАТЕЛЬ (3 ЭТАПА) ---
@dp.message(F.text.lower() == "работа")
async def work_s1(message: Message):
    u = get_user(message.from_user.id)
    if u['shovel'] < 1 or u['detector'] < 1: return await message.answer("❌ Купи лопату и детектор!")
    if datetime.now().timestamp() - u['last_work'] < 600: return await message.answer("⏳ Отдохни!")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Начать поиск 🗺️", callback_data="w_2")]])
    await message.answer("🔎 Ищем место для раскопок?", reply_markup=kb)

@dp.callback_query(F.data == "w_2")
async def work_s2(call: CallbackQuery):
    await call.message.edit_text("📡 <i>Сканирование местности...</i>")
    await asyncio.sleep(2)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛏️ КОПАТЬ", callback_data="w_fin")]])
    await call.message.edit_text("📍 Сигнал пойман! Копаем?", reply_markup=kb)

@dp.callback_query(F.data == "w_fin")
async def work_fin(call: CallbackQuery):
    u = get_user(call.from_user.id)
    u['last_work'] = datetime.now().timestamp()
    win = random.randint(10000, 150000) if random.random() > 0.1 else random.randint(500000, 2000000)
    u['balance'] += win
    u['xp'] += 3
    if u['xp'] >= u['lvl']*10: u['lvl'] += 1; u['xp'] = 0
    await save_data()
    await call.message.edit_text(f"💎 Найдено: <b>{format_num(win)} $</b>\n📊 +3 XP")

# --- РЫНОК И МАГАЗИН ---
@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    p = await get_btc_price(); u = get_user(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰 Продать BTC", callback_data="btc_info")]])
    await message.answer(f"📊 <b>Курс: {format_num(p)} $</b>\nУ вас: {u['btc']:.6f} BTC", reply_markup=kb)

@dp.callback_query(F.data == "btc_info")
async def btc_info(call: CallbackQuery):
    await call.message.answer("Пиши: <code>Продать биткоин [кол-во]</code>")
    await call.answer()

@dp.message(F.text.lower().startswith("продать биткоин"))
async def btc_sell(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = float(message.text.split()[2].replace(",", "."))
        if amt > u['btc'] or amt <= 0: raise ValueError
        p = await get_btc_price(); gain = int(amt * p)
        u['btc'] -= amt; u['balance'] += gain
        await save_data(); await message.answer(f"✅ Продано за {format_num(gain)} $")
    except: await message.answer("❌ Ошибка суммы")

@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    u = get_user(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Лопата (50к)", callback_data="buy_sh"), InlineKeyboardButton(text="Детектор (100к)", callback_data="buy_dt")]
    ])
    await message.answer(f"🏪 <b>МАГАЗИН</b>\nЛопата: {'✅' if u['shovel'] else '❌'}\nДетектор: {'✅' if u['detector'] else '❌'}", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def shop_buy(call: CallbackQuery):
    u = get_user(call.from_user.id); item = "shovel" if "sh" in call.data else "detector"
    price = 50000 if item == "shovel" else 100000
    if u[item] or u['balance'] < price: return await call.answer("Нельзя купить")
    u['balance'] -= price; u[item] = 1; await save_data(); await cmd_shop(call.message)

# --- ФИНАНСЫ И БАНК ---
@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); tid = int(args[1]); amt = parse_amount(args[2], u['balance'])
        if tid not in users or amt > u['balance'] or amt <= 0: raise ValueError
        u['balance'] -= amt; users[tid]['balance'] += amt
        await save_data(); await message.answer(f"✅ Переведено {format_num(amt)} $")
    except: await message.answer("❌ Ошибка перевода")

@dp.message(F.text.lower().startswith("деп"))
async def cmd_dep(message: Message):
    u = get_user(message.from_user.id); amt = parse_amount(message.text.split()[1], u['balance'])
    if amt and 0 < amt <= u['balance']:
        u['balance'] -= amt; u['bank'] += amt; await save_data(); await message.answer(f"🏦 Деп: {format_num(amt)} $")

@dp.message(F.text.lower().startswith("снять"))
async def cmd_with(message: Message):
    u = get_user(message.from_user.id); amt = parse_amount(message.text.split()[1], u['bank'])
    if amt and 0 < amt <= u['bank']:
        u['bank'] -= amt; u['balance'] += amt; await save_data(); await message.answer(f"💳 Снято: {format_num(amt)} $")

@dp.message(F.text.lower() == "банк")
async def cmd_bank_view(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(f"🏦 <b>БАНК</b>\nНа счету: {format_num(u['bank'])} $\n+10% в полночь.")

# --- АДМИНКА ---
@dp.message(F.text.lower().startswith("выдать"))
async def adm_give(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split(); target = get_user(args[1])
        if "бтк" in message.text.lower(): target['btc'] += float(args[2])
        else: target['balance'] += parse_amount(args[2], 0)
        await save_data(); await message.answer("✅ Выдано")
    except: await message.answer("Ошибка")

@dp.message(F.text.lower().startswith("бан"))
async def adm_ban(message: Message):
    if message.from_user.id in ADMIN_IDS:
        get_user(message.text.split()[1])['banned'] = True
        await save_data(); await message.answer("🚫 Забанен")

@dp.message(F.text.lower().startswith("разбан"))
async def adm_unban(message: Message):
    if message.from_user.id in ADMIN_IDS:
        get_user(message.text.split()[1])['banned'] = False
        await save_data(); await message.answer("✅ Разбанен")

# --- ГЕМБЛИНГ (РУЛЕТКА И КРАШ) ---
@dp.message(F.text.lower().startswith("рул"))
async def cmd_roul(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance']); col = args[2].lower(); u['balance'] -= amt
        res = random.randint(0,36)
        win_c = "зеленый" if res==0 else "красный" if res in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
        mul = 14 if col=="зеленый" and win_c=="зеленый" else 2 if col[:3]==win_c[:3] else 0
        u['balance'] += amt*mul; await save_data()
        await message.answer(f"🎲 Выпало: {res} ({win_c})\n{'✅ Победа!' if mul else '❌ Проигрыш'}")
    except: await message.answer("Пример: <code>рул 100 крас</code>")

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance']); target = float(args[2].replace(",","."))
        u['balance'] -= amt; cp = round(random.uniform(1.0, 3.0), 2)
        if target <= cp: u['balance'] += int(amt*target); res = f"🚀 Вылет {cp}x. Успех!"
        else: res = f"💥 КРАШ {cp}x!"
        await save_data(); await message.answer(res)
    except: await message.answer("Пример: <code>краш 100 2.0</code>")

# --- ЗАПУСК ---
async def bank_job():
    for u in users.values(): u['bank'] += int(u['bank'] * 0.10)
    await save_data()

async def main():
    sync_load()
    scheduler.add_job(bank_job, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
    scheduler.start()
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
