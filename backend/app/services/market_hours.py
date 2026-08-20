from __future__ import annotations
from datetime import datetime, time, date
import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def is_weekday(d: date) -> bool:
    return d.weekday() < 5  # Mon-Fri; NSE holiday calendar not modeled -- see README


def is_market_open(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    if not is_weekday(dt.date()):
        return False
    return MARKET_OPEN <= dt.time() <= MARKET_CLOSE


def has_market_closed_today(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    return is_weekday(dt.date()) and dt.time() > MARKET_CLOSE
