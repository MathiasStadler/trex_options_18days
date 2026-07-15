#!/usr/bin/env python3
"""
Debug Snapshot - fetches market data snapshot with delayed data type
"""

import sys
import logging
from ib_insync import IB, Stock

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def main():
    if len(sys.argv) < 2:
        print("Usage: python pltr_debug.py <TICKER>")
        sys.exit(1)
    ticker_symbol = sys.argv[1]
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7496, clientId=38)
        # Use delayed market data (type 3) - required for Paper Trading
        ib.reqMarketDataType(3)
        stock = Stock(ticker_symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        t = ib.reqMktData(stock, snapshot=True, regulatorySnapshot=False)
        ib.sleep(8)  # give more time for delayed data
        print(f"Snapshot data for {ticker_symbol}:")
        print(f"  Last: {t.last}")
        print(f"  Bid: {t.bid}")
        print(f"  Ask: {t.ask}")
        print(f"  Volume: {t.volume}")
        print(f"  Open Interest: {getattr(t, 'openInterest', 'N/A')}")
        if hasattr(t, 'modelGreeks') and t.modelGreeks:
            g = t.modelGreeks
            print(f"  Delta: {getattr(g, 'delta', 'N/A')}")
            print(f"  Gamma: {getattr(g, 'gamma', 'N/A')}")
            print(f"  Theta: {getattr(g, 'theta', 'N/A')}")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ib.disconnect()

if __name__ == "__main__":
    main()