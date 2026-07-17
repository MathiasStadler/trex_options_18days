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
        # Mapping von gängigen Symbolen zu ihren offiziellen Namen
        symbol_to_name = {
            'SPY': 'S&P 500',
            'QQQ': 'Nasdaq 100',
            'IWM': 'Russell 2000',
            'DE': 'DAX',
            'DJI': 'Dow Jones',
            'NDX': 'Nasdaq',
        }
        real_name = symbol_to_name.get(ticker_symbol.upper(), ticker_symbol.upper())
        
        lines = [f"# {ticker_symbol} – Options-Chain (Min. 18 Tage)\n"]
        lines.append("## Zusammenfassung\n")
        lines.append(f"- Aktueller Kurs: ${current_price:.2f}\n")
        lines.append(f"- Real Name: {real_name}\n")
        lines.append(f"- Verfallsdaten: {', '.join(selected_exps)}\n")
        lines.append(f"- Strikes: {len(set(r['strike'] for r in rows))} | Optionen gesamt: {len(rows)}\n")
        lines.append("")
        lines.append("## Kategorien\n")
        lines.append("| Kategorie | Anzahl |\n")
        lines.append("|-----------|--------|\n")
        for k, v in cats.items():
            lines.append(f"| {k} | {len(v)} |\n")
        lines.append("\n")