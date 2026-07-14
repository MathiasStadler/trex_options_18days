#!/usr/bin/env python3
"""
CROX Options Chain Fetcher - Min 18 Tage
Fetches put options with ask, bid, delta, gamma, theta, volume, open_interest, ask/strike*100
Uses TWS socket API (Port 7496) via ib_insync

Features:
- Marktopen-Erkennung (US-Markt 9:30-16:00 ET, Werktage)
- Exponentielles Retry mit wachsender Verzögerung (2s, 4s, 8s)
- Robuste Datenvalidierung vor Contract-Erstellung
- get_stock_price Methode mit 3-sekündiger Wiederholung
"""

import sys
import csv
import time
import logging
from datetime import datetime, time as dtime
from typing import Optional, List, Dict, Any

# Add system packages path
sys.path.insert(0, '/usr/lib/python3/dist-packages')

from ib_insync import util, IB, Stock, Option

# Konfigurierung
TWS_HOST = '127.0.0.1'
TWS_PORT = 7496
CLIENT_ID = 38
MARKET_DATA_TYPE = 3  # 3 = Delayed (für nicht-abonnierte Instrumente)

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================

def is_market_open() -> bool:
    """
    Überprüfe ob der US-Aktienmarkt aktuell gehandelt wird.
    Öffnungszeiten: Montag-Freitag 09:30-16:00 Eastern Time
    
    Returns:
        bool: True wenn Markt offen ist, False sonst
    """
    try:
        # Aktuelle Zeit in Eastern Timezone (Python 3.9+ hat zoneinfo eingebaut)
        from zoneinfo import ZoneInfo
        
        eastern = ZoneInfo('US/Eastern')
        now = datetime.now(eastern)
        
        # Wochenende
        if now.weekday() >= 5:
            logger.info("Wochenende - Markt geschlossen")
            return False
        
        # Marktschlusszeiten (09:30-16:00 ET)
        market_open = dtime(9, 30)
        market_close = dtime(16, 0)
        
        current_time = now.time()
        
        if market_open <= current_time <= market_close:
            logger.info(f"Markt offen: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return True
        else:
            logger.info(f"Markt geschlossen: {now.strftime('%H:%M:%S')} (Öffnung: 09:30, Schluss: 16:00 ET)")
            return False
    except Exception as e:
        logger.warning(f"Fehler bei Marktstatus-Prüfung: {e}, setze auf 'offen'")
        return True  # Fallback: Annahme, dass Markt offen ist

def retry_with_backoff(func, *args, max_attempts: int = 3, base_delay: int = 2, **kwargs):
    """
    Führe Funktion mit exponentiellem Backoff-Retry aus.
    
    Args:
        func: Funktion die aufgerufen werden soll
        *args: Positionelle Argumente für func
        max_attempts: Maximale Anzahl an Versuchen (Standard: 3)
        base_delay: Grundverzögerung in Sekunden (Standard: 2)
        **kwargs: Schlüsselwort-Argumente für func
    
    Returns:
        Ergebnis von func oder None wenn alle Versuche fehlschlagen
    """
    last_error = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            result = func(*args, **kwargs)
            if attempt > 1:
                logger.info(f"✅ Erfolg nach {attempt} Versuchen")
            return result
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))  # 2, 4, 8
                logger.warning(f"Versuch {attempt}/{max_attempts} fehlgeschlagen: {e}")
                logger.info(f"Warte {delay} Sekunden vor Wiederholung...")
                time.sleep(delay)
    
    logger.error(f"Alle {max_attempts} Versuche fehlgeschlagen")
    return None

def get_stock_price(ticker, max_attempts: int = 3) -> Optional[float]:
    """
    Rufe letzten Preis ab mit 3-sekündiger Wiederholung falls nötig.
    
    Args:
        ticker: IB Ticker Objekt
        max_attempts: Maximale Anzahl an Versuchen (Standard: 3)
    
    Returns:
        float: Letzter Preis oder None wenn nicht verfügbar
    """
    for attempt in range(1, max_attempts + 1):
        price = ticker.marketPrice()
        
        # Prüfe ob Preis gültig ist (> 0)
        if price is not None and price > 0:
            if attempt > 1:
                logger.info(f"✅ Preis erhalten nach {attempt} Versuchen: ${price:.2f}")
            return price
        
        if attempt < max_attempts:
            logger.warning(f"Versuch {attempt}/{max_attempts}: Kein gültiger Preis erhalten")
            logger.info("Warte 3 Sekunden vor Wiederholung...")
            time.sleep(3)
    
    logger.warning(f"Kein gültiger Preis nach {max_attempts} Versuchen")
    return None

