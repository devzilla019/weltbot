from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base

class Trade(Base):
    __tablename__ = "trades"
    id               = Column(Integer, primary_key=True, index=True)
    asset            = Column(String, index=True)
    signal           = Column(String)
    confidence       = Column(Float)
    entry_price      = Column(Float)
    stop_loss        = Column(Float)
    take_profit      = Column(Float)
    position_sz      = Column(Float)
    risk_usd         = Column(Float)
    risk_reward      = Column(Float)
    outcome          = Column(String, default="OPEN")
    pnl              = Column(Float, nullable=True)
    binance_order_id = Column(String, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    closed_at        = Column(DateTime(timezone=True), nullable=True)

class SignalAccuracy(Base):
    __tablename__ = "signal_accuracy"
    id         = Column(Integer, primary_key=True)
    asset      = Column(String, unique=True)
    total      = Column(Integer, default=0)
    wins       = Column(Integer, default=0)
    losses     = Column(Integer, default=0)
    avg_conf   = Column(Float, default=50.0)
    conf_bias  = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

class SignalCache(Base):
    __tablename__ = "signal_cache"
    id         = Column(Integer, primary_key=True)
    asset      = Column(String, unique=True, index=True)
    payload    = Column(String)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

class BotState(Base):
    __tablename__ = "bot_state"
    id          = Column(Integer, primary_key=True)
    is_running  = Column(Integer, default=0)
    paused      = Column(Integer, default=0)
    pause_reason= Column(String, nullable=True)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now())

class RiskSettings(Base):
    """
    Runtime-tunable risk controls, editable from the dashboard and persisted
    so they survive a redeploy.

    Every limit can be switched off, because a hard daily stop that cannot be
    relaxed makes the strategy impossible to evaluate: once it trips, no
    further trades fire until the next day, so there is nothing to learn from.
    """
    __tablename__ = "risk_settings"
    id                          = Column(Integer, primary_key=True)

    # Master switches
    forex_enabled               = Column(Boolean, default=True)
    crypto_enabled              = Column(Boolean, default=True)

    # Daily loss limits (fractions, e.g. 0.06 = 6%)
    forex_daily_limit_enabled   = Column(Boolean, default=True)
    forex_daily_loss_limit      = Column(Float, default=0.06)
    crypto_daily_limit_enabled  = Column(Boolean, default=True)
    crypto_daily_loss_limit     = Column(Float, default=0.05)

    # Risk per trade (fractions)
    forex_risk_pct              = Column(Float, default=0.02)
    crypto_risk_pct             = Column(Float, default=0.01)

    # Minimum confidence to trade
    forex_min_confidence        = Column(Float, default=88.0)
    crypto_min_confidence       = Column(Float, default=90.0)

    # Position caps
    forex_max_trades            = Column(Integer, default=3)
    crypto_max_trades           = Column(Integer, default=2)

    # Behaviour
    diagnostic_mode             = Column(Boolean, default=False)
    auto_resume                 = Column(Boolean, default=True)
    weekend_guard               = Column(Boolean, default=True)

    updated_at                  = Column(DateTime(timezone=True), server_default=func.now())

class ActiveSetup(Base):
    __tablename__ = "active_setups"
    id          = Column(Integer, primary_key=True)
    symbol      = Column(String, unique=True, index=True)
    direction   = Column(String)
    bos_level   = Column(Float)
    fib_high    = Column(Float)
    fib_low     = Column(Float)
    ob_high     = Column(Float)
    ob_low      = Column(Float)
    impulse_high= Column(Float)
    impulse_low = Column(Float)
    candles_age = Column(Integer, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now())

class ForexTrade(Base):
    __tablename__ = "forex_trades"
    id                  = Column(Integer, primary_key=True, index=True)
    symbol              = Column(String, index=True)
    signal              = Column(String)
    confidence          = Column(Float)
    entry_price         = Column(Float)
    stop_loss           = Column(Float)
    take_profit         = Column(Float)
    lots                = Column(Float)
    kronos_bias         = Column(String)
    crt_setup           = Column(String)
    pdh                 = Column(Float)
    pdl                 = Column(Float)
    # Cascade tracking — which timeframe chain produced the trade
    crt_timeframe       = Column(String, nullable=True)   # 1d / 4h / 1h / 15m
    confirm_timeframe   = Column(String, nullable=True)   # POI timeframe
    entry_timeframe     = Column(String, nullable=True)   # SMC entry timeframe
    poi                 = Column(String, nullable=True)   # order_block / breaker_block / fvg / support_resistance
    # Refined CRT — partial take-profit tracking
    tp1                 = Column(Float, nullable=True)    # partial target (50% of the move)
    tp2                 = Column(Float, nullable=True)    # final target
    entry_type          = Column(String, nullable=True)   # QM / FVG / OB
    partial_tp_hit      = Column(Boolean, default=False)
    outcome             = Column(String, default="OPEN")
    pnl                 = Column(Float, nullable=True)
    metaapi_position_id = Column(String, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    closed_at           = Column(DateTime(timezone=True), nullable=True)

    # ── Silver Bullet trade management ────────────────────────────────────────
    # The state below exists so a backend restart can resume a live position
    # instead of re-deriving it from price. Without it a restart either repeats
    # a partial close or forgets a stop that has already been trailed.
    tp3                 = Column(Float, nullable=True)    # liquidity target
    original_lots       = Column(Float, nullable=True)    # size at entry, before any partial
    initial_stop        = Column(Float, nullable=True)    # stop at entry, before any move
    initial_risk        = Column(Float, nullable=True)    # |entry - initial_stop|
    tp1_done            = Column(Boolean, default=False)
    tp2_done            = Column(Boolean, default=False)
    tp3_done            = Column(Boolean, default=False)
    breakeven_done      = Column(Boolean, default=False)
    trailing_active     = Column(Boolean, default=False)
    peak_price          = Column(Float, nullable=True)    # best price seen, for trailing
    session_name        = Column(String, nullable=True)   # which window opened it
    session_expires_at  = Column(DateTime(timezone=True), nullable=True)
    management_state    = Column(String, nullable=True)   # JSON blob of the live state
    close_reason        = Column(String, nullable=True)   # why it was closed
    vp_confluence       = Column(String, nullable=True)   # POC_OVERLAP / VAH_.. / NONE
    partial_close_pct   = Column(Float, nullable=True)    # share of the original closed so far

class CRTLevel(Base):
    __tablename__ = "crt_levels"
    id              = Column(Integer, primary_key=True)
    symbol          = Column(String, index=True)
    date            = Column(String, index=True)
    timeframe       = Column(String, default="1d", index=True)   # 1d / 4h / 1h / 15m
    pdh             = Column(Float)
    pdl             = Column(Float)
    sweep_type      = Column(String, default="NONE")
    sweep_confirmed = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())