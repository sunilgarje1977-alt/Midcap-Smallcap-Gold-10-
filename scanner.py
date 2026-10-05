import os, requests, pyotp, concurrent.futures, pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD_KEY")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

TOKEN_MAP = {}

def load_tokens():
    global TOKEN_MAP
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    data = requests.get(url, timeout=30).json()
    TOKEN_MAP = {d['symbol'].replace('-EQ',''): d['token'] for d in data if d['exch_seg']=='NSE' and d['symbol'].endswith('-EQ')}
    print(f"Tokens Loaded {len(TOKEN_MAP)}")

def login():
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    s = obj.generateSession(CLIENT_CODE, PASSWORD, totp)
    if s['status']:
        print("Login OK")
        return obj
    print(s)
    return None

def check_one(args):
    obj, sym = args
    try:
        token = TOKEN_MAP.get(sym)
        if not token: return None
        to_d = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_d = (datetime.now()-timedelta(days=6)).strftime("%Y-%m-%d %H:%M")
        p = {"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d}
        r = obj.getCandleData(p)
        if not r or not r.get('data') or len(r['data']) < 20:
            return None
        df = pd.DataFrame(r['data'], columns=['dt','o','h','l','c','v'])
        df['dt'] = pd.to_datetime(df['dt'])
        today = datetime.now().strftime("%Y-%m-%d")
        df_t = df[df['dt'].dt.strftime('%Y-%m-%d')==today]
        if len(df_t)<1: return None
        curr = df_t.iloc[-1]
        df_prev = df[df['dt'].dt.strftime('%Y-%m-%d') < today]
        if df_prev.empty: return None
        pdh = df_prev['h'].max()
        if curr['c'] > pdh and curr['c'] > curr['o'] and curr['v'] > 5000:
            return f"🚀 BUY {sym} @ {curr['c']} (PDH {pdh:.1f})"
    except:
        return None
    return None

def main():
    load_tokens()
    obj = login()
    if not obj: return
    print(f"Scanning {len(FULL_STOCKS[:200])} fast...")
    found=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        res = ex.map(check_one, [(obj, s) for s in FULL_STOCKS[:200]])
        for r in res:
            if r:
                found.append(r)
                print(r)
    msg = "⚡ Gold PDH Break:\n" + "\n".join(found) if found else "No Signal - 200 Scanned"
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": msg})
    print(msg)
    obj.terminateSession(CLIENT_CODE)

if __name__ == "__main__":
    main()
