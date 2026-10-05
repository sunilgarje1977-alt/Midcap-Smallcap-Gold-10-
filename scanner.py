import os, requests, pyotp, pandas as pd
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

def get_rsi(s, p=14):
    d=s.diff()
    g=(d.where(d>0,0)).rolling(p).mean()
    l=(-d.where(d<0,0)).rolling(p).mean()
    return 100-(100/(1+g/(l+1e-9)))

def login():
    obj=SmartConnect(api_key=API_KEY)
    totp=pyotp.TOTP(TOTP_SECRET).now()
    sess=obj.generateSession(CLIENT_CODE,PASSWORD,totp)
    return obj if sess['status'] else None

def scan_one(obj, sym):
    try:
        token=TOKEN_MAP.get(sym)
        if not token: return None
        to_d=datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d=(datetime.now(IST)-timedelta(days=4)).strftime("%Y-%m-%d %H:%M")
        params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d}
        resp=obj.getCandleData(params)
        if not resp or not resp.get('data') or len(resp['data'])<20: return None

        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']: df[c]=pd.to_numeric(df[c])
        df['dt']=pd.to_datetime(df['dt'])
        df['rsi']=get_rsi(df['c'])
        df['ema20']=df['c'].ewm(span=20).mean()

        today=datetime.now(IST).strftime("%Y-%m-%d")
        dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today].reset_index(drop=True)
        if len(dft)<5: return None

        last=dft.iloc[-1]
        first_open=dft.iloc[0]['o']
        pct=((last['c']-first_open)/first_open*100)

        # ORB
        orb_high=dft.iloc[:3]['h'].max()
        orb_vol=dft.iloc[:3]['v'].mean()

        # Consolidation (last 1 hour = 12 candles)
        last_12_high = dft.iloc[-13:-1]['h'].max() if len(dft)>=13 else orb_high
        last_12_vol = dft.iloc[-13:-1]['v'].mean() if len(dft)>=13 else orb_vol

        # Condition 1: Morning ORB Breakout
        is_orb = last['c'] > orb_high and last['rsi']>60 and last['c']>last['ema20'] and last['v'] > orb_vol*1.2 and last['v']>10000

        # Condition 2: Day Consolidation Breakout (तुझा 12:05 वाला)
        is_day = False
        if len(dft)>=13:
            is_day = last['c'] > last_12_high*1.001 and last['rsi']>65 and last['v'] > last_12_vol*1.8 and last['v']>20000 and last['c']>last['ema20']

        breakout_type = None
        if is_orb: breakout_type = f"ORB Break {orb_high:.1f}"
        elif is_day: breakout_type = f"Day High Break {last_12_high:.1f} (12:05 Setup)"

        return {
            "sym":sym, "c":last['c'], "pct":pct, "rsi":last['rsi'], "vol":last['v'],
            "orb":orb_high, "day_high":last_12_high,
            "type":breakout_type, "is_break": bool(breakout_type),
            "time":last['dt'].strftime("%H:%M")
        }
    except: return None

def main():
    load_tokens()
    obj=login()
    if not obj: return

    all_data=[]
    breakouts=[]
    for s in FULL_STOCKS[:345]:
        r=scan_one(obj,s)
        if r:
            all_data.append(r)
            if r['is_break']: breakouts.append(r)

    now_ist=datetime.now(IST).strftime("%I:%M %p IST")

    if breakouts:
        breakouts=sorted(breakouts,key=lambda x:x['pct'],reverse=True)[:10]
        msg=f"🔥 BREAKOUTS {now_ist} - {len(breakouts)} Found\n(9:15 to 3:00 Logic)\n\n"
        for b in breakouts:
            msg+=f"🚀 {b['sym']} @ {b['c']:.1f} (+{b['pct']:.1f}%)\n{b['type']} | RSI {b['rsi']:.0f} Vol {int(b['vol']/1000)}k {b['time']}\n\n"
    else:
        top=sorted([x for x in all_data if x['vol']>10000],key=lambda x:x['pct'],reverse=True)[:5]
        if not top: top=sorted(all_data,key=lambda x:x['pct'],reverse=True)[:5]
        msg=f"⚡ TOP 5 MOVERS {now_ist}\nNo ORB/Day Break in last 15m\n\n"
        for t in top:
            msg+=f"{t['sym']} @ {t['c']:.1f} (+{t['pct']:.2f}%) RSI {t['rsi']:.0f} Vol {int(t['vol']/1000)}k\n"

    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",json={"chat_id":TG_CHAT,"text":msg})
    print(msg)
    obj.terminateSession(CLIENT_CODE)

if __name__=="__main__": main()
