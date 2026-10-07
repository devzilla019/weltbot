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