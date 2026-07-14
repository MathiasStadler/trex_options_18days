# TREX Options Chain Fetcher

## Overview
This script fetches TREX options chain data with a minimum expiration of 18 days. It retrieves:
- Option contract details (ConID, strike price, expiration date)
- Market data fields (bid, ask, delta, gamma, theta, vega, volume, open_interest, etc.)
- Stock price with retry logic (wait 3 seconds and retry if last price not available)
- CSV output with calculated ask/strike ratio

## Requirements
- Python 3.11+
- IBKR Gateway running on localhost:4002
- Properly configured credentials
- pytz package (optional, for better timezone handling)

## Installation
```bash
cd /home/hermes/trex_options_18days
pip install requests
# Optional: pip install pytz  
```

## Usage
```bash
# Default - fetches TREX options with 18+ days to expiration
cd /home/hermes/trex_options_18days
python3 src/fetch_trex_options.py

# Specify symbol, min days, or output path
python3 src/fetch_trex_options.py --symbol TREX --min-days 18 --output ./my_output.csv
```

## Output Files
- **Primary Output:** `./trex_options_18days.csv` - Complete options chain with all fields
- **Stock Price:** `./stock_price.csv` - Historical stock price data
- **Logs:** Console and auto-generated logs

## Features
- **18-Day Filter:** Automatically filters options with at least 18 days to expiration
- **Field-by-Field Retrieval:** Robust error handling for individual field failures
- **Exponential Backoff:** Retry delays of 2s, 4s, 8s for field failures
- **Stock Price Retry Logic:** Waits 3 seconds and retries if last price not available
- **Market Open Check:** Validates if US market is open before fetching
- **CSV Output:** Structured CSV with all requested fields including ask/strike ratio
- **Error Handling:** Comprehensive error logging and graceful failure handling

## Fields Retrieved
| API Field | Attribute Name | Description |
|-----------|---------------|-------------|
| 84 | bid | Best bid price |
| 85 | ask | Best ask price |
| 86 | delta | Option delta |
| 87 | gamma | Option gamma |
| 88 | theta | Option theta |
| 89 | vega | Option vega |
| 100 | volume | Trading volume |
| 101 | open_interest | Open interest |
| 104 | historical_volatility | Historical volatility |
| 106 | implied_volatility | Implied volatility |
| 31 | last | Stock last price (used for filtering) |

## Calculations
- **Ask/Strike Ratio:** (Ask / Strike) × 100, calculated for all contracts

## Notes
- Script checks market open status before fetching option data
- All numeric values from IBKR API are automatically converted from strings
- Missing values are handled gracefully with N/A in CSV output
- Consult `ibkr_field_retrieval.md` for field-by-field retrieval details
- Verify: GRE exclusive logic implemented, exponential backoff working, stock price retry failing

## Troubleshooting
- **IBKR Gateway Not Found:** Ensure gateway is running on localhost:4002
- **Authentication Issues:** Check gateway credentials and permissions
- **Market Closed:** Script will warn but proceed; data may be delayed
- **Field Retrieval Issues:** Review logs for specific field failures
- **CSV Output Empty:** Verify underlying ConID and expiration dates are correct

## Examples
```bash
# Standard run for TREX
python3 src/fetch_trex_options.py

# Run with custom parameters
python3 src/fetch_trex_options.py --symbol AAPL --min-days 30 --output ./options_output.csv

# Quick test with VERBOSE logging
cd /home/hermes/trex_options_18days
python3 -c "
from src.fetch_trex_options import IBKRClient, Config, setup_logging
config = Config()
logger = setup_logging(config)
client = IBKRClient(config, logger)
print('Testing IBKR connection...')
result = client.is_market_open()
print(f'Market open: {result.ok}')
if not result.ok:
    print(f'Error: {result.error}')
"
```

## Best Practices
- Run script during market hours for real-time data
- Monitor script logs for API rate limit warnings
- Consider running with increased timeout for large option chains
- Ensure IBKR Gateway has proper market data permissions
- Validate output CSV before using for trading decisions

## Support
For issues or questions:
1. Check console logs for specific error messages
2. Verify IBKR Gateway is running and configured
3. Ensure network connectivity to localhost:4002
4. Review the skill documentation for advanced troubleshooting
