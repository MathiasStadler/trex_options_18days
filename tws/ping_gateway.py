#!/usr/bin/env python3
"""Ping IBKR Gateway – kein API-Key erforderlich.

Prüft nur, ob ein lokaler TWS/Gateway (Socket-API) erreichbar ist.
Verwendet: ib_insync
"""

import sys
sys.path.insert(0, '/home/hermes/.hermes/hermes-agent/venv/lib/python3.11/site-packages')

from ib_insync import IB

def ping_gateway(host: str = '127.0.0.1', port: int = 7497, client_id: int = 1) -> bool:
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id)
        version = ib.serverVersion()
        ts = ib.connectionTime()
        ib.disconnect()
        print(f"Gateway erreichbar (v{version}) – {ts}")
        return True
    except Exception as e:
        print(f"Gateway NICHT erreichbar: {e}")
        return False

if __name__ == "__main__":
    ok = ping_gateway()
    sys.exit(0 if ok else 1)