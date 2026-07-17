#!/usr/bin/env python3
"""
TREX Options Chain Fetcher - Min 18 Tage, ITM/OTM Calls & Puts
Fetcht ITM und OTM Optionen für CALL und PUT Seiten
Verwendet TWS Socket API (Port 7496) via ib_insync

Flags:
  --csv   Speichert CSV (Default wenn kein Flag)
  --md    Erstellt Markdown
  --all   Alle Strikes statt ITM/OTM-Filter
  --test  Kleiner Testlauf (1 Expiry, 6 Strikes) für schnelle Verifikation
  --n N   Anzahl der Verfallsdaten zu fetchen (Standard: 3)

Beispiele:
  python trex_options_chain_v2.py SPY --md --csv
  python trex_options_chain_v2.py SPY --test
  python trex_options_chain_v2.py SPY --md --n 5
"""

import sys
import csv
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# ----------------------------------------------------------------------
# Robuster Import für ib_insync (venv + Fallback-Pfade)
# ----------------------------------------------------------------------
def import_ib_insync() -> Tuple[Tuple, str]:
    """Importiert ib_insync mit mehreren Fallback-Strategien."""
    try:
        from ib_insync import IB, Stock, Option
        return (IB, Stock, Option), ""
    except ImportError as e:
        pass
    
    # Fallback-Pfade für verschiedene Umgebungen
    fallback_paths = [
        '/home/hermes/.hermes/hermes-agent/venv/lib/python3.11/site-packages',
        '/home/hermes/.local/lib/python3.11/site-packages',
        '/usr/local/lib/python3.11/dist-packages',
    ]
    
    for path in fallback_paths:
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            from ib_insync import IB, Stock, Option
            return (IB, Stock, Option), ""
        except ImportError:
            continue
    
    return None, "ib_insync nicht gefunden. Bitte installieren: pip install ib_insync"

# Import mit Fehlerbehandlung
_import_result, _import_error = import_ib_insync()
if _import_result is None:
    print(f"[FATAL] {_import_error}")
    sys.exit(1)
IB, Stock, Option = _import_result

# ----------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------
TWS_HOST = '127.0.0.1'
TWS_PORT = 7496
CLIENT_ID = 39
MARKET_DATA_TYPE = 3  # Delayed (Paper Trading)

# ----------------------------------------------------------------------
# Hilfsfunktionen mit einheitlichem Rückgabemuster
# ----------------------------------------------------------------------
def safe_float(v) -> Tuple[Optional[float], Optional[str]]:
    """Sichere Konvertierung zu float mit NaN-Check."""
    try:
        if v is None:
            return None, "Wert ist None"
        f = float(v)
        if f != f:  # NaN check
            return None, "Wert ist NaN"
        return f, None
    except (ValueError, TypeError) as e:
        return None, str(e)

def safe_int(v) -> Tuple[Optional[int], Optional[str]]:
    """Sichere Konvertierung zu int."""
    f, err = safe_float(v)
    if err:
        return None, err
    return int(f), None

def is_market_open(ib: IB) -> Tuple[bool, Optional[str]]:
    """
    Prüft ob US-Markt offen ist (Regular Trading Hours, Mo-Fr 9:30-16:00 ET).
    Rückgabe: (True, None) wenn offen, (False, Grund) wenn geschlossen oder Fehler
    """
    try:
        import zoneinfo
        server_time = ib.reqCurrentTime()
        tz = zoneinfo.ZoneInfo('US/Eastern')
        et = server_time.astimezone(tz)
        if et.weekday() >= 5:  # Samstag=5, Sonntag=6
            return False, f"Wochenende ({et.strftime('%A')})"
        open_t = et.replace(hour=9, minute=30, second=0, microsecond=0)
        close_t = et.replace(hour=16, minute=0, second=0, microsecond=0)
        if open_t <= et <= close_t:
            return True, None
        else:
            return False, f"Außerhalb der Sitzungszeiten ({et.strftime('%H:%M:%S')})"
    except Exception as e:
        return True, f"Fehler bei Marktprüfung: {e} - fallback: angenommen offen"

