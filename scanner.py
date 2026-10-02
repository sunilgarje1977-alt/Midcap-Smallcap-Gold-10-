import pandas as pd
import pandas_ta as ta
import pyotp
import requests
from datetime import datetime, timedelta
from SmartApi import SmartConnect

# ==========================================
# १. तुमचे ANGEL ONE API क्रेडेन्शियल्स इथे टाका
# ==========================================
API_KEY = "तुमचा_API_KEY"
CLIENT_CODE = "तुमचा_CLIENT_CODE"
PASSWORD = "तुमचा_MPIN"
TOTP_SECRET = "तुमचा_TOTP_KEY_FROM_ANGEL" # Google Authenticator सेटअप करताना मिळणारा की

# ==========================================
# २. स्टॉक आणि त्यांचे Angel Token (NSE Midcap/Smallcap उदाहरणे)
# (तुम्ही ब्रोकरच्या स्क्रिप मास्टर फायलीमधून इतर टोकन्स जोडू शकता)
# ==========================================
WATCHLIST = [
    {"symbol": "VOLTAS", "token": "3721"},
    {"symbol": "JINDALSTEL", "token": "1317"},
    {"symbol": "HAL", "token": "2306"},
    {"symbol": "TATAMOTORS", "token": "3456"}
]

def login_angel_one():
    """Angel One SmartAPI मध्ये लॉग इन करून सेशन तयार करणे"""
    try:
        smart_conn = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = smart_conn.generateSession(CLIENT_CODE, PASSWORD, totp)
        if data['status']:
            print("✅ Angel One लॉग इन यशस्वी झाले!")
            return smart_conn
        else:
            print("❌ लॉग इन अपयशी: ", data['message'])
            return None
    except Exception as e:
        print(f"❌ लॉग इन करताना एरर आली: {e}")
        return None

def fetch_angel_data(smart_conn, token, symbol):
    """Angel API मधून ५ मिनिटांच्या कॅन्डलचा लाईव्ह डेटा गोळा करणे"""
    try:
        # आजचा आणि कालचा डेटा मागवणे
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d 09:15")

        historic_param = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }

        # Angel API कॉल
        response = smart_conn.getCandleData(historic_param)
        if response['status'] and response['data'] is not None:
            # डेटा DataFrame मध्ये बदलणे
            # Angel डेटा फॉरमॅट: [Datetime, Open, High, Low, Close, Volume]
            df = pd.DataFrame(response['data'], columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Datetime'] = pd.to_datetime(df['Datetime'])
            return df
        return None
    except Exception as e:
        print(f"❌ {symbol} चा डेटा मिळवताना अडचण: {e}")
        return None

def scan_stocks():
    obj = login_angel_one()
    if not obj:
        return

    print(f"\n🚀 --- ऑन-टाईम स्कॅनिंग सुरू झाले: {datetime.now().strftime('%H:%M:%S')} ---")

    for stock in WATCHLIST:
        df = fetch_angel_data(obj, stock['token'], stock['symbol'])
        
        if df is None or len(df) < 30:
            continue

        # आजच्या दिवसाचा डेटा वेगळा करणे
        today_str = datetime.now().strftime("%Y-%m-%d")
        df_today = df[df['Datetime'].dt.strftime('%Y-%m-%d') == today_str].reset_index(drop=True)

        if len(df_today) < 3:
            continue  # जर तिसरी कॅन्डल अजून बनली नसेल तर पुढचा स्टॉक पहा

        # ३ री कॅन्डल आणि मागील २ कॅन्डल्स
        third_candle = df_today.iloc[2]
        prev_candles = df_today.iloc[0:2]

        # मागील दिवसाचा हाय (PDH) काढणे
        df_prev_days = df[df['Datetime'].dt.strftime('%Y-%m-%d') < today_str]
        if df_prev_days.empty:
            continue
        pdh = df_prev_days['High'].max()

        # --- इंडिकेटर्स कॅल्क्युलेशन (pandas_ta चा वापर) ---
        df['VWAP'] = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])
        df['EMA_9'] = ta.ema(df['Close'], length=9)
        df['EMA_21'] = ta.ema(df['Close'], length=21)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        # Supertrend
        sti = ta.supertrend(df['High'], df['Low'], df['Close'], length=10, multiplier=2)
        df['ST_Direction'] = sti['SUPERTd_10_2.0']

        # डेटा अपडेट करणे
        third_candle_idx = df[df['Datetime'] == third_candle['Datetime']].index[0]
        current_data = df.iloc[third_candle_idx]

        # --- आपल्या ९ सुवर्ण अटींचे लॉजिक (Golden Conditions) ---
        is_open_low = (current_data['Open'] == current_data['Low']) # विग नसलेली सपाट कॅन्डल
        is_pdh_breakout = (current_data['Close'] > pdh)
        is_volume_blast = (current_data['Volume'] > prev_candles['Volume'].max())
        is_ema_bullish = (current_data['EMA_9'] > current_data['EMA_21']) and (current_data['Close'] > current_data['EMA_9'])
        is_above_vwap = (current_data['Close'] > current_data['VWAP'])
        is_st_buy = (current_data['ST_Direction'] == 1)
        is_rsi_perfect = (55 <= current_data['RSI'] <= 65)

        # सर्व अटी पूर्ण झाल्यास मॅसेज प्रिंट करा
        if is_open_low and is_pdh_breakout and is_volume_blast and is_ema_bullish and is_above_vwap and is_st_buy and is_rsi_perfect:
            print(f"🔥 [STRONG BUY SIGNAL - 5% to 10% BLAST POTENTIAL] -> {stock['symbol']}")
            print(f"   किंमत: {current_data['Close']} | सुरुवातीचा SL (Low): {current_data['Low']}")
            print(f"   💡 ट्रेलिंग नियम: ९ EMA रेषेच्या खाली कॅन्डल क्लोज होईपर्यंत थांबा.")
            print("-" * 60)

    # सेशन लॉग आऊट करणे
    obj.terminateSession(CLIENT_CODE)

if __name__ == "__main__":
    scan_stocks()
