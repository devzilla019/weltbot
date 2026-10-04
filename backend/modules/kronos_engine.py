"""
backend/modules/kronos_engine.py
Kronos AI forecasting engine for directional bias
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

_kronos_model = None
_kronos_tokenizer = None
_kronos_predictor = None
_kronos_bias_cache: Dict[str, dict] = {}


def _load_kronos_model():
    """Load Kronos model once at startup"""
    global _kronos_model, _kronos_tokenizer, _kronos_predictor
    
    if _kronos_model is not None:
        return
    
    from config import KRONOS_ENABLED, KRONOS_MODEL_PATH, KRONOS_TOKENIZER
    
    if not KRONOS_ENABLED:
        logger.info("[kronos] disabled via config")
        return
    
    try:
        import torch
        import sys
        
        # Search common locations for the cloned Kronos repo
        here = os.path.dirname(os.path.abspath(__file__))          # backend/modules
        backend_dir = os.path.dirname(here)                        # backend
        repo_root = os.path.dirname(backend_dir)                   # repo root
        candidates = [
            os.path.join(backend_dir, "Kronos"),
            os.path.join(repo_root, "Kronos"),
            os.path.join(here, "Kronos"),
            os.getenv("KRONOS_REPO_PATH", ""),
        ]
        for kronos_repo in candidates:
            if kronos_repo and os.path.exists(kronos_repo):
                if kronos_repo not in sys.path:
                    sys.path.insert(0, kronos_repo)
                logger.info(f"[kronos] using repo at {kronos_repo}")
                break
        
        from model import Kronos, KronosTokenizer, KronosPredictor
        
        logger.info(f"[kronos] loading tokenizer from {KRONOS_TOKENIZER}")
        _kronos_tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER)
        
        logger.info(f"[kronos] loading model from {KRONOS_MODEL_PATH}")
        _kronos_model = Kronos.from_pretrained(KRONOS_MODEL_PATH)
        _kronos_model.to('cpu')
        _kronos_model.eval()
        
        _kronos_predictor = KronosPredictor(
            model=_kronos_model,
            tokenizer=_kronos_tokenizer,
            max_context=2048
        )
        
        logger.info("[kronos] model loaded successfully (CPU mode)")
    except Exception as e:
        logger.error(f"[kronos] failed to load model: {e}")
        _kronos_model = None
        _kronos_tokenizer = None
        _kronos_predictor = None


def is_kronos_available() -> bool:
    """Check if Kronos is loaded and ready"""
    return _kronos_predictor is not None


def predict_bias(symbol: str, ohlcv_df: pd.DataFrame) -> Optional[dict]:
    """
    Predict 24-hour directional bias using Kronos
    
    Args:
        symbol: Trading pair (e.g. XAUUSD)
        ohlcv_df: DataFrame with columns: timestamp, open, high, low, close, volume
                  Must have at least 400 rows of H1 data
    
    Returns:
        dict with bias, confidence, current_close, predicted_close, predicted_change_pct
    """
    global _kronos_bias_cache
    
    if _kronos_predictor is None:
        _load_kronos_model()
        if _kronos_predictor is None:
            return None
    
    try:
        if len(ohlcv_df) < 400:
            logger.warning(f"[kronos] {symbol} insufficient data: {len(ohlcv_df)} rows")
            return None
        
        df = ohlcv_df.tail(400).copy()
        df = df.reset_index(drop=True)
        
        if 'timestamp' not in df.columns:
            logger.error(f"[kronos] {symbol} missing timestamp column")
            return None
        
        x_timestamps = df['timestamp'].tolist()
        y_timestamps = []
        last_ts = x_timestamps[-1]
        
        for i in range(1, 25):
            if isinstance(last_ts, (int, float)):
                next_ts = last_ts + (i * 3600000)
            else:
                next_ts = pd.Timestamp(last_ts) + pd.Timedelta(hours=i)
                next_ts = int(next_ts.timestamp() * 1000)
            y_timestamps.append(next_ts)
        
        pred_df = _kronos_predictor.predict(
            df=df[['open', 'high', 'low', 'close']],
            x_timestamp=x_timestamps,
            y_timestamp=y_timestamps,
            pred_len=24,
            T=0.8,
            top_p=0.9,
            sample_count=3
        )
        
        current_close = float(df['close'].iloc[-1])
        forecast_close = float(pred_df['close'].iloc[-1])
        change_pct = ((forecast_close - current_close) / current_close) * 100
        
        if abs(change_pct) > 0.3:
            bias = 'BULLISH' if forecast_close > current_close else 'BEARISH'
            confidence_boost = min(abs(change_pct) * 2, 8)
        else:
            bias = 'NEUTRAL'
            confidence_boost = 0
        
        result = {
            'symbol': symbol,
            'bias': bias,
            'confidence_boost': round(confidence_boost, 2),
            'current_close': round(current_close, 5),
            'predicted_close_24h': round(forecast_close, 5),
            'predicted_change_pct': round(change_pct, 3),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        _kronos_bias_cache[symbol] = result
        logger.info(f"[kronos] {symbol} bias={bias} change={change_pct:.2f}% boost={confidence_boost}")
        
        return result
        
    except Exception as e:
        logger.error(f"[kronos] prediction error for {symbol}: {e}")
        return None


def get_cached_bias(symbol: str) -> Optional[dict]:
    """Get cached Kronos bias for symbol"""
    return _kronos_bias_cache.get(symbol)


def clear_cache():
    """Clear bias cache"""
    global _kronos_bias_cache
    _kronos_bias_cache = {}
    logger.info("[kronos] cache cleared")


def get_all_biases() -> Dict[str, dict]:
    """Get all cached biases"""
    return _kronos_bias_cache.copy()