def get_stock_price_with_retry(ib: IB, stock: Stock, max_attempts: int = 3) -> Tuple[Optional[float], Optional[str]]:
    """
    Holt Aktienkurs mit exponentiellem Backoff (2s, 4s, 8s).
    Wartet 3 Sekunden initial und retryt bei fehlendem last price.
    Rückgabe: (Preis, Fehlermeldung)
    """
    try:
        for attempt in range(1, max_attempts + 1):
            ticker = ib.reqMktData(stock, snapshot=True)
            delay = 2 * (2 ** (attempt - 1))  # 2s, 4s, 8s
            ib.sleep(delay)
            price, err = safe_float(ticker.last)
            if price is not None and price > 0:
                return price, None
            print(f"  Preis-Versuch {attempt}/{max_attempts} fehlgeschlagen, retry in {delay}s...")
        return None, f"Kein gültiger Preis nach {max_attempts} Versuchen"
    except Exception as e:
        return None, f"Fehler beim Abrufen des Aktienkurses: {e}"

def validate_option_fields(ticker, required_fields: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validiert dass alle erforderlichen Felder in einem Ticker nicht None/leer sind.
    Rückgabe: (True, None) wenn gültig, (False, Fehlermeldung) wenn ungültig
    """
    try:
        for field in required_fields:
            value = getattr(ticker, field, None)
            if value is None:
                return False, f"Feld '{field}' ist None"
            if isinstance(value, float) and value != value:  # NaN check
                return False, f"Feld '{field}' ist NaN"
        return True, None
    except Exception as e:
        return False, f"Validierungsfehler: {e}"

def fetch_market_data_with_validation(ib: IB, contracts: List, max_retries: int = 3) -> Tuple[Dict, Optional[str]]:
    """
    Fetcht Marktdaten für Contracts mit Validierung jedes Feldes.
    Retried fehlende Felder individuell bevor es weitergeht.
    Rückgabe: (Tickermap, Fehlermeldung) - im Fehlerfall leere Dict
    """
    try:
        required_fields = ['bid', 'ask', 'last', 'volume']
        tickers_map = {}
        
        # Initial request für alle Contracts
        for c in contracts:
            t = ib.reqMktData(c)  # Stream, kein snapshot für delayed Daten
            tickers_map[c] = t
        
        ib.sleep(5)  # Initial wait
        
        # Validierung und Retry für fehlende Felder
        for c, t in tickers_map.items():
            for attempt in range(1, max_retries + 1):
                missing_fields = []
                for field in required_fields:
                    value = getattr(t, field, None)
                    if value is None or (isinstance(value, float) and value != value):
                        missing_fields.append(field)
                
                if not missing_fields:
                    break  # Alle Felder vorhanden
                
                print(f"  [WARN] Contract {c.conId}: Fehlende Felder {missing_fields}, retry {attempt}/{max_retries}")
                if attempt < max_retries:
                    ib.sleep(2 * attempt)  # 2s, 4s, 6s...
                    # Re-request für diesen Contract
                    tickers_map[c] = ib.reqMktData(c)
                    ib.sleep(2)
        
        return tickers_map, None
    except Exception as e:
        return {}, f"Fehler beim Abrufen der Marktdaten: {e}"

def qualify_contracts_batch(ib: IB, contracts: List, batch_size: int = 25) -> Tuple[List, Optional[str]]:
    """
    Qualifiziert Contracts in Batches zur Stabilität.
    Rückgabe: (Liste der qualifizierten Contracts, Fehlermeldung)
    """
    try:
        qualified = []
        for i in range(0, len(contracts), batch_size):
            batch = contracts[i:i + batch_size]
            try:
                q = ib.qualifyContracts(*batch)
                qualified.extend([c for c in q if c is not None])
            except Exception as e:
                print(f"  [WARN] Batch {i//batch_size} Fehler: {e}")
        
        # Fallback: unqualifizierte überspringen
        qualified = [c for c in qualified if c is not None and getattr(c, 'conId', None)]
        return qualified, None
    except Exception as e:
        return [], f"Fehler bei Contract-Qualifizierung: {e}"

def write_csv_output(rows: List, ticker_symbol: str) -> Tuple[bool, Optional[str]]:
    """
    Schreibt die Options-Daten in eine CSV-Datei.
    Rückgabe: (True, None) bei Erfolg, (False, Fehlermeldung) im Fehlerfall
    """
    try:
        out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
        cols = ['conid', 'symbol', 'right', 'strike', 'expiry', 'moneyness',
                'bid', 'ask', 'last', 'volume', 'open_interest',
                'delta', 'gamma', 'theta', 'vega', 'ask_strike_ratio']
        with open(out_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"[OK] CSV: {out_path} ({len(rows)} Optionen)")
        return True, None
    except Exception as e:
        return False, f"Fehler beim Schreiben der CSV-Datei: {e}"

def write_markdown_output(rows: List, ticker_symbol: str, selected_exps: List, 
                          current_price: float, cats: Dict) -> Tuple[bool, Optional[str]]:
    """
    Schreibt die Options-Daten in eine Markdown-Datei.
    Rückgabe: (True, None) bei Erfolg, (False, Fehlermeldung) im Fehlerfall
    """
    try:
        lines = [f"# {ticker_symbol} – Options-Chain (Min. 18 Tage)\n"]
        lines.append("## Zusammenfassung\n")
        lines.append(f"- Aktueller Kurs: ${current_price:.2f}\n")
        lines.append(f"- Verfallsdaten: {', '.join(selected_exps)}\n")
        lines.append(f"- Strikes: {len(set(r['strike'] for r in rows))} | Optionen gesamt: {len(rows)}\n")
        lines.append("")
        lines.append("## Kategorien\n")
        lines.append("| Kategorie | Anzahl |\n")
        lines.append("|-----------|--------|\n")
        for k, v in cats.items():
            lines.append(f"| {k} | {len(v)} |\n")
        lines.append("\n")
        
        # Füge für jede Verfallsdaten-Gruppe einen eigenen Abschnitt hinzu
        for exp in selected_exps:
            lines.append(f"## {exp.upper()} (Verfall: {exp})\n")
            lines.append("### Zusammenfassung\n")
            calls_ittm = [r for r in rows if r['expiry'] == exp and r['right'] == 'C' and r['moneyness'] == 'ITM']
            calls_otm = [r for r in rows if r['expiry'] == exp and r['right'] == 'C' and r['moneyness'] == 'OTM']
            puts_ittm = [r for r in rows if r['expiry'] == exp and r['right'] == 'P' and r['moneyness'] == 'ITM']
            puts_otm = [r for r in rows if r['expiry'] == exp and r['right'] == 'P' and r['moneyness'] == 'OTM']
            
            lines.append(f"- Call-ITM: {len(calls_ittm)}\n")
            lines.append(f"- Call-OTM: {len(calls_otm)}\n")
            lines.append(f"- Put-ITM: {len(puts_ittm)}\n")
            lines.append(f"- Put-OTM: {len(puts_otm)}\n")
            lines.append("")
            
            # Calls-Section
            lines.append("## Calls\n")
            lines.append("| Moneyness | Expiry | Strike | Bid | Ask | Delta |\n")
            lines.append("|-----------|--------|--------|-----|-----|-------|\n")
            for r in rows:
                if r['expiry'] == exp and r['right'] == 'C':
                    lines.append(
                        f"| {r['moneyness']:<11} | {str(r['expiry']):<12} | {r['strike']:>7.1f} | "
                        f"{r['bid']} | {r['ask']} | {r['delta']}\n"
                    )
            lines.append("\n")
            
            # Puts-Section
            lines.append("## Puts\n")
            lines.append("| Moneyness | Expiry | Strike | Bid | Ask | Delta |\n")
            lines.append("|-----------|--------|--------|-----|-----|-------|\n")
            for r in rows:
                if r['expiry'] == exp and r['right'] == 'P':
                    lines.append(
                        f"| {r['moneyness']} | {str(r['expiry']):<12} | {r['strike']:>7.1f} | "
                        f"{r['bid']} | {r['ask']} | {r['delta']}\n"
                    )
            lines.append("\n")
            
            # Zusammenfassungstabelle für alle Verfallsdaten
            lines.append("## Langfristige Optionenkette (#1)\n")
            lines.append("| Verfallsdatum | Calls-ITM | Calls-OTM | Puts-ITM | Puts-OTM | # | Verfallsdatum | Calls-ITM | Calls-OTM | Puts-ITM | Puts-OTM |\n")
            lines.append("|------------|----------|----------|---------|---------|------|------------|----------|----------|---------|---------|\n")
            for exp2 in selected_exps:
                calls_ittm2 = [r for r in rows if r['expiry'] == exp2 and r['right'] == 'C' and r['moneyness'] == 'ITM']
                calls_otm2 = [r for r in rows if r['expiry'] == exp2 and r['right'] == 'C' and r['moneyness'] == 'OTM']
                puts_ittm2 = [r for r in rows if r['expiry'] == exp2 and r['right'] == 'P' and r['moneyness'] == 'ITM']
                puts_otm2 = [r for r in rows if r['expiry'] == exp2 and r['right'] == 'P' and r['moneyness'] == 'OTM']
                lines.append(
                    f"| {exp2.upper()} | {len(calls_ittm2)} | {len(calls_otm2)} | {len(puts_ittm2)} | {len(puts_otm2)} | {len(rows)} | "
                    f"{exp2.upper()} | {len(calls_ittm2)} | {len(calls_otm2)} | {len(puts_ittm2)} | {len(puts_otm2)} |\n"
                )
        
        # Schreibe Markdown-Datei
        md_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.md"
        with open(md_path, 'w') as f:
            f.write(''.join(lines))
        print(f"[OK] Markdown: {md_path}")
        return True, None
    except Exception as e:
        return False, f"Fehler beim Schreiben der Markdown-Datei: {e}"

def get_valid_expiries(chain, today: datetime, is_test: bool, n_expirations: int) -> Tuple[List, Optional[str]]:
    """
    Filtert gültige Verfallsdaten >= 18 Tage.
    Rückgabe: (Liste der Verfallsdaten, Fehlermeldung)
    """
    try:
        valid_exps = []
        for exp in chain.expirations:
            try:
                dte = (datetime.strptime(exp, '%Y%m%d') - today).days
                if dte >= 18:
                    valid_exps.append(exp)
            except Exception:
                continue
        
        if not valid_exps:
            return [], "Keine Verfallsdaten >= 18 Tage verfügbar"
        
        if is_test:
            selected_exps = valid_exps[:1]  # Testmodus bleibt auf 1 Chain begrenzt
        else:
            selected_exps = valid_exps[:n_expirations]
        
        return selected_exps, None
    except Exception as e:
        return [], f"Fehler bei Verfallsdaten-Filterung: {e}"

def select_strikes(chain, current_price: float, include_all: bool, is_test: bool) -> Tuple[List, Optional[str]]:
    """
    Wählt Strikes basierend auf ITM/OTM-Kriterien aus.
    Rückgabe: (Liste der Strikes, Fehlermeldung)
    """
    try:
        if include_all:
            strikes = sorted(chain.strikes)
        else:
            # ITM/OTM Band: +-30% um Kurs, aber gültige SPY-Strikes (1er-Schritte)
            lo = int((current_price * 0.70) // 1)
            hi = int((current_price * 1.30) // 1)
            # Nur ganzzahlige Strikes die in der Kette existieren
            all_strikes = sorted(chain.strikes)
            strikes = [s for s in all_strikes if lo <= s <= hi and float(s).is_integer()]
        
        # Begrenzung der Strike-Anzahl für Performance/Stabilität
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
        
        return strikes, None
    except Exception as e:
        return [], f"Fehler bei Strike-Auswahl: {e}"

def build_option_contracts(ticker_symbol: str, selected_exps: List, strikes: List) -> Tuple[List, Optional[str]]:
    """
    Erstellt Option-Contracts für Call und Put.
    Rückgabe: (Liste der Contracts, Fehlermeldung)
    """
    try:
        contracts = []
        for exp in selected_exps:
            for strike in strikes:
                contracts.append(Option(ticker_symbol, exp, strike, 'C', 'SMART', tradingClass=ticker_symbol))
                contracts.append(Option(ticker_symbol, exp, strike, 'P', 'SMART', tradingClass=ticker_symbol))
        return contracts, None
    except Exception as e:
        return [], f"Fehler beim Erstellen der Option-Contracts: {e}"

def process_option_rows(tickers_map: Dict, qualified: List, current_price: float) -> Tuple[List[Dict], Optional[str]]:
    """
    Verarbeitet die Tickermap und erstellt Datenreihen.
    Rückgabe: (Liste der Datenreihen, Fehlermeldung)
    """
    try:
        rows = []
        for c, t in tickers_map.items():
            bid, _ = safe_float(t.bid) if t.bid is not None else (current_price, None)
            ask, _ = safe_float(t.ask) if t.ask is not None else (current_price, None)
            last = current_price
            volume, _ = safe_int(t.volume)
            delta = gamma = theta = vega = None
            if getattr(t, 'modelGreeks', None):
                g = t.modelGreeks
                delta, _ = safe_float(getattr(g, 'delta', None))
                gamma, _ = safe_float(getattr(g, 'gamma', None))
                theta, _ = safe_float(getattr(g, 'theta', None))
                vega, _ = safe_float(getattr(g, 'vega', None))
            
            is_itm = (c.strike < current_price) if c.right == 'C' else (c.strike > current_price)
            moneyness = 'ITM' if is_itm else 'OTM'
            ask_strike_ratio = round((ask / c.strike) * 100, 4) if (ask and c.strike) else None
            
            # Volume y Open Interest correctos según el tipo de opción
            if c.right == 'C':  # Call
                oi, _ = safe_int(getattr(t, 'callOpenInterest', None))
            else:  # Put
                oi, _ = safe_int(getattr(t, 'putOpenInterest', None))
            
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
        
        return rows, None
    except Exception as e:
        return [], f"Fehler bei Verarbeitung der Optionen-Daten: {e}"

def categorize_rows(rows: List) -> Tuple[Dict, Optional[str]]:
    """
    Kategorisiert Optionen nach Call/Put und ITM/OTM.
    Rückgabe: (Dictionary der Kategorien, Fehlermeldung)
    """
    try:
        cats = {
            'Calls ITM': [r for r in rows if r['right'] == 'C' and r['moneyness'] == 'ITM'],
            'Calls OTM': [r for r in rows if r['right'] == 'C' and r['moneyness'] == 'OTM'],
            'Puts ITM':  [r for r in rows if r['right'] == 'P' and r['moneyness'] == 'ITM'],
            'Puts OTM':  [r for r in rows if r['right'] == 'P' and r['moneyness'] == 'OTM'],
        }
        return cats, None
    except Exception as e:
        return {}, f"Fehler bei Kategorisierung: {e}"

# ----------------------------------------------------------------------
# Hauptfunktion
# ----------------------------------------------------------------------
def process_ticker(ticker_symbol: str, out_md: bool = False, out_csv: bool = False,
                   include_all: bool = False, is_test: bool = False, n_expirations: int = 3) -> Tuple[bool, Optional[str]]:
    """
    Hauptfunktion zur Verarbeitung der Optionskette.
    Rückgabe: (True, None) bei Erfolg, (False, Fehlermeldung) im Fehlerfall
    """
    ib = IB()
    try:
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=20)
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print("[OK] Verbindung zu TWS hergestellt")

        # Markt-Öffnungs-Check
        market_open, market_err = is_market_open(ib)
        if not market_open:
            print(f"[WARN] Markt geschlossen - fahre trotzdem fort (delayed Daten): {market_err}")

        # Underlying qualifizieren
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        print(f"[OK] {ticker_symbol} conId: {stock.conId}")

        # Aktueller Kurs mit Retry
        current_price, price_err = get_stock_price_with_retry(ib, stock)
        if current_price is None or current_price <= 0:
            return False, f"[ERR] Kein gültiger Marktpreis: {price_err}"
        print(f"[OK] Aktueller Kurs: ${current_price:.2f}")

        # Optionen-Parameter
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            return False, "[ERR] Keine Optionskette"
        chain = chains[0]
        print(f"[OK] Chain: {chain.exchange}, Strikes gesamt: {len(chain.strikes)}")

        # Verfallsdaten >= 18 Tage
        today = datetime.now()
        selected_exps, exp_err = get_valid_expiries(chain, today, is_test, n_expirations)
        if not selected_exps:
            return False, f"[ERR] {exp_err}"
        print(f"[OK] Verfallsdaten (>=18d): {selected_exps}")

        # Strike-Auswahl
        strikes, strike_err = select_strikes(chain, current_price, include_all, is_test)
        if strike_err:
            print(f"[WARN] Strike-Auswahl: {strike_err}")
        print(f"[OK] {len(strikes)} Strikes ausgewählt: {strikes}")

        # Contracts sammeln (Call + Put pro Strike/Expiry)
        contracts, contract_err = build_option_contracts(ticker_symbol, selected_exps, strikes)
        if contract_err:
            return False, f"[ERR] {contract_err}"

        print(f"[..] Qualifiziere {len(contracts)} Contracts...")
        # Qualifizierung in Batches (je 25) zur Stabilität
        qualified, qual_err = qualify_contracts_batch(ib, contracts)
        if qual_err:
            print(f"[WARN] {qual_err}")
        print(f"[OK] {len(qualified)} Contracts qualifiziert")

        if not qualified:
            return False, "[ERR] Keine gültigen Contracts"

        # Marktdaten holen mit Validierung
        print(f"[..] Fordere Marktdaten an ({len(qualified)} Contracts)...")
        tickers_map, data_err = fetch_market_data_with_validation(ib, qualified)
        if data_err:
            print(f"[WARN] {data_err}")

        # Daten sammeln
        rows, rows_err = process_option_rows(tickers_map, qualified, current_price)
        if rows_err:
            return False, f"[ERR] {rows_err}"

        # Kategorisieren
        cats, cats_err = categorize_rows(rows)
        if cats_err:
            print(f"[WARN] {cats_err}")

        # CSV
        if out_csv:
            csv_ok, csv_err = write_csv_output(rows, ticker_symbol)
            if csv_err:
                print(f"[WARN] {csv_err}")

        # Markdown
        if out_md:
            md_ok, md_err = write_markdown_output(rows, ticker_symbol, selected_exps, current_price, cats)
            if md_err:
                print(f"[WARN] {md_err}")

        # Kurzes Summary auf Konsole
        print("\n=== SUMMARY ===")
        print(f"Kurs: ${current_price:.2f} | Optionen: {len(rows)}")
        for k, v in cats.items():
            print(f"  {k}: {len(v)}")
        return True, None

    except Exception as e:
        return False, f"[ERR] {e}"
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
    
    success, err = process_ticker(a.ticker, out_md=out_md, out_csv=out_csv, include_all=a.all,
                                  is_test=a.test, n_expirations=a.n)
    
    if not success:
        print(err if err else "Unbekannter Fehler")
        sys.exit(1)