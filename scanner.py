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

def get_rsi(s, p=14):
    d=s.diff()
    g=(d.where(d>0,0)).rolling(p).mean()
    l=(-d.where(d<0,0)).rolling(p).mean()
    rs=g/l
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
        from_d=(datetime.now()-timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d}
        resp=obj.getCandleData(params)
        if not resp or not resp.get('data') or len(resp['data'])<20: return None
        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        df['c']=pd.to_numeric(df['c']); df['h']=pd.to_numeric(df['h']); df['l']=pd.to_numeric(df['l']); df['v']=pd.to_numeric(df['v']); df['o']=pd.to_numeric(df['o'])
        df['dt']=pd.to_datetime(df['dt'])
        df['ema20']=df['c'].ewm(span=20).mean()
        df['rsi']=get_rsi(df['c'])

        today=datetime.now().strftime("%Y-%m-%d")
        dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today]
        if len(dft)<3: return None

        last=dft.iloc[-1]
        first_open=dft.iloc[0]['o']
        pdh=df[df['dt'].dt.strftime("%Y-%m-%d")<today]['h'].max()
        orb_high=dft.iloc[:3]['h'].max() if len(dft)>=3 else last['h']

        pct = ((last['c']-first_open)/first_open*100)
        is_breakout = last['c'] > orb_high and last['c'] > pdh*0.99 and last['rsi']>58 and last['v']>15000

        return {"sym":sym,"c":last['c'],"pct":pct,"rsi":last['rsi'],"vol":last['v'],"orb":orb_high,"pdh":pdh,"time":last['dt'].strftime("%H:%M"),"breakout":is_breakout}
    except: return None

def main():
    load_tokens(); obj=login()
    if not obj:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":"Angel Login Fail"})
        return
    all_data=[]
    for s in FULL_STOCKS[:345]:
        r=scan_one(obj,s)
        if r: all_data.append(r)

    breakouts=[x for x in all_data if x['breakout']]

    if breakouts:
        breakouts=sorted(breakouts,key=lambda x:x['pct'],reverse=True)[:10]
        msg="🔥 LIVE BREAKOUTS (ORB+PDH)\n\n"
        for b in breakouts:
            msg+=f"{b['sym']} @ {b['c']:.1f} (+{b['pct']:.1f}%) RSI {b['rsi']:.0f} Vol {int(b['vol'])}\n"
    else:
        # NO SIGNAL न देता TOP 5 GAINERS दे
        top=sorted(all_data,key=lambda x:x['pct'],reverse=True)[:5]
        msg=f"⚡ TOP 5 TODAY MOVERS {datetime.now().strftime('%H:%M')}\n(ORB Break नाही, पण हे Strong आहेत)\n\n"
        for t in top:
            msg+=f"{t['sym']} @ {t['c']:.1f} (+{t['pct']:.1f}%) RSI {t['rsi']:.0f}\nORB {t['orb']:.1f} PDH {t['pdh']:.1f} Vol {int(t['vol'])}\n\n"

    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":msg})
    print(msg)
    obj.terminateSession(CLIENT_CODE)

if __name__=="__main__": main()
