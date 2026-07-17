#!/usr/bin/env python3
"""
SPY Options Chain Fetcher – Min 18 Tage, dynamische Strike-Auswahl
Inkludiert Retry-Logik für fehlende Bid/Ask/Greeks
"""

import sys
import csv
import time
from datetime import datetime
from typing import Optional, Dict, Any

SYSPATH = '/home/hermes/.hermes/hermes-agent/venv/lib/python3.11/site-packages'
if SYSPATH not in sys.path:
    sys.path.insert(0, SYSPATH)

from ib_insync import IB, Stock, Option

TWS_HOST = '127.0.0.1'
TWS_PORT = 7496
CLIENT_ID = 38
MARKET_DATA_TYPE = 3  # Delayed data
MAX_RETRIES = 3
BASE_WAIT = 2  # 2s, dann 4s, dann 8s

def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (ValueError, TypeError):
        return None

def safe_int(v) -> Optional[int]:
    f = safe_float(v)
    return int(f) if f is not None else None

def fetch_market_data_with_retry(ib: IB, contract, ticker, max_retries=MAX_RETRIES):
    """Wiederholt reqMktData bis Felder gefüllt sind oder max_retries erreicht."""
    for attempt in range(1, max_retries + 1):
        t = ib.reqMktData(contract, snapshot=True)
        wait = BASE_WAIT * (2 ** (attempt - 1))  # 2, 4, 8
        ib.sleep(wait)

        bid = safe_float(t.bid)
        ask = safe_float(t.ask)
        last = safe_float(t.last)
        volume = safe_int(t.volume)
        oi = safe_int(getattr(t, 'putOpenInterest', None) or getattr(t, 'callOpenInterest', None))

        delta = gamma = theta = None
        if hasattr(t, 'modelGreeks') and t.modelGreeks:
            g = t.modelGreeks
            delta = safe_float(getattr(g, 'delta', None))
            gamma = safe_float(getattr(g, 'gamma', None))
            theta = safe_float(getattr(g, 'theta', None))

        # Prüfe, ob alle Felder vorhanden sind (außer last & oi)
        if all(v is not None for v in [bid, ask, delta, gamma, theta]):
            return bid, ask, last, volume, oi, delta, gamma, theta

    # Timeout – gebe letzten bekannten Wert zurück (auch wenn None)
    return (
        safe_float(t.bid), safe_float(t.ask), safe_float(t.last),
        safe_int(t.volume), safe_int(getattr(t, 'putOpenInterest', None)),
        delta, gamma, theta
    )

def process_ticker(ticker_symbol: str, out_md: bool = False, out_csv: bool = False):
    ib = IB()
    try:
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print("Verbindung zu TWS hergestellt")

        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        print(f"{ticker_symbol} conId: {stock.conId}")

        # Snapshot für Kurs
        stock_ticker = ib.reqMktData(stock, snapshot=True)
        ib.sleep(3)
        current_price = safe_float(stock_ticker.last)
        if current_price is None or current_price <= 0:
            print(f"Kein gueltiger Kurs, Abbruch")
            return None
        print(f"Aktueller Kurs: ${current_price:.2f}")

        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            return None
        chain = chains[0]
        print(f"Chain: {chain.exchange}, {chain.tradingClass}")

        # Verfallsdaten
        today = datetime.now()
        valid_exps = [e for e in chain.expirations
                      if (datetime.strptime(e, '%Y%m%d') - today).days >= 18][:3]
        print(f"Verfallsdaten: {valid_exps}")

        # Dynamische Strikes
        min_strike = int(current_price * 0.85)
        max_strike = int(current_price * 1.15)
        strikes = sorted(s for s in chain.strikes if min_strike <= s <= max_strike)[:15]
        print(f"Strikes: {strikes}")

        # Contracts bauen und qualifizieren
        contracts = []
        for exp in valid_exps:
            for strike in strikes:
                contracts.append(Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol))

        qualified = ib.qualifyContracts(*contracts)
        print(f"{len(qualified)} Contracts qualifiziert")

        # Marktdaten mit Retry
        rows = []
        for c in qualified:
            bid, ask, last, vol, oi, delta, gamma, theta = fetch_market_data_with_retry(ib, c, ticker_symbol)
            ask_strike_ratio = round((ask / c.strike) * 100, 4) if ask and c.strike else None

            rows.append({
                'conid': c.conId, 'symbol': c.symbol, 'right': c.right,
                'strike': c.strike, 'expiry': c.lastTradeDateOrContractMonth,
                'bid': bid, 'ask': ask, 'last': last, 'volume': vol,
                'open_interest': oi, 'delta': delta, 'gamma': gamma,
                'theta': theta, 'ask_strike_ratio': ask_strike_ratio,
            })

        rows.sort(key=lambda r: float(r['strike']))

        # CSV speichern
        if out_csv:
            path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
            fn = ['conid','symbol','right','strike','expiry','bid','ask','last',
                  'volume','open_interest','delta','gamma','theta','ask_strike_ratio']
            with open(path, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=fn)
                w.writeheader()
                w.writerows(rows)
            print(f"CSV gespeichert: {path}")

        # Markdown speichern
        if out_md:
            md = [f"# {ticker_symbol} – Options-Chain (Min. 18 Tage)", "",
                  "## Zusammenfassung", f"- Kurs: ${current_price:.2f}",
                  f"- Verfallsdaten: {', '.join(valid_exps)}",
                  f"- Strikes: {strikes}", "", "## Put-Options-Chain", "",
                  "| Expiry | Strike | Bid | Ask | Delta | Gamma | Theta | Vol |",
                  "|--------|-------|-----|-----|-------|-------|-------|-----|"]
            for r in rows:
                md.append(f"| {r['expiry']:<12} | {r['strike']:>7.1f} | "
                          f"{str(r['bid']):>6} | {str(r['ask']):>5} | "
                          f"{str(r['delta']):>8} | {str(r['gamma']):>5} | "
                          f"{str(r['theta']):>5} | {r['volume']:>8} |")
            path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.md"
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(md))
            print(f"Markdown gespeichert: {path}")

        return True
    except Exception as e:
        print(f"Fehler: {e}")
        import traceback; traceback.print_exc()
        return False
    finally:
        ib.disconnect(); print("Verbindung geschlossen")

if __name__ == "__main__":
    args = sys.argv[1:]
    flag_csv = "--csv" in args
    flag_md = "--md" in args
    ticker = next((a for a in args if a not in ("--csv", "--md")), None)
    if not ticker:
        print("Usage: python spy_options_chain.py <TICKER> [--csv|--md]")
        sys.exit(1)
    process_ticker(ticker, out_md=flag_md, out_csv=flag_csv)
