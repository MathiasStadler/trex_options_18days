#!/usr/bin/env python3
"""
SPY Options Chain Fetcher - Min 18 Tage, dynamische Strike-Auswahl
Fetches put options with bid/ask, delta, gamma, theta, volume, open_interest
Uses TWS socket API (Port 7496) via ib_insync
Supports flags:
  --csv  → Save the options CSV file (default behavior)
  --md   → Create a Markdown document with the options chain
Example:
  python spy_options_chain.py SPY --md   # only Markdown output (file created)
  python spy_options_chain.py SPY --csv  # only CSV (default)
  python spy_options_chain.py SPY --md --csv  # both
"""

import sys
import csv
import time
from datetime import datetime
from typing import Optional, Dict, Any

# ib_insync-Pfad
SYSPATH = '/home/hermes/.hermes/hermes-agent/venv/lib/python3.11/site-packages'
if SYSPATH not in sys.path:
    sys.path.insert(0, SYSPATH)

from ib_insync import IB, Stock, Option

# Konfiguration
TWS_HOST = '127.0.0.1'
TWS_PORT = 7496
CLIENT_ID = 38
MARKET_DATA_TYPE = 3  # Delayed data for Paper Trading

# Hilfsfunktionen (identisch zu den vorherigen Versionen)
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

