import asyncio
import os
import logging
import random
import asyncpg
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, FSInputFile
)
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
        if num < 1_000_000: return f"{num/1000:.2f}к".replace(".00", "")
        if num < 1_000_000_000: return f"{num/1_000_000:.2f}кк".replace(".00", "")
        return f"{num/1_000_000_000:.2f}ккк".replace(".00", "")
    except:
        return "0"

def parse_amount(text):
    if not text:
        return None
    text = text.lower().strip().replace('k', 'к').replace(',', '.')
    mults = {'ккк': 10**9, 'кк': 10**6, 'к': 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try:
                return int(float(text.replace(m, '')) * v)
            except:
                return None
    try:
        return int(float(text))
    except:
        return None

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=bitcoin&vs_currencies=usd"
            ) as resp:
                data = await resp.json()
                return data['bitcoin']['usd'] * 100
    except:
        return 10_000_000

# --- ПРОВЕРКА ПОДПИСКИ ---
async def is_subscribed(user_id):
    try:
        s1 = await bot.get_chat_member(CHANNEL_ID, user_id)
        s2 = await bot.get_chat_member(CHAT_ID, user_id)
        valid = ['member', 'administrator', 'creator']
        return s1.status in valid and s2.status in valid
    except:
        return False

def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL),
            InlineKeyboardButton(text="💬 Чат", url=CHAT_URL)
        ],
        [
            InlineKeyboardButton(
                text="✅ Проверить подписку",
                callback_data="check_sub"
            )
        ]
    ])

# --- БАЗА ДАННЫХ ---
async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 50000,
                btc NUMERIC DEFAULT 0,
                lvl INT DEFAULT 1,
                xp INT DEFAULT 0,
                deposit BIGINT DEFAULT 0,
                tools_durability INT DEFAULT 0
            );
        """)
    logging.info("✅ База данных готова")

# --- ФОНОВАЯ ЗАДАЧА ---
async def bank_scheduler():
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            async with dp['db_pool'].acquire() as conn:
                await conn.execute("""
                    UPDATE users
                    SET deposit = deposit + (deposit * 0.1)
                    WHERE deposit > 0
                """)
            logging.info("🏦 Начислены проценты по вкладам")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

# --- HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    async with dp['db_pool'].acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING",
            message.from_user.id
        )

    caption = (
        "✨ **Добро пожаловать в Vibe Bet!**\n\n"
        "Игровой бот в Telegram 🎰🔥\n\n"
        "⚠️ Чтобы начать — подпишись:"
    )
    try:
        await message.answer_photo(
            FSInputFile("start_img.jpg"),
            caption=caption,
            reply_markup=sub_kb()
        )
    except:
        await message.answer(caption, reply_markup=sub_kb())

@dp.callback_query(F.data == "check_sub")
async def check_sub_call(call: CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.delete()
        await call.message.answer("🎉 Доступ открыт! Напиши **Я**")
    else:
        await call.answer(
            "❌ Подписка не найдена!",
            show_alert=True
        )

@dp.message(F.text.lower() == "я")
async def profile(message: Message):
    if not await is_subscribed(message.from_user.id):
        return await message.answer("🛑 Сначала подпишись", reply_markup=sub_kb())

    async with dp['db_pool'].acquire() as conn:
        u = await conn.fetchrow(
            "SELECT * FROM users WHERE id=$1",
            message.from_user.id
        )

    text = (
        f"👤 **ПРОФИЛЬ**\n"
        f"💰 Баланс: **{format_num(u['balance'])}**\n"
        f"🏦 Банк: **{format_num(u['deposit'])}**\n"
        f"₿ BTC: **{u['btc']:.6f}**\n"
        f"🛠 Инструменты: **{u['tools_durability']}/5**"
    )
    await message.answer(text)

# --- SYSTEM ---
async def handle_ping(request):
    return web.Response(text="Bot is running")

async def main():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL не задан")

    dp['db_pool'] = await asyncpg.create_pool(
    DB_URL,
    min_size=1,
    max_size=5,  # лучше меньше для pooler
    statement_cache_size=0,
    max_cacheable_statement_size=0
)


    await init_db(dp['db_pool'])

    asyncio.create_task(bank_scheduler())

    # Render healthcheck
    app = web.Application()
    app.router.add_get("/", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    ).start()

    logging.info("🚀 БОТ УСПЕШНО ЗАПУЩЕН")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
