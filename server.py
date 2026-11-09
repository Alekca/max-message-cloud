import hmac
import json
import os
import re
import sqlite3
import ssl
import sys
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB = os.getenv("DB_PATH", str(ROOT / "event.sqlite3"))
ADMIN = os.environ["ADMIN_KEY"]
TOKEN = os.getenv("MAX_BOT_TOKEN")
SECRET = os.getenv("MAX_WEBHOOK_SECRET")
ORIGIN = os.getenv("SCREEN_ORIGIN", "https://alekca.github.io")
BOT_URL = os.getenv("MAX_BOT_URL", "")
EMOJI = {"heart": "❤️", "fire": "🔥", "clap": "👏", "like": "👍"}
EVENTS = ["bot_started", "message_created", "message_callback"]


@contextmanager
def database():
    connection = sqlite3.connect(DB, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def max_request(path, body=None, *, timeout=6, **params):
    url = "https://platform-api2.max.ru/" + path
    if params:
        url += "?" + urlencode(params)
    request = Request(url, None if body is None else json.dumps(body).encode(), {
        "Authorization": TOKEN, "Content-Type": "application/json",
    })
    context = ssl.create_default_context()
    if os.getenv("MAX_CA_FILE"):
        context.load_verify_locations(os.environ["MAX_CA_FILE"])
    with urlopen(request, context=context, timeout=timeout) as response:
        return json.load(response)


def welcome(user_id, text):
    buttons = [
        {"type": "callback", "text": emoji, "payload": key}
        for key, emoji in EMOJI.items()
    ]
    max_request("messages", {
        "text": text,
        "attachments": [{"type": "inline_keyboard", "payload": {"buttons": [buttons]}}],
    }, user_id=user_id)


def submit(db, key, text, author=None, avatar=None):
    return db.execute(
        "INSERT OR IGNORE INTO messages(key,text,status,author,avatar) VALUES (?,?,'pending',?,?)",
        (key, text, author, avatar),
    ).rowcount


def author_details(sender, chat_id):
    profile = sender
    if type(chat_id) is int:
        try:
            dialog = max_request(f"chats/{chat_id}", timeout=3).get("dialog_with_user") or {}
            if dialog.get("user_id") == sender.get("user_id"):
                profile = {**sender, **dialog}
        except (OSError, ValueError):
            pass
    username = profile.get("username")
    name = " ".join(filter(None, (profile.get("first_name"), profile.get("last_name"))))
    author = ("@" + username.lstrip("@")) if username else name or profile.get("name")
    avatar = profile.get("avatar_url") or profile.get("full_avatar_url")
    if not isinstance(avatar, str) or not avatar.startswith("https://"):
        avatar = None
    return author, avatar


def react(db, key, emoji, user_id=None):
    now = time.time()
    row = db.execute("""
        INSERT OR IGNORE INTO reactions(key,emoji,created,user_id,accepted)
        VALUES (?,?,?,?,NOT EXISTS (
            SELECT 1 FROM reactions WHERE user_id=? AND accepted=1 AND created>?
        ))
        RETURNING accepted
    """, (key, emoji, now, user_id, user_id, now - 1)).fetchone()
    return None if row is None else bool(row["accepted"])


def handle_update(update):
    kind = update.get("update_type")
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    dialog = recipient.get("chat_type") == "dialog"
    if kind == "bot_started":
        user_id = (update.get("user") or {}).get("user_id")
        if user_id:
            welcome(user_id, "Напишите сообщение до 180 символов. После проверки ведущим оно появится на общем экране с вашим именем и фото профиля, если они доступны. Можно отправлять одну реакцию в секунду.")
    elif kind == "message_created" and dialog:
        sender = message.get("sender") or {}
        body = message.get("body") or {}
        user_id = sender.get("user_id")
        text = (body.get("text") or "").strip()
        key = body.get("mid")
        if not user_id or sender.get("is_bot") or not key:
            return
        if not text or len(text) > 180 or text == "/start":
            welcome(user_id, "Отправьте текст до 180 символов или выберите реакцию.")
            return
        author, avatar = author_details(sender, recipient.get("chat_id"))
        with database() as db:
            inserted = submit(db, key, text, author, avatar)
        if inserted:
            welcome(user_id, "Сообщение на проверке у ведущего. После одобрения оно появится на экране с вашим именем и фото профиля, если они доступны.")
    elif kind == "message_callback" and dialog:
        callback = update.get("callback") or {}
        emoji = EMOJI.get(callback.get("payload"))
        callback_id = callback.get("callback_id")
        user_id = (callback.get("user") or {}).get("user_id")
        if emoji and callback_id and type(user_id) is int:
            with database() as db:
                accepted = react(db, callback_id, emoji, user_id)
            if accepted is not None:
                notification = "Реакция отправлена" if accepted else "Можно отправлять одну реакцию в секунду"
                max_request("answers", {"notification": notification}, callback_id=callback_id)


def matches(received, expected):
    return bool(expected) and hmac.compare_digest(received.encode(), expected.encode())


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data=None, content_type="application/json"):
        payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.path == "/api/screen" and self.headers.get("Origin") == ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self):
        return matches(self.headers.get("Authorization", ""), "Bearer " + ADMIN)

    def do_GET(self):
        files = {
            "/": ("index.html", "text/html"),
            "/admin": ("admin.html", "text/html"),
            "/screen.css": ("screen.css", "text/css"),
            "/screen.js": ("screen.js", "text/javascript"),
            "/bot-qr.png": ("bot-qr.png", "image/png"),
        }
        if urlsplit(self.path).path == "/":
            self.path = "/"
        if self.path in files:
            name, mime = files[self.path]
            directory = ROOT if self.path == "/admin" else ROOT / "docs"
            return self.respond(200, (directory / name).read_bytes(), mime if mime.startswith("image/") else mime + "; charset=utf-8")
        if self.path == "/api/screen":
            with database() as db:
                messages = db.execute(
                    "SELECT id,text,author,avatar FROM messages WHERE status='visible' ORDER BY shown,id"
                ).fetchall()
                position = db.execute("SELECT message_id, fraction FROM screen_position WHERE id=1").fetchone()
                reactions = db.execute(
                    "SELECT id,emoji FROM reactions WHERE accepted=1 AND created>? ORDER BY id DESC LIMIT 30",
                    (time.time() - 4,),
                ).fetchall()
            return self.respond(200, {
                "messages": [dict(row) for row in messages],
                "reactions": [dict(row) for row in reversed(reactions)],
                "botUrl": BOT_URL,
                "maxConnected": bool(TOKEN),
                "position": dict(position) if position else None,
            })
        if self.path == "/api/moderate":
            if not self.authorized():
                return self.respond(401, {"error": "Неверный ключ"})
            with database() as db:
                rows = db.execute(
                    "SELECT id,text,status,author,avatar FROM messages WHERE status IN ('pending','visible') ORDER BY id DESC"
                ).fetchall()
            return self.respond(200, {"messages": [dict(row) for row in rows]})
        self.respond(404, {})

    def do_POST(self):
        if self.path == "/max/webhook":
            if not matches(self.headers.get("X-Max-Bot-Api-Secret", ""), SECRET):
                return self.respond(403, {})
        elif self.path in ("/api/moderate", "/api/position"):
            if not self.authorized():
                return self.respond(401, {"error": "Неверный ключ"})
        else:
            return self.respond(404, {})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 262144:
                return self.respond(413, {})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                return self.respond(400, {})
        except ValueError:
            return self.respond(400, {})
        if self.path == "/max/webhook":
            try:
                handle_update(body)
            except OSError as error:
                # The message or reaction is already stored before outbound acknowledgement.
                print(f"MAX request failed: {type(error).__name__}", file=sys.stderr)
            return self.respond(200, {})
        if self.path == "/api/position":
            message_id = body.get("message_id")
            fraction = body.get("fraction")
            if (message_id is not None and (type(message_id) is not int or not 0 < message_id < 2**63)
                    or type(fraction) not in (int, float) or not 0 <= fraction <= 1):
                return self.respond(400, {"error": "Некорректная позиция"})
            with database() as db:
                db.execute(
                    "INSERT OR REPLACE INTO screen_position VALUES (1,?,?)",
                    (message_id, fraction),
                )
            return self.respond(200, {})
        action = body.get("action")
        with database() as db:
            if action == "clear":
                db.execute("UPDATE messages SET status='hidden' WHERE status='visible'")
            elif action in ("show", "hide") and type(body.get("id")) is int:
                status = "visible" if action == "show" else "hidden"
                previous = ("pending",) if action == "show" else ("pending", "visible")
                db.execute(
                    "UPDATE messages SET status=?,shown=? WHERE id=? AND status IN (?,?)",
                    (status, time.time(), body["id"], previous[0], previous[-1]),
                )
            elif not TOKEN and action == "sample":
                text = body.get("text")
                if not isinstance(text, str) or not 0 < len(text.strip()) <= 180:
                    return self.respond(400, {"error": "Нужно от 1 до 180 символов"})
                submit(db, None, text.strip())
            elif not TOKEN and action == "reaction" and body.get("emoji") in EMOJI:
                react(db, None, EMOJI[body["emoji"]])
            else:
                return self.respond(400, {"error": "Действие недоступно"})
        self.respond(200, {})


