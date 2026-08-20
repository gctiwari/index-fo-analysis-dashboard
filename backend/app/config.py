"""
Central configuration: index registry, strike intervals, lot sizes.
Adding a new index later = adding one entry here, nothing else changes.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexConfig:
    key: str
    display_name: str
    yf_ticker: str          # yfinance ticker for the underlying
    strike_interval: int    # option strike spacing
    lot_size: int           # F&O lot size (approx, update per NSE circulars)


INDEX_REGISTRY: dict[str, IndexConfig] = {
    "NIFTY": IndexConfig("NIFTY", "NIFTY 50", "^NSEI", 50, 75),
    "BANKNIFTY": IndexConfig("BANKNIFTY", "BANK NIFTY", "^NSEBANK", 100, 30),
    "SENSEX": IndexConfig("SENSEX", "SENSEX", "^BSESN", 100, 20),
    # Not yet wired to a live yfinance ticker -- kept here so the UI/API
    # already understand these indices; enable once a data source is set.
    "FINNIFTY": IndexConfig("FINNIFTY", "FINNIFTY", "", 50, 40),
    "MIDCPNIFTY": IndexConfig("MIDCPNIFTY", "MIDCAP NIFTY", "", 25, 75),
}

ACTIVE_INDICES = [k for k, v in INDEX_REGISTRY.items() if v.yf_ticker]

# Correlation / macro context tickers
MACRO_TICKERS = {
    "INDIA_VIX": "^INDIAVIX",
    "USDINR": "INR=X",
    "CRUDE": "CL=F",
    "GOLD": "GC=F",
    "US10Y": "^TNX",
    "DOWJONES": "^DJI",
    "NASDAQ": "^IXIC",
    "SGX_NIFTY_PROXY": "^NSEI",  # SGX Nifty is discontinued (moved to GIFT); GIFT feed needs a vendor.
}

RISK_FREE_RATE = 0.065  # approx India risk-free rate, used only for premium estimation
