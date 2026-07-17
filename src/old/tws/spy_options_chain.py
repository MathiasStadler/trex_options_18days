#!/usr/bin/env python3
"""SPY Options Chain Fetcher - Min 18 days, dynamic strike selection
Fetches put options with bid/ask, delta, gamma, theta, volume, open_interest
Uses IBKR Web API v1.0 via local gateway (http://127.0.0.1:4002) without token auth.
"""

import sys
import csv
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests

# ==================== CONFIGURATION ====================
API_BASE = "http://127.0.0.1:4002/api"  # Local gateway endpoint
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # Exponential backoff: 2s, 4s, 8s

# ==================== ZENTRALE REQUEST-METHODE ====================
def request_api(
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Zentrale Methode für alle API-Anfragen an den lokalen Gateway.
    Unterstützt Wiederholungen mit exponentiellen Pausen.
    """
    url = f"{API_BASE}{endpoint}"
    for attempt in range(MAX_RETRIES):
        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=10)
            elif method.upper() == "POST":
                response = requests.post(url, data=data, json=json_data, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:  # Rate limit
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAYS[attempt]
                    print(f"Rate limit hit, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(wait)
                    continue
            else:
                print(f"HTTP {response.status_code}: {response.text}")
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAYS[attempt]
                    time.sleep(wait)
                    continue

            # If we reach here, the request failed
            return None

        except requests.exceptions.RequestException as e:
            print(f"Request error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAYS[attempt]
                time.sleep(wait)
            else:
                raise

    return None


# ==================== HILFSFUNKTIONEN ====================
def safe_float(v: Optional[Any]) -> Optional[float]:
    """Konvertiert einen Wert in float, gibt None bei Fehler zurück."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (ValueError, TypeError):
        return None


def safe_int(v: Optional[Any]) -> Optional[int]:
    """Konvertiert einen Wert in int, gibt None bei Fehler zurück."""
    f = safe_float(v)
    return int(f) if f is not None else None


def validate_field(value: Any, field_name: str) -> bool:
    """Validiert, dass ein Feld nicht None oder leer ist."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


# ==================== HAUPTFUNKTION ====================
def process_ticker(ticker_symbol: str, out_md: bool = False, out_csv: bool = False) -> bool:
    """Fetch and display options chain for a ticker using the IBKR Web API v1.0."""
    
    # 1️⃣ Qualify underlying contract
    stock_params = {
        "symbol": ticker_symbol,
        "secType": "STK",
        "exchange": "SMART",
        "currency": "USD",
    }
    stock_data = request_api("/v1/contracts/qualify", params=stock_params)
    if not stock_data or len(stock_data) == 0:
        print(f"Could not qualify contract for {ticker_symbol}")
        return False
    
    contract = stock_data[0]
    conId = contract.get("conId")
    if not validate_field(conId, "conId"):
        print(f"Invalid conId for {ticker_symbol}")
        return False
    print(f"{ticker_symbol} conId: {conId}")

    # 2️⃣ Get current market price (snapshot)
    price_params = {
        "symbols": ticker_symbol,
        "snapshot": "true",
    }
    price_data = request_api("/v1/marketdata/quotes", params=price_params)
    if not price_data:
        print(f"Could not fetch market data for {ticker_symbol}")
        return False
    
    quotes = price_data.get("quotes", [])
    if not quotes or len(quotes) == 0:
        print(f"No quote data for {ticker_symbol}")
        return False
    
    quote = quotes[0]
    current_price = safe_float(quote.get("last"))
    if not validate_field(current_price, "last price") or current_price <= 0:
        print(f"Invalid price for {ticker_symbol}")
        return False
    print(f"Current {ticker_symbol} price: ${current_price:.2f}")

    # 3️⃣ Get option chain parameters
    opt_params = {
        "symbol": ticker_symbol,
        "secType": "OPT",
        "exchange": "SMART",
        "currency": "USD",
    }
    opt_resp = request_api("/v1/secdef/optparams", params=opt_params)
    if not opt_resp or len(opt_resp) == 0:
        print("No option chain found")
        return False
    
    chain = opt_resp[0]
    chain_exchange = chain.get("exchange", "SMART")
    chain_trading_class = chain.get("tradingClass", ticker_symbol)
    chain_strikes = chain.get("strikes", [])
    chain_expirations = chain.get("expirations", [])
    
    print(f"Chain: {chain_exchange}, strikes: {len(chain_strikes)}")

    # 4️⃣ Filter expirations >= 18 days
    today = datetime.now()
    valid_expirations: List[str] = []
    for exp in chain_expirations:
        try:
            exp_date = datetime.strptime(exp, "%Y%m%d")
            dte = (exp_date - today).days
            if dte >= 18:
                valid_expirations.append(exp)
        except Exception:
            continue
    
    if not valid_expirations:
        print("No expirations >= 18 days")
        return False
    
    selected_exps = valid_expirations[:3]
    print(f"Selected expirations (>=18d): {selected_exps}")

    # 5️⃣ Dynamic strike selection (±15% of current price)
    min_strike = int(current_price * 0.85)
    max_strike = int(current_price * 1.15)
    strikes = [s for s in chain_strikes if min_strike <= s <= max_strike][:15]
    print(f"Selected strikes (±15%): {strikes}")

    # 6️⃣ Build put option contracts and fetch market data
    rows: List[Dict[str, Any]] = []
    
    for exp in selected_exps:
        for strike in strikes:
            # Get market data for this specific option
            # We need to identify the option by its parameters
            option_params = {
                "symbol": ticker_symbol,
                "lastTradeDateOrContractMonth": exp,
                "strike": strike,
                "right": "P",
            }
            
            # Request market data for this option
            md_data = request_api("/v1/marketdata/quotes", params=option_params)
            if not md_data:
                continue
            
            quote_list = md_data.get("quotes", [])
            if not quote_list:
                continue
            
            opt_quote = quote_list[0]
            
            # Validate all required fields
            bid = safe_float(opt_quote.get("bid"))
            ask = safe_float(opt_quote.get("ask"))
            last = safe_float(opt_quote.get("last"))
            volume = safe_int(opt_quote.get("volume"))
            oi = safe_int(opt_quote.get("openInterest"))
            
            # Get Greeks
            greeks = opt_quote.get("greeks", {})
            delta = safe_float(greeks.get("delta"))
            gamma = safe_float(greeks.get("gamma"))
            theta = safe_float(greeks.get("theta"))
            
            ask_strike_ratio = round((ask / strike) * 100, 4) if (ask and strike) else None
            
            # Get contract ID if available
            opt_conid = opt_quote.get("conId") or opt_quote.get("contract", {}).get("conId")
            
            row: Dict[str, Any] = {
                "conid": opt_conid,
                "symbol": ticker_symbol,
                "right": "P",
                "strike": strike,
                "expiry": exp,
                "bid": bid,
                "ask": ask,
                "last": last,
                "volume": volume,
                "open_interest": oi,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "ask_strike_ratio": ask_strike_ratio,
            }
            rows.append(row)

    # Sort by strike for consistent ordering
    rows.sort(key=lambda r: float(r["strike"]))

    # --------------------------------------------------------------
    # CSV output
    # --------------------------------------------------------------
    if out_csv:
        out_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.csv"
        fieldnames = [
            "conid", "symbol", "right", "strike", "expiry",
            "bid", "ask", "last", "volume", "open_interest",
            "delta", "gamma", "theta", "ask_strike_ratio",
        ]
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV saved: {out_path}")
        print(f"{len(rows)} Put options written")

    # --------------------------------------------------------------
    # Markdown output
    # --------------------------------------------------------------
    if out_md:
        md_lines = []
        md_lines.append(f"# {ticker_symbol} – Options Chain (Min. 18 Tage)")
        md_lines.append("")
        md_lines.append("## Zusammenfassung")
        md_lines.append(f"- **Aktuellster Kurs:** ${current_price:.2f}")
        md_lines.append(f"- **Verfallsdaten (≥ 18 Tage):** {', '.join(selected_exps)}")
        md_lines.append(f"- **Strikes (±15 % des Kurses):** {strikes}")
        md_lines.append("")
        md_lines.append("## Put-Options-Chain")
        md_lines.append("")
        md_lines.append("### Chain-Informationen")
        md_lines.append(f"- **Exchange:** {chain_exchange}")
        md_lines.append(f"- **Trading-Class:** {chain_trading_class}")
        md_lines.append(f"- **Verfügbare Strikes:** {len(chain_strikes)}")
        md_lines.append(f"- **Verfügbare Verfallsdaten:** {', '.join(chain_expirations)}")
        md_lines.append("")
        md_lines.append("## Detailtabelle")
        md_lines.append("")
        md_lines.append("| Expiry | Strike | Bid | Ask | Delta | Gamma | Theta | Volume |")
        md_lines.append("|--------|--------|-----|-----|-------|-------|-------|------|")
        for row in rows:
            bid_str = f"{row['bid']:>6}" if row["bid"] is not None else "   None"
            ask_str = f"{row['ask']:>5}" if row["ask"] is not None else "  None"
            delta_str = f"{row['delta']:>8}" if row["delta"] is not None else "      None"
            gamma_str = f"{row['gamma']:>5}" if row["gamma"] is not None else "   None"
            theta_str = f"{row['theta']:>5}" if row["theta"] is not None else "   None"
            vol_str = f"{row['volume']:>8}" if row["volume"] is not None else "     None"
            md_lines.append(
                f"| {row['expiry']:<12} | {row['strike']:>7.1f} | {bid_str} | {ask_str} | {delta_str} | {gamma_str} | {theta_str} | {vol_str} |"
            )
        md_path = f"/home/hermes/{ticker_symbol.lower()}_options_18days.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        print(f"Markdown gespeichert: {md_path}")

    return True


# ==================== CLI HANDLING ====================
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