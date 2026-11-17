"""Send a one-off test notification:  python -m scanner.test_push"""
import os
from . import notify

if __name__ == "__main__":
    n = notify.send_push({"title": "Stock Crawler ✅", "body": "Test notification — your phone is set up. "
                          "Real alerts arrive weekdays after 6 PM IST.",
                          "url": os.environ.get("DASHBOARD_URL") or "./", "tag": "test"})
    if n == 0:
        raise SystemExit("No notification was delivered — check the secrets and the log above.")
