import os, pytz, requests, pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import pyotp
from concurrent.futures import ThreadPoolExecutor

IST = pytz.timezone("Asia/Kolkata")

# 200+ STOCKS
STOCKS=["SUZLON","IDEA","YESBANK","JPASSOCIAT","RPOWER","IRB","JPPOWER","HCC","GMRINFRA","UNITECH","JAIBALAJI","ADANIGREEN","ADANIENT","SOUTHBANK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK","PNB","BANKBARODA","CANBK","INDIANB","UNIONBANK","CENTRALBK","IOB","UCOBANK","MAHABANK","PSB","KARURVYSYA","CUB","RBLBANK","IIFL","MUTHOOTFIN","MANAPPURAM","ANGELONE","BSE","CDSL","MCX","CAMS","KFINTECH","AFFLE","LATENTVIEW","MAPMYINDIA","EASEMYTRIP","IRCTC","ZOMATO","PAYTM","NYKAA","DELHIVERY","POLICYBZR","TATATECH","TATAELXSI","PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","LTTS","INTELLECT","MASTEK","BIRLASOFT","CYIENT","ZENSAR","SONATSOFTW","TANLA","FSL","ROUTE","HAPPSTMNDS","INDIAMART","JUSTDIAL","BLS","PRAJIND","TRIVENI","THERMAX","BHEL","BEL","BEML","COCHINSHIP","MAZDOCK","GRSE","HAL","BDL","MIDHANI","SAIL","NATIONALUM","HINDALCO","VEDL","HINDZINC","NMDC","COALINDIA","TATASTEEL","JSWSTEEL","APLAPOLLO","JINDALSAW","WELCORP","RATNAMANI","TATACHEM","DEEPAKNTR","AARTIIND","ATUL","NAVINFLOUR","VINATIORGA","FINEORG","GALAXYSURF","TATACOMM","HFCL","TEJASNET","RAILTEL","TATAPOWER","ADANIPOWER","JSWENERGY","TORNTPOWER","CESC","NHPC","SJVN","POWERGRID","NTPC","REC","PFC","IRFC","HUDCO","NBCC","IRCON","RITES","RVNL","CONCOR","BLUESTAR","VOLTAS","WHIRLPOOL","CROMPTON","HAVELLS","POLYCAB","KEI","BAJAJELEC","VGUARD","AMBER","DIXON","SYRMA","KAYNES","SAFARI","BATAINDIA","RELAXO","METROBRAND","TITAN","SENCO","JUBLFOOD","DEVYANI","SAPPHIRE","WESTLIFE","BIKAJI","VARUNBEV","TATACONSUM","DABUR","MARICO","GODREJCP","ASTRAL","SUPREME","FINOLEXIND","PRINCEPIPE","VIPIND","CERA","KAJARIACER","GREENLAM","CENTURYPLY","RKFORGE","ASHOKLEY","TATAMOTORS","M&M","MARUTI","EICHERMOT","TVSMOTOR","BAJAJ-AUTO","HEROMOTOCO","BHARATFORG","MOTHERSON","SONACOMS","ENDURANCE","TIMKEN","SKFINDIA","TIINDIA","CUMMINSIND","ELGIEQUIP","GRINDWELL","CARBORUNDA","ABB","SIEMENS","LAXMIMACH","TRITURBINE","AIAENG","JWL","TITAGARH","FINCABLES","RRKABEL","PGEL","SHYAMMETL","WELSPUN","INDIGO","5PAISA"]

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
        if not tok: return None

        to_d = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d = (datetime.now(IST) - timedelta(days=20)).strftime("%Y-%m-%d %H:%M")
        r = obj.getCandleData({"exchange":"NSE","symboltoken":tok,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d})

        if not r or not r.get('data') or len(r['data']) < 50: return None

        df = pd.DataFrame(r['data'], columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']: df[c] = pd.to_numeric(df[c], errors='coerce')
        df['dt'] = pd.to_datetime(df['dt'])

        today = datetime.now(IST).strftime("%Y-%m-%d")
        dft = df[df['dt'].dt.strftime("%Y-%m-%d") == today].copy().reset_index(drop=True)
        if len(dft) < 6: return None

        # 9:15-9:30 ORB (First 3 Candles)
        orb_high = dft.iloc[:3]['h'].max()
        orb_low = dft.iloc[:3]['l'].min()

        # 9:30-3:30 Breakout Check
        breakout_candle = None
        for i in range(3, len(dft)):
            if dft.iloc[i]['c'] > orb_high:
                breakout_candle = dft.iloc[i]
                break
        if breakout_candle is None: return None

        # Indicators
        dft['ema9'] = dft['c'].ewm(span=9).mean()
        dft['ema15'] = dft['c'].ewm(span=15).mean()
        tp = (dft['h']+dft['l']+dft['c'])/3
        dft['vwap'] = (tp*dft['v']).cumsum() / dft['v'].cumsum()
        dft['rsi'] = get_rsi(dft['c'])
        dft['vol_avg_10'] = dft['v'].rolling(10).mean()

        # 3-5 Candle Tight Base
        base_df = dft.iloc[max(0, len(dft)-6):len(dft)-1]
        base_range_pct = (base_df['h'].max() - base_df['l'].min()) / base_df['c'].mean() * 100

        curr = dft.iloc[-1]
        avg10 = curr['vol_avg_10'] if pd.notna(curr['vol_avg_10']) else dft['v'].mean()

        daily_vol = dft['v'].sum()
        hist_vol = df.groupby(df['dt'].dt.date)['v'].sum().mean()
        dvolx = daily_vol / hist_vol if hist_vol > 0 else 0

        ltpr = obj.ltpData("NSE", sym+"-EQ", tok)
        ltp = ltpr['data']['ltp'] if ltpr and ltpr.get('data') else curr['c']
        pct = (ltp - dft.iloc[0]['o']) / dft.iloc[0]['o'] * 100

        # ========== FINAL GOLD CONDITIONS ==========
        # 1. Gain Filter
        if pct < 0.5 or pct > 10: return None
        # 2. RSI 60 (तुझं मागणं)
        if curr['rsi'] < 60 or curr['rsi'] > 90: return None
        # 3. EMA + VWAP
        if not (curr['ema9'] > curr['ema15'] and ltp > curr['vwap'] and ltp > curr['ema9']): return None
        # 4. ORB Breakout
        if ltp < orb_high * 0.998: return None
        # 5. Volume Breakout
        if curr['v'] < avg10 * 1.5: return None
        if dvolx < 1.2: return None
        # 6. 3-5 Candle Tight (Optional - सैल ठेवलंय)
        # if base_range_pct > 2.5: return None

        # Entry SL 
