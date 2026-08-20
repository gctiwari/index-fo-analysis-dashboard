"""
Starlette's default JSONResponse uses allow_nan=False (correct, per the JSON
spec -- NaN/Infinity aren't valid JSON), which means a single stray NaN
anywhere in a response crashes the whole request with a 500. Real market
data has enough edge cases (illiquid instruments, short history windows,
zero-volume index tickers, etc.) that relying solely on every individual
calculation to never produce one is fragile. This response class is a
blanket safety net: it recursively replaces any NaN/Infinity float with
null right before serialization, on top of the targeted fixes already in
the analysis code (see indicators.py's `_safe` helper).
"""
from __future__ import annotations
import math
from typing import Any
from starlette.responses import JSONResponse


def sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    return obj


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(sanitize_for_json(content))
