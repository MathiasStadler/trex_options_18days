#!/usr/bin/env python3
"""
SPY Options Chain Fetcher - Min 18 Tage, ITM/OTM Calls & Puts
Fetches ITM and OTM options for both CALL and PUT sides
Uses TWS socket API (Port 7496) via ib_insync

Flags:
  --csv   Speichert CSV (Default wenn kein Flag)
  --md    Erstellt Markdown
  --all   Alle Strikes statt ITM/OTM-Filter
  --test  Kleiner Testlauf (1 Expiry, 6 Strikes) fuer schnelle Verifikation
  --n N   Anzahl der Verfallsdaten zu fetchen (Standard: 3)

Beispiele:
  python tws_get_options_chain_hernes3.py SPY --md --csv
  python tws_get_options_chain_hernes3.py SPY --test
  python tws_get_options_chain_hernes3.py SPY --md --n 5
"""

import sys
import csv
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List

# ib_insync import (venv oder Fallback-Pfad)
try:
    from ib_insync import IB, Stock, Option
except ImportError:
    SYSPATH = '/home/hermes/.hermes/hermes-agent/venv/lib/python3.11/site-packages'
    if SYSPATH not in sys.path:
        sys.path.insert(0, SYSPATH)
    from ib_insync import IB, Stock, Option

# Konfiguration
TWS_HOST = '127.0.0.1'
TWS_PORT = 7496
CLIENT_ID = 39
MARKET_DATA_TYPE = 3  # Delayed (Paper Trading)

# ----------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------
def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (ValueError, TypeError):
        return None

def safe_int(v) -> Optional[int]:
    f = safe_float(v)
    return int(f) if f is not None else None

def is_market_open(ib: IB) -> bool:
    """Prueft ob US-Markt offen ist (Regular Trading Hours, Mo-Fr 9:30-16:00 ET)."""
    try:
        import zoneinfo
        server_time = ib.reqCurrentTime()
        tz = zoneinfo.ZoneInfo('US/Eastern')
        et = server_time.astimezone(tz)
        if et.weekday() >= 5:
            return False
        open_t = et.replace(hour=9, minute=30, second=0, microsecond=0)
        close_t = et.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_t <= et <= close_t
    except Exception:
        return True  # Fallback: trotzdem versuchen

def get_stock_price_with_retry(ib: IB, stock: Stock, max_attempts: int = 3) -> Optional[float]:
    """Holt Aktienkurs mit exponentiellem Backoff (3s, 6s, 12s)."""
    for attempt in range(1, max_attempts + 1):
        ticker = ib.reqMktData(stock, snapshot=True)
        delay = 3 * (2 ** (attempt - 1))
        ib.sleep(delay)
        price = safe_float(ticker.last)
        if price is not None and price > 0:
            return price
        print(f"  Preis-Versuch {attempt}/{max_attempts} fehlgeschlagen, retry in {delay}s...")
    return None

