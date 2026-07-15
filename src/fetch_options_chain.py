#!/usr/bin/env python3
"""
SYMBOL Options Chain Fetcher - Min 18 Tage
Fetches put options with ask, bid, delta, gamma, theta, volume, open_interest, ask/strike*100
Uses TWS socket API (Port 7496) via ib_insync
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
TWS_PORT = 7496  # Paper Trading Port
CLIENT_ID = 38
MARKET_DATA_TYPE = 3  # 3 = Delayed (fuer nicht-abonnierte Instrumente)

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
    """Ueberpruefe ob der US-Aktienmarkt aktuell gehandelt wird.
    Oeffnungszeiten: Montag-Freitag 09:30-16:00 Eastern Time"""
    try:
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo('US/Eastern')
        now = datetime.now(eastern)
        if now.weekday() >= 5:
            logger.info("Wochenende - Markt geschlossen")
            return False
        market_open = dtime(9, 30)
        market_close = dtime(16, 0)
        current_time = now.time()
        if market_open <= current_time <= market_close:
            logger.info(f"Markt offen: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return True
        else:
            logger.info(f"Markt geschlossen: {now.strftime('%H:%M:%S')} (Oeffnung: 09:30, Schluss: 16:00 ET)")
            return False
    except Exception as e:
        logger.warning(f"Fehler bei Marktstatus-Pruefung: {e}, setze auf 'offen'")
        return True

def retry_with_backoff(func, *args, max_attempts: int = 3, base_delay: int = 2, **kwargs):
    """Fuehre Funktion mit exponentiellem Backoff-Retry aus."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = func(*args, **kwargs)
            if attempt > 1:
                logger.info(f"Erfolg nach {attempt} Versuchen")
            return result
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(f"Versuch {attempt}/{max_attempts} fehlgeschlagen: {e}")
                logger.info(f"Warte {delay} Sekunden vor Wiederholung...")
                time.sleep(delay)
    logger.error(f"Alle {max_attempts} Versuche fehlgeschlagen")
    return None

def get_stock_price(ticker, max_attempts: int = 3) -> Optional[float]:
    """Rufe den letzten Preis ab mit 3-sekuendiger Wiederholung falls noetig."""
    for attempt in range(1, max_attempts + 1):
        price = ticker.marketPrice()
        if price is not None and price > 0:
            if attempt > 1:
                logger.info(f"Preis erhalten nach {attempt} Versuchen: ${price:.2f}")
            return price
        if attempt < max_attempts:
            logger.warning(f"Versuch {attempt}/{max_attempts}: Kein gueltiger Preis erhalten")
            logger.info("Warte 3 Sekunden vor Wiederholung...")
            time.sleep(3)
    logger.warning(f"Kein gueltiger Preis nach {max_attempts} Versuchen")
    return None

