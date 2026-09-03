# Session-Bot

Erzeugt den `TELETHON_SESSION`-Schlüssel per Telegram. Läuft bei
Railway, kein Terminal nötig. **Der Bot spricht Armenisch.**

**Besitzer darf immer, andere nur nach deiner Freigabe.** Jede Person
erzeugt dabei nur ihren **eigenen** Schlüssel für ihr **eigenes** Konto.
Fremde Schlüssel bekommst du nie zu sehen.

---

## Dateien

- `bot.py` — der Bot
- `requirements.txt` — aiogram + telethon
- `Procfile` — sagt Railway, wie gestartet wird
- `.gitignore` — hält Geheimnisse aus dem Repo

---

## Einrichten

### 1 · Eigenen Bot anlegen

Bei **@BotFather** den Befehl `/newbot` schicken, Name und Username
vergeben, Token merken. Das ist ein **eigener** Bot, nicht dein
Musik-Bot.

### 2 · Repo anlegen

Auf GitHub ein neues Repository erstellen und diese vier Dateien
hochladen. Am besten **Private** — nötig ist es nicht, im Code steht
kein Geheimnis, aber sauberer ist es.

### 3 · Bei Railway

`New Project` → `Deploy from GitHub repo` → dieses Repo wählen. Dann
unter **Variables** eintragen:

- `SESSION_BOT_TOKEN` — Token vom BotFather · **Pflicht**
- `OWNER_ID` — deine Telegram-User-ID · **Pflicht**
- `ALLOWED_IDS` — weitere erlaubte IDs, mit Komma getrennt, z. B.
  `123456789, 987654321` · freiwillig
- `TG_API_ID` — Zahl von my.telegram.org · freiwillig
- `TG_API_HASH` — Text von my.telegram.org · freiwillig

Die letzten beiden sparen Tipparbeit: sind sie gesetzt, fragt der Bot
nicht jedes Mal danach.

Fehlt eine Pflichtvariable, stürzt der Bot beim Start ab und schreibt
den fehlenden Namen ins Log.

### 4 · Läuft es?

Im Railway-Log steht dann in etwa:

```
Session-Bot laeuft als @DeinBot — Owner 111..., 1 erlaubte ID(s)
```

---

## Wer darf den Bot benutzen

- **Du (OWNER_ID):** immer.
- **IDs in ALLOWED_IDS:** sofort, und das bleibt auch nach einem
  Neustart erhalten.
- **Alle anderen:** sehen beim `/start` einen Knopf **🙋 Zugang
  anfragen**. Tippt jemand darauf, bekommst **du** eine Nachricht mit
  zwei Knöpfen — **✅ Bestätigen** oder **🚫 Ablehnen**. Erst nach
  „Bestätigen“ darf die Person den Bot benutzen.

Eine Freigabe per Knopf gilt **bis zum nächsten Neustart** (Railway
startet bei jedem neuen Deploy neu). Soll jemand **dauerhaft** dürfen,
trag seine ID zusätzlich in `ALLOWED_IDS` ein.

Mit `/erlaubte` (nur du) zeigt der Bot dir, welche IDs gerade Zugang
haben.

---

## Benutzen

Bot in Telegram mit `/start` anschreiben. Auf **🔑 Session erstellen**
tippen, dann der Reihe nach:

1. API-ID *(entfällt bei gesetzter Variable)*
2. API-Hash *(entfällt bei gesetzter Variable)*
3. Telefonnummer mit Vorwahl: `+491701234567`
4. Code von Telegram — **mit Trennzeichen:** `1 2 3 4 5`
5. Zwei-Faktor-Passwort, falls eingeschaltet

Am Ende kommt der Schlüssel in einer eigenen Nachricht. Antippen
kopiert ihn komplett. `/cancel` bricht jederzeit ab.

---

## Warum der Code mit Trennzeichen muss

Telegram erkennt, wenn ein Login-Code als reine Zahl in einem
Telegram-Chat verschickt wird, und macht ihn sofort ungültig — ein
Schutz gegen Betrüger, die sich Codes weiterleiten lassen. Deshalb
`1 2 3 4 5` statt `12345`. Der Bot filtert die Trennzeichen selbst
wieder raus.

---

## Sicherheit

- **Zugriff:** Nur Owner und freigegebene IDs kommen zur
  Session-Erzeugung durch. Fremde können höchstens Zugang anfragen.
- **Getrennt pro Person:** Jede Person hat ihre **eigene** Verbindung
  zu Telegram. Es gibt keine gemeinsame Verbindung, an der sich zwei
  Logins vermischen könnten — so kommt niemand an den Schlüssel einer
  anderen Person.
- **Nur an den Ersteller:** Der fertige Schlüssel geht ausschließlich
  an die Person, die ihn gerade erzeugt hat. Auch **du** als Besitzer
  bekommst fremde Schlüssel nicht zu sehen — der Bot leitet sie
  bewusst nirgendwohin weiter.
- **Logs:** Weder Nummer noch Code, Passwort oder Schlüssel landen in
  einer Logzeile.
- **Chat:** Nachrichten mit Code und Passwort löscht der Bot sofort
  wieder.
- **Der Schlüssel selbst** ist wie ein Passwort für das jeweilige
  Telegram-Konto. Er gehört ins Railway-Feld `TELETHON_SESSION` des
  eigenen Bots und sonst nirgendwohin. Nach dem Eintragen die Nachricht
  im Bot-Chat löschen.
- **Niemals** Token, Session-Schlüssel oder API-Hash in eine Datei im
  Repo schreiben. Alles kommt aus den Railway-Variablen.

---

## Lokal statt Railway

```
pip install -r requirements.txt

export SESSION_BOT_TOKEN=...
export OWNER_ID=...
export ALLOWED_IDS=...        # freiwillig
export TG_API_ID=...          # freiwillig
export TG_API_HASH=...        # freiwillig

python bot.py
```