if __name__ == "__main__":
    if len(ADMIN) < 8:
        sys.exit("ADMIN_KEY must be at least 8 characters")
    if TOKEN and not re.fullmatch(r"[a-zA-Z0-9_-]{20,64}", SECRET or ""):
        sys.exit("Set MAX_WEBHOOK_SECRET (20–64 letters, digits, underscores or hyphens)")
    if SECRET and not TOKEN:
        sys.exit("MAX_WEBHOOK_SECRET requires MAX_BOT_TOKEN")
    if len(sys.argv) == 3 and sys.argv[1] == "subscribe":
        endpoint = urlsplit(sys.argv[2])
        if not TOKEN or endpoint.scheme != "https" or not endpoint.hostname or endpoint.path != "/max/webhook":
            sys.exit("Pass the public HTTPS URL ending in /max/webhook and set MAX credentials")
        print(max_request("subscriptions", {
            "url": sys.argv[2], "update_types": EVENTS, "secret": SECRET,
        }))
        sys.exit()
    with database() as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, key TEXT UNIQUE, text TEXT NOT NULL,
                status TEXT NOT NULL, shown REAL
            );
            CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY, key TEXT UNIQUE, emoji TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS screen_position (
                id INTEGER PRIMARY KEY, message_id INTEGER, fraction REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS reactions_created ON reactions(created);
        """)
        for table, additions in {
            "messages": {"author": "TEXT", "avatar": "TEXT"},
            "reactions": {"user_id": "INTEGER", "accepted": "INTEGER NOT NULL DEFAULT 1"},
        }.items():
            columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, declaration in additions.items():
                if column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        db.execute("CREATE INDEX IF NOT EXISTS reactions_user_recent ON reactions(user_id,created) WHERE accepted=1")
    ThreadingHTTPServer(
        (os.getenv("BIND", "127.0.0.1"), int(os.getenv("PORT", "8000"))), Handler
    ).serve_forever()
