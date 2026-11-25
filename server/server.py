"""Live NSE chart server (Angel One SmartAPI). View-only: it never places orders."""
import os, json, time, asyncio, threading, calendar, requests, pyotp
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

# ---- STOCKS: 3 screens x 4 charts. ';' separates screens, ',' separates stocks.
# Change without code: set the PAGES environment variable on Render. NSE symbols (no -EQ).
# Format: SYMBOL:Display Name   (":Display Name" is optional)
DEFAULT_PAGES = ("MENONBE:Menon Bearings,CUPID:Cupid,MCX:MCX,GROWW:Groww;"
                 "ANLON:Anlon Healthcare,PRIZOR:Prizor Viztech,KSHINTL:KSH International,GURJATH:Gurjath Inject;"
                 "SBC:SBC Exports,SAILIFE:Sai Life Sciences,SHUKRAPHAR:Shukra Medtech,SOUTHBANK:South Indian Bank;"
                 "DIVISLAB:Divi's Labs,RELIANCE:Reliance,HDFCBANK:HDFC Bank,TCS:TCS;"
                 "NIFTY:Nifty 50,BANKNIFTY:Bank Nifty,INFY:Infosys,SBIN:SBI")
RAW = [[x.strip() for x in p.split(",") if x.strip()]
       for p in os.environ.get("PAGES", DEFAULT_PAGES).split(";") if p.strip()]
PAGES = [[x.split(":")[0].strip().upper() for x in p] for p in RAW]
LABELS = {x.split(":")[0].strip().upper(): (x.split(":", 1)[1].strip() if ":" in x else x.strip().upper())
          for p in RAW for x in p}
INTERVAL = os.environ.get("INTERVAL", "FIVE_MINUTE")
BUCKETS = {"ONE_MINUTE": 60, "THREE_MINUTE": 180, "FIVE_MINUTE": 300, "TEN_MINUTE": 600,
           "FIFTEEN_MINUTE": 900, "THIRTY_MINUTE": 1800, "ONE_HOUR": 3600}
BUCKET = BUCKETS[INTERVAL]
INDEX_TOKENS = {"NIFTY": "99926000", "BANKNIFTY": "99926009"}
SYMS = list(dict.fromkeys(s for p in PAGES for s in p))
KEY = os.environ.get("VIEW_KEY", "")
IST = 19800            # seconds; chart times are shifted so the axis shows IST
OPEN = 9 * 3600 + 15 * 60   # NSE candles start at 09:15

clients, tokens, by_token, cache = set(), {}, {}, {}
all_eq = []
exch = {}   # symbol -> "NSE" or "BSE"
pc = {}     # symbol -> official previous close from the exchange feed
ready, loop, last_tick, cur_ws = threading.Event(), None, [0.0], [None]
status = {"state": "starting", "message": "Starting market-data service"}
session_day, morning_refresh_day = [None], [None]


def set_status(state, message):
    status.update({"state": state, "message": str(message)[:240]})


def ist_now():
    return datetime.now(timezone.utc) + timedelta(seconds=IST)


def bucket(ts):
    t = int(ts) + IST
    return (t - OPEN) // BUCKET * BUCKET + OPEN


def on_tick(sym, price, ts):
    """Fold one tick into the server's candle list and return the candle."""
    local = datetime.fromtimestamp(ts, timezone.utc) + timedelta(seconds=IST)
    if not (9 * 3600 + 15 * 60 <= local.hour * 3600 + local.minute * 60 + local.second < 15 * 3600 + 30 * 60):
        return None
    rows = cache.setdefault(sym, [])
    b = bucket(ts)
    if rows and rows[-1]["time"] == b:
        c = rows[-1]
        c["high"] = max(c["high"], price); c["low"] = min(c["low"], price); c["close"] = price
    elif rows and rows[-1]["time"] > b:
        return None
    else:
        c = {"time": b, "open": price, "high": price, "low": price, "close": price}
        rows.append(c)
    return c


def prev_close(rows):
    if not rows:
        return None
    today = rows[-1]["time"] // 86400
    for c in reversed(rows):
        if c["time"] // 86400 < today:
            return c["close"]
    return None


