import os, requests, pyotp, pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS

API_KEY=os.getenv("ANGEL_API_KEY")
CLIENT_CODE=os.getenv("ANGEL_CLIENT_ID")
PASSWORD=os.getenv("ANGEL_PASSWORD_KEY")
TOTP_SECRET=os.getenv("ANGEL_TOTP_SECRET")
TG_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT=os.getenv("TELEGRAM_CHAT_ID")

TOKEN_MAP={}
def load_tokens():
    global TOKEN_MAP
    url="https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    data=requests.get(url,timeout=30).json()
    TOKEN_MAP={d['symbol'].replace('-EQ',''):d['token'] for d in data if d['exch_seg']=='NSE' and d['symbol'].endswith('-EQ')}
    print(f"Loaded {len(TOKEN_MAP)}")

def get_rsi(series, period=14):
    delta=series.diff()
    gain=(delta.where(delta>0,0)).rolling(window=period).mean()
    loss=(-delta.where(delta<0,0)).rolling(window=period).mean()
    rs=gain/loss
    return 100-(100/(1+rs))

def login():
    obj=SmartConnect(api_key=API_KEY)
    totp=pyotp.TOTP(TOTP_SECRET).now()
    sess=obj.generateSession(CLIENT_CODE,PASSWORD,totp)
    return obj if sess['status'] else None

def scan_one(obj, sym):
    try:
        token=TOKEN_MAP.get(sym)
        if not token: return None
        to_d=datetime.now().strftime("%Y-%m-%d %H:%M")
        from_d=(datetime.now()-timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
        params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d}
        resp=obj.getCandleData(params)
        if not resp or not resp.get('data') or len(resp['data'])<50:
            return None
        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        df['c']=pd.to_numeric(df['c'])
        df['h']=pd.to_numeric(df['h'])
        df['v']=pd.to_numeric(df['v'])
        df['dt']=pd.to_datetime(df['dt'])
        
        df['ema20']=df['c'].ewm(span=20).mean()
        df['ema50']=df['c'].ewm(span=50).mean()
        df['rsi']=get_rsi(df['c'])

        today_str=datetime.now().strftime("%Y-%m-%d")
        df_today=df[df['dt'].dt.strftime("%Y-%m-%d")==today_str]
        if df_today.empty: return None
        
        last=df_today.iloc[-1]
        prev_high=df[df['dt'].dt.strftime("%Y-%m-%d") < today_str]['h'].max()
        second_high=df_today['h'].nlargest(2).iloc[-1] if len(df_today)>=2 else prev_high

        cond1 = last['c'] > second_high
        cond2 = last['rsi'] > 58
        cond3 = last['ema20'] > last['ema50']
        cond4 = last['v'] > 25000

        if cond1 and cond2 and cond3 and cond4:
            return f"🔥 5 MIN LIVE BUY\n{sym} @ {last['c']}\n> 2nd High {second_high:.1f}\nRSI {last['rsi']:.1f} EMA {last['ema20']:.1f}>{last['ema50']:.1f}\nVol {int(last['v'])} > 25k\nTime {last['dt'].strftime('%H:%M')}"
    except Exception as e:
        # print(f"{sym} err {e}")
        return None
    return None

def main():
    load_tokens()
    obj=login()
    if not obj:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":"Angel Login Fail"})
        return
    print("Scanning 345...")
    found=[]
    for s in FULL_STOCKS[:345]:
        res=scan_one(obj,s)
        if res:
            found.append(res)
            print(res)
    if found:
        msg="\n\n".join(found[:10])
    else:
        msg=f"Today {datetime.now().strftime('%Y-%m-%d')} - No Gold Signal - Scanned 345 (RSI>58 EMA20>50 Vol>25k)"
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":msg})
    print(msg)
    obj.terminateSession(CLIENT_CODE)

if __name__=="__main__":
    main()
