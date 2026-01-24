import asyncio
import os
import logging
import random
import asyncpg
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiohttp import web

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DB_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

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

# --- БАЗА ДАННЫХ ---
async def init_db():
    try:
        conn = await asyncpg.connect(DB_URL, ssl='disable')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY, balance BIGINT DEFAULT 50000, btc NUMERIC DEFAULT 0,
                lvl INT DEFAULT 1, xp INT DEFAULT 0, deposit BIGINT DEFAULT 0,
                tools_durability INT DEFAULT 0
            );
        ''')
        await conn.close()
        logging.info("✅ База данных подключена и настроена")
    except Exception as e:
        logging.error(f"❌ Ошибка БД: {e}")

# --- ФОНОВАЯ ЗАДАЧА: БАНК (10% в 00:00) ---
async def bank_scheduler():
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            async with dp['db_pool'].acquire() as conn:
                await conn.execute("UPDATE users SET deposit = deposit + (deposit * 0.1) WHERE deposit > 0")
            logging.info("🏦 Начислены проценты по вкладам!")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    async with dp['db_pool'].acquire() as conn:
        await conn.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", message.from_user.id)
    
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
        await call.message.answer("🎉 Доступ разрешен! Напиши **Я**, чтобы открыть профиль.")
    else:
        await call.answer("❌ Подписка не найдена! Проверь канал и чат.", show_alert=True)

# Профиль
@dp.message(F.text.lower() == "я")
async def cmd_profile(message: Message):
    if not await is_subscribed(message.from_user.id):
        return await message.answer("🛑 Сначала подпишись!", reply_markup=sub_kb())
    
    async with dp['db_pool'].acquire() as conn:
        u = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
        text = (f"👤 **ПРОФИЛЬ | {message.from_user.first_name}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 Баланс: **{format_num(u['balance'])}**\n"
                f"🏦 Банк: **{format_num(u['deposit'])}**\n"
                f"₿ Биткоины: **{u['btc']:.6f} BTC**\n"
                f"🛠 Инструменты: **{u['tools_durability']}/5**")
        await message.answer(text)

# Работа: Кладоискатель
@dp.message(Command("кладоискатель"))
async def cmd_treasure(message: Message):
    if not await is_subscribed(message.from_user.id): return
    
    async with dp['db_pool'].acquire() as conn:
        u = await conn.fetchrow("SELECT tools_durability, balance FROM users WHERE id = $1", message.from_user.id)
        if u['tools_durability'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Купить за 250к 💰", callback_data="buy_tools")]])
            return await message.answer("🪓 Твои инструменты сломаны! Купи новые за 250,000.", reply_markup=kb)
        
        money = random.randint(30000, 120000)
        btc_find = random.uniform(0.0001, 0.0006) if random.random() < 0.09 else 0
        
        await conn.execute('''
            UPDATE users SET balance = balance + $1, btc = btc + $2, 
            tools_durability = tools_durability - 1 WHERE id = $3
        ''', money, btc_find, message.from_user.id)
        
        res = f"🏺 **Успех!** Ты выкопал клад на **{format_num(money)} 💰**"
        if btc_find > 0: res += f"\n🟠 **НАХОДКА!** Ты нашел **{btc_find:.6f} BTC**"
        res += f"\n📉 Прочность: {u['tools_durability']-1}/5"
        await message.answer(res)

@dp.callback_query(F.data == "buy_tools")
async def buy_tools(call: CallbackQuery):
    async with dp['db_pool'].acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", call.from_user.id)
        if bal < 250000: return await call.answer("❌ Нужно 250,000 💰", show_alert=True)
        await conn.execute("UPDATE users SET balance = balance - 250000, tools_durability = 5 WHERE id = $1", call.from_user.id)
        await call.message.edit_text("✅ Ты купил новую лопату и металлоискатель!")

# Банковская система (Улучшенная)
@dp.message(Command("bank"))
async def cmd_bank(message: Message, command: CommandObject):
    if not await is_subscribed(message.from_user.id): return
    
    async with dp['db_pool'].acquire() as conn:
        # Если есть аргументы (напр. /bank dep 100)
        if command.args:
            args = command.args.split()
            action = args[0].lower()
            amount = parse_amount(args[1]) if len(args) > 1 else None
            
            u = await conn.fetchrow("SELECT balance, deposit FROM users WHERE id = $1", message.from_user.id)
            
            if action in ['dep', 'положить', '+']:
                if not amount or amount > u['balance'] or amount <= 0:
                    return await message.answer("❌ Укажи верную сумму для вклада.")
                await conn.execute("UPDATE users SET balance = balance - $1, deposit = deposit + $1 WHERE id = $2", amount, message.from_user.id)
                return await message.answer(f"✅ Внесено **{format_num(amount)} 💰**")
            
            if action in ['wd', 'снять', '-']:
                if not amount or amount > u['deposit'] or amount <= 0:
                    return await message.answer("❌ На вкладе недостаточно средств.")
                await conn.execute("UPDATE users SET balance = balance + $1, deposit = deposit - $1 WHERE id = $2", amount, message.from_user.id)
                return await message.answer(f"✅ Снято **{format_num(amount)} 💰**")

        # Основное меню
        dep = await conn.fetchval("SELECT deposit FROM users WHERE id = $1", message.from_user.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Внести всё", callback_data="bank_dep_all"),
             InlineKeyboardButton(text="➖ Снять всё", callback_data="bank_wd_all")]
        ])
        text = (f"🏦 **БАНК VIBE BET**\n\n"
                f"💰 Твой вклад: **{format_num(dep)}**\n"
                f"📈 Процент: **+10% в сутки**\n\n"
                f"ℹ️ Чтобы внести/снять сумму:\n"
                f"`/bank dep [сумма]` — Положить\n"
                f"`/bank wd [сумма]` — Снять")
        await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("bank_"))
async def bank_callback(call: CallbackQuery):
    async with dp['db_pool'].acquire() as conn:
        u = await conn.fetchrow("SELECT balance, deposit FROM users WHERE id = $1", call.from_user.id)
        if call.data == "bank_dep_all":
            if u['balance'] <= 0: return await call.answer("Баланс пуст!")
            await conn.execute("UPDATE users SET deposit = deposit + balance, balance = 0 WHERE id = $1", call.from_user.id)
            await call.answer("✅ Все деньги в банке!")
        elif call.data == "bank_wd_all":
            if u['deposit'] <= 0: return await call.answer("Вклад пуст!")
            await conn.execute("UPDATE users SET balance = balance + deposit, deposit = 0 WHERE id = $1", call.from_user.id)
            await call.answer("✅ Деньги сняты!")
        
        new_dep = await conn.fetchval("SELECT deposit FROM users WHERE id = $1", call.from_user.id)
        await call.message.edit_text(f"🏦 **БАНК VIBE BET**\n\n💰 Твой вклад: **{format_num(new_dep)}**\n📈 Процент: **+10%**\n\nℹ️ `/bank dep [сумма]` или `/bank wd [сумма]`", reply_markup=call.message.reply_markup)

# Продажа BTC
@dp.message(Command("sell_btc"))
async def cmd_sell_btc(message: Message, command: CommandObject):
    if not command.args: return await message.answer("ℹ️ Пример: `/sell_btc 0.005`")
    try:
        amt = float(command.args.replace(',', '.'))
        async with dp['db_pool'].acquire() as conn:
            u_btc = await conn.fetchval("SELECT btc FROM users WHERE id = $1", message.from_user.id)
            if u_btc < amt or amt <= 0: return await message.answer("❌ У тебя столько нет!")
            
            price = await get_btc_price()
            total = int(amt * price)
            await conn.execute("UPDATE users SET btc = btc - $1, balance = balance + $2 WHERE id = $3", amt, total, message.from_user.id)
            await message.answer(f"✅ Продано по курсу {format_num(price)}!\nПолучено: **{format_num(total)} 💰**")
    except: await message.answer("❌ Ошибка в сумме")

# Переводы по ID
@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    parts = message.text.split()
    if len(parts) < 3: return await message.answer("ℹ️ Формат: `перевести [ID] [сумма]`")
    try:
        to_id, amt = int(parts[1]), parse_amount(parts[2])
        async with dp['db_pool'].acquire() as conn:
            bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
            if amt > bal or amt <= 0: return await message.answer("❌ Недостаточно средств!")
            
            exists = await conn.fetchval("SELECT id FROM users WHERE id = $1", to_id)
            if not exists: return await message.answer("❌ Игрок не найден!")
            
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", amt, message.from_user.id)
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", amt, to_id)
            await message.answer(f"🤝 Ты перевел **{format_num(amt)}** игроку `{to_id}`")
    except: await message.answer("❌ Ошибка данных.")

# --- СИСТЕМНОЕ ---
async def handle_ping(request): return web.Response(text="Bot is running")

async def main():
    await init_db()
# Внутри функции main()
    dp['db_pool'] = await asyncpg.create_pool(
        DB_URL, 
        ssl='disable',
        min_size=1,
        max_size=10,
        statement_cache_size=0,         # Обязательно для Supabase Pooler
        max_cacheable_statement_size=0   # Обязательно для Supabase Pooler
    )
    asyncio.create_task(bank_scheduler())
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logging.info("🚀 БОТ ЗАПУЩЕН!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
