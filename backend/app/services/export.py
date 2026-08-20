"""Builds a flat trade-log DataFrame and serializes it to CSV / XLSX bytes."""
from __future__ import annotations
import io
import pandas as pd
from sqlalchemy.orm import Session

from app.models_db import Recommendation


def build_trade_log_dataframe(db: Session, index_key: str | None = None) -> pd.DataFrame:
    q = db.query(Recommendation)
    if index_key:
        q = q.filter(Recommendation.index_key == index_key)
    recs = q.order_by(Recommendation.trade_date.asc()).all()

    rows = []
    for r in recs:
        pt = r.paper_trade
        rows.append({
            "Date": r.trade_date.isoformat(),
            "Index": r.index_key,
            "Leg": r.role,
            "Status": r.status,
            "Direction": r.direction,
            "Option Type": r.option_type,
            "Strike": r.strike,
            "Expiry": r.expiry,
            "Lot Size": r.lot_size,
            "Confidence %": r.confidence_score,
            "CMP @ Generation": r.cmp_at_generation,
            "Premium @ Generation": r.premium_at_generation,
            "Entry Type": r.entry_type,
            "Entry Trigger": r.entry_trigger_desc,
            "Entry Time": pt.entry_time.isoformat() if pt and pt.entry_time else None,
            "Entry Index Level": pt.entry_index_level if pt else None,
            "Entry Premium": pt.entry_premium if pt else None,
            "Exit Time": pt.exit_time.isoformat() if pt and pt.exit_time else None,
            "Exit Index Level": pt.exit_index_level if pt else None,
            "Exit Premium": pt.exit_premium if pt else None,
            "Outcome": pt.outcome if pt else None,
            "Targets Hit": ", ".join(pt.targets_hit) if pt and pt.targets_hit else None,
            "PnL (Rs per lot)": pt.pnl_rupees if pt else None,
            "PnL %": pt.pnl_pct if pt else None,
            "Not Executed Reason": r.not_executed_reason,
            "No Signal Reason": r.no_signal_reason,
            "Reasoning": r.reasoning,
        })
    columns = [
        "Date", "Index", "Leg", "Status", "Direction", "Option Type", "Strike", "Expiry", "Lot Size",
        "Confidence %", "CMP @ Generation", "Premium @ Generation", "Entry Type", "Entry Trigger",
        "Entry Time", "Entry Index Level", "Entry Premium", "Exit Time", "Exit Index Level",
        "Exit Premium", "Outcome", "Targets Hit", "PnL (Rs per lot)", "PnL %",
        "Not Executed Reason", "No Signal Reason", "Reasoning",
    ]
    return pd.DataFrame(rows, columns=columns)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Trade Log")
        ws = writer.sheets["Trade Log"]
        for col_cells in ws.columns:
            length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 40)
    return buf.getvalue()
