 import os, pyotp, requests, time
import pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def ema(s, l):
    return s.ewm(span=l, adjust=False).mean()

def rsi(s, l=14):
    d=s.diff()
    g=d.where(d>0,0).ewm(alpha=1/l,adjust=False).mean()
    loss=-d.where(d<0,0).ewm(alpha=1/l,adjust=False).mean()
    rs=g/loss
    return 100-(100/(1+rs))

def vwap(df):
    df['Typical']=(df['High']+df['Low']+df['Close'])/3
    df['DateOnly']=pd.to_datetime(df['Datetime']).dt.date
    df['CumVol']=df.groupby('DateOnly')['Volume'].cumsum()
    df['CumTypVol']=(df['Typical']*df['Volume']).groupby(df['DateOnly']).cumsum()
    return df['CumTypVol']/df['CumVol']

def supertrend_dir(df,l=10,m=2):
    hl2=(df['High']+df['Low'])/2
    tr1=df['High']-df['Low']
    tr2=(df['High']-df['Close'].shift()).abs()
    tr3=(df['Low']-df['Close'].shift()).abs()
    tr=pd.concat([tr1,tr2,tr3],axis=1).max(axis=1)
    atr=tr.ewm(span=l,adjust=False).mean()
    upper=hl2+(m*atr)
    lower=hl2-(m*atr)
    dirs=[1]*len(df)
    for i in range(1,len(df)):
        if df['Close'].iloc[i]<=lower.iloc[i-1]: dirs[i]=-1
        elif df['Close'].iloc[i]>=upper.iloc[i-1]: dirs[i]=1
        else: dirs[i]=dirs[i-1]
    return dirs

def login():
    c=SmartConnect(api_key=API_KEY)
    totp=pyotp.TOTP(TOTP_SECRET).now()
    d=c.generateSession(CLIENT_CODE,PASSWORD,totp)
    return c if d['status'] else None

def get_token(conn, symbol):
    try:
        res=conn.searchScrip("NSE", symbol)
        if res['status']:
            for s in res['data']:
                if s['tradingsymbol']==symbol+"-EQ":
                    return s['symboltoken']
        return None
    except:
        return None

def fetch_data(conn, token):
    to_date=datetime.now().strftime("%Y-%m-%d %H:%M")
    from_date=(datetime.now()-timedelta(days=5)).strftime("%Y-%m-%d 09:15")
    params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_date,"todate":to_date}
    for attempt in range(4):
        try:
            resp=conn.getCandleData(params)
            if resp and resp.get('status') and resp.get('data'):
                df=pd.DataFrame(resp['data'])
                df.columns=['Datetime','Open','High','Low','Close','Volume']
                df['Datetime']=pd.to_datetime(df['Datetime'])
                return df
            if 'exceeding' in str(resp) or 'Access denied' in str(resp):
                time.sleep(3+attempt)
                continue
            return None
        except Exception as e:
            if 'exceeding' in str(e) or 'Access denied' in str(e):
                time.sleep(2*(attempt+1))
                continue
            return None
    return None

def send_tg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":msg},timeout=10)
    except:
        pass

def scan():
    obj=login()
    if not obj:
        send_tg("Angel Login Fail")
        return

    print(f"Scan start {datetime.now()} - {len(FULL_STOCKS)} stocks")
    found=[]

    for sym in FULL_STOCKS:
        token=get_token(obj, sym)
        if not token:
            time.sleep(1.2)
            continue

        df=fetch_data(obj, token)
        if df is None or len(df)<30:
            time.sleep(1.2)
            continue

        df['EMA_9']=ema(df['Close'],9)
        df['EMA_21']=ema(df['Close'],21)
        df['RSI']=rsi(df['Close'],14)
        df['VWAP']=vwap(df)
        df['ST_Dir']=supertrend_dir(df)

        today=datetime.now().strftime("%Y-%m-%d")
        df_today=df[df['Datetime'].dt.strftime('%Y-%m-%d')==today].reset_index(drop=True)
        if len(df_today)<3:
            time.sleep(1.2)
            continue

        third=df_today.iloc[2]
        prev=df_today.iloc[0:2]
        df_prev=df[df['Datetime'].dt.strftime('%Y-%m-%d')<today]
        if df_prev.empty:
            time.sleep(1.2)
            continue

        pdh=df_prev['High'].max()
        mt=df[df['Datetime']==third['Datetime']]
        if mt.empty:
            time.sleep(1.2)
            continue
        curr=df.iloc[mt.index[0]]

        cond1 = abs(curr['Open'] - curr['Low']) < (curr['Close'] * 0.002)
        cond2 = curr['Close'] > pdh
        cond3 = curr['Volume'] > prev['Volume'].max()*0.8
        cond4 = (curr['EMA_9'] > curr['EMA_21']) and (curr['Close'] > curr['EMA_9'])
        cond5 = curr['Close'] > curr['VWAP']
        cond6 = curr['ST_Dir'] == 1
        cond7 = 50 <= curr['RSI'] <= 70

        if cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7:
            msg=f"🔥 5 MIN LIVE BUY {sym} @ {curr['Close']}\n> PDH {pdh:.1f} RSI {curr['RSI']:.1f} Time {third['Datetime'].strftime('%H:%M')}"
            found.append(msg)

        time.sleep(1.2)

    final="🔥 Gold Signals (Mid+Small 400):\n" + "\n\n".join(found) if found else f"Today {datetime.now().strftime('%Y-%m-%d')} - No Gold Signal (Scanned {len(FULL_STOCKS)} stocks)"
    print(final)
    send_tg(final)
    obj.terminateSession(CLIENT_CODE)

if __name__=="__main__":
    scan()
