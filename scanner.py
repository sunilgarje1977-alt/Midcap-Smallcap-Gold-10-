import os, pyotp, requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from SmartApi import SmartConnect

# Secrets मधून घेणार - इथे काही टाकू नकोस
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
    {"symbol": "BSE", "token": "4170"},
    {"symbol": "KPITTECH", "token": "9719"},
]

# --- Indicator Functions (pandas_ta शिवाय) ---
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, length=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/length, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def vwap(df):
    # Daily VWAP - प्रत्येक दिवसासाठी reset
    df['Typical'] = (df['High'] + df['Low'] + df['Close']) / 3
    df['Date'] = pd.to_datetime(df['Datetime']).dt.date
    df['CumVol'] = df.groupby('Date')['Volume'].cumsum()
    df['CumTypVol'] = (df['Typical'] * df['Volume']).groupby(df['Date']).cumsum()
    return df['CumTypVol'] / df['CumVol']

def supertrend(df, length=10, multiplier=2):
    hl2 = (df['High'] + df['Low']) / 2
    atr = (df['High'] - df['Low']).ewm(span=length, adjust=False).mean() # Simplified ATR
    # True ATR for better accuracy
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift()).abs()
    tr3 = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=length, adjust=False).mean()

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    st_dir = [1] * len(df)
    for i in range(1, len(df)):
        if df['Close'].iloc[i] <= lower_band.iloc[i-1]:
            st_dir[i] = -1
        elif df['Close'].iloc[i] >= upper_band.iloc[i-1]:
            st_dir[i] = 1
        else:
            st_dir[i] = st_dir[i-1]
    return st_dir

def login_angel_one():
    try:
        smart_conn = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = smart_conn.generateSession(CLIENT_CODE, PASSWORD, totp)
        if data['status']:
            print("✅ Angel One लॉग इन यशस्वी!")
            return smart_conn
        else:
            print(f"❌ लॉग इन अपयशी: {data['message']}")
            return None
    except Exception as e:
        print(f"❌ Login Error: {e}")
        return None

def fetch_angel_data(smart_conn, token, symbol):
    try:
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d 09:15")
        historic_param = {
            "exchange": "NSE", "symboltoken": token,
            "interval": "FIVE_MINUTE", "fromdate": from_date, "tod
