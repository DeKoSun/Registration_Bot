import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

BOT_TOKEN = os.environ.get("BOT_TOKEN")
REG_URL   = os.environ.get("REG_URL")  # ссылка на форму (GitHub Pages)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not REG_URL:
    raise RuntimeError("REG_URL is not set")

dp = Dispatcher()

def registration_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Начать регистрацию", url=REG_URL)]
        ]
    )

@dp.message(Command("start"))
async def on_start(m: Message):
    await m.answer(
        "Привет! Я бот клана ФЕНИКС.\nНажми кнопку, чтобы пройти регистрацию:",
        reply_markup=registration_inline()
    )

@dp.message(Command("registration"))
async def on_registration(m: Message):
    await m.answer("Открываю форму регистрации:", reply_markup=registration_inline())

async def main():
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