def check(k):
    if KEY and k != KEY:
        raise HTTPException(403)


def login():
    api = SmartConnect(api_key=os.environ["ANGEL_API_KEY"])
    d = api.generateSession(os.environ["ANGEL_CLIENT_CODE"], os.environ["ANGEL_PIN"],
                            pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now())
    if not d.get("status"):
        raise RuntimeError(d)
    return api, d["data"]["jwtToken"], api.getfeedToken()


def load_tokens():
    """NSE first (EQ, BE, BZ, SM, ST). Any symbol not found on NSE is looked up on BSE."""
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    series = ["EQ", "BE", "BZ", "SM", "ST"]
    best, bse = {}, {}
    for s, t in INDEX_TOKENS.items():
        if s in SYMS:
            tokens[s] = t; by_token["1:" + t] = s; exch[s] = "NSE"
    for r in requests.get(url, timeout=180).json():
        seg, sym = r["exch_seg"], r["symbol"]
        if seg == "NSE" and "-" in sym:
            base, suf = sym.rsplit("-", 1)
            if suf not in series:
                continue
            all_eq.append(sym)
            if base in SYMS and base not in INDEX_TOKENS:
                rank = series.index(suf)
                if base not in best or rank < best[base][0]:
                    best[base] = (rank, r["token"])
        elif seg == "BSE" and r.get("instrumenttype", "") == "":
            base = sym.split("-")[0]
            all_eq.append("BSE:" + sym)
            if base in SYMS and base not in bse:
                bse[base] = r["token"]
    for s, (_, t) in best.items():
        tokens[s] = t; by_token["1:" + t] = s; exch[s] = "NSE"
    for s in SYMS:
        if s not in tokens and s in bse:
            tokens[s] = bse[s]; by_token["3:" + bse[s]] = s; exch[s] = "BSE"
            print("Using BSE for", s)
        elif s not in tokens:
            print("UNKNOWN SYMBOL (check spelling):", s)


