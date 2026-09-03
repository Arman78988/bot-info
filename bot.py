"""Session-Bot — erzeugt TELETHON_SESSION-Schluessel per Telegram.

Der Bot spricht Armenisch. Er fuehrt jede Person Schritt fuer Schritt
durch den Login und gibt am Ende ihren fertigen Schluessel zum Antippen
und Kopieren aus.

WER DARF DAS
------------
Der Besitzer (OWNER_ID) darf immer. Andere koennen den Bot ebenfalls
benutzen, aber nur nach Freigabe:

  * Wer schon in ALLOWED_IDS steht, darf sofort (bleibt ueber Neustarts).
  * Alle anderen sehen beim /start einen Knopf "Hasanelijutjun khndrel"
    (Zugang anfragen). Der Besitzer bekommt die Anfrage mit zwei Knoepfen
    (Hastatel / Merjel) und entscheidet. Eine Freigabe per Knopf gilt bis
    zum naechsten Neustart; dauerhaft wird sie, wenn die ID in ALLOWED_IDS
    landet.

SICHERHEIT — WARUM NIEMAND AN FREMDE SCHLUESSEL KOMMT
-----------------------------------------------------
Jede Person hat ihre EIGENE Telethon-Verbindung (Dict nach User-ID). Es
gibt keine gemeinsame globale Verbindung mehr, an der sich zwei Logins
vermischen koennten.

Der fertige Schluessel wird ausschliesslich an die Person geschickt, die
ihn gerade erzeugt hat. Der Besitzer bekommt fremde Schluessel NICHT zu
sehen — es gibt bewusst keinen Weg, sie irgendwohin weiterzuleiten. So
ist der Bot kein Werkzeug zum Abgreifen fremder Konten: jeder erzeugt
nur seinen eigenen Schluessel fuer sein eigenes Konto.

Nichts Sensibles (Nummer, Code, Passwort, Schluessel) landet im Log.
Nachrichten mit Code und Passwort loescht der Bot sofort aus dem Chat.

UMGEBUNGSVARIABLEN
------------------
Pflicht:
    SESSION_BOT_TOKEN    Token dieses Bots (vom BotFather, eigener Bot)
    OWNER_ID             deine Telegram-User-ID

Freiwillig:
    ALLOWED_IDS          weitere erlaubte IDs, mit Komma/Leerzeichen
                         getrennt, z. B. "123456789, 987654321"
    TG_API_ID            von my.telegram.org (spart Tipparbeit)
    TG_API_HASH          von my.telegram.org (spart Tipparbeit)

STARTEN
-------
    pip install aiogram telethon
    python bot.py
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


def _ids_lesen(name: str) -> set[int]:
    """Liest eine Liste von IDs aus einer Variable (Komma/Leerzeichen)."""
    roh = os.getenv(name) or ""
    ids: set[int] = set()
    for teil in re.split(r"[,\s]+", roh):
        teil = teil.strip()
        if teil.isdigit():
            ids.add(int(teil))
    return ids


# Dauerhaft erlaubte IDs (aus der Variable). Owner ist immer dabei.
ERLAUBT_STATISCH = _ids_lesen("ALLOWED_IDS") | {OWNER_ID}

# Zur Laufzeit per Knopf freigegeben (weg nach Neustart).
erlaubt_laufzeit: set[int] = set()
# Wer schon eine Anfrage gestellt hat (gegen doppelte Meldungen).
angefragt: set[int] = set()

# Vorgaben, damit API-ID und -Hash nicht jedes Mal getippt werden muessen.
VORGABE_API_ID = (os.getenv("TG_API_ID") or "").strip()
VORGABE_API_HASH = (os.getenv("TG_API_HASH") or "").strip()


def ist_erlaubt(uid: int) -> bool:
    return uid in ERLAUBT_STATISCH or uid in erlaubt_laufzeit


# ── Zugangskontrolle ────────────────────────────────────

class Zugangskontrolle(BaseMiddleware):
    """Reicht fuer jede Nachricht mit, ob der Absender erlaubt ist.

    Verwirft niemanden hart — sonst koennten Fremde nicht einmal Zugang
    anfragen. Die eigentliche Session-Erzeugung ist aber gesperrt: nur
    erlaubte IDs kommen durch den Start-Knopf.
    """

    async def __call__(self, handler, event, data):
        nutzer = data.get("event_from_user")
        if nutzer is None:
            return None
        data["ist_erlaubt"] = ist_erlaubt(nutzer.id)
        data["ist_owner"] = nutzer.id == OWNER_ID
        return await handler(event, data)


# ── Ablauf ──────────────────────────────────────────────

class Ablauf(StatesGroup):
    api_id = State()
    api_hash = State()
    telefon = State()
    code = State()
    passwort = State()


router = Router(name="session")

# WICHTIG fuer Mehr-Personen-Betrieb: pro User-ID eine eigene Verbindung.
# Keine gemeinsame globale Verbindung -> zwei Logins koennen sich nicht
# vermischen, niemand kommt an den Schluessel eines anderen.
klienten: dict[int, TelegramClient] = {}
code_hashes: dict[int, str] = {}


async def _klient_weg(uid: int) -> None:
    kl = klienten.pop(uid, None)
    code_hashes.pop(uid, None)
    if kl is not None:
        try:
            await kl.disconnect()
        except Exception:
            pass


def _knopf(text: str, daten: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=daten)],
    ])


def _abbrechen() -> InlineKeyboardMarkup:
    return _knopf("✖️ Չեղարկել", "abbruch")


def _startknopf() -> InlineKeyboardMarkup:
    return _knopf("🔑 Ստեղծել session", "los")


def _zugangknopf() -> InlineKeyboardMarkup:
    return _knopf("🙋 Խնդրել հասանելիություն", "zugang")


def _entscheidung(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Հաստատել", callback_data=f"ok:{uid}"),
        InlineKeyboardButton(text="🚫 Մերժել", callback_data=f"no:{uid}"),
    ]])


async def _weg(message: types.Message) -> None:
    """Nachricht mit Geheimnis (Code/Passwort) aus dem Chat raeumen."""
    try:
        await message.delete()
    except Exception:
        pass


async def _zugang_screen(ziel: types.Message) -> None:
    await ziel.answer(
        "👋 Բարև։ Այս բոտը Telegram-ի համար <b>session</b> բանալի է ստեղծում։\n\n"
        "Օգտագործելու համար պետք է տիրոջ հաստատումը։ Սեղմիր ներքևի կոճակը՝ "
        "հասանելիություն խնդրելու համար։",
        reply_markup=_zugangknopf(),
    )


# ── Start ───────────────────────────────────────────────

@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext, ist_erlaubt: bool):
    await state.clear()
    await _klient_weg(message.from_user.id)

    if not ist_erlaubt:
        await _zugang_screen(message)
        return

    bereit = "✅ պահված է" if (VORGABE_API_ID and VORGABE_API_HASH) else "❓ կհարցնեմ"
    await message.answer(
        "🔑 <b>Session-բոտ</b>\n\n"
        "Ես պատրաստում եմ քո <code>TELETHON_SESSION</code> բանալին — "
        "այն երկար տեքստը Railway-ի դաշտի համար։\n\n"
        f"API-ID և API-Hash: {bereit}\n\n"
        "<b>Ինչ է պետք ինձ՝</b>\n"
        "• քո հեռախոսահամարը՝ երկրի կոդով\n"
        "• կոդը, որ Telegram-ը կուղարկի քեզ\n"
        "• քո երկքայլ գաղտնաբառը, եթե միացված է\n\n"
        "<i>Կոդն ու գաղտնաբառը անմիջապես ջնջում եմ չատից և ոչ մի բան "
        "չեմ գրում լոգերում։</i>",
        reply_markup=_startknopf(),
    )


@router.message(Command("cancel"))
@router.callback_query(F.data == "abbruch")
async def abbruch(ereignis, state: FSMContext):
    await state.clear()
    await _klient_weg(ereignis.from_user.id)
    ziel = ereignis.message if isinstance(ereignis, types.CallbackQuery) else ereignis
    await ziel.answer("✖️ Չեղարկված է։", reply_markup=_startknopf())
    if isinstance(ereignis, types.CallbackQuery):
        await ereignis.answer()


# ── Zugang anfragen / freigeben ─────────────────────────

@router.callback_query(F.data == "zugang")
async def zugang(call: types.CallbackQuery, ist_erlaubt: bool):
    await call.answer()
    uid = call.from_user.id

    if ist_erlaubt:
        await call.message.answer("Դու արդեն հասանելիություն ունես։ Գրիր /start")
        return

    if uid in angefragt:
        await call.message.answer("Խնդրանքդ արդեն ուղարկված է։ Սպասիր հաստատմանը։")
        return

    angefragt.add(uid)
    n = call.from_user
    name = n.first_name or "—"
    handle = f"@{n.username}" if n.username else "առանց username"
    try:
        await call.bot.send_message(
            OWNER_ID,
            "🙋 <b>Նոր խնդրանք</b>\n\n"
            "Օգտվողը ուզում է օգտագործել բոտը՝\n"
            f"{name} ({handle})\n"
            f"ID: <code>{uid}</code>\n\n"
            "Հաստատե՞լ։",
            reply_markup=_entscheidung(uid),
        )
    except Exception:
        pass
    await call.message.answer(
        "✅ Խնդրանքդ ուղարկվեց տիրոջը։ Սպասիր հաստատմանը։\n\n"
        "Երբ հաստատեն, նորից գրիր /start։"
    )


@router.callback_query(F.data.startswith("ok:"))
async def genehmigen(call: types.CallbackQuery, ist_owner: bool):
    if not ist_owner:
        await call.answer()
        return
    uid = int(call.data.split(":")[1])
    erlaubt_laufzeit.add(uid)
    angefragt.discard(uid)
    await call.answer("Հաստատված է")
    await call.message.edit_text(
        f"✅ Հաստատված՝ <code>{uid}</code>\n\n"
        "<i>Մշտական դարձնելու համար ավելացրու այս ID-ն "
        "<code>ALLOWED_IDS</code> փոփոխականում (Railway → Variables)։ "
        "Հակառակ դեպքում վերագործարկումից հետո նորից պետք է հաստատել։</i>"
    )
    try:
        await call.bot.send_message(uid, "✅ Հաստատված է։ Կարող ես սկսել՝ գրիր /start")
    except Exception:
        pass


@router.callback_query(F.data.startswith("no:"))
async def ablehnen(call: types.CallbackQuery, ist_owner: bool):
    if not ist_owner:
        await call.answer()
        return
    uid = int(call.data.split(":")[1])
    erlaubt_laufzeit.discard(uid)
    angefragt.discard(uid)
    await call.answer("Մերժված է")
    await call.message.edit_text(f"🚫 Մերժված՝ <code>{uid}</code>")
    try:
        await call.bot.send_message(uid, "🚫 Խնդրանքը մերժվեց։")
    except Exception:
        pass


# ── Session-Ablauf (nur fuer Erlaubte) ──────────────────

@router.callback_query(F.data == "los")
async def los(call: types.CallbackQuery, state: FSMContext, ist_erlaubt: bool):
    if not ist_erlaubt:
        await call.answer("Հասանելիություն չունես։", show_alert=True)
        return
    await call.answer()
    await _klient_weg(call.from_user.id)

    if VORGABE_API_ID and VORGABE_API_HASH:
        await state.update_data(api_id=int(VORGABE_API_ID), api_hash=VORGABE_API_HASH)
        await _frage_telefon(call.message, state)
        return

    await state.set_state(Ablauf.api_id)
    await call.message.answer(
        "1️⃣ <b>API-ID</b>\n\n"
        "Այն թիվը՝ <a href=\"https://my.telegram.org\">my.telegram.org</a> "
        "→ API development tools էջից։\n\n"
        "<i>Օրինակ՝ 2040123</i>",
        reply_markup=_abbrechen(),
        disable_web_page_preview=True,
    )


@router.message(Ablauf.api_id, F.text)
async def hat_api_id(message: types.Message, state: FSMContext):
    roh = (message.text or "").strip()
    if not roh.isdigit():
        await message.answer("⚠️ Դա պետք է լինի միայն թիվ։ Նորից՝",
                             reply_markup=_abbrechen())
        return
    await state.update_data(api_id=int(roh))
    await state.set_state(Ablauf.api_hash)
    await message.answer(
        "2️⃣ <b>API-Hash</b>\n\n"
        "Նույն էջի երկար տեքստը։\n\n"
        "<i>32 նիշ՝ տառերից և թվերից</i>",
        reply_markup=_abbrechen(),
    )


@router.message(Ablauf.api_hash, F.text)
async def hat_api_hash(message: types.Message, state: FSMContext):
    wert = (message.text or "").strip()
    if len(wert) < 16:
        await message.answer("⚠️ Սա շատ կարճ է թվում։ Նորից՝",
                             reply_markup=_abbrechen())
        return
    await state.update_data(api_hash=wert)
    await _frage_telefon(message, state)


async def _frage_telefon(ziel: types.Message, state: FSMContext):
    await state.set_state(Ablauf.telefon)
    await ziel.answer(
        "3️⃣ <b>Հեռախոսահամար</b>\n\n"
        "Երկրի կոդով և գումարած նշանով (+)։\n\n"
        "<i>Օրինակ՝ +491701234567</i>\n\n"
        "Դա այն հաշիվն է, որով քո բոտը հետո կաշխատի։",
        reply_markup=_abbrechen(),
    )


@router.message(Ablauf.telefon, F.text)
async def hat_telefon(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    nummer = re.sub(r"[^\d+]", "", message.text or "")
    if not nummer.startswith("+") or len(nummer) < 8:
        await message.answer(
            "⚠️ Խնդրում եմ <b>+</b> նշանով և երկրի կոդով, "
            "օր.՝ <code>+491701234567</code>",
            reply_markup=_abbrechen())
        return

    warte = await message.answer("⏳ Միանում եմ Telegram-ին…")
    daten = await state.get_data()

    try:
        kl = TelegramClient(StringSession(), daten["api_id"], daten["api_hash"])
        await kl.connect()
        antwort = await kl.send_code_request(nummer)
        klienten[uid] = kl
        code_hashes[uid] = antwort.phone_code_hash
    except ApiIdInvalidError:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text("❌ API-ID-ն կամ API-Hash-ը սխալ է։",
                              reply_markup=_startknopf())
        return
    except PhoneNumberInvalidError:
        await _klient_weg(uid)
        await warte.edit_text("❌ Telegram-ը այս համարը չգիտի։ Նորից՝",
                              reply_markup=_abbrechen())
        return
    except PhoneNumberBannedError:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text("❌ Այս համարը արգելափակված է Telegram-ում։",
                              reply_markup=_startknopf())
        return
    except FloodWaitError as e:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text(
            f"⏳ Telegram-ը մեզ դանդաղեցնում է։ Խնդրում եմ սպասիր "
            f"<b>{e.seconds} վայրկյան</b>։",
            reply_markup=_startknopf())
        return
    except Exception as e:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text(f"❌ Սխալ՝ <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    await state.update_data(telefon=nummer)
    await state.set_state(Ablauf.code)
    await warte.edit_text(
        "4️⃣ <b>Մուտքագրիր կոդը</b>\n\n"
        "Telegram-ը հենց նոր քեզ կոդ ուղարկեց։\n\n"
        "⚠️ <b>Կարևոր՝</b> գրիր այն բաժանիչ նշաններով, օրինակ՝ "
        "<code>1 2 3 4 5</code> կամ <code>1-2-3-4-5</code>։\n\n"
        "<i>Եթե ուղարկես որպես սովորական թիվ, Telegram-ը դա կնկատի և "
        "կոդն անմիջապես անվավեր կդառնա — այդ դեպքում չի ստացվի։</i>",
        reply_markup=_abbrechen(),
    )


@router.message(Ablauf.code, F.text)
async def hat_code(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    code = re.sub(r"\D", "", message.text or "")
    await _weg(message)

    if not code:
        await message.answer("⚠️ Այնտեղ թիվ չկար։ Նորից՝",
                             reply_markup=_abbrechen())
        return

    kl = klienten.get(uid)
    if kl is None:
        await state.clear()
        await message.answer("❌ Կապը կորավ։ Սկսիր նորից՝ /start",
                             reply_markup=_startknopf())
        return

    daten = await state.get_data()
    warte = await message.answer("⏳ Մուտք եմ գործում…")

    try:
        await kl.sign_in(phone=daten["telefon"], code=code,
                         phone_code_hash=code_hashes.get(uid))
    except SessionPasswordNeededError:
        await state.set_state(Ablauf.passwort)
        await warte.edit_text(
            "5️⃣ <b>Երկքայլ գաղտնաբառ</b>\n\n"
            "Քո հաշիվը լրացուցիչ պաշտպանված է։ Ուղարկիր ինձ գաղտնաբառը։\n\n"
            "<i>Նամակը անմիջապես կջնջեմ։</i>",
            reply_markup=_abbrechen())
        return
    except PhoneCodeInvalidError:
        await warte.edit_text("❌ Կոդը սխալ է։ Նորից՝",
                              reply_markup=_abbrechen())
        return
    except PhoneCodeExpiredError:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text("❌ Կոդը ժամկետանց է։ Սկսիր նորից։",
                              reply_markup=_startknopf())
        return
    except Exception as e:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text(f"❌ Սխալ՝ <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    await _fertig(warte, state, uid)


@router.message(Ablauf.passwort, F.text)
async def hat_passwort(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    passwort = message.text or ""
    await _weg(message)

    kl = klienten.get(uid)
    if kl is None:
        await state.clear()
        await message.answer("❌ Կապը կորավ։ Սկսիր նորից՝ /start",
                             reply_markup=_startknopf())
        return

    warte = await message.answer("⏳ Ստուգում եմ գաղտնաբառը…")
    try:
        await kl.sign_in(password=passwort)
    except PasswordHashInvalidError:
        await warte.edit_text("❌ Գաղտնաբառը սխալ է։ Նորից՝",
                              reply_markup=_abbrechen())
        return
    except Exception as e:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text(f"❌ Սխալ՝ <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    await _fertig(warte, state, uid)


async def _fertig(warte: types.Message, state: FSMContext, uid: int):
    """Schluessel ausgeben und alles aufraeumen.

    Der Schluessel geht nur an diese eine Person (warte.answer schreibt in
    ihren Chat). Er wird nirgends geloggt und nirgendwohin weitergeleitet.
    """
    kl = klienten.get(uid)
    if kl is None:
        await state.clear()
        await warte.edit_text("❌ Կապը կորավ։ Սկսիր նորից՝ /start",
                              reply_markup=_startknopf())
        return
    try:
        ich = await kl.get_me()
        schluessel = kl.session.save()
    except Exception as e:
        await _klient_weg(uid); await state.clear()
        await warte.edit_text(f"❌ Կարդալու սխալ՝ <code>{type(e).__name__}</code>",
                              reply_markup=_startknopf())
        return

    name = ich.first_name or "—"
    nutzername = f"@{ich.username}" if ich.username else "առանց username"

    await warte.edit_text(
        f"✅ <b>Պատրաստ է</b>\n\nՄուտք գործված է որպես {name} ({nutzername})")

    # Schluessel in eigener Nachricht: antippen kopiert alles auf einmal.
    await warte.answer(f"<code>{schluessel}</code>")

    await warte.answer(
        "☝️ <b>Սա քո բանալին է։</b> Սեղմիր վրան՝ պատճենելու համար։\n\n"
        "Railway-ում մուտքագրիր <b>Variables</b> բաժնում՝\n"
        "<code>TELETHON_SESSION</code> = այս տեքստը\n\n"
        "⚠️ Այն նման է քո հաշվի գաղտնաբառին։ Մի փոխանցիր ուրիշին, մի դիր "
        "GitHub-ում։ Երբ այլևս պետք չլինի, ջնջիր վերևի նամակը։",
        reply_markup=_startknopf(),
    )

    await _klient_weg(uid)
    await state.clear()


# ── Owner-Werkzeug ──────────────────────────────────────

@router.message(Command("erlaubte"))
async def erlaubte(message: types.Message, ist_owner: bool):
    if not ist_owner:
        await message.answer("Գրիր /start")
        return
    alle = sorted(ERLAUBT_STATISCH | erlaubt_laufzeit)
    zeilen = "\n".join(
        f"• <code>{i}</code>" + (" (դու)" if i == OWNER_ID else "")
        for i in alle
    )
    await message.answer(f"👥 <b>Հասանելիություն ունեն՝</b>\n{zeilen}")


@router.message()
async def sonst(message: types.Message, ist_erlaubt: bool):
    if ist_erlaubt:
        await message.answer("Գրիր /start", reply_markup=_startknopf())
    else:
        await _zugang_screen(message)


# ── Start ───────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )
    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(Zugangskontrolle())
    dp.include_router(router)

    ich = await bot.get_me()
    log.info("Session-Bot laeuft als @%s — Owner %s, %d erlaubte ID(s)",
             ich.username, OWNER_ID, len(ERLAUBT_STATISCH))
    try:
        await dp.start_polling(bot)
    finally:
        for uid in list(klienten):
            await _klient_weg(uid)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