def safe_float(v) -> Optional[float]:
    """Convert to float safely, return None for invalid values."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None

def safe_int(v) -> Optional[int]:
    """Convert to int safely, return None for invalid values."""
    f = safe_float(v)
    if f is None:
        return None
    return int(f)

def validate_option_data(row_data: Dict[str, Any]) -> bool:
    """
    Validiere dass alle erforderlichen Felder vorhanden und gültig sind.
    
    Args:
        row_data: Dictionary mit Option Daten
    
    Returns:
        bool: True wenn Daten gültig sind
    """
    # Mindestens diese Felder müssen gültig sein
    required_fields = ['conid', 'symbol', 'right', 'strike', 'expiry']
    
    for field in required_fields:
        if field not in row_data:
            logger.warning(f"Fehlendes Feld: {field}")
            return False
        if row_data[field] is None or row_data[field] == '':
            logger.warning(f"Ungültiges Feld: {field}")
            return False
    
    # Strike muss positiv sein
    if row_data.get('strike', 0) <= 0:
        logger.warning("Ungültiger Strike-Wert")
        return False
    
    return True

# ============================================================================
# HAUPTFUNKTIONEN
# ============================================================================

def get_symbol_options_chain(ticker_symbol: str, max_attempts: int = 3) -> str:
    """Fetch put options chain with minimum 18 days to expiration for given ticker symbol."""
    util.startLoop()
    ib = IB()
    
    try:
        # Marktstatus prüfen
        if not is_market_open():
            logger.warning("⚠️ US-Markt geschlossen - Verwende verzögerte Daten")
        
        logger.info(f"🔧 Verbinde zu TWS Paper ({TWS_HOST}:{TWS_PORT})...")
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        logger.info("✅ Verbindung hergestellt")
        
        # Qualifiziere gegebenen Ticker
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        logger.info(f"🔑 {ticker_symbol} conId: {stock.conId}")
        
        # Hole verfügbare Optionen (SecDef)
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        
        # Finde SMART-Kette
        chain = None
        for c in chains:
            if c.exchange == 'SMART' or c.tradingClass == ticker_symbol:
                chain = c
                break
        if not chain:
            chain = chains[0] if chains else None
        
        if not chain:
            logger.error(f"❌ Keine Optionen-Kette für {ticker_symbol} gefunden")
            return None
            
        logger.info(f"📋 Option Chain: {chain.exchange}, TradingClass: {chain.tradingClass}")
        logger.info(f"💰 Strikes verfügbar: {len(chain.strikes)}")
        
        # Filtere Verfallsdaten >= 18 Tage
        today = datetime.now()
        valid_expirations = []
        for exp in chain.expirations:
            try:
                exp_date = datetime.strptime(exp, '%Y%m%d')
                dte = (exp_date - today).days
                if dte >= 18:
                    valid_expirations.append((exp, dte))
            except:
                continue
        
        logger.info(f"✅ {len(valid_expirations)} Verfallsdaten mit >= 18 Tagen:")
        for exp, dte in valid_expirations[:5]:
            logger.info(f"   {exp} ({dte} Tage)")
        
        if not valid_expirations:
            logger.error("❌ Keine Verfallsdaten mit >= 18 Tagen")
            return None
        
        # Wähle erste 3 Verfallsdaten
        selected_exps = [e[0] for e in valid_expirations[:3]]
        
        # Nimm Strikes aus der Chain
        strikes = sorted(chain.strikes)[:15]
        logger.info(f"💰 Verwende {len(strikes)} Strikes: {strikes[:5]}...")
        
        # Alle Put-Contracts sammeln
        all_contracts = []
        for exp in selected_exps:
            for strike in strikes:
                contract = Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol)
                all_contracts.append(contract)
        
        logger.info(f"📊 Qualifiziere {len(all_contracts)} Put-Contracts...")
        qualified = ib.qualifyContracts(*all_contracts)
        logger.info(f"✅ {len(qualified)} Contracts qualifiziert")
        
        # Fordere Marktdaten einzeln an (snapshot für sofortige Daten)
        logger.info("📥 Fordere Marktdaten an (Snapshot)...")
        tickers = []
        for c in qualified:
            t = ib.reqMktData(c, snapshot=True)
            tickers.append(t)
        
        # Warte auf Daten (max 10 Sekunden)
        ib.sleep(10)
        
        # CSV-Daten sammeln
        rows = []
        for t in tickers:
            c = t.contract
            
            bid = safe_float(t.bid)
            ask = safe_float(t.ask)
            last = safe_float(t.last)
            volume = safe_int(t.volume)
            
            # Open Interest - Ticker hat kein .openInterest direkt
            oi_raw = getattr(t, 'putOpenInterest', None)
            if oi_raw is None:
                oi_raw = getattr(t, 'callOpenInterest', None)
            open_interest = safe_int(oi_raw)
            
            # Greeks
            delta = None
            gamma = None
            theta = None
            
            if hasattr(t, 'modelGreeks') and t.modelGreeks:
                g = t.modelGreeks
                delta = safe_float(getattr(g, 'delta', None))
                gamma = safe_float(getattr(g, 'gamma', None))
                theta = safe_float(getattr(g, 'theta', None))
            
            # ask/strike * 100
            ask_strike_ratio = None
            if ask and c.strike and c.strike > 0:
                ask_strike_ratio = round((ask / c.strike) * 100, 4)
            
            row = {
                'conid': c.conId,
                'symbol': c.symbol,
                'right': c.right,
                'strike': c.strike,
                'expiry': c.lastTradeDateOrContractMonth,
                'bid': bid,
                'ask': ask,
                'last': last,
                'volume': volume,
                'open_interest': open_interest,
                'delta': delta,
                'gamma': gamma,
                'theta': theta,
                'ask_strike_ratio': ask_strike_ratio,
            }
            
            # Validiere Daten vor Hinzufügen
            if validate_option_data(row):
                rows.append(row)
            else:
                logger.warning(f"Ungültige Daten übersprungen: {c.conId} {c.strike} {c.right}")
        
        # CSV schreiben (ohne Pandas)
        out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
        fieldnames = ['conid', 'symbol', 'right', 'strike', 'expiry', 'bid', 'ask', 'last', 
                      'volume', 'open_interest', 'delta', 'gamma', 'theta', 'ask_strike_ratio']
        
        with open(out_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                # Ersetze None durch leere Zeichenketten für CSV
                clean_row = {k: (v if v is not None else '') for k, v in row.items()}
                writer.writerow(clean_row)
        
        logger.info(f"✨ CSV gespeichert: {out_path}")
        logger.info(f"📊 {len(rows)} Put-Optionen")
        
        # Zeige erste 10 Zeilen (manuell formatiert)
        print("\n--- Erste 10 Zeilen ---")
        print(f"{'Expiry':<10} {'Strike':>8} {'Bid':>8} {'Ask':>8} {'Delta':>8} {'Gamma':>8} {'Theta':>8} {'Vol':>6}")
        print("-" * 80)
        for row in rows[:10]:
            print(f"{row['expiry']:<10} {row['strike']:>8.1f} {str(row['bid']):>8} {str(row['ask']):>8} {str(row['delta']):>8} {str(row['gamma']):>8} {str(row['theta']):>8} {str(row['volume']):>6}")
        
        return out_path
        
    except Exception as e:
        logger.error(f"🔥 Fehler: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        ib.disconnect()
        logger.info("🔌 Verbindung geschlossen")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = get_symbol_options_chain(sys.argv[1])
    else:
        print("ERROR: ES MUSS EIN TICKER-SYMBOL ALS ERSTER PARAMETER AUFGENOMMEN WERDEN")
        sys.exit(1)
    if result:
        logger.info(f"✅ Fertig! CSV: {result}")
    else:
        logger.error("❌ Fehlgeschlagen")