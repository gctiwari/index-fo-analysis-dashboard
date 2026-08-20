from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Boolean, ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db import Base


class Recommendation(Base):
    """
    One row per index per trading day PER ROLE. Up to 3 roles can exist for
    the same index on the same day:
      - PRIMARY: the confluence-gated pick (only exists if confluence clears
        the high-conviction bar -- otherwise that role is NO_SIGNAL)
      - BREAKOUT_UP: "if price closes above resistance, buy this call"
      - BREAKOUT_DOWN: "if price closes below support, buy this put"
    All three are independent, level-triggered watches -- not a strict OCO
    pair. All three lock their numbers at generation time; only their status
    (PENDING -> EXECUTED/NOT_EXECUTED) and any paper trade evolve afterward.
    """
    __tablename__ = "recommendations"
    __table_args__ = (UniqueConstraint("index_key", "trade_date", "role", name="uq_index_date_role"),)

    id = Column(Integer, primary_key=True)
    index_key = Column(String, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    role = Column(String, nullable=False, default="PRIMARY", index=True)  # PRIMARY | BREAKOUT_UP | BREAKOUT_DOWN
    generated_at = Column(DateTime, default=datetime.utcnow)

    status = Column(String, default="PENDING")  # PENDING | EXECUTED | NOT_EXECUTED | NO_SIGNAL | INVALIDATED
    not_executed_reason = Column(String, nullable=True)
    invalidated_reason = Column(String, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)

    direction = Column(String, nullable=True)
    option_type = Column(String, nullable=True)
    strike = Column(Float, nullable=True)
    expiry = Column(String, nullable=True)
    lot_size = Column(Integer, nullable=True)

    cmp_at_generation = Column(Float, nullable=True)
    premium_at_generation = Column(Float, nullable=True)
    entry_type = Column(String, nullable=True)
    entry_trigger_desc = Column(String, nullable=True)
    entry_trigger_index_level = Column(Float, nullable=True)

    target_index_1 = Column(Float, nullable=True)
    target_index_2 = Column(Float, nullable=True)
    target_index_3 = Column(Float, nullable=True)
    stop_index_level = Column(Float, nullable=True)

    target_premium_1 = Column(Float, nullable=True)
    target_premium_2 = Column(Float, nullable=True)
    target_premium_3 = Column(Float, nullable=True)
    stop_premium = Column(Float, nullable=True)

    atr_pct_at_generation = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    reasoning = Column(String, nullable=True)
    raw_json = Column(JSON, nullable=True)  # full TradeIdea payload for detail views
    no_signal_reason = Column(String, nullable=True)

    # --- Monitoring diagnostics (Step 9 of the RCA this was added for) ---
    # These make "why did/didn't this trigger" answerable by reading the row,
    # instead of having to re-derive it from logs or code.
    last_price_checked = Column(Float, nullable=True)
    last_price_checked_at = Column(DateTime, nullable=True)
    last_check_source = Column(String, nullable=True)  # e.g. "completed_15m_close", "live_tick_fallback"
    mfe_index_level = Column(Float, nullable=True)  # most favorable price seen so far while PENDING
    trigger_reached_at = Column(DateTime, nullable=True)
    monitor_tick_count = Column(Integer, default=0)  # how many times this row was actually checked -- a low
    # count relative to how long it's been PENDING is itself direct evidence of a coverage gap.

    paper_trade = relationship("PaperTrade", back_populates="recommendation", uselist=False)


class PaperTrade(Base):
    """Created the moment a recommendation's entry condition triggers."""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True)
    recommendation_id = Column(Integer, ForeignKey("recommendations.id"), unique=True)
    index_key = Column(String, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)

    entry_index_level = Column(Float, nullable=False)
    entry_premium = Column(Float, nullable=False)
    entry_time = Column(DateTime, nullable=False)

    exit_index_level = Column(Float, nullable=True)
    exit_premium = Column(Float, nullable=True)
    exit_time = Column(DateTime, nullable=True)

    mfe_premium = Column(Float, nullable=True)  # max favorable excursion, for targets_hit tracking
    targets_hit = Column(JSON, default=list)
    stop_hit = Column(Boolean, default=False)

    status = Column(String, default="OPEN")  # OPEN | CLOSED
    outcome = Column(String, nullable=True)  # TARGET_1 | STOP_LOSS | EOD_EXIT | OPEN

    pnl_rupees = Column(Float, nullable=True)   # per 1 lot
    pnl_pct = Column(Float, nullable=True)

    recommendation = relationship("Recommendation", back_populates="paper_trade")
