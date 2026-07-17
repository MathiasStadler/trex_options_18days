#!/usr/bin/env python3
"""
TREX Options Chain Fetcher - Min 18 Tage
Verwendet ib_insync (wie der funktionierende TTM Squeeze Scanner)
"""

from __future__ import annotations
import sys
import os
import csv
import json
import time
import logging
import urllib3
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict, Tuple, List
from pathlib import Path

from ib_insync import IB, Option, Stock, util

# ----------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    """Konfiguration für den TREX Options-Chain-Fetcher."""
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7496  # TWS Client Port
    client_id: int = 1
    request_timeout: int = 15
    max_retries: int = 5
    retry_base_delay: float = 2.0
    retry_max_delay: float = 60.0
    csv_output: str = "./trex_options_18days.csv"
    log_level: int = logging.INFO
    log_format: str = "%(asctime)s - %(levelname)s : %(lineno)d - %(message)s"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            ibkr_host=os.getenv("IBKR_HOST", "127.0.0.1"),
            ibkr_port=int(os.getenv("IBKR_PORT", "7496")),
            client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
            request_timeout=int(os.getenv("IBKR_TIMEOUT", "15")),
            max_retries=int(os.getenv("IBKR_MAX_RETRIES", "5")),
            log_level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        )


# ----------------------------------------------------------------------
# Result Type
# ----------------------------------------------------------------------
@dataclass
class Result:
    """Ergebnis-Container für API-Aufrufe."""
    ok: bool
    data: Any = None
    error: Optional[str] = None

    @classmethod
    def success(cls, data: Any) -> "Result":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str) -> "Result":
        return cls(ok=False, error=error)

    def unwrap(self) -> Any:
        if not self.ok:
            raise RuntimeError(f"Result is error: {self.error}")
        return self.data


# ----------------------------------------------------------------------
# Domain Models
# ----------------------------------------------------------------------
@dataclass
class StockPrice:
    """Aktienkurs-Daten."""
    symbol: str
    conid: int
    last: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class OptionContract:
    """Optionsvertrag mit allen relevanten Feldern."""
    conid: int
    symbol: str
    strike: float
    maturity_date: str
    right: str = "P"  # Put
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    historical_volatility: Optional[float] = None
    implied_volatility: Optional[float] = None
    ask_strike_ratio: Optional[float] = None  # ask/strike * 100

    def to_csv_row(self) -> Dict[str, Any]:
        """Konvertiere zu CSV-Zeile."""
        row = {k: (v if v is not None else "") for k, v in asdict(self).items()}
        return row


@dataclass
class SecdefSearchResult:
    """Ergebnis der Sechdef-Suche."""
    under_conid: int
    expirations: List[str]  # Format: YYYYMMDD


# ----------------------------------------------------------------------
# Logging Setup
# ----------------------------------------------------------------------
def setup_logging(config: Config) -> logging.Logger:
    """Initialisiere Logging-Konfiguration."""
    logging.basicConfig(level=config.log_level, format=config.log_format)
    logger = logging.getLogger(__name__)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return logger


