import os, pytz, requests
import pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import pyotp
from concurrent.futures import ThreadPoolExecutor

IST = pytz.timezone("Asia/Kolkata")

def get_smallcap_400():
    try:
        from smallcap_stocks import FULL_STOCKS
        return FULL_STOCKS[:400]
    except:
        return []

def get_rsi(s, p=14):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    rs=g.ewm(alpha=1/p).mean()/l.ewm(alpha=1/p).mean()
    return 100-(100/(1+rs))

def get_vwap(df):
    tp=(df['h']+df['l']+df['c'])/3
    return (tp*df['v']).cumsum()/df['v'].cumsum()

def scan_one(args):
    obj, sym, token_map = args
    try:
        token=token_map.get(sym)
        if not token: return None
        to_d=datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d=(datetime.now(IST)-timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        resp=obj.getCandleData({"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d})
        if not resp or not resp.get('data') or len(resp['data'])<30: return None
        df=pd.DataFrame(resp['data'],columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']: df[c]=pd.to_numeric(df[c],errors='coerce')
        df['dt']=pd.to_datetime(df['dt'])
        today=datetime.now(IST).strftime("%Y-%m-%d")
        dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today].copy().reset_index(drop=True)
        if len(dft)<10: return None

        dft['ema9']=dft['c'].ewm(span=9).mean()
        dft['ema15']=dft['c'].ewm(span=15).mean()
        dft['vwap']=get_vwap(dft)
        dft['rsi']=get_rsi(dft['c'])

        orb_high=dft.iloc[:3]['h'].max()
        orb_low=dft.iloc[:3]['l'].min()
        curr=dft.iloc[-1]

        ltp_resp=obj.ltpData("NSE",sym+"-EQ",token)
        ltp=ltp_resp['data']['ltp'] if ltp_resp and ltp_resp.get('data') else curr['c']
        first_open=dft.iloc[0]['o']
        pct=(ltp-first_open)/first_open*100

        breakout_time=None
        breakout_price=0
        for i in range(2, len(dft)):
            c=dft.iloc[i]; p=dft.iloc[i-1]
            if p['ema9']<=p['ema15'] and c['ema9']>c['ema15'] and c['c']>c['vwap'] and c['c']>orb_high*0.998:
                breakout_time=c['dt'].strftime("%H:%M")
                breakout_price=c['c']
                break
        if not breakout_time: return None

        if not (curr['ema9']>curr['ema15'] and ltp>curr['vwap'] and ltp>curr['ema9']): return None
        if pct<0.5 or pct>10: return None
        if curr['rsi']<52 or curr['rsi']>86: return None

        # === 1:2.5 + TRAILING ===
        entry=round(ltp+0.1,2)
        sl=round(min(orb_low, curr['ema15'], curr['vwap'])*0.997,2)
        risk=entry-sl
        if risk<=0: sl=round(entry*0.97,2); risk=entry-sl
        if risk/entry>0.035: sl=round(entry*0.965,2); risk=entry-sl

        t1=round(entry+risk*1.0,2)
        t2=round(entry+risk*1.5,2)
        t3=round(entry+risk*2.5,2)
        tsl1=round(entry,2)
        tsl2=round(entry+risk*0.8,2)
        tsl3=round(entry+risk*1.5,2)

        return {"sym":sym,"c":ltp,"pct":pct,"rsi":curr['rsi'],"b_time":breakout_time,"b_price":breakout_price,"orb":orb_high,"entry":entry,"sl":sl,"risk":round(risk/entry*100,2),"t1":t1,"t2":t2,"t3":t3,"tsl1":tsl1,"tsl2":tsl2,"tsl3":tsl3,"ema9":curr['ema9'],"ema15":curr['ema15'],"vwap":curr['vwap']}
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
    print(f"Scanning {len(stocks)}...")
    with ThreadPoolExecutor(max_workers=12) as exe:
        results=list(exe.map(scan_one, [(obj,s,TOKEN_MAP) for s in stocks]))
    breaks=[r for r in results if r]
    token=os.getenv("TELEGRAM_BOT_TOKEN")
    chat=os.getenv("TELEGRAM_CHAT_ID")
    if breaks:
        breaks=sorted(breaks,key=lambda x:x['pct'],reverse=True)[:10]
        now=datetime.now(IST).strftime("%d-%b %H:%M")
        msg=f"🔥 ANGEL GOLD 1:2.5 {now}\n\n"
        for b in breaks:
            msg+=f"🚀 {b['sym']} @ {b['c']:.1f} (+{b['pct']:.1f}%) {b['b_time']}\nE:{b['entry']} SL:{b['sl']}({b['risk']}%)\n🎯 T1:{b['t1']} T2:{b['t2']} T3:{b['t3']}\n🔄 >T1 SL>{b['tsl1']} >T2 SL>{b['tsl2']} >2R SL>{b['tsl3']}\n\n"
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage",params={"chat_id":chat,"text":msg})
        print(msg)
    else:
        print("No Breakout")

if __name__=="__main__":
    main() 
