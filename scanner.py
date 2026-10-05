import os, sys, pytz, requests, pandas as pd, pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from concurrent.futures import ThreadPoolExecutor

try:
    import websocket
except:
    os.system(f"{sys.executable} -m pip install websocket-client -q")

IST = pytz.timezone("Asia/Kolkata")
STOCKS = ["SUZLON","IDEA","YESBANK","RPOWER","IRB","HCC","GMRINFRA","SOUTHBANK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK","PNB","BANKBARODA","CANBK","RBLBANK","ANGELONE","BSE","CDSL","MCX","IRCTC","ZOMATO","PAYTM","BHEL","BEL","MAZDOCK","HAL","SAIL","VEDL","TATASTEEL","JSWSTEEL","TATAPOWER","ADANIPOWER","NHPC","POWERGRID","NTPC","REC","PFC","IRFC","RVNL","TITAN","TATAMOTORS","M&M","MARUTI","INDIGO"]

def get_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.ewm(alpha=1/p).mean() / l.ewm(alpha=1/p).mean()
    return 100 - (100 / (1 + rs))

def scan_one(args):
    obj, sym, tmap = args
    try:
        tok = tmap.get(sym)
        if not tok:
            return None
        to_d = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d = (datetime.now(IST) - timedelta(days=20)).strftime("%Y-%m-%d %H:%M")
        r = obj.getCandleData({"exchange":"NSE","symboltoken":tok,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d})
        if not r or not r.get('data') or len(r['data']) < 50:
            return None
        df = pd.DataFrame(r['data'], columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['dt'] = pd.to_datetime(df['dt'])
        today = datetime.now(IST).strftime("%Y-%m-%d")
        dft = df[df['dt'].dt.strftime("%Y-%m-%d") == today].copy().reset_index(drop=True)
        if len(dft) < 4:
            return None
        orb_h = dft.iloc[:3]['h'].max()
        orb_l = dft.iloc[:3]['l'].min()
        breakout = None
        for i in range(3, len(dft)):
            if dft.iloc[i]['c'] > orb_h:
                breakout = dft.iloc[i]
                break
        if breakout is None:
            return None
        dft['ema9'] = dft['c'].ewm(span=9).mean()
        dft['ema15'] = dft['c'].ewm(span=15).mean()
        tp = (dft['h'] + dft['l'] + dft['c']) / 3
        dft['vwap'] = (tp * dft['v']).cumsum() / dft['v'].cumsum()
        dft['rsi'] = get_rsi(dft['c'])
        dft['vol_avg_10'] = dft['v'].rolling(10).mean()
        curr = dft.iloc[-1]
        avg10 = curr['vol_avg_10'] if pd.notna(curr['vol_avg_10']) else dft['v'].mean()
        daily_vol = dft['v'].sum()
        hist_vol = df.groupby(df['dt'].dt.date)['v'].sum().mean()
        dvolx = daily_vol / hist_vol if hist_vol > 0 else 0
        ltpr = obj.ltpData("NSE", sym + "-EQ", tok)
        ltp = ltpr['data']['ltp'] if ltpr and ltpr.get('data') else curr['c']
        pct = (ltp - dft.iloc[0]['o']) / dft.iloc[0]['o'] * 100
        if pct < 0.5 or pct > 10:
            return None
        if curr['rsi'] < 60 or curr['rsi'] > 90:
            return None
        if not (curr['ema9'] > curr['ema15'] and ltp > curr['vwap']):
            return None
        if ltp < orb_h:
            return None
        if curr['v'] < avg10 * 1.5:
            return None
        if dvolx < 1.2:
            return None
        entry = round(ltp + 0.1, 2)
        sl = round(min(orb_l, curr['ema15']) * 0.997, 2)
        risk = entry - sl
        if risk <= 0:
            sl = round(entry * 0.97, 2)
            risk = entry - sl
        if risk / entry > 0.035:
            sl = round(entry * 0.965, 2)
            risk = entry - sl
        return {"sym":sym,"c":ltp,"pct":pct,"rsi":curr['rsi'],"b_time":breakout['dt'].strftime("%H:%M"),"volx":curr['v']/avg10,"dvolx":dvolx,"entry":entry,"sl":sl,"t1":round(entry+risk*1,2),"t2":round(entry+risk*1.5,2),"t3":round(entry+risk*2.5,2)}
    except:
        return None

def main():
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    totp = pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
    obj.generateSession(os.getenv("ANGEL_CLIENT_ID"), os.getenv("ANGEL_PASSWORD_KEY"), totp)
    scrips = requests.get("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json").json()
    tmap = {s['symbol'].replace('-EQ',''):s['token'] for s in scrips if s['exch_seg']=='NSE' and s['symbol'].endswith('-EQ')}
    with ThreadPoolExecutor(max_workers=10) as ex:
        res = list(ex.map(scan_one, [(obj,s,tmap) for s in STOCKS]))
    br = [r for r in res if r]
    now = datetime.now(IST).strftime("%d-%b %H:%M")
    if br:
        br = sorted(br, key=lambda x:(x['dvolx'],x['pct']), reverse=True)[:10]
        msg = "GOLD RSI60 " + now + " Breakout\n\n"
        for b in br:
            msg = msg + f"{b['sym']} {b['c']} {b['pct']:.1f}% RSI {b['rsi']:.0f} BO {b['b_time']} E {b['entry']} SL {b['sl']} T1 {b['t1']} T2 {b['t2']} T3 {b['t3']}\n"
    else:
        msg = "Scanner OK " + now + " - No Breakout Today - Test OK"
    print(msg)
    bot = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{bot}/sendMessage"
    requests.get(url, params={"chat_id":chat,"text":msg})

if __name__ == "__main__":
    main()