# ----------------------------------------------------------------------
# IBKR Client using ib_insync
# ----------------------------------------------------------------------
class IBKRClient:
    """Client für die IBKR TWS API via ib_insync."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.ib = IB()
        self._connected = False

    def connect(self) -> Result:
        """Verbinde mit TWS."""
        try:
            self.logger.info(f"🔌 Verbinde zu {self.config.ibkr_host}:{self.config.ibkr_port} (Client {self.config.client_id})...")
            self.ib.connect(
                self.config.ibkr_host,
                self.config.ibkr_port,
                clientId=self.config.client_id,
                timeout=self.config.request_timeout
            )
            self._connected = True
            self.logger.info("✅ Verbindung hergestellt!")
            return Result.success(True)
        except Exception as e:
            self.logger.error(f"❌ Verbindung fehlgeschlagen: {e}")
            return Result.failure(f"Connection failed: {e}")

    def disconnect(self):
        """Trenne Verbindung."""
        if self._connected:
            self.ib.disconnect()
            self._connected = False
            self.logger.info("🔌 Verbindung getrennt")

    def search_secdef(self, symbol: str) -> Result:
        """Search for underlying ConID and valid expiration dates."""
        try:
            # Create stock contract
            stock = Stock(symbol, 'SMART', 'USD')
            
            # Qualify to get conid
            qualified = self.ib.qualifyContracts(stock)
            if not qualified:
                return Result.failure(f"No contract found for {symbol}")
            
            stock = qualified[0]
            under_conid = stock.conId
            self.logger.info(f"✅ Found ConID for {symbol}: {under_conid}")

            # Get option chain details (expirations and strikes)
            chains = self.ib.reqSecDefOptParams(stock.symbol, '', stock.secType, under_conid)
            
            if not chains:
                return Result.failure(f"No option chains found for {symbol}")

            # Use SMART exchange chain
            chain = None
            for c in chains:
                if c.exchange == 'SMART':
                    chain = c
                    break
            
            if not chain:
                chain = chains[0]  # Fallback to first chain

            # Get expirations (already in YYYYMMDD format)
            expirations = chain.expirations
            self.logger.info(f"📅 Available expirations: {len(expirations)} dates")
            
            return Result.success(SecdefSearchResult(under_conid=under_conid, expirations=expirations))
            
        except Exception as e:
            self.logger.error(f"❌ search_secdef failed: {e}")
            return Result.failure(f"search_secdef failed: {e}")

    def get_strikes_and_contracts(self, under_conid: int, expiration: str, right: str = 'P') -> List[OptionContract]:
        """Get all option contracts for a specific expiration."""
        try:
            stock = Stock('TREX', 'SMART', 'USD')
            stock.conId = under_conid
            
            # Get option chain for this expiration
            chains = self.ib.reqSecDefOptParams(stock.symbol, '', stock.secType, under_conid)
            
            if not chains:
                return []
            
            chain = None
            for c in chains:
                if c.exchange == 'SMART':
                    chain = c
                    break
            if not chain:
                chain = chains[0]
            
            # Find strikes for this expiration
            strikes = []
            for strike in chain.strikes:
                # Create option contract
                opt = Option(stock.symbol, expiration, strike, right, 'SMART')
                qualified = self.ib.qualifyContracts(opt)
                if qualified:
                    q = qualified[0]
                    strikes.append(OptionContract(
                        conid=q.conId,
                        symbol=q.symbol,
                        strike=q.strike,
                        maturity_date=q.lastTradeDateOrContractMonth,
                        right=q.right
                    ))
            
            self.logger.info(f"Expiration {expiration}: {len(strikes)} {right} strikes")
            return strikes
            
        except Exception as e:
            self.logger.error(f"❌ get_strikes failed: {e}")
            return []

    def get_market_data(self, contracts: List[OptionContract]) -> Dict[int, Dict]:
        """Get market data for contracts using snapshot."""
        if not contracts:
            return {}
        
        results = {}
        
        # Convert our dataclass objects to ib_insync Option objects
        ib_contracts = [
            Option(c.symbol, c.maturity_date, c.strike, c.right, 'SMART', conId=c.conid)
            for c in contracts
        ]
        
        # Request market data for each contract individually
        for contract in ib_contracts:
            try:
                tickers = self.ib.reqMktData(contract, snapshot=True)
                self.ib.sleep(0.5)  # small delay between requests
                
                if tickers:
                    ticker = tickers[0]
                    conid = ticker.contract.conId if hasattr(ticker, 'contract') else contract.conId
                    
                    data = {
                        'conid': conid,
                        'bid': ticker.bid if hasattr(ticker, 'bid') and ticker.bid != -1 else None,
                        'ask': ticker.ask if hasattr(ticker, 'ask') and ticker.ask != -1 else None,
                        'delta': None,
                        'gamma': None,
                        'theta': None,
                        'vega': None,
                        'volume': ticker.volume if hasattr(ticker, 'volume') and ticker.volume != -1 else None,
                        'open_interest': ticker.openInterest if hasattr(ticker, 'openInterest') and ticker.openInterest != -1 else None,
                    }
                    
                    # Try to get greeks from modelGreeks (older ib_insync version may have it)
                    if hasattr(ticker, 'modelGreeks') and ticker.modelGreeks:
                        try:
                            greeks = ticker.modelGreeks
                            data['delta'] = greeks.delta if hasattr(greeks, 'delta') and greeks.delta != -1 else None
                            data['gamma'] = greeks.gamma if hasattr(greeks, 'gamma') and greeks.gamma != -1 else None
                            data['theta'] = greeks.theta if hasattr(greeks, 'theta') and greeks.theta != -1 else None
                            data['vega'] = greeks.vega if hasattr(greeks, 'vega') and greeks.vega != -1 else None
                            data['historical_volatility'] = greeks.histVol if hasattr(greeks, 'histVol') and greeks.histVol != -1 else None
                            data['implied_volatility'] = greeks.impliedVol if hasattr(greeks, 'impliedVol') and greeks.impliedVol != -1 else None
                        except Exception as e:
                            self.logger.warning(f"Could not extract greeks: {e}")
                    
                    results[conid] = data
            except Exception as e:
                self.logger.warning(f"Failed to get market data for contract {contract.conId if contract else 'unknown'}: {e}")
                continue
        
        return results

    def get_stock_price(self, under_conid: int, symbol: str) -> Result:
        """Get stock price with retry logic."""
        stock = Stock(symbol, 'SMART', 'USD')
        stock.conId = under_conid
        
        for attempt in range(self.config.max_retries):
            try:
                tickers = self.ib.reqMktData([stock], snapshot=True)
                self.ib.sleep(1)
                
                ticker = tickers[0]
                
                # Check last price
                last = ticker.last if hasattr(ticker, 'last') and ticker.last != -1 else None
                
                if last is None or last == 0:
                    if attempt < self.config.max_retries - 1:
                        self.logger.warning(f"Last price missing, waiting 3s and retrying... (attempt {attempt + 1})")
                        time.sleep(3)
                        continue
                    
                    # Fallback to bid/ask midpoint
                    bid = ticker.bid if hasattr(ticker, 'bid') and ticker.bid != -1 else None
                    ask = ticker.ask if hasattr(ticker, 'ask') and ticker.ask != -1 else None
                    if bid and ask:
                        last = (bid + ask) / 2.0
                        self.logger.info(f"Using bid/ask midpoint as last: {last}")
                        return Result.success(StockPrice(symbol=symbol, conid=under_conid, last=last, bid=bid, ask=ask))
                    return Result.failure("Could not retrieve stock price after retries")
                
                bid = ticker.bid if hasattr(ticker, 'bid') and ticker.bid != -1 else None
                ask = ticker.ask if hasattr(ticker, 'ask') and ticker.ask != -1 else None
                
                return Result.success(StockPrice(symbol=symbol, conid=under_conid, last=last, bid=bid, ask=ask))
                
            except Exception as e:
                self.logger.error(f"Request error: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(3)
                else:
                    return Result.failure(f"Request failed: {e}")
        
        return Result.failure("Max retries exceeded")


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
def days_until(date_str: str) -> int:
    """Calculate days until a given date string (YYYYMMDD format)."""
    try:
        target = datetime.strptime(date_str, "%Y%m%d")
        now = datetime.now()
        return (target - now).days
    except ValueError:
        return 0


def write_csv(contracts: List[OptionContract], path: str, logger: logging.Logger) -> Result:
    """Write contracts to CSV file."""
    headers = [
        "conid", "symbol", "right", "strike", "maturity_date",
        "bid", "ask", "delta", "gamma", "theta", "vega",
        "volume", "open_interest", "historical_volatility", 
        "implied_volatility", "ask_strike_ratio"
    ]

    try:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for c in contracts:
                # Calculate ask/strike ratio
                if c.ask is not None and c.strike and c.strike > 0:
                    c.ask_strike_ratio = round((c.ask / c.strike) * 100, 4)
                writer.writerow(c.to_csv_row())
        logger.info(f"✅ Options CSV saved to {path}")
        return Result.success(True)
    except Exception as e:
        logger.error(f"Failed to write CSV: {e}")
        return Result.failure(str(e))


def append_stock_price(stock: StockPrice, path: str, logger: logging.Logger) -> Result:
    """Append stock price to CSV file."""
    try:
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                stock.timestamp, stock.symbol, stock.conid,
                stock.last, stock.bid, stock.ask
            ])
        logger.info(f"✅ Stock price appended to {path}")
        return Result.success(True)
    except Exception as e:
        logger.error(f"Failed to append stock price: {e}")
        return Result.failure(str(e))


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    """Main entry point for TREX options chain fetcher."""
    import argparse

    parser = argparse.ArgumentParser(description="Fetch TREX options chain (min 18 days)")
    parser.add_argument(
        "--symbol", "-s", default="TREX", 
        help="Underlying symbol (default: TREX)"
    )
    parser.add_argument(
        "--min-days", "-d", type=int, default=18,
        help="Minimum days to expiration (default: 18)"
    )
    parser.add_argument(
        "--output", "-o", default="./trex_options_18days.csv",
        help="Output CSV file path"
    )
    args = parser.parse_args()

    config = Config.from_env()
    config = Config(
        ibkr_host=config.ibkr_host,
        ibkr_port=config.ibkr_port,
        csv_output=args.output,
        log_level=config.log_level,
    )
    
    logger = setup_logging(config)
    client = IBKRClient(config, logger)

    logger.info(f"🔍 Fetching options chain for {args.symbol} (min {args.min_days} days)")

    # Connect
    conn_result = client.connect()
    if not conn_result.ok:
        logger.error(f"❌ Connection failed: {conn_result.error}")
        sys.exit(1)

    try:
        # 1️⃣ Get underlying ConID and expiration dates
        secdef_res = client.search_secdef(args.symbol)
        if not secdef_res.ok:
            logger.error(f"❌ Failed to find {args.symbol}: {secdef_res.error}")
            sys.exit(1)
        
        search_res = secdef_res.unwrap()
        logger.info(f"✅ Found ConID: {search_res.under_conid}")
        logger.info(f"📅 Available expirations: {len(search_res.expirations)} dates")

        # 2️⃣ Filter expirations to those >= min_days
        valid_expirations = []
        for exp in search_res.expirations:
            days = days_until(exp)
            if days >= args.min_days:
                valid_expirations.append(exp)
                logger.info(f"  {exp}: {days} days to expiration ✓")
            else:
                logger.info(f"  {exp}: {days} days to expiration (skipped, need {args.min_days}+)")

        if not valid_expirations:
            logger.error(f"❌ No expiration dates with {args.min_days}+ days found")
            sys.exit(1)

        # 3️⃣ Collect contracts for each valid expiration
        all_contracts: List[OptionContract] = []
        
        for exp in valid_expirations:
            contracts = client.get_strikes_and_contracts(search_res.under_conid, exp, right='P')
            all_contracts.extend(contracts)

        logger.info(f"📋 Collected {len(all_contracts)} put contracts")

        if not all_contracts:
            logger.error("❌ No contracts collected")
            sys.exit(1)

        # 4️⃣ Fetch market data for all contracts
        logger.info(f"📊 Fetching market data for {len(all_contracts)} contracts...")
        market_data = client.get_market_data(all_contracts)

        # Apply market data to contracts
        for c in all_contracts:
            data = market_data.get(c.conid, {})
            for attr, value in data.items():
                if attr != 'conid' and hasattr(c, attr):
                    setattr(c, attr, value)

        # Calculate ask/strike ratio
        for c in all_contracts:
            if c.ask is not None and c.strike and c.strike > 0:
                c.ask_strike_ratio = round((c.ask / c.strike) * 100, 4)

        # 5️⃣ Write CSV
        write_csv(all_contracts, config.csv_output, logger)

        # 6️⃣ Get stock price
        stock_res = client.get_stock_price(search_res.under_conid, args.symbol)
        if stock_res.ok:
            append_stock_price(stock_res.unwrap(), "./stock_price.csv", logger)
        else:
            logger.error(f"❌ Failed to get stock price: {stock_res.error}")

        logger.info("✅ Script completed successfully!")
        print(f"\n📁 Output saved to: {config.csv_output}")
        print(f"📊 Total contracts: {len(all_contracts)}")

    finally:
        client.disconnect()


if __name__ == "__main__":
    main()