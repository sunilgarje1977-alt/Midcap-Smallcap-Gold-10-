import os, time, requests, pandas as pd, pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS

# तुझ्या Secrets नुसार - 100% Correct
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD_KEY")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def login():
    c=SmartConnect(api_key=API_KEY)
    totp=pyotp.TOTP(TOTP_SECRET).now()
    d=c.generateSession(CLIENT_CODE,PASSWORD,totp)
    if d['status']:
        print("Angel Login Success")
        return c
    else:
        print(f"Login Fail {d}")
        return None

def send_tg(msg):
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data={"chat_id":TELEGRAM_CHAT_ID,"text":msg}
        requests.post(url,data=data,timeout=10)
    except: pass

def scan():
    obj=login()
    if not obj:
        send_tg("❌ Angel Login Fail - Secret Check Kara")
        return
    print(f"Scan Start {datetime.now()} Total {len(FULL_STOCKS)}")
    found=[]
    for sym in FULL_STOCKS[:300]: # Fast साठी 300 - Ontime येईल
        try:
            r=obj.searchScrip("NSE", sym)
            token=None
            if r['status']:
                for s in r['data']:
                    if s['tradingsymbol']==sym+"-EQ":
                        token=s['symboltoken']; break
            if not token:
                time.sleep(0.3); continue

            to_date=datetime.now().strftime("%Y-%m-%d %H:%M")
            from_date=(datetime.now()-timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
            params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_date,"todate":to_date}
            resp=obj.getCandleData(params)
            if not resp or not resp.get('data'):
                time.sleep(0.3); continue

            df=pd.DataFrame(resp['data'])
            df.columns=['Datetime','Open','High','Low','Close','Volume']
            df['Datetime']=pd.to_datetime(df['Datetime'])
            if len(df)<20:
                time.sleep(0.3); continue

            today=datetime.now().strftime("%Y-%m-%d")
            df_today=df[df['Datetime'].dt.strftime('%Y-%m-%d')==today]
            if len(df_today)<2:
                time.sleep(0.3); continue

            curr=df_today.iloc[-1]
            df_prev=df[df['Datetime'].dt.strftime('%Y-%m-%d')<today]
            if df_prev.empty:
                time.sleep(0.3); continue
            pdh=df_prev['High'].max()

            # Gold Logic - PDH Break + Volume
            if curr['Close'] > pdh and curr['Close'] > curr['Open'] and curr['Volume']>10000:
                found.append(f"🚀 BUY {sym} @ {curr['Close']} | PDH {pdh:.1f}")

        except Exception as e:
            print(f"{sym} error {e}")
        time.sleep(0.3)

    msg="⚡ Gold Signals:\n" + "\n".join(found) if found else f"No Signal Today - Scanned {len(FULL_STOCKS[:300])} Stocks"
    print(msg); send_tg(msg)
    obj.terminateSession(CLIENT_CODE)

if __name__ == "__main__":
    scan()
