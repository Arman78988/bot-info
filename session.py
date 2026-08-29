"""Session-Bot — erzeugt TELETHON_SESSION-Schluessel per Telegram.

Statt jedes Mal ein Skript im Terminal zu starten, redest du einfach
mit diesem Bot. Er fragt dich Schritt fuer Schritt alles ab und gibt
am Ende den fertigen Schluessel zum Antippen und Kopieren aus.

WER DARF DAS
------------
Nur du. Ganz am Anfang haengt eine Sperre vor allen Handlern: kommt
eine Nachricht von einer anderen ID als OWNER_ID, wird sie kommentarlos
verworfen. Kein Menue, keine Antwort, nichts. Fremde koennen den Bot
also nicht benutzen, selbst wenn sie ihn finden.

Das ist wichtig, weil hier Anmeldedaten durchlaufen. Ein solcher Bot
ohne Sperre waere ein Werkzeug zum Abgreifen fremder Konten.

WAS DER SCHLUESSEL IST
----------------------
Der fertige Text ist wie ein Passwort fuer dein Telegram-Konto. Wer
ihn hat, ist drin. Er gehoert ins Railway-Feld TELETHON_SESSION und
sonst nirgendwohin - nicht in GitHub, nicht in einen Chat.

Der Bot schreibt nichts davon ins Log und loescht deine Nachrichten
mit Code und Passwort sofort wieder aus dem Chat.

UMGEBUNGSVARIABLEN
------------------
Pflicht:
    SESSION_BOT_TOKEN    Token dieses Bots (vom BotFather, eigener Bot)
    OWNER_ID             deine Telegram-User-ID

Freiwillig (spart Tipparbeit, sonst fragt der Bot danach):
    TG_API_ID            von my.telegram.org
    TG_API_HASH          von my.telegram.org

STARTEN
-------
    pip install aiogram telethon
    python session_bot.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

log = logging.getLogger("sessionbot")


# ── Einstellungen ───────────────────────────────────────

def _pflicht(name: str) -> str:
    wert = (os.getenv(name) or "").strip()
    if not wert:
        raise SystemExit(
            f"\n  Die Umgebungsvariable {name} fehlt.\n"
            f"  So setzt du sie einmalig fuer diesen Start:\n\n"
            f"      export {name}=...\n"
        )
    return wert


BOT_TOKEN = _pflicht("SESSION_BOT_TOKEN")
try:
    OWNER_ID = int(_pflicht("OWNER_ID"))
except ValueError:
    raise SystemExit("\n  OWNER_ID muss eine reine Zahl sein.\n")

# Vorgaben, damit du API-ID und -Hash nicht jedes Mal tippen musst.
VORGABE_API_ID = (os.getenv("TG_API_ID") or "").strip()
VORGABE_API_HASH = (os.getenv("TG_API_HASH") or "").strip()


# ── Sperre: alles ausser dem Besitzer fliegt raus ───────

class NurBesitzer(BaseMiddleware):
    """Verwirft jede Nachricht, die nicht von OWNER_ID kommt.

    Haengt vor allen Handlern. Fremde bekommen keine Antwort - nicht
    einmal eine Fehlermeldung, damit der Bot fuer Aussenstehende tot
    wirkt.
    """

    async def __call__(self, handler, event, data):
        nutzer = data.get("event_from_user")
        if nutzer is None or nutzer.id != OWNER_ID:
            if nutzer is not None:
                log.warning("Abgewiesen: ID %s", nutzer.id)
            return None
        return await handler(event, data)


# ── Ablauf ──────────────────────────────────────────────

class Ablauf(StatesGroup):
    api_id = State()
    api_hash = State()
    telefon = State()
    code = State()
    passwort = State()


router = Router(name="session")

# Die Telethon-Verbindung muss zwischen den Schritten offen bleiben.
_klient: Optional[TelegramClient] = None
_code_hash: Optional[str] = None


async def _klient_schliessen() -> None:
    global _klient, _code_hash
    if _klient is not None:
        try:
            await _klient.disconnect()
        except Exception:
            pass
    _klient = None
    _code_hash = None


def _knopf(text: str, daten: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=daten)],
    ])


def _abbrechen() -> InlineKeyboardMarkup:
    return _knopf("✖️ Abbrechen", "abbruch")


def _startknopf() -> InlineKeyboardMarkup:
    return _knopf("🔑 Session erstellen", "los")


async def _weg(message: types.Message) -> None:
    """Nachricht mit Geheimnis aus dem Chat raeumen.

    Code und Passwort sollen nicht im Verlauf stehenbleiben. Klappt in
    Privatchats; wenn Telegram es doch verweigert, ignorieren wir es.
    """
    try:
        await message.delete()
    except Exception:
        pass


# ── Start ───────────────────────────────────────────────

@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await _klient_schliessen()
    bereit = "✅ hinterlegt" if (VORGABE_API_ID and VORGABE_API_HASH) else "❓ wird abgefragt"
    await message.answer(
        "🔑 <b>Session-Bot</b>\n\n"
        "Ich baue dir den <code>TELETHON_SESSION</code>-Schlüssel — "
        "den langen Text für das Railway-Feld.\n\n"
        f"API-ID und API-Hash: {bereit}\n\n"
        "<b>Was ich brauche:</b>\n"
        "• deine Telefonnummer mit Vorwahl\n"
        "• den Code, den Telegram dir schickt\n"
        "• dein Zwei-Faktor-Passwort, falls eingeschaltet\n\n"
        "<i>Code und Passwort lösche ich sofort wieder aus dem Chat "
        "und schreibe nichts davon ins Log.</i>",
        reply_markup=_startknopf(),
    )


@router.message(Command("cancel"))
@router.callback_query(F.data == "abbruch")
async def abbruch(ereignis, state: FSMContext):
    await state.clear()
    await _klient_schliessen()
    ziel = ereignis.message if isinstance(ereignis, types.CallbackQuery) else ereignis
    await ziel.answer("✖️ Abgebrochen.", reply_markup=_startknopf())
    if isinstance(ereignis, types.CallbackQuery):
        await ereignis.answer()


@router.callback_query(F.data == "los")
async def los(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _klient_schliessen()

    if VORGABE_API_ID and VORGABE_API_HASH:
        await state.update_data(api_id=int(VORGABE_API_ID), api_hash=VORGABE_API_HASH)
        await _frage_telefon(call.message, state)
        return

    await state.set_state(Ablauf.api_id)
    await call.message.answer(
        "1️⃣ <b>API-ID</b>\n\n"
        "Die Zahl von <a href=\"https://my.telegram.org\">my.telegram.org</a> "
        "→ API development tools.\n\n"
        "<i>Beispiel: 2040123</i>",
        reply_markup=_abbrechen(),
        disable_web_page_preview=True,
    )


@router.message(Ablauf.api_id, F.text)
async def hat_api_id(message: types.Message, state: FSMContext):
    roh = (message.text or "").strip()
    if not roh.isdigit():
        await message.answer("⚠️ Das muss eine reine Zahl sein. Nochmal:",
                             reply_markup=_abbrechen())
        return
    await state.update_data(api_id=int(roh))
    await state.set_state(Ablauf.api_hash)
    await message.answer(
        "2️⃣ <b>API-Hash</b>\n\n"
        "Der lange Text von derselben Seite.\n\n"
        "<i>32 Zeichen aus Buchstaben und Zahlen</i>",
        reply_markup=_abbrechen(),
    )


@router.message(Ablauf.api_hash, F.text)
async def hat_api_hash(message: types.Message, state: FSMContext):
    wert = (message.text or "").strip()
    if len(wert) < 16:
        await message.answer("⚠️ Das sieht zu kurz aus. Nochmal:",
                             reply_markup=_abbrechen())
        return
    await state.update_data(api_hash=wert)
    await _frage_telefon(message, state)


async def _frage_telefon(ziel: types.Message, state: FSMContext):
    await state.set_state(Ablauf.telefon)
    await ziel.answer(
        "3️⃣ <b>Telefonnummer</b>\n\n"
        "Mit Landesvorwahl und Pluszeichen.\n\n"
        "<i>Beispiel: +491701234567</i>\n\n"
        "Das ist das Konto, über das dein Musik-Bot später mit "
        "@LuxSaverBot redet.",
        reply_markup=_abbrechen(),
    )


@router.message(Ablauf.telefon, F.text)
async def hat_telefon(message: types.Message, state: FSMContext):
    global _klient, _code_hash

    nummer = re.sub(r"[^\d+]", "", message.text or "")
    if not nummer.startswith("+") or len(nummer) < 8:
        await message.answer(
            "⚠️ Bitte mit <b>+</b> und Landesvorwahl, z. B. <code>+491701234567</code>",
            reply_markup=_abbrechen())
        return

    warte = await message.answer("⏳ Verbinde mit Telegram…")
    daten = await state.get_data()

    try:
        _klient = TelegramClient(StringSession(), daten["api_id"], daten["api_hash"])
        await _klient.connect()
        antwort = await _klient.send_code_request(nummer)
        _code_hash = antwort.phone_code_hash
    except ApiIdInvalidError:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text("❌ API-ID oder API-Hash stimmen nicht.",
                              reply_markup=_startknopf())
        return
    except PhoneNumberInvalidError:
        await _klient_schliessen()
        await warte.edit_text("❌ Diese Nummer kennt Telegram nicht. Nochmal:",
                              reply_markup=_abbrechen())
        return
    except PhoneNumberBannedError:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text("❌ Diese Nummer ist bei Telegram gesperrt.",
                              reply_markup=_startknopf())
        return
    except FloodWaitError as e:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text(
            f"⏳ Telegram bremst uns aus. Bitte <b>{e.seconds} Sekunden</b> warten.",
            reply_markup=_startknopf())
        return
    except Exception as e:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text(f"❌ Fehler: <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    await state.update_data(telefon=nummer)
    await state.set_state(Ablauf.code)
    await warte.edit_text(
        "4️⃣ <b>Code eingeben</b>\n\n"
        "Telegram hat dir gerade einen Code geschickt.\n\n"
        "⚠️ <b>Wichtig:</b> Tipp ihn mit Trennzeichen, z. B. "
        "<code>1 2 3 4 5</code> oder <code>1-2-3-4-5</code>.\n\n"
        "<i>Schickst du ihn als reine Zahl, erkennt Telegram das und "
        "macht den Code sofort ungültig — dann geht es nicht.</i>",
        reply_markup=_abbrechen(),
    )


@router.message(Ablauf.code, F.text)
async def hat_code(message: types.Message, state: FSMContext):
    code = re.sub(r"\D", "", message.text or "")
    await _weg(message)

    if not code:
        await message.answer("⚠️ Da war keine Zahl dabei. Nochmal:",
                             reply_markup=_abbrechen())
        return

    daten = await state.get_data()
    warte = await message.answer("⏳ Melde an…")

    try:
        await _klient.sign_in(phone=daten["telefon"], code=code,
                              phone_code_hash=_code_hash)
    except SessionPasswordNeededError:
        await state.set_state(Ablauf.passwort)
        await warte.edit_text(
            "5️⃣ <b>Zwei-Faktor-Passwort</b>\n\n"
            "Dein Konto ist zusätzlich geschützt. Schick mir das Passwort.\n\n"
            "<i>Ich lösche die Nachricht sofort wieder.</i>",
            reply_markup=_abbrechen())
        return
    except PhoneCodeInvalidError:
        await warte.edit_text("❌ Code stimmt nicht. Nochmal:",
                              reply_markup=_abbrechen())
        return
    except PhoneCodeExpiredError:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text("❌ Code ist abgelaufen. Fang neu an.",
                              reply_markup=_startknopf())
        return
    except Exception as e:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text(f"❌ Fehler: <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    await _fertig(warte, state)


@router.message(Ablauf.passwort, F.text)
async def hat_passwort(message: types.Message, state: FSMContext):
    passwort = message.text or ""
    await _weg(message)

    warte = await message.answer("⏳ Prüfe Passwort…")
    try:
        await _klient.sign_in(password=passwort)
    except PasswordHashInvalidError:
        await warte.edit_text("❌ Passwort stimmt nicht. Nochmal:",
                              reply_markup=_abbrechen())
        return
    except Exception as e:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text(f"❌ Fehler: <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    await _fertig(warte, state)


async def _fertig(warte: types.Message, state: FSMContext):
    """Schluessel ausgeben und alles aufraeumen."""
    global _klient
    try:
        ich = await _klient.get_me()
        schluessel = _klient.session.save()
    except Exception as e:
        await _klient_schliessen(); await state.clear()
        await warte.edit_text(f"❌ Fehler beim Auslesen: <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    name = ich.first_name or "—"
    nutzername = f"@{ich.username}" if ich.username else "ohne Username"

    await warte.edit_text(
        f"✅ <b>Fertig</b>\n\nAngemeldet als {name} ({nutzername})")

    # Schluessel in eigener Nachricht: antippen kopiert alles auf einmal.
    await warte.answer(f"<code>{schluessel}</code>")

    await warte.answer(
        "☝️ <b>Das ist dein Schlüssel.</b> Antippen kopiert ihn.\n\n"
        "Bei Railway eintragen unter <b>Variables</b>:\n"
        "<code>TELETHON_SESSION</code> = dieser Text\n\n"
        "⚠️ Er ist wie ein Passwort für dein Konto. Nicht weitergeben, "
        "nicht auf GitHub. Wenn er nicht mehr gebraucht wird, lösch die "
        "Nachricht hier oben.",
        reply_markup=_startknopf(),
    )

    await _klient_schliessen()
    await state.clear()


@router.message()
async def sonst(message: types.Message):
    await message.answer("Tipp /start", reply_markup=_startknopf())


# ── Start ───────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(NurBesitzer())
    dp.include_router(router)

    ich = await bot.get_me()
    log.info("Session-Bot laeuft als @%s — nur ID %s darf ihn benutzen",
             ich.username, OWNER_ID)
    try:
        await dp.start_polling(bot)
    finally:
        await _klient_schliessen()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
      
