#!/usr/bin/env python3
"""
S P Y Options Chain Fetcher - Dynamic Strike Selection
Fetches put options with ask, bid, delta, gamma, theta, volume, open_interest, ask/strike*100
Uses TWS socket API (Port 7496) via ib_insync
Dynamically selects strikes around current market price
"""

import sys
import csv
import time
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

# Zustand der virtuellen Umgebung sichern
# sys.path.insert(0, '/home/hermes/trex_options_18days/.venv/lib/python3.11/site-packages')
# Da wir im Hermeshäuschen aus dem Agent-Venv starten, setzen wir PYTHONPATH manuell:
sys.path.insert(0, '/home/hermes/.hermes/hermes-agent/venv/lib/python3.11/site-packages')

from ib_insync import util, IB, Stock, Option

# ----------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------
TWS_HOST = '127.0.0.1'
TWS_PORT = 7496
CLIENT_ID = 38
MARKET_DATA_TYPE = 3   # Delayed market data (für Paper-Trading)

# ----------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------
def is_market_open() -> bool:
    """Prüfe, ob US-Markt aktuell geöffnet ist."""
    try:
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo('US/Eastern')
        now = datetime.now(eastern)
        if now.weekday() >= 5:
            return False
        market_open = datetime.strptime('09:30', '%H:%M').time()
        market_close = datetime.strptime('16:00', '%H:%M').time()
        now_time = now.time()
        return market_open <= now_time <= market_close
    except Exception:
        return True


