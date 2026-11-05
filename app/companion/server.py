"""Local, single-presenter companion dashboard and read-only AI chat."""

import asyncio
import concurrent.futures
import http.cookies
import http.server
import json
import pathlib
import secrets
import threading
import time
import urllib.parse
import uuid

from chat_engine import ChatEngine
import capacity_cost
import gold_data

ROOT = pathlib.Path(__file__).parent
PORT = 8765
ORIGIN = f"http://localhost:{PORT}"
CSRF = secrets.token_urlsafe(32)
LOOP = asyncio.new_event_loop()
ENGINE = ChatEngine()
TURNS = {}
OWNERS = {}
CACHE = {}
CACHE_LOCK = threading.RLock()
FABRIC_URL = (
    "https://app.fabric.microsoft.com/groups/0660f2dc-333d-445c-8c62-6d15515f7206/"
    "kustodashboards/f1c393ae-1770-40b9-94b5-e9ee2c2e6e58"
)


def dashboard(selection):
    key = json.dumps(selection, sort_keys=True)
    with CACHE_LOCK:
        entry = CACHE.get(key)
        if entry and time.monotonic() - entry[0] < 30:
            return entry[1]
    filters = [{"field": "country", "op": "eq", "value": selection["country"]}] if selection.get("country") else []
    common = {
        "filters": filters, "date_from": selection.get("date_from") or None,
        "date_to": selection.get("date_to") or None,
    }
    gold_data.snapshot()
    jobs = {
        "summary": lambda: gold_data.analytics(**common)["rows"][0],
        "initiators": lambda: gold_data.analytics("grouped", ["originator_type"], **common)["rows"],
        "reasons": lambda: gold_data.analytics("grouped", ["reported_reason"], **common)["rows"],
        "findings": lambda: gold_data.analytics("grouped", ["inspection_finding"], **common)["rows"],
        "batches": lambda: gold_data.analytics("grouped", ["batch_id", "product_id"], limit=30, **common)["rows"],
        "trend": lambda: gold_data.analytics(
            "trend", ["return_month"], sort_by="return_month", direction="asc", limit=100, **common
        )["rows"],
        "cases": lambda: gold_data.case_records(limit=30, **common)["rows"],
        "countries": lambda: gold_data.analytics("grouped", ["country"], limit=100)["rows"],
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        pending = {key: executor.submit(function) for key, function in jobs.items()}
        result = {key: future.result() for key, future in pending.items()}
    result["lineage"] = gold_data.lineage()
    result["generated_at"] = time.time()
    with CACHE_LOCK:
        CACHE[key] = (time.monotonic(), result)
    return result


def finish_turn(future, turn):
    try:
        future.result()
    except Exception as error:
        turn.update({"status": "failed", "error": str(error)[:600]})


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def send(self, code, payload, content_type="application/json", headers=None):
        body = json.dumps(payload, ensure_ascii=True).encode() if content_type == "application/json" else payload
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';"
            " img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed_host(self):
        return self.headers.get("Host") in {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}

    def browser_id(self):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            value = cookie.get("battery_demo")
            return str(uuid.UUID(value.value)) if value else None
        except (ValueError, http.cookies.CookieError):
            return None

    def selection(self, query):
        if any(key not in {"country", "date_from", "date_to"} for key in query):
            raise ValueError("Unsupported dashboard filter.")
        if any(len(value) != 1 or not isinstance(value[0], str) for value in query.values()):
            raise ValueError("Each dashboard filter must have one text value.")
        values = {key: value[0] for key, value in query.items()}
        if len(values.get("country", "")) > 100:
            raise ValueError("Country name is too long.")
        start = gold_data.date_value(values["date_from"]) if values.get("date_from") else None
        end = gold_data.date_value(values["date_to"]) if values.get("date_to") else None
        if start and end and start > end:
            raise ValueError("Start date must not follow end date.")
        return values

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403, {"error": "Only the local companion origin is allowed."})
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                browser = self.browser_id() or str(uuid.uuid4())
                return self.send(200, (ROOT / "public" / "index.html").read_bytes(), "text/html; charset=utf-8", {
                    "Set-Cookie": f"battery_demo={browser}; HttpOnly; SameSite=Strict; Path=/",
                })
            if parsed.path in {"/app.js", "/styles.css"}:
                path = ROOT / "public" / parsed.path.lstrip("/")
                content_type = "text/javascript; charset=utf-8" if path.suffix == ".js" else "text/css; charset=utf-8"
                return self.send(200, path.read_bytes(), content_type)
            if parsed.path == "/api/config":
                return self.send(200, {
                    "csrf_token": CSRF, "assistant_ready": ENGINE.authenticated,
                    "fabric_url": FABRIC_URL, "workspace": "Waferwire_hackathon",
                    "mode": "Local single-presenter demo; uses the presenter's Azure and Copilot access",
                })
            if parsed.path == "/api/health":
                return self.send(200, {"status": "ready", "ai_authenticated": ENGINE.authenticated})
            if parsed.path == "/api/dashboard":
                query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
                return self.send(200, dashboard(self.selection(query)))
            if parsed.path == "/api/cost":
                query = urllib.parse.parse_qs(parsed.query)
                if any(key not in {"sku", "hours", "currency"} for key in query):
                    raise ValueError("Unsupported cost input.")
                return self.send(200, capacity_cost.estimate(
                    query.get("sku", ["F2"])[0], float(query.get("hours", ["24"])[0]),
                    query.get("currency", ["USD"])[0],
                ))
            if parsed.path.startswith("/api/turn/"):
                turn_id = str(uuid.UUID(parsed.path.rsplit("/", 1)[-1]))
                turn = TURNS.get(turn_id)
                if not turn or turn["owner"] != self.browser_id():
                    return self.send(404, {"error": "Turn not found."})
                result = {key: value for key, value in turn.items() if key not in {"owner", "conversation"}}
                if turn.get("conversation"):
                    result["activity"] = turn["conversation"].activity
                return self.send(200, result)
            return self.send(404, {"error": "Not found."})
        except (ValueError, gold_data.InvalidQuestion) as error:
            return self.send(400, {"error": str(error)})
        except Exception as error:
            return self.send(503, {"error": str(error)[:600]})

    def do_POST(self):
        if (
            not self.allowed_host()
            or self.headers.get("Origin") != ORIGIN
            or self.headers.get("X-CSRF-Token") != CSRF
        ):
            return self.send(403, {"error": "Invalid local origin or request token."})
        try:
            if self.path != "/api/chat":
                return self.send(404, {"error": "Not found."})
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Use JSON.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 12000:
                raise ValueError("Message is too large or empty.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("The request must be a JSON object.")
            if set(body) - {"message", "conversation_id", "selection"}:
                raise ValueError("Unsupported request fields.")
            message = body.get("message", "")
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 5000:
                raise ValueError("Enter a question of 1 to 5,000 characters.")
            owner = self.browser_id()
            if not owner:
                return self.send(403, {"error": "Open the companion page before starting chat."})
            if not isinstance(body.get("conversation_id"), str):
                raise ValueError("A conversation identifier is required.")
            conversation_id = str(uuid.UUID(body["conversation_id"]))
            if conversation_id in OWNERS and OWNERS[conversation_id] != owner:
                return self.send(403, {"error": "This conversation belongs to a different browser."})
            OWNERS[conversation_id] = owner
            selection = body.get("selection", {})
            if not isinstance(selection, dict) or any(not isinstance(value, str) for value in selection.values()):
                raise ValueError("Invalid dashboard selection.")
            selection = self.selection({key: [value] for key, value in selection.items() if value})
            if selection:
                message = (
                    "Current dashboard selection (apply unless the question explicitly changes it): "
                    + json.dumps(selection) + "\n\n" + message
                )
            turn_id = str(uuid.uuid4())
            turn = {"status": "running", "owner": owner, "evidence": [], "created_at": time.time()}
            TURNS[turn_id] = turn
            future = asyncio.run_coroutine_threadsafe(
                ENGINE.answer(conversation_id, message, turn), LOOP
            )
            future.add_done_callback(lambda future: finish_turn(future, turn))
            return self.send(202, {"turn_id": turn_id})
        except (ValueError, KeyError, TypeError) as error:
            return self.send(400, {"error": str(error)})


def main():
    thread = threading.Thread(target=LOOP.run_forever, daemon=True)
    thread.start()
    server = None
    try:
        asyncio.run_coroutine_threadsafe(ENGINE.start(), LOOP).result(timeout=120)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        print(f"READY {ORIGIN} | Gold data + Copilot chat | local single-presenter demo", flush=True)
        server.serve_forever()
    finally:
        if server:
            server.server_close()
        asyncio.run_coroutine_threadsafe(ENGINE.stop(), LOOP).result(timeout=30)
        LOOP.call_soon_threadsafe(LOOP.stop)


if __name__ == "__main__":
    main()
