# Fire TV Stock Charts (Angel One live data)

3 screens x 4 live candlestick charts. Remote LEFT/RIGHT (or UP/DOWN, rewind/fast-forward) switches screens.
MENU button (three lines) reloads. View-only: this code never places orders.

Charts = TradingView's open-source Lightweight Charts. Data = your Angel One SmartAPI (real-time).

## One-time setup (about 1 evening, do it outside market hours)

### 1. Angel One SmartAPI
- smartapi.angelone.in -> log in -> create an app. Tick Market Feed + Historical Data if the form asks. Copy the **API key**.
- Enable TOTP on the SmartAPI site and copy the **TOTP secret text** shown under the QR code (not the 6-digit code).
- You will use: API key, Client code (login ID), 4-digit PIN, TOTP secret.

### 2. GitHub
- New repository (public is fine: no secrets are stored in it). Upload everything in this folder.
- The hidden folder `.github/workflows/build.yml` may be skipped by drag-and-drop. If so: Add file -> Create new file,
  name it `.github/workflows/build.yml`, paste the file contents.

### 3. Render (server)
- render.com -> New -> Blueprint -> pick the repo. Fill in:
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET, VIEW_KEY (invent a long random password).
- When deployed, open `https://YOURNAME.onrender.com/?k=YOUR_VIEW_KEY` on a laptop/phone. Wait up to a minute: charts appear.

### 4. Build the Fire TV app
- GitHub repo -> Settings -> Secrets and variables -> Actions -> New secret:
  name `APP_URL`, value `https://YOURNAME.onrender.com/?k=YOUR_VIEW_KEY`
- Actions tab -> build-apk -> Run workflow. After ~3 minutes the Releases page has `stockcharts.apk`.

### 5. Install on the Fire TV
- Install **Downloader** (Fire TV app store). Settings -> My Fire TV -> Developer Options -> Install unknown apps -> Downloader ON.
- Open Downloader, enter: `https://github.com/YOUR_USER/YOUR_REPO/releases/latest/download/stockcharts.apk` -> Install.
- Home -> Your Apps & Channels -> find Stock Charts -> Options (three lines) -> Move to front.

## Everyday changes (no rebuild needed)
Render -> your service -> Environment:
- `PAGES` = `DIVISLAB,RELIANCE,HDFCBANK,TCS;INFY,ICICIBANK,SBIN,ITC;NIFTY,BANKNIFTY,LT,BAJFINANCE`
  (`;` between screens, `,` between stocks, NSE symbols; NIFTY and BANKNIFTY work too)
- `INTERVAL` = ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE (default), TEN_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR

## Good to know
- Render's free plan sleeps after ~15 min idle. The first open can take ~1 min; the app keeps retrying by itself.
  Free fix: a free uptime pinger (e.g. UptimeRobot) on `/healthz` during market hours. Or Render's paid plan.
- History = Angel's exchange candles. The live candle is built from LTP ticks, so its high/low can differ slightly from
  the official candle; a server restart reloads official history.
- If the feed goes silent for 3 minutes in market hours, the server reconnects and re-logs in by itself.
- Anyone with the APK link plus the key can view your charts (not trade). Keep VIEW_KEY private;
  to rotate: change it on Render and in the APP_URL secret, then re-run the build.
- If Angel login fails, check Render -> Logs. Common causes: wrong TOTP secret, wrong PIN, API app not approved.