def safe_float(v) -> Optional[float]:
    """Sichere Konvertierung in Float, Rueckgabe von None bei ungueltigen Werten."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except (ValueError, TypeError):
        return None

def safe_int(v) -> Optional[int]:
    """Sichere Konvertierung in Int, Rueckgabe von None bei ungueltigen Werten."""
    f = safe_float(v)
    if f is None:
        return None
    return int(f)

def validate_option_data(row_data: Dict[str, Any]) -> bool:
    """Validiere dass alle erforderlichen Felder vorhanden und gueltig sind."""
    required_fields = ['conid', 'symbol', 'right', 'strike', 'expiry']
    for field in required_fields:
        if field not in row_data:
            logger.warning(f"Fehlendes Feld: {field}")
            return False
        if row_data[field] is None or row_data[field] == '':
            logger.warning(f"Ungueltiges Feld: {field}")
            return False
    if row_data.get('strike', 0) <= 0:
        logger.warning("Ungueltiger Strike-Wert")
        return False
    return True

def is_valid_symbol(ib: IB, ticker_symbol: str) -> bool:
    """Prueft, ob der gegebene Ticker im TWS Paper-Trading existiert.
    Nutzt die bereits existierende IB-Verbindung (ib), um einen doppelten
    Connect mit derselben clientId zu vermeiden."""
    try:
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        return True
    except Exception as e:
        logger.warning(f"Symbol '{ticker_symbol}' nicht gefunden: {e}")
        return False

# ============================================================================
# HAUPTFUNKTION
# ============================================================================

def get_symbol_options_chain(ticker_symbol: str, max_attempts: int = 3) -> str:
    """Fetch put options chain with minimum 18 days to expiration for given ticker symbol."""
    util.startLoop()
    ib = IB()
    try:
        if not is_market_open():
            logger.warning("US-Markt geschlossen - Verwende verzoegerte Daten")
        logger.info(f"Verbinde zu TWS Paper ({TWS_HOST}:{TWS_PORT})...")
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        logger.info("Verbindung hergestellt")
        if not is_valid_symbol(ib, ticker_symbol):
            logger.error(f"Symbol '{ticker_symbol}' existiert nicht im TWS Paper-Trading - abgebrochen")
            return None
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        logger.info(f"{ticker_symbol} conId: {stock.conId}")
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        chain = None
        for c in chains:
            if c.exchange == 'SMART' or c.tradingClass == ticker_symbol:
                chain = c
                break
        if not chain:
            chain = chains[0] if chains else None
        if not chain:
            logger.error(f"Keine Optionen-Kette fuer {ticker_symbol} gefunden")
            return None
        logger.info(f"Option Chain: {chain.exchange}, TradingClass: {chain.tradingClass}")
        logger.info(f"Strikes verfuegbar: {len(chain.strikes)}")
        today = datetime.now()
        valid_expirations = []
        for exp in chain.expirations:
            try:
                exp_date = datetime.strptime(exp, '%Y%m%d')
                dte = (exp_date - today).days
                if dte >= 18:
                    valid_expirations.append((exp, dte))
            except Exception:
                continue
        logger.info(f"{len(valid_expirations)} Verfallsdaten mit >= 18 Tagen:")
        for exp, dte in valid_expirations[:5]:
            logger.info(f"   {exp} ({dte} Tage)")
        if not valid_expirations:
            logger.error("Keine Verfallsdaten mit >= 18 Tagen")
            return None
        selected_exps = [e[0] for e in valid_expirations[:3]]
        strikes = sorted(chain.strikes)[:15]
        logger.info(f"Verwende {len(strikes)} Strikes: {strikes[:5]}...")
        all_contracts = []
        for exp in selected_exps:
            for strike in strikes:
                contract = Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol)
                all_contracts.append(contract)
        logger.info(f"Qualifiziere {len(all_contracts)} Put-Contracts...")
        qualified = ib.qualifyContracts(*all_contracts)
        logger.info(f"{len(qualified)} Contracts qualifiziert")
        logger.info("Fordere Marktdaten an (Snapshot)...")
        tickers = []
        for c in qualified:
            t = ib.reqMktData(c, snapshot=True)
            tickers.append(t)
        ib.sleep(10)
        rows = []
        for t in tickers:
            c = t.contract
            bid = safe_float(t.bid)
            ask = safe_float(t.ask)
            last = safe_float(t.last)
            volume = safe_int(t.volume)
            oi_raw = getattr(t, 'putOpenInterest', None)
            if oi_raw is None:
                oi_raw = getattr(t, 'callOpenInterest', None)
            open_interest = safe_int(oi_raw)
            delta = None
            gamma = None
            theta = None
            if hasattr(t, 'modelGreeks') and t.modelGreeks:
                g = t.modelGreeks
                delta = safe_float(getattr(g, 'delta', None))
                gamma = safe_float(getattr(g, 'gamma', None))
                theta = safe_float(getattr(g, 'theta', None))
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
            if validate_option_data(row):
                rows.append(row)
            else:
                logger.warning(f"Ungueltige Daten uebersprungen: {c.conId} {c.strike} {c.right}")
        out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
        fieldnames = ['conid', 'symbol', 'right', 'strike', 'expiry', 'bid', 'ask', 'last',
                      'volume', 'open_interest', 'delta', 'gamma', 'theta', 'ask_strike_ratio']
        with open(out_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                clean_row = {k: (v if v is not None else '') for k, v in row.items()}
                writer.writerow(clean_row)
        logger.info(f"CSV gespeichert: {out_path}")
        logger.info(f"{len(rows)} Put-Optionen")
        print("\n--- Erste 10 Zeilen ---")
        print(f"{'Expiry':<10} {'Strike':>8} {'Bid':>8} {'Ask':>8} {'Delta':>8} {'Gamma':>8} {'Theta':>8} {'Vol':>6}")
        print("-" * 80)
        for row in rows[:10]:
            print(f"{row['expiry']:<10} {row['strike']:>8.1f} {str(row['bid']):>8} {str(row['ask']):>8} {str(row['delta']):>8} {str(row['gamma']):>8} {str(row['theta']):>8} {str(row['volume']):>6}")
        return out_path
    except Exception as e:
        logger.error(f"Fehler: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        ib.disconnect()
        logger.info("Verbindung geschlossen")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = get_symbol_options_chain(sys.argv[1])
    else:
        print("ERROR: ES MUSS EIN TICKER-SYMBOL ALS ERSTER PARAMETER AUFGENOMMEN WERDEN")
        sys.exit(1)
    if result:
        logger.info(f"Fertig! CSV: {result}")
    else:
        logger.error("Fehlgeschlagen")
