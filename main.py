import asyncio
import os
import logging
import random
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiohttp import web

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ЛОКАЛЬНАЯ БАЗА ДАННЫХ (Сбросится при перезагрузке) ---
users = {}

def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "balance": 50000,
            "deposit": 0,
            "btc": 0.0,
            "tools_durability": 0
        }
    return users[user_id]

# --- UTILS ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        if num < 1000000: return f"{num/1000:.2f}к".replace(".00", "")
        if num < 1000000000: return f"{num/1000000:.2f}кк".replace(".00", "")
        return f"{num/1000000000:.2f}ккк".replace(".00", "")
    except: return "0"

def parse_amount(text):
    if not text: return None
    text = text.lower().strip().replace('k', 'к').replace(',', '.')
    mults = {'ккк': 10**9, 'кк': 10**6, 'к': 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try: return int(float(text.replace(m, '')) * v)
            except: return None
    try: return int(float(text))
    except: return None

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data['bitcoin']['usd'] * 100 
    except: return 10000000 

# --- ПРОВЕРКА ПОДПИСКИ ---
async def is_subscribed(user_id):
    try:
        s1 = await bot.get_chat_member(CHANNEL_ID, user_id)
        s2 = await bot.get_chat_member(CHAT_ID, user_id)
        valid = ['member', 'administrator', 'creator']
        return s1.status in valid and s2.status in valid
    except: return False

def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL), InlineKeyboardButton(text="💬 Чат", url=CHAT_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
    ])

# --- ФОНОВАЯ ЗАДАЧА: БАНК ---
async def bank_scheduler():
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            for uid in users:
                if users[uid]['deposit'] > 0:
                    users[uid]['deposit'] = int(users[uid]['deposit'] * 1.1)
            logging.info("🏦 Начислены проценты!")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id) # Создаем профиль
    caption = (
        "✨ **Добро Пожаловать в Vibe Bet!**\n\n"
        "Игровой бот в Телеграмм! Играй и Веселись. 🎰🔥\n\n"
        "⚠️ **Чтобы начать, подпишись на канал и чат:**"
    )
    try:
        await message.answer_photo(photo=FSInputFile("start_img.jpg"), caption=caption, reply_markup=sub_kb())
    except:
        await message.answer(caption, reply_markup=sub_kb())

@dp.callback_query(F.data == "check_sub")
async def check_sub_call(call: CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.delete()
        await call.message.answer("🎉 Доступ разрешен! Напиши **Я**")
    else:
        await call.answer("❌ Подписка не найдена!", show_alert=True)

@dp.message(F.text.lower() == "я")
async def cmd_profile(message: Message):
    if not await is_subscribed(message.from_user.id):
        return await message.answer("🛑 Сначала подпишись!", reply_markup=sub_kb())
    
    u = get_user(message.from_user.id)
    text = (f"👤 **ПРОФИЛЬ | {message.from_user.first_name}**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс: **{format_num(u['balance'])}**\n"
            f"🏦 Банк: **{format_num(u['deposit'])}**\n"
            f"₿ Биткоины: **{u['btc']:.6f} BTC**\n"
            f"🛠 Инструменты: **{u['tools_durability']}/5**")
    await message.answer(text)

@dp.message(Command("кладоискатель"))
async def cmd_treasure(message: Message):
    if not await is_subscribed(message.from_user.id): return
    u = get_user(message.from_user.id)
    
    if u['tools_durability'] <= 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Купить за 250к 💰", callback_data="buy_tools")]])
        return await message.answer("🪓 Инструменты сломаны!", reply_markup=kb)
    
    money = random.randint(30000, 120000)
    btc_find = random.uniform(0.0001, 0.0006) if random.random() < 0.09 else 0
    
    u['balance'] += money
    u['btc'] += btc_find
    u['tools_durability'] -= 1
    
    res = f"🏺 Клад на **{format_num(money)} 💰**"
    if btc_find > 0: res += f"\n🟠 Найдено: **{btc_find:.6f} BTC**"
    res += f"\n📉 Прочность: {u['tools_durability']}/5"
    await message.answer(res)

@dp.callback_query(F.data == "buy_tools")
async def buy_tools(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if u['balance'] < 250000: return await call.answer("❌ Нужно 250,000 💰", show_alert=True)
    u['balance'] -= 250000
    u['tools_durability'] = 5
    await call.message.edit_text("✅ Ты купил инструменты!")

@dp.message(Command("bank"))
async def cmd_bank(message: Message, command: CommandObject):
    if not await is_subscribed(message.from_user.id): return
    u = get_user(message.from_user.id)
    
    if command.args:
        args = command.args.split()
        action = args[0].lower()
        amount = parse_amount(args[1]) if len(args) > 1 else None
        
        if action in ['dep', 'положить', '+']:
            if not amount or amount > u['balance'] or amount <= 0: return await message.answer("❌ Ошибка суммы")
            u['balance'] -= amount
            u['deposit'] += amount
            return await message.answer(f"✅ Внесено {format_num(amount)}")
        
        if action in ['wd', 'снять', '-']:
            if not amount or amount > u['deposit'] or amount <= 0: return await message.answer("❌ Ошибка суммы")
            u['balance'] += amount
            u['deposit'] -= amount
            return await message.answer(f"✅ Снято {format_num(amount)}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Внести всё", callback_data="bank_dep_all"),
         InlineKeyboardButton(text="➖ Снять всё", callback_data="bank_wd_all")]
    ])
    await message.answer(f"🏦 **БАНК**\nВклад: **{format_num(u['deposit'])}**\nПроцент: +10% в 00:00\n\n`/bank dep [сумма]`", reply_markup=kb)

@dp.callback_query(F.data.startswith("bank_"))
async def bank_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if call.data == "bank_dep_all":
        u['deposit'] += u['balance']
        u['balance'] = 0
    elif call.data == "bank_wd_all":
        u['balance'] += u['deposit']
        u['deposit'] = 0
    await call.answer("Готово!")
    await cmd_bank(call.message, CommandObject(command="bank", args=None)) # Обновляем меню

@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    parts = message.text.split()
    if len(parts) < 3: return
    try:
        to_id, amt = int(parts[1]), parse_amount(parts[2])
        u_from = get_user(message.from_user.id)
        u_to = get_user(to_id)
        if amt > u_from['balance'] or amt <= 0: return await message.answer("❌ Нет денег")
        u_from['balance'] -= amt
        u_to['balance'] += amt
        await message.answer(f"🤝 Переведено **{format_num(amt)}** игроку `{to_id}`")
    except: pass

# --- СИСТЕМНОЕ ---
async def handle_ping(request): return web.Response(text="Bot Alive")

async def main():
    asyncio.create_task(bank_scheduler())
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