# ----------------------------------------------------------------------
# Hauptfunktion – verarbeitet einen einzelnen Ticker
# ----------------------------------------------------------------------
def process_ticker(ticker_symbol: str, out_md: bool = False, out_csv: bool = False):
    ib = IB()
    try:
        # 1️⃣ Verbindung zum TWS aufbauen
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print("Verbindung zu TWS hergestellt")

        # 2️⃣ Underlying qualifizieren
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        print(f"{ticker_symbol} conId: {stock.conId}")

        # 3️⃣ Aktuellen Kurs holen (Snapshot)
        stock_ticker = ib.reqMktData(stock, snapshot=True)
        ib.sleep(3)
        current_price = safe_float(stock_ticker.last)
        if current_price is None or current_price <= 0:
            print(f"Kein gueltiger Marktpreis fuer {ticker_symbol}, Abbruch")
            return None
        print(f"Aktueller {ticker_symbol} Kurs: ${current_price:.2f}")

        # 4️⃣ Optionen-Parameter holen
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            print("Keine Optionen-Kette gefunden")
            return None
        chain = chains[0]
        print(f"Chain: {chain.exchange}, {chain.tradingClass}, Strikes: {len(chain.strikes)}")

        # 5️⃣ Verfallsdaten >= 18 Tage auswählen
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
        if not valid_expirations:
            print("Keine Verfallsdaten mit >= 18 Tagen")
            return None
        selected_exps = valid_expirations[:3]
        print(f"Verfallsdaten (>=18d): {selected_exps[:3]}")

        # 6️⃣ Dynamische Strike-Auswahl (±15 % um den Kurs)
        min_strike = int(current_price * 0.85)
        max_strike = int(current_price * 1.15)
        strikes = sorted([s for s in chain.strikes if min_strike <= s <= max_strike])[:15]
        print(f"Strikes ({len(strikes)}): {strikes}")

        # 7️⃣ Put-Contracts sammeln
        all_contracts = []
        for exp in selected_exps:
            for strike in strikes:
                contract = Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol)
                all_contracts.append(contract)

        print(f"Qualifiziere {len(all_contracts)} Put-Contracts...")
        qualified = ib.qualifyContracts(*all_contracts)
        print(f"{len(qualified)} Contracts qualifiziert")

        # 8️⃣ Marktdaten (Snapshot) holen
        tickers = []
        for c in qualified:
            t = ib.reqMktData(c, snapshot=True)
            tickers.append(t)
        ib.sleep(10)

        # 9️⃣ Daten sammeln
        rows = []
        for t in tickers:
            c = t.contract
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

            ask_strike_ratio = round((ask / c.strike) * 100, 4) if (ask and c.strike) else None

            row: Dict[str, Any] = {
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
            rows.append(row)

        # Sortieren nach Strike für konsistente Reihenfolge
        rows.sort(key=lambda r: float(r['strike']))

        # --------------------------------------------------------------
        # CSV-Ausgabe (falls gewünscht)
        # --------------------------------------------------------------
        if out_csv:
            out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
            fieldnames = ['conid', 'symbol', 'right', 'strike', 'expiry',
                          'bid', 'ask', 'last', 'volume', 'open_interest',
                          'delta', 'gamma', 'theta', 'ask_strike_ratio']
            with open(out_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"CSV gespeichert: {out_path}")
            print(f"{len(rows)} Put-Optionen")

        # 12️⃣ Markdown-Ausgabe (falls angefordert)
        if out_md:
            md_lines = []
            md_lines.append(f"# {ticker_symbol} – Options‑Chain (Min. 18 Tage)")
            md_lines.append("")
            md_lines.append("## Zusammenfassung")
            md_lines.append(f"- **Aktueller Kurs:** ${current_price:.2f}")
            md_lines.append(f"- **Verfallsdaten (≥ 18 Tage):** {', '.join(selected_exps)}")
            md_lines.append(f"- **Strikes (15 Stk., ±15 % um den Kurs):** {strikes}")
            md_lines.append("")
            md_lines.append("## Put‑Options‑Chain")
            md_lines.append("")
            md_lines.append("### Chain‑Informationen")
            md_lines.append(f"- **Exchange:** {chain.exchange}")
            md_lines.append(f"- **Trading‑Class:** {chain.tradingClass}")
            md_lines.append(f"- **Anzahl verfügbarer Strikes:** {len(chain.strikes)}")
            md_lines.append(f"- **Verfügbare Verfallsdaten:** {', '.join(chain.expirations)}")
            md_lines.append("")

            md_lines.append("## Put‑Options‑Chain – Detailtabelle")
            md_lines.append("")
            md_lines.append("| Expiry | Strike | Bid | Ask | Delta | Gamma | Theta | Vol |")
            md_lines.append("|--------|-------|-----|-----|-------|-------|-------|-----|")
            for row in rows:
                bid_str = f"{row['bid']:>6}" if row['bid'] is not None else "   None"
                ask_str = f"{row['ask']:>5}" if row['ask'] is not None else "  None"
                delta_str = f"{row['delta']:>8}" if row['delta'] is not None else "      None"
                gamma_str = f"{row['gamma']:>5}" if row['gamma'] is not None else "   None"
                theta_str = f"{row['theta']:>5}" if row['theta'] is not None else "   None"
                vol_str = f"{row['volume']:>8}" if row['volume'] is not None else "     None"
                md_lines.append(
                    f"| {str(row['expiry']):<12} | {row['strike']:>7.1f} | "
                    f"{bid_str} | {ask_str} | {delta_str} | {gamma_str} | {theta_str} | {vol_str} |"
                )
            md_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))
            print(f"Markdown gespeichert: {md_path}")

        return True

    except Exception as e:
        print(f"Fehler: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        ib.disconnect()
        print("Verbindung geschlossen")

# ----------------------------------------------------------------------
# Argument-Parser – Flags und Ticker
# ----------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    flag_csv = "--csv" in args
    flag_md = "--md" in args

    # Ticker ist das erste Argument, das nicht mit '--' beginnt
    ticker = None
    for a in args:
        if a not in ("--csv", "--md"):
            ticker = a
            break

    if not ticker:
        print("Usage: python spy_options_chain.py <TICKER> [--csv|--md] ...")
        print("If no flag is provided, CSV is generated by default.")
        sys.exit(1)

    # Aufruf mit den Flags
    process_ticker(ticker, out_md=flag_md, out_csv=flag_csv)
