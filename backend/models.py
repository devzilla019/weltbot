from sqlalchemy import Column, Integer, String, Float, DateTime
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