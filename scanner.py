import os, pyotp, requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from SmartApi import SmartConnect

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WATCHLIST = [
    {"symbol": "VOLTAS", "token": "3721"},
    {"symbol": "JINDALSTEL", "token": "1317"},
    {"symbol": "HAL", "token": "2306"},
    {"symbol": "TATAMOTORS", "token": "3456"},
]

def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, length=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/length, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/length, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def vwap(df):
    df['Typical'] = (df['High'] + df['Low'] + df['Close']) / 3
    df['DateOnly'] = pd.to_datetime(df['Datetime']).dt.date
    df['CumVol'] = df.groupby('DateOnly')['Volume'].cumsum()
    df['CumTypVol'] = (df['Typical'] * df['Volume']).groupby(df['DateOnly']).cumsum()
    return df['CumTypVol'] / df['CumVol']

def supertrend_dir(df, length=10, mult=2):
    hl2 = (df['High'] + df['Low']) / 2
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift()).abs()
    tr3 = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=length, adjust=False).mean()
    upper = hl2 + (mult * atr)
    lower = hl2 - (mult * atr)
    dirs = [1] * len(df)
    for i in range(1, len(df)):
        if df['Close'].iloc[i] <= lower.iloc[i-1]:
            dirs[i] = -1
        elif df['Close'].iloc[i] >= upper.iloc[i-1]:
            dirs[i] = 1
        else:
            dirs[i] = dirs[i-1]
    return dirs

def login_angel_one():
    try:
        conn = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = conn.generateSession(CLIENT_CODE, PASSWORD, totp)
        if data['status']:
            print("Angel Login Success")
            return conn
        print(data['message'])
        return None
    except Exception as e:
        print(f"Login Error {e}")
        return None

def fetch_data(conn, token):
    to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d 09:15")
    params = {}
    params["exchange"] = "NSE"
    params["symboltoken"] = token
    params["interval"] = "FIVE_MINUTE"
    params["fromdate"] = from_date
    params["todate"] = to_date
    resp = conn.getCandleData(params)
    if resp['status'] and resp['data']:
        df = pd.DataFrame(resp['data'])
        df.columns = ['Datetime','Open','High','Low','Close','Volume']
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        return df
    return None

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except: pass

def scan_stocks():
    obj = login_angel_one()
    if not obj:
        send_telegram("Angel Login Fail")
        return
    print(f"Scan start {datetime.now()}")
    found = []
    for stock in WATCHLIST:
        df = fetch_data(obj, stock["token"])
        if df is None or len(df) < 30:
            continue
        df['EMA_9'] = ema(df['Close'], 9)
        df['EMA_21'] = ema(df['Close'], 21)
        df['RSI'] = rsi(df['Close'], 14)
        df['VWAP'] = vwap(df)
        df['ST_Dir'] = supertrend_dir(df)

        today = datetime.now().strftime("%Y-%m-%d")
        df_today = df[df['Datetime'].dt.strftime('%Y-%m-%d') == today].reset_index(drop=True)
        if len(df_today) < 3:
            continue
        third = df_today.iloc[2]
        prev = df_today.iloc[0:2]
        df_prev = df[df['Datetime'].dt.strftime('%Y-%m-%d') < today]
        if df_prev.empty:
            continue
        pdh = df_prev['High'].max()
        idx = df[df['Datetime'] == third['Datetime']].index[0]
        curr = df.iloc[idx]

        cond1 = abs(curr['Open'] - curr['Low']) < (curr['Close'] * 0.0005)
        cond2 = curr['Close'] > pdh
        cond3 = curr['Volume'] > prev['Volume'].max()
        cond4 = (curr['EMA_9'] > curr['EMA_21']) and (curr['Close'] > curr['EMA_9'])
        cond5 = curr['Close'] > curr['VWAP']
        cond6 = curr['ST_Dir'] == 1
        cond7 = 55 <= curr['RSI'] <= 65

        if cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7:
            msg = f"STRONG BUY {stock['symbol']} Price {curr['Close']} SL {curr['Low']}"
            found.append(msg)
            print(msg)

    if found:
        final = "Gold Signals:\n" + "\n".join(found)
    else:
        final = f"Today {today} - No Gold Signal"
    print(final)
    send_telegram(final)
    obj.terminateSession(CLIENT_CODE)  
