import os, pytz, time, requests, io
import pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import pyotp
from concurrent.futures import ThreadPoolExecutor

IST = pytz.timezone("Asia/Kolkata")

def get_smallcap_400():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_niftysmallcap500list.csv"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        df = pd.read_csv(io.StringIO(r.text))
        symbols = [s.strip().upper() for s in df['Symbol'].dropna().tolist()]
        return symbols[:400]
    except:
        from smallcap_stocks import FULL_STOCKS
        return FULL_STOCKS[:400]

def get_rsi(s, p=14):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    rs=g.ewm(alpha=1/p).mean()/l.ewm(alpha=1/p).mean()
    return 100-(100/(1+rs))

def scan_one(args):
    obj, sym, token_map = args
    try:
        token=token_map.get(sym)
        if not token: return None
        to_d=datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d=(datetime.now(IST)-timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        resp=obj.getCandleData({"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d})
        if not resp or not resp.get('data') or len(resp['data'])<25: return None
        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']: df[c]=pd.to_numeric(df[c],errors='coerce')
        df['dt']=pd.to_datetime(df['dt'])
        df['rsi']=get_rsi(df['c'])
        df['ema20']=df['c'].ewm(span=20).mean()
        today=datetime.now(IST).strftime("%Y-%m-%d")
        dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today].reset_index(drop=True)
        if len(dft)<4: return None
        orb_high=dft.iloc[:3]['h'].max()
        orb_low=dft.iloc[:3]['l'].min()
        orb_vol=dft.iloc[:3]['v'].mean()
        first_open=dft.iloc[0]['o']
        prev_12_high=dft.iloc[max(0,len(dft)-12):len(dft)-1]['h'].max() if len(dft)>1 else 0
        prev_12_vol=dft.iloc[max(0,len(dft)-12):len(dft)-1]['v'].mean()+1 if len(dft)>1 else 1
        ltp_resp=obj.ltpData("NSE",sym+"-EQ",token)
        ltp=ltp_resp['data']['ltp'] if ltp_resp and ltp_resp.get('data') else dft.iloc[-1]['c']
        curr=dft.iloc[-1]
        pct=(ltp-first_open)/first_open*100

        # LOOSE FILTER FOR MONDAY
        if pct>9 or pct<0.05: return None
        if ltp<curr['ema20']: return None
        if curr['v']<2000: return None

        is_orb=ltp>orb_high and 45<=curr['rsi']<=90 and curr['v']>orb_vol*1.05
        is_day=ltp>=prev_12_high*0.999 and 45<=curr['rsi']<=90 and curr['v']>prev_12_vol*1.1

        if is_orb or is_day:
            entry=round(ltp+0.1,2)
            day_low=dft['l'].min()
            sl=round(min(orb_low,curr['ema20']*0.998),2) if is_orb else round(min(day_low*1.001,ltp*0.985),2)
            risk=entry-sl
            if risk<=0: return None
            if risk/entry>0.03: sl=round(entry*0.97,2); risk=entry-sl
            t1=round(entry+risk*1.8,2)
            t2=round(entry+risk*3.0,2)
            trail=round(entry+risk*0.8,2)
            return {"sym":sym,"c":ltp,"pct":pct,"rsi":curr['rsi'],"vol":curr['v'],"type":f"ORB {orb_high:.1f}" if is_orb else f"DAY {prev_12_high:.1f}","b_time":datetime.now(IST).strftime("%H:%M"),"entry":entry,"sl":sl,"t1":t1,"t2":t2,"trail":trail,"risk_per":round(risk/entry*100,2),"logic":"ORB" if is_orb else "DAY"}
        return None
    except:
        return None

def main():
    obj=SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    totp=pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
    obj.generateSession(os.getenv("ANGEL_CLIENT_ID"),os.getenv("ANGEL_PASSWORD_KEY"),totp)
    url="https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    scrips=requests.get(url).json()
    TOKEN_MAP={s['symbol'].replace('-EQ',''):s['token'] for s in scrips if s['exch_seg']=='NSE' and s['symbol'].endswith('-EQ')}
    stocks=get_smallcap_400()
    print(f"Loaded {len(stocks)} stocks")
    breaks=[]
    with ThreadPoolExecutor(max_workers=12) as exe:
        results=list(exe.map(scan_one, [(obj,s,TOKEN_MAP) for s in stocks]))
    breaks=[r for r in results if r]

    token=os.getenv("TELEGRAM_BOT_TOKEN")
    chat=os.getenv("TELEGRAM_CHAT_ID")

    if breaks:
        breaks=sorted(breaks,key=lambda x:x['pct'],reverse=True)[:10]
        now=datetime.now(IST).strftime("%d-%b %H:%M")
        msg=f"🔥 SMALLCAP 400 BREAKOUT {now}\n400 Stocks | LOOSE FILTER\n\n"
        for b in breaks:
            msg+=f"🚀 {b['sym']} @ {b['c']:.1f} (+{b['pct']:.1f}%) [{b['logic']} {b['type']}]\n📌 Entry: {b['entry']} | RSI {b['rsi']:.0f}\n🛡️ SL: {b['sl']} ({b['risk_per']}%) Vol {int(b['vol']/1000)}k\n🎯 T1: {b['t1']} | T2: {b['t2']}\n📈 Trail: {b['trail']} @ {b['b_time']}\n\n"
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage",params={"chat_id":chat,"text":msg})
        print(msg)
    else:
        # TELEGRAM ला पण कळवेल की Bot चाललाय
        now=datetime.now(IST).strftime("%d-%b %H:%M")
        msg=f"ℹ️ Smallcap 400 Scan {now}\nNo Breakout found in 400 stocks (Loose filter). Bot is LIVE ✅"
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage",params={"chat_id":chat,"text":msg})
        print("No Breakout - Sent info to Telegram")

if __name__=="__main__":
    main()
