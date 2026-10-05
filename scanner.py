import os, requests, pyotp, pandas as pd, time
from datetime import datetime, timedelta
import pytz
from SmartApi import SmartConnect
from stocks_full import FULL_STOCKS

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
    print(f"Loaded {len(TOKEN_MAP)}")

def get_rsi(s,p=14):
    d=s.diff(); g=d.where(d>0,0).rolling(p).mean(); l=-d.where(d<0,0).rolling(p).mean()
    return 100-(100/(1+g/(l+1e-9)))

def login():
    obj=SmartConnect(api_key=API_KEY)
    sess=obj.generateSession(CLIENT_CODE,PASSWORD,pyotp.TOTP(TOTP_SECRET).now())
    return obj if sess['status'] else None

def scan_one(obj,sym):
    try:
        token=TOKEN_MAP.get(sym)
        if not token: return None
        to_d=datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d=(datetime.now(IST)-timedelta(days=4)).strftime("%Y-%m-%d %H:%M")
        resp=obj.getCandleData({"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d})
        if not resp or not resp.get('data') or len(resp['data'])<25: return None

        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']: df[c]=pd.to_numeric(df[c],errors='coerce')
        df['dt']=pd.to_datetime(df['dt']); df['rsi']=get_rsi(df['c']); df['ema20']=df['c'].ewm(span=20).mean()
        today=datetime.now(IST).strftime("%Y-%m-%d"); dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today].reset_index(drop=True)
        if len(dft)<4: return None

        orb_high=dft.iloc[:3]['h'].max(); orb_vol=dft.iloc[:3]['v'].mean(); first_open=dft.iloc[0]['o']

        # 9:30 ते 3:00 पर्यंत प्रत्येक Candle - Early पकड
        for i in range(3, len(dft)):
            curr=dft.iloc[i]
            if curr['v']<8000: continue
            pct=(curr['c']-first_open)/first_open*100
            if pct>4.5 or pct<0.15: continue # 8% Late नको

            prev_12_high=dft.iloc[max(0,i-12):i]['h'].max()
            prev_12_vol=dft.iloc[max(0,i-12):i]['v'].mean()+1

            is_orb = curr['c']>orb_high and 58<=curr['rsi']<=78 and curr['c']>curr['ema20'] and curr['v']>orb_vol*1.3
            is_day = curr['c']>prev_12_high*1.001 and 62<=curr['rsi']<=82 and curr['v']>prev_12_vol*1.7 and curr['v']>12000

            if is_orb or is_day:
                return {"sym":sym,"c":curr['c'],"pct":pct,"rsi":curr['rsi'],"vol":curr['v'],"type":f"ORB {orb_high:.1f}" if is_orb else f"1H {prev_12_high:.1f}","b_time":curr['dt'].strftime("%H:%M"),"logic": "ORB" if is_orb else "DAY","is_break":True}
        return None
    except: return None

def main():
    load_tokens(); obj=login()
    if not obj: return
    breaks=[]
    for s in FULL_STOCKS[:345]:
        r=scan_one(obj,s)
        if r: breaks.append(r)
        time.sleep(0.12)

    now=datetime.now(IST).strftime("%I:%M %p IST")
    if breaks:
        breaks=sorted(breaks,key=lambda x:x['b_time'],reverse=True)[:10]
        msg=f"🔥 BREAKOUT {now}\n9:30 to 3:00 Active | {len(breaks)} Found\n\n"
        for b in breaks:
            msg+=f"🚀 {b['sym']} @ {b['c']:.1f} (+{b['pct']:.1f}%)\n{b['type']} at {b['b_time']} RSI {b['rsi']:.0f} Vol {int(b['vol']/1000)}k [{b['logic']}]\n\n"
    else:
        msg=f"⏳ {now}\nNo Early Breakout 9:30-3:00\nScanned 345 | Next in 5 Min"

    print(msg)
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":msg},timeout=10)
    except Exception as e:
        print(e)
    try: obj.terminateSession(CLIENT_CODE)
    except: pass

if __name__=="__main__": main()
