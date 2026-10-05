import os, requests, pyotp, pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS
import pytz

IST = pytz.timezone('Asia/Kolkata')

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
    d=s.diff(); g=(d.where(d>0,0)).rolling(p).mean(); l=(-d.where(d<0,0)).rolling(p).mean(); rs=g/l; return 100-(100/(1+rs))

def login():
    obj=SmartConnect(api_key=API_KEY); totp=pyotp.TOTP(TOTP_SECRET).now(); sess=obj.generateSession(CLIENT_CODE,PASSWORD,totp); return obj if sess['status'] else None

def scan_one(obj, sym):
    try:
        token=TOKEN_MAP.get(sym)
        if not token: return None
        to_d=datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d=(datetime.now(IST)-timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d}
        resp=obj.getCandleData(params)
        if not resp or not resp.get('data') or len(resp['data'])<10: return None
        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        for col in ['o','h','l','c','v']: df[col]=pd.to_numeric(df[col])
        df['dt']=pd.to_datetime(df['dt']); df['ema20']=df['c'].ewm(span=20).mean(); df['rsi']=get_rsi(df['c'])
        today=datetime.now(IST).strftime("%Y-%m-%d")
        dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today]
        if len(dft)<2: return None
        last=dft.iloc[-1]; first=dft.iloc[0]
        pct=((last['c']-first['o'])/first['o']*100)
        return {"sym":sym,"c":last['c'],"pct":pct,"rsi":last['rsi'],"vol":last['v'],"time":datetime.now(IST).strftime("%I:%M %p")}
    except: return None

def main():
    load_tokens(); obj=login();
    if not obj: return
    all_data=[]
    for s in FULL_STOCKS[:345]:
        r=scan_one(obj,s)
        if r and r['pct']>0: all_data.append(r)
    if not all_data:
        msg=f"Market Closed Today (Sunday) - {datetime.now(IST).strftime('%d-%m %I:%M %p')} IST - No Live Data"
    else:
        top=sorted(all_data,key=lambda x:x['pct'],reverse=True)[:5]
        msg=f"⚡ TOP 5 MOVERS {top[0]['time']} IST\n\n"
        for t in top:
            msg+=f"{t['sym']} @ {t['c']:.1f} (+{t['pct']:.2f}%) RSI {t['rsi']:.0f} Vol {int(t['vol']/1000)}k\n"
        msg+="\nAuto Scan Every 15 Min"
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":msg})
    obj.terminateSession(CLIENT_CODE)

if __name__=="__main__": main()
