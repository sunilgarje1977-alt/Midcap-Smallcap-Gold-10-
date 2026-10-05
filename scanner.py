import os, pyotp, requests
import pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Global lock for rate limit
lock = threading.Lock()
found_signals = []

def ema(s, l): return s.ewm(span=l, adjust=False).mean()
def rsi(s, l=14):
    d=s.diff(); g=d.where(d>0,0).ewm(alpha=1/l,adjust=False).mean()
    loss=-d.where(d<0,0).ewm(alpha=1/l,adjust=False).mean()
    rs=g/loss; return 100-(100/(1+rs))
def vwap(df):
    df['Typical']=(df['High']+df['Low']+df['Close'])/3
    df['DateOnly']=pd.to_datetime(df['Datetime']).dt.date
    df['CumVol']=df.groupby('DateOnly')['Volume'].cumsum()
    df['CumTypVol']=(df['Typical']*df['Volume']).groupby(df['DateOnly']).cumsum()
    return df['CumTypVol']/df['CumVol']

def login():
    c=SmartConnect(api_key=API_KEY)
    totp=pyotp.TOTP(TOTP_SECRET).now()
    d=c.generateSession(CLIENT_CODE,PASSWORD,totp)
    return c if d['status'] else None

def process_stock(args):
    conn, sym = args
    try:
        # Token
        res=conn.searchScrip("NSE", sym)
        token=None
        if res['status']:
            for s in res['data']:
                if s['tradingsymbol']==sym+"-EQ":
                    token=s['symboltoken']
                    break
        if not token: return None

        # Candle - FAST
        to_date=datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date=(datetime.now()-timedelta(days=3)).strftime("%Y-%m-%d 09:15")
        params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_date,"todate":to_date}
        resp=conn.getCandleData(params)

        if not resp or not resp.get('status') or not resp.get('data'):
            return None

        df=pd.DataFrame(resp['data'])
        df.columns=['Datetime','Open','High','Low','Close','Volume']
        df['Datetime']=pd.to_datetime(df['Datetime'])
        if len(df)<30: return None

        df['EMA_9']=ema(df['Close'],9)
        df['EMA_21']=ema(df['Close'],21)
        df['RSI']=rsi(df['Close'],14)
        df['VWAP']=vwap(df)

        today=datetime.now().strftime("%Y-%m-%d")
        df_today=df[df['Datetime'].dt.strftime('%Y-%m-%d')==today]
        if len(df_today)<3: return None

        third=df_today.iloc[2]
        prev=df_today.iloc[0:2]
        df_prev=df[df['Datetime'].dt.strftime('%Y-%m-%d')<today]
        if df_prev.empty: return None
        pdh=df_prev['High'].max()

        curr = df[df['Datetime']==third['Datetime']].iloc[0] if not df[df['Datetime']==third['Datetime']].empty else df.iloc[-1]

        # GOLD LOGIC - LOOSE for FAST moment capture
        cond1 = curr['Close'] > curr['Open'] * 1.001 # Bullish
        cond2 = curr['Close'] > pdh
        cond3 = curr['Volume'] > prev['Volume'].mean()
        cond4 = curr['EMA_9'] > curr['EMA_21']
        cond5 = curr['Close'] > curr['VWAP']
        cond6 = 48 <= curr['RSI'] <= 72

        if cond1 and cond2 and cond3 and cond4 and cond5 and cond6:
            return f"⚡ FAST BUY {sym} @ {curr['Close']:.1f} | PDH {pdh:.1f} RSI {curr['RSI']:.0f} Vol {int(curr['Volume']/1000)}k {third['Datetime'].strftime('%H:%M')}"
        return None
    except:
        return None

def send_tg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":msg},timeout=10)
    except: pass

def scan():
    obj=login()
    if not obj:
        send_tg("Login Fail")
        return

    print(f"FAST Scan start {datetime.now()} - {len(FULL_STOCKS)} stocks")

    # 20 threads = 400 stocks in ~60 sec
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(process_stock, (obj, sym)): sym for sym in FULL_STOCKS}
        for future in as_completed(futures):
            result = future.result()
            if result:
                found_signals.append(result)
                print(result)

    if found_signals:
        final = f"⚡ FAST Gold ({len(FULL_STOCKS)} Scanned {datetime.now().strftime('%H:%M:%S')}):\n\n" + "\n\n".join(found_signals[:20])
    else:
        final = f"On Time Scan {datetime.now().strftime('%H:%M')} - No Signal ({len(FULL_STOCKS)} scanned in 60s)"

    print(final)
    send_tg(final)
    obj.terminateSession(CLIENT_CODE)

if __name__=="__main__":
    scan()