def safe_float(v):
    """Sichere Konvertierung in float, Rückgabe von None bei ungültigen Werten."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (ValueError, TypeError):
        return None


def safe_int(v):
    f = safe_float(v)
    return int(f) if f is not None else None


def validate_option_data(row_data: Dict[str, Any]) -> bool:
    """Prüfe, ob die Option-Daten plausibel sind."""
    required_fields = ['conid', 'symbol', 'right', 'strike', 'expiry']
    for field in required_fields:
        if field not in row_data:
            print(f"❌Missing field: {field}")
            return False
        if row_data[field] is None or row_data[field] == '':
            print(f"❌Invalid field: {field}")
            return False
    if row_data.get('strike', 0) <= 0:
        print("❌Invalid strike value")
        return False
    return True


# ----------------------------------------------------------------------
# Hauptlogik
# ----------------------------------------------------------------------
def get_symbol_options_chain(ticker_symbol: str, max_attempts: int = 3) -> str:
    """Fetch put options chain with min 18 days to expiration, dynamically selected strikes."""
    util.startLoop()
    ib = IB()
    try:
        # Marktstatus prüfen
        if not is_market_open():
            print("⚠️ US-Markt geschlossen – benutze verzögerte Daten")

        # Verbindung zu TWS aufbauen
        print(f"🔧 Verbinde zu TWS Paper ({TWS_HOST}:{TWS_PORT})...")
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print("✅ Verbindung hergestellt")

        # Underlying-Symbol qualifizieren
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        print(f"🔑 {ticker_symbol} conId: {stock.conId}")

        # Optionenparameters abrufen
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        chain = chains[0] if chains else None
        if not chain:
            print(f"❌ Keine Optionen-Kette für {ticker_symbol} gefunden")
            return None
        print(f"📋 Option Chain: {chain.exchange}, TradingClass: {chain.tradingClass}")
        print(f"💰 Strikes verfügbar: {len(chain.strikes)}")

        # Aktueller Preis holen (Snapshot)
        current_price = None
        for contract in stock:
            t = ib.reqMktData(contract, snapshot=True)
            current_price = t.last
            break  # Nur ein Contract reicht für den Preis

        if current_price is None or current_price <= 0:
            print(f"❌ Aktueller Preis konnte nicht abgerufen werden: {current_price}")
            return None
        print(f"📈 Aktueller {ticker_symbol} Kurs: ${current_price:.2f}")

        # 1️⃣ Verfallsdaten >= 18 Tage auswählen
        today = datetime.now()
        valid_expirations = []
        for exp in chain.expirations:
            try:
                exp_date = datetime.strptime(exp, '%Y%m%d')
                dte = (exp_date - today).days
                if dte >= 18:
                    valid_expirations.append(exp)
            except Exception:
                continue
        print(f"✅ {len(valid_expirations)} Verfallsdaten >= 18 Tage")
        for exp in valid_expirations[:5]:
            print(f"   → {exp}")

        # 2️⃣ Strikes dynamisch auswählen: ±15% um den aktuellen Preis
        price_range = current_price * 0.15
        min_strike = max(0, int(current_price - price_range))
        max_strike = int(current_price + price_range)
        # Alle verfügbaren Strikes, aber auf den berechneten Bereich beschränken
        strikes = [int(s) for s in sorted(chain.strikes) if min_strike <= int(s) <= max_strike][:15]
        print(f"✂️ Dynamische Strike-Auswahl: min={min_strike}, max={max_strike}, ausgewählte={len(strikes)} Strikes")
        print(f"🔢 Strikes: {strikes}")

        # 3️⃣ Put-Contracts konstruieren
        all_contracts = []
        for exp in valid_expirations:
            for strike in strikes:
                contract = Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol)
                all_contracts.append(contract)

        print(f"📊 Qualifiziere {len(all_contracts)} Put-Contracts...")
        qualified = ib.qualifyContracts(*all_contracts)

        # 4️⃣ Market Data (Snapshot) holen
        print("📥 Hole Marktdata-Snapshot...")
        tickers = []
        for contract in qualified:
            t = ib.reqMktData(contract, snapshot=True)
            tickers.append(t)
        ib.sleep(10)   # Warten auf Daten

        # 5️⃣ Daten sammeln & CSV schreiben
        rows = []
        for t in tickers:
            c = t.contract
            bid = safe_float(t.bid)
            ask = safe_float(t.ask)
            last = safe_float(t.last)
            volume = safe_int(t.volume)
            oi = safe_int(getattr(t, 'putOpenInterest', None) or getattr(t, 'callOpenInterest', None))
            delta = safe_float(getattr(t.modelGreeks, 'delta', None) if hasattr(t, 'modelGreeks') and t.modelGreeks else None
            gamma = safe_float(getattr(t.modelGreeks, 'gamma', None) if hasattr(t, 'modelGreeks') and t.modelGreeks else None
            theta = safe_float(getattr(t.modelGreeks, 'theta', None) if hasattr(t, 'modelGreeks') and t.modelGreeks else None
            ask_strike_ratio = round((ask / c.strike) * 100, 4) if ask and c.strike else None

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
                'open_interest': oi,
                'delta': delta,
                'gamma': gamma,
                'theta': theta,
                'ask_strike_ratio': ask_strike_ratio,
            }
            if validate_option_data(row):
                rows.append(row)
            else:
                print(f"⚠️ Ungültige Daten übersprungen: {c.conId} {c.strike} {c.right}")

        # Ausgabe der Ziel-Datei
        out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
        fieldnames = ['conid', 'symbol', 'right', 'strike', 'expiry', 'bid', 'ask', 'last', 'volume',
                      'open_interest', 'delta', 'gamma', 'theta', 'ask_strike_ratio']

        with open(out_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print(f"✓ CSV gespeichert: {out_path}")
        print(f"📊 {len(rows)} gültige Put-Optionen gefunden")

        # Erste 10 Zeilen zur Kontrolle ausgeben
        print("\n--- Erste 10 Zeilen (expiry strike bid ask delta gamma theta volume) ---")
        for row in rows[:10]:
            print(f"{row['expiry']} {row['strike']:.1f} "
                  f"BID:{row['bid']:.4f} ASK:{row['ask']:.4f} "
                  f"Δ:{row.get('delta')} Γ:{row.get('gamma')} Θ:{row.get('theta')} "
                  f"Vol:{row['volume']}")

        return out_path

    except Exception as e:
        print(f"🔥 Fehler: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        ib.disconnect()
        print("🔌 Verbindung geschlossen")

# ----------------------------------------------------------------------
# Einstiegspunkt
# ----------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = get_symbol_options_chain(sys.argv[1])
    else:
        print("ERROR: ES MUSS EIN TICKER-SYMBOL ALS PARAMETER AUFGENOMMEN WERDEN")
        sys.exit(1)
    if result:
        print(f"✅ Vorgang abgeschlossen, CSV: {result}")
    else:
        print("❌ Vorgang fehlgeschlagen")