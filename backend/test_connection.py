import requests
import hmac
import hashlib
import time
from urllib.parse import urlencode

API_KEY = "rhbiThDyaTIKMMNdavi1vC4oYDkoB7x6blsnkNQXx0I2cntLD53UMgbH25K5SNrT"
SECRET  = "ltj5vlAROBl2dXrdsA8bq875OSjvwCkM8Y54BVIbDzhGOpWur6bJBVNDPyYZoWQn"
BASE    = "https://testnet.binance.vision"

def sign(params):
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params)
    sig   = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params

headers = {"X-MBX-APIKEY": API_KEY}

print("Test 1 — ping...")
r = requests.get(f"{BASE}/api/v3/ping", timeout=5)
print(f"  status: {r.status_code} response: {r.text}")

print("Test 2 — BTC price...")
r = requests.get(f"{BASE}/api/v3/ticker/price", params={"symbol": "BTCUSDT"}, timeout=5)
print(f"  {r.json()}")

print("Test 3 — account balance...")
r = requests.get(f"{BASE}/api/v3/account", params=sign({}), headers=headers, timeout=10)
data = r.json()
if "balances" in data:
    for b in data["balances"]:
        if float(b["free"]) > 0:
            print(f"  {b['asset']}: {b['free']}")
else:
    print(f"  error: {data}")

print("Done.")