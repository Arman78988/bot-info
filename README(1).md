# Session-Bot

Erzeugt `TELETHON_SESSION`-Schlüssel per Telegram. Läuft bei Railway,
kein Terminal nötig.

**Nur der Besitzer kann ihn benutzen.** Vor allen Handlern hängt eine
Sperre auf `OWNER_ID` — Nachrichten von anderen IDs werden kommentarlos
verworfen.

---

## Dateien

| Datei | Zweck |
|---|---|
| `session_bot.py` | der Bot |
| `requirements.txt` | aiogram + telethon |
| `Procfile` | sagt Railway, wie gestartet wird |
| `.gitignore` | hält Geheimnisse aus dem Repo |

---

## Einrichten

### 1 · Eigenen Bot anlegen

Bei **@BotFather**:

```
/newbot
```

Name und Username vergeben, Token merken. Das ist ein **eigener** Bot,
nicht dein Musik-Bot.

### 2 · Repo anlegen

Auf GitHub ein neues Repository erstellen und diese vier Dateien
hochladen. Am besten **Private** — nötig ist es nicht, im Code steht
kein Geheimnis, aber sauberer ist es.

### 3 · Bei Railway

`New Project` → `Deploy from GitHub repo` → dieses Repo wählen.

Dann unter **Variables** eintragen:

| Variable | Wert | Pflicht |
|---|---|---|
| `SESSION_BOT_TOKEN` | Token vom BotFather | ja |
| `OWNER_ID` | deine Telegram-User-ID | ja |
| `TG_API_ID` | Zahl von my.telegram.org | nein |
| `TG_API_HASH` | Text von my.telegram.org | nein |

Die letzten beiden sparen Tipparbeit: sind sie gesetzt, fragt der Bot
nicht jedes Mal danach.

Fehlt eine Pflichtvariable, stürzt der Bot beim Start ab und schreibt
den fehlenden Namen ins Log.

### 4 · Läuft es?

Im Railway-Log steht dann:

```
Session-Bot laeuft als @DeinBot — nur ID 8722868247 darf ihn benutzen
```

---

## Benutzen

Bot in Telegram anschreiben:

```
/start
```

Auf **🔑 Session erstellen** tippen, dann:

| Schritt | Eingabe |
|---|---|
| 1 | API-ID *(entfällt bei gesetzter Variable)* |
| 2 | API-Hash *(entfällt bei gesetzter Variable)* |
| 3 | Telefonnummer mit Vorwahl: `+491701234567` |
| 4 | Code von Telegram — **mit Trennzeichen:** `1 2 3 4 5` |
| 5 | Zwei-Faktor-Passwort, falls eingeschaltet |

Am Ende kommt der Schlüssel in einer eigenen Nachricht. Antippen
kopiert ihn komplett.

`/cancel` bricht jederzeit ab.

---

## Warum der Code mit Trennzeichen muss

Telegram erkennt, wenn ein Login-Code als reine Zahl in einem
Telegram-Chat verschickt wird, und macht ihn sofort ungültig — ein
Schutz gegen Betrüger, die sich Codes weiterleiten lassen.

Deshalb `1 2 3 4 5` statt `12345`. Der Bot filtert die Trennzeichen
selbst wieder raus.

---

## Sicherheit

**Zugriff:** Nur `OWNER_ID` kommt durch. Für alle anderen antwortet der
Bot überhaupt nicht.

**Logs:** Weder Nummer noch Code, Passwort oder Schlüssel landen in
einer Logzeile.

**Chat:** Deine Nachrichten mit Code und Passwort löscht der Bot sofort
wieder.

**Der Schlüssel selbst** ist wie ein Passwort für dein Telegram-Konto.
Er gehört ins Railway-Feld `TELETHON_SESSION` deines Musik-Bots und
sonst nirgendwohin. Wenn du ihn eingetragen hast, lösch die Nachricht
im Bot-Chat.

**Niemals** Token, Session-Schlüssel oder API-Hash in eine Datei im
Repo schreiben. Alles kommt aus den Railway-Variablen.

---

## Lokal statt Railway

Geht auch:

```
pip install -r requirements.txt

export SESSION_BOT_TOKEN=...
export OWNER_ID=...
export TG_API_ID=...
export TG_API_HASH=...

python session_bot.py
```