def load_candles(api):
    now = datetime.now(timezone.utc) + timedelta(seconds=IST)
    for s in SYMS:
        if s not in tokens:
            cache[s] = []; continue
        try:
            r = api.getCandleData({"exchange": exch.get(s, "NSE"), "symboltoken": tokens[s], "interval": INTERVAL,
                                   "fromdate": (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M"),
                                   "todate": now.strftime("%Y-%m-%d %H:%M")})
            rows = r.get("data") or []
            cache[s] = [{"time": calendar.timegm(time.strptime(x[0][:19], "%Y-%m-%dT%H:%M:%S")),
                         "open": x[1], "high": x[2], "low": x[3], "close": x[4]} for x in rows]
        except Exception as e:
            print("candle error", s, e)
            cache.setdefault(s, [])
        time.sleep(0.5)   # Angel rate limit


async def broadcast(msg):
    for c in list(clients):
        try:
            await c.send_text(msg)
        except Exception:
            clients.discard(c)


def stream(jwt, feed):
    sws = SmartWebSocketV2(jwt, os.environ["ANGEL_API_KEY"], os.environ["ANGEL_CLIENT_CODE"], feed)
    cur_ws[0] = sws

    def on_open(ws):
        groups = {}
        for key in by_token:
            et, tk = key.split(":")
            groups.setdefault(int(et), []).append(tk)
        sws.subscribe("c1", 2, [{"exchangeType": e, "tokens": t} for e, t in groups.items()])

    def on_data(ws, msg):
        tok = str(msg.get("token")).strip('"')
        s = by_token.get(str(msg.get("exchange_type")) + ":" + tok)
        if s and "last_traded_price" in msg:
            p = msg["last_traded_price"] / 100
            if msg.get("closed_price"):
                pc[s] = msg["closed_price"] / 100
            now = time.time(); last_tick[0] = now
            on_tick(s, p, now)
            if loop:
                out = json.dumps({"s": s, "p": p, "pc": pc.get(s), "ts": msg.get("exchange_timestamp")})
                asyncio.run_coroutine_threadsafe(broadcast(out), loop)

    sws.on_open = on_open
    sws.on_data = on_data
    sws.on_error = lambda ws, e: print("ws error", e)
    sws.connect()   # blocks until the socket drops


def market_open():
    t = ist_now()
    return t.weekday() < 5 and (9, 20) <= (t.hour, t.minute) < (15, 30)


def watchdog():
    """Reconnect a stale feed and force a fresh Angel login each morning at 08:45 IST."""
    while True:
        time.sleep(15)
        now = ist_now()
        today = now.date()
        if now.weekday() < 5 and (now.hour, now.minute) >= (8, 45) and morning_refresh_day[0] != today:
            morning_refresh_day[0] = today
            print("watchdog: forcing fresh morning login")
            try:
                if cur_ws[0]:
                    cur_ws[0].close_connection()
            except Exception as e:
                print("morning refresh close failed", e)
        if ready.is_set() and market_open() and last_tick[0] and time.time() - last_tick[0] > 180:
            print("watchdog: feed silent, reconnecting")
            last_tick[0] = time.time()
            try:
                if cur_ws[0]:
                    cur_ws[0].close_connection()
            except Exception as e:
                print("watchdog close failed", e)
                time.sleep(20)
                os._exit(1)


def runner():
    failed_logins = 0
    delay = 10
    while True:
        t0 = time.time()
        try:
            set_status("logging_in", "Connecting to Angel One…")
            api, jwt, feed = login()
            failed_logins = 0
            login_time = ist_now()
            session_day[0] = login_time.date()
            if (login_time.hour, login_time.minute) >= (8, 45):
                morning_refresh_day[0] = login_time.date()
        except Exception as e:
            failed_logins += 1
            reason = str(e) or e.__class__.__name__
            print("Angel login failed", failed_logins, "of 3:", reason)
            set_status("login_error", f"Angel login failed ({failed_logins}/3): {reason}")
            if failed_logins >= 3:
                set_status("login_blocked", f"Login stopped after 3 failures. Check API key, client code, PIN and TOTP secret. Last error: {reason}")
                print("runner: stopping after 3 consecutive Angel login failures")
                break
            time.sleep(10 * failed_logins)
            continue

        try:
            if not tokens:
                load_tokens()
            set_status("loading", "Angel login successful. Loading symbols and candle history…")
            load_candles(api)
            ready.set()
            set_status("ready", "Connected to Angel One market data")
            last_tick[0] = time.time()
            stream(jwt, feed)
            set_status("reconnecting", "Market-data connection closed. Reconnecting…")
        except Exception as e:
            print("runner error", e)
            set_status("reconnecting", f"Feed/server error: {e}")
        delay = 10 if time.time() - t0 > 120 else min(delay * 2, 300)
        time.sleep(delay)


@asynccontextmanager
async def lifespan(app):
    global loop
    loop = asyncio.get_running_loop()
    threading.Thread(target=runner, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
HERE = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.get("/healthz")
def healthz():
    return {"ok": True, "ready": ready.is_set()}


@app.get("/api/status")
def api_status(k: str = ""):
    check(k)
    return {"ready": ready.is_set(), **status}


@app.get("/")
def index(k: str = ""):
    check(k)
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/candles")
def candles(k: str = ""):
    check(k)
    if not ready.is_set():
        raise HTTPException(503, "loading")
    return {"pages": PAGES, "labels": LABELS, "candles": cache, "prev": {s: (pc.get(s) or prev_close(cache.get(s, []))) for s in SYMS}}


@app.get("/api/find")
def find(q: str = "", k: str = ""):
    """Search Angel symbols, e.g. /api/find?q=GUJ&k=YOURKEY"""
    check(k)
    q = q.strip().upper()
    return {"matches": [x for x in all_eq if q and q in x][:60]}


@app.websocket("/ws")
async def ws(w: WebSocket):
    if KEY and w.query_params.get("k", "") != KEY:
        await w.close(); return
    await w.accept(); clients.add(w)
    try:
        while True:
            await w.receive_text()
    except Exception:
        clients.discard(w)