# ----------------------------------------------------------------------
# Hauptfunktion
# ----------------------------------------------------------------------
def process_ticker(ticker_symbol: str, out_md: bool = False, out_csv: bool = False,
                   include_all: bool = False, is_test: bool = False, n_expirations: int = 3):
    ib = IB()
    try:
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=20)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print("[OK] Verbindung zu TWS hergestellt")

        if not is_market_open(ib):
            print("[WARN] Markt geschlossen - fahre trotzdem fort (delayed Daten)")

        # Underlying qualifizieren
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        print(f"[OK] {ticker_symbol} conId: {stock.conId}")

        # Aktueller Kurs
        current_price = get_stock_price_with_retry(ib, stock)
        if current_price is None or current_price <= 0:
            print("[ERR] Kein gueltiger Marktpreis")
            return False
        print(f"[OK] Aktueller Kurs: ${current_price:.2f}")

        # Optionen-Parameter
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            print("[ERR] Keine Optionskette")
            return False
        chain = chains[0]
        print(f"[OK] Chain: {chain.exchange}, Strikes gesamt: {len(chain.strikes)}")

        # Verfallsdaten >= 18 Tage
        today = datetime.now()
        valid_exps = []
        for exp in chain.expirations:
            try:
                dte = (datetime.strptime(exp, '%Y%m%d') - today).days
                if dte >= 18:
                    valid_exps.append(exp)
            except Exception:
                continue
        if not valid_exps:
            print("[ERR] Keine Verfallsdaten >= 18 Tage")
            return False

        # Anzahl Expirations beschraenken
        if is_test:
            selected_exps = valid_exps[:1]  # Testmodus bleibt auf 1 Chain begrenzt
        else:
            selected_exps = valid_exps[:n_expirations]
        print(f"[OK] Verfallsdaten (>=18d): {selected_exps}")

        # Strike-Auswahl
        if include_all:
            strikes = sorted(chain.strikes)
        else:
            # ITM/OTM Band: +-30% um Kurs, aber gueltige SPY-Strikes (1er-Schritte)
            lo = int((current_price * 0.70) // 1)
            hi = int((current_price * 1.30) // 1)
            # Nur ganzzahlige Strikes die in der Kette existieren
            all_strikes = sorted(chain.strikes)
            strikes = [s for s in all_strikes if lo <= s <= hi and float(s).is_integer()]

        # Begrenzung der Strike-Anzahl fuer Performance/Stabilitaet
        if is_test:
            # Zentral um den Kurs herum, je 3 ITM + 3 OTM
            strikes_above = [s for s in strikes if s >= current_price]
            strikes_below = [s for s in strikes if s < current_price]
            chosen = (strikes_below[-3:] if len(strikes_below) >= 3 else strikes_below) + \
                     (strikes_above[:3] if len(strikes_above) >= 3 else strikes_above)
            strikes = sorted(set(chosen))
        else:
            # Max 20 Strikes zentral um Kurs
            if len(strikes) > 20:
                mid = min(strikes, key=lambda s: abs(s - current_price))
                idx = strikes.index(mid)
                lo_i = max(0, idx - 10)
                hi_i = min(len(strikes), idx + 10)
                strikes = strikes[lo_i:hi_i]
        print(f"[OK] {len(strikes)} Strikes ausgewaehlt: {strikes}")

        # Contracts sammeln (Call + Put pro Strike/Expiry)
        contracts = []
        for exp in selected_exps:
            for strike in strikes:
                contracts.append(Option(ticker_symbol, exp, strike, 'C', 'SMART', tradingClass=ticker_symbol))
                contracts.append(Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol))

        print(f"[..] Qualifiziere {len(contracts)} Contracts...")
        # Qualifizierung in Batches (je 25) zur Stabilitaet
        qualified = []
        batch_size = 25
        for i in range(0, len(contracts), batch_size):
            batch = contracts[i:i + batch_size]
            try:
                q = ib.qualifyContracts(*batch)
                qualified.extend([c for c in q if c is not None])
            except Exception as e:
                print(f"  [WARN] Batch {i//batch_size} Fehler: {e}")
        # Fallback: unqualifizierte ueberspringen
        qualified = [c for c in qualified if c is not None and getattr(c, 'conId', None)]
        print(f"[OK] {len(qualified)} Contracts qualifiziert")

        if not qualified:
            print("[ERR] Keine gueltigen Contracts")
            return False

        # Marktdaten holen (kein snapshot, da delayed Daten besser via Stream)
        print(f"[..] Fordere Marktdaten an ({len(qualified)} Contracts)...")
        tickers_map = {}
        for c in qualified:
            t = ib.reqMktData(c)  # kein snapshot -> stream
            tickers_map[c] = t
        ib.sleep(12)  # Warte auf Daten

        # Daten sammeln
        rows = []
        for c, t in tickers_map.items():
            bid = safe_float(t.bid)
            ask = safe_float(t.ask)
            last = safe_float(t.last)
            volume = safe_int(t.volume)
            oi = safe_int(getattr(t, 'putOpenInterest', None))
            delta = gamma = theta = vega = None
            if getattr(t, 'modelGreeks', None):
                g = t.modelGreeks
                delta = safe_float(getattr(g, 'delta', None))
                gamma = safe_float(getattr(g, 'gamma', None))
                theta = safe_float(getattr(g, 'theta', None))
                vega = safe_float(getattr(g, 'vega', None))

            is_itm = (c.strike < current_price) if c.right == 'C' else (c.strike > current_price)
            moneyness = 'ITM' if is_itm else 'OTM'
            ask_strike_ratio = round((ask / c.strike) * 100, 4) if (ask and c.strike) else None

            rows.append({
                'conid': c.conId, 'symbol': c.symbol, 'right': c.right,
                'strike': c.strike, 'expiry': c.lastTradeDateOrContractMonth,
                'moneyness': moneyness, 'bid': bid, 'ask': ask, 'last': last,
                'volume': volume, 'open_interest': oi,
                'delta': delta, 'gamma': gamma, 'theta': theta, 'vega': vega,
                'ask_strike_ratio': ask_strike_ratio,
            })

        rows.sort(key=lambda r: (0 if r['right'] == 'C' else 1,
                                 0 if r['moneyness'] == 'ITM' else 1,
                                 float(r['strike'])))

        # CSV
        if out_csv:
            out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
            cols = ['conid', 'symbol', 'right', 'strike', 'expiry', 'moneyness',
                    'bid', 'ask', 'last', 'volume', 'open_interest',
                    'delta', 'gamma', 'theta', 'vega', 'ask_strike_ratio']
            with open(out_path, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
            print(f"[OK] CSV: {out_path} ({len(rows)} Optionen)")

        # Markdown
        if out_md:
            lines = [f"# {ticker_symbol} – Options-Chain (Min. 18 Tage)",
                     "", "## Zusammenfassung",
                     f"- Aktueller Kurs: ${current_price:.2f}",
                     f"- Verfallsdaten: {', '.join(selected_exps)}",
                     f"- Strikes: {len(strikes)} | Optionen gesamt: {len(rows)}", ""]
            cats = {
                'Calls ITM': [r for r in rows if r['right'] == 'C' and r['moneyness'] == 'ITM'],
                'Calls OTM': [r for r in rows if r['right'] == 'C' and r['moneyness'] == 'OTM'],
                'Puts ITM':  [r for r in rows if r['right'] == 'P' and r['moneyness'] == 'ITM'],
                'Puts OTM':  [r for r in rows if r['right'] == 'P' and r['moneyness'] == 'OTM'],
            }
            lines.append("## Kategorien")
            lines.append("")
            lines.append("| Kategorie | Anzahl |")
            lines.append("|-----------|--------|")
            for k, v in cats.items():
                lines.append(f"| {k} | {len(v)} |")
            lines.append("")
            for title, key in [("📈 Calls", 'C'), ("📉 Puts", 'P')]:
                sub = [r for r in rows if r['right'] == key]
                if not sub:
                    continue
                lines.append(f"## {title}")
                lines.append("")
                lines.append("| Moneyness | Expiry | Strike | Bid | Ask | Delta | Gamma | Theta | Vol |")
                lines.append("|-----------|--------|--------|-----|-----|-------|-------|-------|-----|")
                for r in sub:
                    def fmt(v, w):
                        return f"{v:>{w}}" if v is not None else " " * (w-2) + "NA"
                    lines.append(
                        f"| {r['moneyness']:<11} | {str(r['expiry']):<12} | {r['strike']:>7.1f} | "
                        f"{fmt(r['bid'],6)} | {fmt(r['ask'],5)} | {fmt(r['delta'],7)} | "
                        f"{fmt(r['gamma'],5)} | {fmt(r['theta'],5)} | {fmt(r['volume'],6)} |"
                    )
                lines.append("")
            md_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.md"
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))
            print(f"[OK] Markdown: {md_path}")

        # Kurzes Summary auf Konsole
        print("\n=== SUMMARY ===")
        print(f"Kurs: ${current_price:.2f} | Optionen: {len(rows)}")
        for k, v in cats.items():
            print(f"  {k}: {len(v)}")
        return True

    except Exception as e:
        print(f"[ERR] {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
        print("[OK] Verbindung geschlossen")

# ----------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Options Chain Fetcher ITM/OTM Calls & Puts")
    parser.add_argument('ticker', help='Ticker (z.B. SPY)')
    parser.add_argument('--csv', action='store_true')
    parser.add_argument('--md', action='store_true')
    parser.add_argument('--all', action='store_true', help='Alle Strikes')
    parser.add_argument('--test', action='store_true', help='Kleiner Testlauf')
    parser.add_argument('--n', type=int, default=3, help='Anzahl der Verfallsdaten zu fetchen (Standard: 3)')
    a = parser.parse_args()

    out_csv = a.csv or (not a.md and not a.test)
    out_md = a.md
    process_ticker(a.ticker, out_md=out_md, out_csv=out_csv, include_all=a.all,
                   is_test=a.test, n_expirations=a.n)