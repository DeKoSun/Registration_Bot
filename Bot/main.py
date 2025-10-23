# main.py
import asyncio
import logging
import os
import signal
from contextlib import suppress
from urllib.parse import urlparse
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

# ---------- Supabase ----------
# pip install supabase
# (для новой версии supabase-py v2)
from supabase import create_client, Client


# =============================
# Конфиг из переменных окружения
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
REG_URL = os.getenv("REG_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN (или TELEGRAM_BOT_TOKEN) не установлена.")
if not REG_URL:
    raise RuntimeError("Переменная окружения REG_URL не установлена (ссылка на форму регистрации).")

def _is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

if not _is_valid_url(REG_URL):
    raise RuntimeError(f"REG_URL выглядит некорректно: {REG_URL!r}")

# =============================
# Логирование
# =============================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("fenix-bot")

# =============================
# Supabase client
# =============================
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    log.info("Supabase client инициализирован")
else:
    log.warning("SUPABASE_URL/SUPABASE_KEY не заданы — upsert в БД недоступен.")


# =============================
# Aiogram v3
# =============================
dp = Dispatcher()

def registration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔥 Начать регистрацию", url=REG_URL)]])


@dp.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer("Привет! Я бот клана ФЕНИКС.\nНажми кнопку, чтобы пройти регистрацию:", reply_markup=registration_keyboard())


@dp.message(Command("registration"))
async def cmd_registration(m: Message):
    await m.answer("Открываю форму регистрации:", reply_markup=registration_keyboard())


@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "Доступные команды:\n"
        "/start — приветствие и кнопка регистрации\n"
        "/registration — ссылка на форму регистрации\n"
        "/ping — проверка доступности бота\n"
        "/test_upsert — демонстрация upsert в таблицу rg_players"
    )


@dp.message(Command("ping"))
async def cmd_ping(m: Message):
    await m.answer("pong 🧡")


@dp.message(F.text.lower().in_({"регистрация", "registration"}))
async def msg_registration_word(m: Message):
    await m.answer("Регистрация здесь:", reply_markup=registration_keyboard())


# =============================
# Upsert в Supabase
# =============================

TABLE = "rg_players"

async def upsert_player(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Универсальный upsert в rg_players.
    Предпочитаем конфликт по telegram_id, если он есть.
    Если в таблице настроен уникальный индекс по нижнему регистру telegram (например, по колонке telegram_norm),
    можно использовать on_conflict='telegram_norm'.

    Если индекса нет — будет выполнен безопасный fallback (SELECT + UPDATE/INSERT).
    """
    if supabase is None:
        raise RuntimeError("Supabase client не инициализирован (нет SUPABASE_URL/SUPABASE_KEY).")

    # Нормализация полей
    rec = dict(record)
    if "telegram" in rec and rec["telegram"] is not None:
        rec["telegram"] = str(rec["telegram"]).strip()
        # Можно подготовить нормализованное поле (если такая колонка существует в БД):
        # rec["telegram_norm"] = rec["telegram"].lower()

    # 1) Если есть telegram_id — используем его как конфликт
    if rec.get("telegram_id") is not None:
        try:
            resp = supabase.table(TABLE).upsert(rec, on_conflict="telegram_id").execute()
            return {"ok": True, "via": "on_conflict: telegram_id", "data": resp.data}
        except Exception as e:
            log.warning("Upsert по telegram_id не удался: %s", e)

    # 2) Если в БД ЕСТЬ уникальный индекс по НИЖНЕМУ регистру логина (например, столбец telegram_norm UNIQUE):
    #    Тогда раскомментируй БЛОК ниже и УБЕРИ fallback.
    #
    # try:
    #     if "telegram_norm" in rec:
    #         resp = supabase.table(TABLE).upsert(rec, on_conflict="telegram_norm").execute()
    #         return {"ok": True, "via": "on_conflict: telegram_norm", "data": resp.data}
    # except Exception as e:
    #     log.warning("Upsert по telegram_norm не удался: %s", e)

    # 3) Fallback без on_conflict: ищем по telegram (без учета регистра) и либо обновляем, либо вставляем
    try:
        data = rec.get("telegram")
        if data:
            found = supabase.table(TABLE).select("id").ilike("telegram", data).limit(1).execute()
            if found.data:
                player_id = found.data[0]["id"]
                upd = supabase.table(TABLE).update(rec).eq("id", player_id).execute()
                return {"ok": True, "via": "fallback:update", "data": upd.data}
        # ничего не нашли — вставка
        ins = supabase.table(TABLE).insert(rec).execute()
        return {"ok": True, "via": "fallback:insert", "data": ins.data}
    except Exception as e:
        log.error("Ошибка fallback upsert: %s", e)
        return {"ok": False, "error": str(e)}


# Демонстрационная команда: /test_upsert DeKo_Soon
@dp.message(Command("test_upsert"))
async def cmd_test_upsert(m: Message):
    if supabase is None:
        await m.answer("Supabase не сконфигурирован. Задай SUPABASE_URL и SUPABASE_KEY.")
        return

    # Берем аргумент из сообщения как логин Telegram (без @)
    args = m.text.split(maxsplit=1)
    tg_user = args[1].strip() if len(args) > 1 else "demo_user"

    sample = {
        # если есть — лучше указывать telegram_id, это сделает upsert «атомарным»
        "telegram_id": m.from_user.id,
        "telegram": tg_user,
        "nickname": "DeKo_Sun",
        "clan": "Феникс",
        # любые другие поля, которые есть в rg_players:
        # "country": "USA",
        # "city": "New York",
        # "days": ["Понедельник", "Среда"],
        # "times": ["16:00 – 19:00"],
    }

    res = await upsert_player(sample)
    if res.get("ok"):
        await m.answer(f"Upsert OK ({res.get('via')}), записей: {len(res.get('data') or [])}")
    else:
        await m.answer(f"Upsert error: {res.get('error')}")


# =============================
# Служебное
# =============================
async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начало и кнопка регистрации"),
        BotCommand(command="registration", description="Ссылка на форму регистрации"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="ping", description="Проверка связи"),
        BotCommand(command="test_upsert", description="Демо upsert в rg_players"),
    ]
    await bot.set_my_commands(commands)
    log.info("Команды бота установлены")


async def _shutdown(bot: Bot):
    await bot.session.close()
    log.info("Завершение работы бота")


async def main():
    bot = Bot(BOT_TOKEN)
    await set_commands(bot)

    stop_event = asyncio.Event()

    def _handler(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler)

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
