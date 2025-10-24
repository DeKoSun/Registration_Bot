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

from supabase import create_client, Client

# =============================
# Конфиг
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
REG_URL = os.getenv("REG_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не установлен.")
if not REG_URL:
    raise RuntimeError("REG_URL не установлен (ссылка на форму регистрации).")

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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("fenix-bot")

# =============================
# Supabase
# =============================
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    log.info("Supabase client инициализирован")
else:
    log.warning("SUPABASE_URL/SUPABASE_KEY не заданы — запись в БД не будет работать.")

# =============================
# Aiogram
# =============================
dp = Dispatcher()

def registration_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    # передаём tg_id в ссылку для связи анкеты с пользователем
    url = f"{REG_URL}?tg_id={tg_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔥 Начать регистрацию", url=url)]]
    )

@dp.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(
        "Привет! Я бот клана ФЕНИКС.\nНажми кнопку, чтобы пройти регистрацию:",
        reply_markup=registration_keyboard(m.from_user.id)
    )

@dp.message(Command("registration"))
async def cmd_registration(m: Message):
    await m.answer("Открываю форму регистрации:", reply_markup=registration_keyboard(m.from_user.id))

@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "/start — приветствие и кнопка регистрации\n"
        "/registration — ссылка на форму регистрации\n"
        "/ping — проверка доступности бота\n"
        "/test_upsert — демонстрация записи в rg_players"
    )

@dp.message(Command("ping"))
async def cmd_ping(m: Message):
    await m.answer("pong 🧡")

@dp.message(F.text.lower().in_({"регистрация", "registration"}))
async def msg_registration_word(m: Message):
    await m.answer("Регистрация здесь:", reply_markup=registration_keyboard(m.from_user.id))

# =============================
# Upsert в rg_players
# =============================
TABLE = "rg_players"

async def upsert_player(record: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert игрока по telegram_id или telegram_norm"""
    if supabase is None:
        raise RuntimeError("Supabase client не инициализирован.")

    rec = dict(record)

    # нормализация
    if rec.get("telegram"):
        rec["telegram"] = str(rec["telegram"]).strip()
        rec["telegram_norm"] = rec["telegram"].lstrip("@").lower()

    # приоритет — telegram_id
    try:
        if rec.get("telegram_id"):
            resp = supabase.table(TABLE).upsert(rec, on_conflict="telegram_id").execute()
            return {"ok": True, "via": "on_conflict:telegram_id", "data": resp.data}
    except Exception as e:
        log.warning("Upsert по telegram_id не удался: %s", e)

    # fallback — telegram_norm
    try:
        if rec.get("telegram_norm"):
            resp = supabase.table(TABLE).upsert(rec, on_conflict="telegram_norm").execute()
            return {"ok": True, "via": "on_conflict:telegram_norm", "data": resp.data}
    except Exception as e:
        log.warning("Upsert по telegram_norm не удался: %s", e)

    # резервный путь — select/update
    try:
        tgn = rec.get("telegram_norm")
        if tgn:
            found = supabase.table(TABLE).select("id").eq("telegram_norm", tgn).limit(1).execute()
            if found.data:
                pid = found.data[0]["id"]
                upd = supabase.table(TABLE).update(rec).eq("id", pid).execute()
                return {"ok": True, "via": "fallback:update", "data": upd.data}
        ins = supabase.table(TABLE).insert(rec).execute()
        return {"ok": True, "via": "fallback:insert", "data": ins.data}
    except Exception as e:
        log.error("Ошибка upsert: %s", e)
        return {"ok": False, "error": str(e)}

# тестовая команда
@dp.message(Command("test_upsert"))
async def cmd_test_upsert(m: Message):
    if supabase is None:
        await m.answer("Supabase не сконфигурирован.")
        return

    args = m.text.split(maxsplit=1)
    tg_user = args[1].strip() if len(args) > 1 else m.from_user.username or f"user_{m.from_user.id}"

    sample = {
        "telegram_id": m.from_user.id,
        "telegram": tg_user,
        "nickname": "DeKo_Sun",
        "clan": "Феникс",
    }

    res = await upsert_player(sample)
    if res.get("ok"):
        await m.answer(f"✅ Upsert OK ({res.get('via')}), записей: {len(res.get('data') or [])}")
    else:
        await m.answer(f"❌ Upsert error: {res.get('error')}")

# =============================
# Служебное
# =============================
async def set_commands(bot: Bot):
    cmds = [
        BotCommand(command="start", description="Приветствие и регистрация"),
        BotCommand(command="registration", description="Ссылка на регистрацию"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="ping", description="Проверка связи"),
        BotCommand(command="test_upsert", description="Тест записи в БД"),
    ]
    await bot.set_my_commands(cmds)

async def _shutdown(bot: Bot):
    await bot.session.close()
    log.info("Завершение работы бота")

async def main():
    bot = Bot(BOT_TOKEN)
    await set_commands(bot)
    stop_event = asyncio.Event()

    def _handler(*_): stop_event.set()
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
