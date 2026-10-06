"""
backend/modules/kronos_engine.py
Kronos AI forecasting engine for directional bias
"""
import os
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

_kronos_model = None
_kronos_tokenizer = None
_kronos_predictor = None
_kronos_bias_cache: Dict[str, dict] = {}
_kronos_status: Dict[str, object] = {"state": "not_started", "error": None, "repo": None}

# Once loading fails permanently (e.g. no `git` in the container), stop
# retrying on every prediction call — otherwise the logs fill with the same
# error every 15 minutes.
_kronos_load_failed = False

KRONOS_REPO_URL = "https://github.com/shiyu-coder/Kronos.git"


def _git_available() -> bool:
    """Check whether the `git` binary exists in this container."""
    import shutil
    return shutil.which("git") is not None


def _candidate_repo_paths():
    here = os.path.dirname(os.path.abspath(__file__))          # backend/modules
    backend_dir = os.path.dirname(here)                        # backend
    repo_root = os.path.dirname(backend_dir)                   # repo root
    return [
        os.path.join(backend_dir, "Kronos"),
        os.path.join(repo_root, "Kronos"),
        os.path.join(here, "Kronos"),
        os.getenv("KRONOS_REPO_PATH", ""),
    ]


def _ensure_kronos_repo() -> Optional[str]:
    """
    Return a path containing the Kronos `model` package, cloning the repo
    on the fly if it isn't present (Railway build may have skipped it).
    """
    import sys

    # 1) Already importable?
    try:
        import model  # noqa: F401
        return os.path.dirname(os.path.dirname(model.__file__))
    except Exception:
        pass

    # 2) Existing clone on disk?
    for path in _candidate_repo_paths():
        if path and os.path.isdir(path) and os.path.exists(os.path.join(path, "model")):
            if path not in sys.path:
                sys.path.insert(0, path)
            return path

    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Kronos")

    # 3a) Preferred: download the repo tarball (works without `git`)
    if _download_kronos_tarball(target):
        if target not in sys.path:
            sys.path.insert(0, target)
        return target

    # 3b) Fallback: git clone (only if `git` exists)
    if _git_available():
        try:
            import subprocess
            logger.info(f"[kronos] tarball failed — trying git clone into {target}")
            subprocess.run(
                ["git", "clone", "--depth", "1", KRONOS_REPO_URL, target],
                check=True, capture_output=True, timeout=180,
            )
            if os.path.exists(os.path.join(target, "model")):
                if target not in sys.path:
                    sys.path.insert(0, target)
                logger.info("[kronos] git clone complete")
                return target
        except Exception as e:
            logger.error(f"[kronos] git clone failed: {e}")
    else:
        logger.warning("[kronos] `git` not available in this container")

    return None


def _download_kronos_tarball(target: str) -> bool:
    """
    Download the Kronos repo as a GitHub tarball and extract it into `target`.
    Requires no `git` binary — works on any container (Railway/Railpack, etc.).
    Uses `requests` with retries for robustness against flaky networks.
    """
    import io
    import tarfile
    import time as _time

    # NOTE: the Kronos repo's default branch is `master` (not `main`).
    tarball_urls = [
        "https://codeload.github.com/shiyu-coder/Kronos/tar.gz/refs/heads/master",
        "https://codeload.github.com/shiyu-coder/Kronos/tar.gz/refs/heads/main",
    ]

    for url in tarball_urls:
        for attempt in range(3):
            try:
                logger.info(f"[kronos] downloading repo tarball from {url} (attempt {attempt+1})")
                resp = requests.get(
                    url,
                    headers={"User-Agent": "WeltBot/1.0"},
                    timeout=180,
                    stream=True,
                )
                if resp.status_code != 200:
                    logger.warning(f"[kronos] tarball HTTP {resp.status_code} from {url}")
                    break

                # Read the full body (streamed) — more reliable than urllib chunked reads
                raw = resp.content

                with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                    members = tar.getmembers()
                    if not members:
                        break

                    os.makedirs(target, exist_ok=True)
                    for m in members:
                        # strip the leading "Kronos-master/" component
                        parts = m.name.split("/", 1)
                        if len(parts) < 2 or not parts[1]:
                            continue
                        m.name = parts[1]
                        try:
                            tar.extract(m, target, filter="data")
                        except TypeError:
                            # Python < 3.12 has no `filter` kwarg
                            tar.extract(m, target)

                if os.path.exists(os.path.join(target, "model")):
                    logger.info("[kronos] tarball extracted successfully")
                    return True

                logger.warning("[kronos] tarball extracted but no `model` package found")
                break

            except Exception as e:
                logger.error(f"[kronos] tarball download failed ({url}, attempt {attempt+1}): {e}")
                _time.sleep(3)

    return False


def _load_kronos_model():
    """Load Kronos model once at startup"""
    global _kronos_model, _kronos_tokenizer, _kronos_predictor, _kronos_status, _kronos_load_failed

    if _kronos_model is not None:
        return

    # Already failed permanently — don't retry or re-log
    if _kronos_load_failed:
        return

    from config import KRONOS_ENABLED, KRONOS_MODEL_PATH, KRONOS_TOKENIZER

    if not KRONOS_ENABLED:
        _kronos_status = {"state": "disabled", "error": None, "repo": None}
        logger.info("[kronos] disabled via config")
        return

    _kronos_status = {"state": "loading", "error": None, "repo": None}

    try:
        import torch  # noqa: F401

        repo = _ensure_kronos_repo()
        if not repo:
            _kronos_status = {
                "state": "error",
                "error": "Kronos repo not found and auto-clone failed. "
                         "Ensure `git` is available and the build can reach GitHub.",
                "repo": None,
            }
            _kronos_load_failed = True   # latch — stop retrying
            logger.error(f"[kronos] {_kronos_status['error']} (will not retry)")
            return

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
            max_context=2048,
        )

        _kronos_status = {"state": "ready", "error": None, "repo": repo}
        logger.info("[kronos] model loaded successfully (CPU mode)")
    except Exception as e:
        _kronos_status = {"state": "error", "error": str(e), "repo": None}
        _kronos_load_failed = True   # latch — stop retrying
        logger.error(f"[kronos] failed to load model: {e} (will not retry)")
        _kronos_model = None
        _kronos_tokenizer = None
        _kronos_predictor = None


def get_kronos_status() -> Dict:
    """Diagnostic info for the UI / health endpoint."""
    return {
        **_kronos_status,
        "available": _kronos_predictor is not None,
        "cached_biases": len(_kronos_bias_cache),
    }


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
            return None   # load failed (latched) — silently skip
    
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
