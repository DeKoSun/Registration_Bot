# main.py
import asyncio
import logging
import os
import signal
from contextlib import suppress
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)

# -----------------------------
# Конфиг из переменных окружения
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
REG_URL = os.getenv("REG_URL")  # ссылка на страницу регистрации (GitHub Pages)

if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN (или TELEGRAM_BOT_TOKEN) не установлена.")
if not REG_URL:
    raise RuntimeError("Переменная окружения REG_URL не установлена (ссылка на форму регистрации).")

# Небольшая валидация ссылки (чтобы потом не удивляться пустой кнопке)
def _is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

if not _is_valid_url(REG_URL):
    raise RuntimeError(f"REG_URL выглядит некорректно: {REG_URL!r}")

# -----------------------------
# Логирование
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fenix-bot")

# -----------------------------
# Инициализация Aiogram v3
# -----------------------------
dp = Dispatcher()


def registration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Начать регистрацию", url=REG_URL)]
        ]
    )


@dp.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(
        "Привет! Я бот клана ФЕНИКС.\n"
        "Нажми кнопку, чтобы пройти регистрацию:",
        reply_markup=registration_keyboard(),
    )


@dp.message(Command("registration"))
async def cmd_registration(m: Message):
    await m.answer("Открываю форму регистрации:", reply_markup=registration_keyboard())


@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "Доступные команды:\n"
        "/start — приветствие и кнопка регистрации\n"
        "/registration — ссылка на форму регистрации\n"
        "/ping — проверка доступности бота"
    )


@dp.message(Command("ping"))
async def cmd_ping(m: Message):
    await m.answer("pong 🧡")


# На всякий случай — перехват случайного текста
@dp.message(F.text.lower().in_({"регистрация", "registration"}))
async def msg_registration_word(m: Message):
    await m.answer("Регистрация здесь:", reply_markup=registration_keyboard())


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начало и кнопка регистрации"),
        BotCommand(command="registration", description="Ссылка на форму регистрации"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="ping", description="Проверка связи"),
    ]
    await bot.set_my_commands(commands)
    log.info("Команды бота установлены")


async def _shutdown(bot: Bot):
    # сюда можно добавить закрытие соединений к БД/кешам и т.п.
    await bot.session.close()
    log.info("Завершение работы бота")


async def main():
    bot = Bot(BOT_TOKEN)
    await set_commands(bot)

    # Грейсфул-шатдаун под Railway/Heroku
    stop_event = asyncio.Event()

    def _handler(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler)

    # Старт поллинга
    log.info("Запускаю long polling…")
    polling = asyncio.create_task(dp.start_polling(bot))
    await stop_event.wait()
    polling.cancel()
    with suppress(asyncio.CancelledError):
        await polling
    await _shutdown(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
