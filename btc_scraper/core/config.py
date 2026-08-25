# BTC/Multi-coin OHLCV Scraper - Cấu hình

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from dotenv import load_dotenv

# Tải cấu hình từ file .env nếu có
load_dotenv()

_CONFIG_ROOT = Path(__file__).resolve().parents[2]
_MC6_REGISTRY = _CONFIG_ROOT / "model_coverage_mc6_inference_registry.json"
_FALLBACK_AUTHORIZED: tuple[str, ...] = (
    "BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"
)


def get_authorized_symbols() -> tuple[str, ...]:
    """Return the MC6-authorized inference symbols (9 routable routes).

    Truth is read from the sealed MC6 inference registry.  Falls back to a
    hardcoded tuple only if the registry file is unavailable (e.g. early
    test bootstrap before the artifact is on disk).
    """
    if _MC6_REGISTRY.exists():
        try:
            data = json.loads(_MC6_REGISTRY.read_text(encoding="utf-8"))
            syms = tuple(
                sorted(str(r["symbol"]).strip().upper() for r in data.get("routes", []))
            )
            if syms:
                return syms
        except Exception:
            pass
    return _FALLBACK_AUTHORIZED

# Danh sách coin được hỗ trợ (tự động ghép cặp USDT/USDT-spot).
DEFAULT_ANALYSIS_UNIVERSE = (
    "BTC", 
    "ETH", 
    "BNB", 
    "SOL", 
    "ZEC", 
    "XRP", 
    "DOGE", 
    "WLD", 
    "XLM", 
    "NEAR", 
    "AVAX", 
    "TAO", 
    "TRB", 
    "AEVO", 
    "ENA", 
    "AR", 
    "IOTA", 
    "XPL",
    "SOPH",
    "XAUT", 
    "TRX",
    "TRUMP"
)
SUPPORTED_SYMBOLS = frozenset(DEFAULT_ANALYSIS_UNIVERSE)


def parse_runtime_symbols(
    raw: str,
    *,
    field_name: str,
    supported_symbols: Iterable[str] = DEFAULT_ANALYSIS_UNIVERSE,
) -> tuple[str, ...]:
    """Normalize and strictly validate a comma-separated runtime universe."""
    if not str(raw).strip():
        raise ValueError(f"{field_name} must not be empty")
    parts = str(raw).split(",")
    if any(not part.strip() for part in parts):
        raise ValueError(f"{field_name} contains an empty symbol")
    symbols = tuple(part.strip().upper() for part in parts)
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"{field_name} contains duplicate symbols")
    supported = {str(symbol).strip().upper() for symbol in supported_symbols}
    unsupported = sorted(set(symbols) - supported)
    if unsupported:
        raise ValueError(
            f"{field_name} contains unsupported symbols: {','.join(unsupported)}"
        )
    return symbols


def get_analysis_universe() -> tuple[str, ...]:
    """Return the effective runtime analysis universe.

    Defaults to the 9 MC6-authorized symbols (not the full canonical 22).
    If BTC_ANALYSIS_UNIVERSE is set via env, every symbol in it must be in
    the authorized list; any unauthorized symbol raises immediately with
    RUNTIME_UNIVERSE_NOT_AUTHORIZED:<symbol>.
    """
    authorized = get_authorized_symbols()
    raw = os.getenv("BTC_ANALYSIS_UNIVERSE")
    if raw is None or not raw.strip():
        return authorized
    # Validate against canonical universe first (catches typos / unknown coins)
    symbols = parse_runtime_symbols(raw, field_name="BTC_ANALYSIS_UNIVERSE")
    # Then validate against the MC6 authorized list
    auth_set = set(authorized)
    for sym in symbols:
        if sym not in auth_set:
            raise ValueError(f"RUNTIME_UNIVERSE_NOT_AUTHORIZED:{sym}")
    return symbols


def get_execution_universe(
    analysis_symbols: Iterable[str] | None = None,
) -> tuple[str, ...]:
    analysis = tuple(analysis_symbols or get_analysis_universe())
    raw = os.getenv("AUTO_TRADE_COINS")
    execution = (
        analysis
        if raw is None or not raw.strip()
        else parse_runtime_symbols(raw, field_name="AUTO_TRADE_COINS")
    )
    outside_analysis = sorted(set(execution) - set(analysis))
    if outside_analysis:
        raise ValueError(
            "AUTO_TRADE_COINS must be a subset of BTC_ANALYSIS_UNIVERSE; "
            f"outside symbols: {','.join(outside_analysis)}"
        )
    return execution


def analysis_universe_hash(symbols: Iterable[str]) -> str:
    normalized = tuple(str(symbol).strip().upper() for symbol in symbols)
    canonical = json.dumps(
        list(normalized), ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeUniverse:
    analysis_symbols: tuple[str, ...]
    execution_symbols: tuple[str, ...]

    @property
    def analysis_hash(self) -> str:
        return analysis_universe_hash(self.analysis_symbols)


def get_runtime_universe() -> RuntimeUniverse:
    analysis = get_analysis_universe()
    return RuntimeUniverse(
        analysis_symbols=analysis,
        execution_symbols=get_execution_universe(analysis),
    )


# Backward-compatible training/default catalog. Runtime code must use the
# resolver above so an environment-specific cohort cannot leak into tooling.
COINS = list(DEFAULT_ANALYSIS_UNIVERSE)

INTERVAL = "15m"            # Khung nến 15 phút
LIMIT = 210                  # Số nến lấy mỗi lần — cần tối thiểu 200 để tính SMA200 (+ 10 buffer)
FETCH_INTERVAL_MINUTES = 15   # Tần suất cập nhật (phút)

# Database
MONGODB_URI = os.getenv("MONGODB_URI")

# Telegram credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Gemini API Keys (round-robin, tối đa 5 key)
# Ưu tiên dùng GEMINI_API_KEY_1..5, fallback về GEMINI_API_KEY nếu có
_raw_keys = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5"),
    os.getenv("GEMINI_API_KEY"),  # fallback key đơn cũ
]
GEMINI_API_KEYS: list[str] = [k for k in _raw_keys if k]  # Lọc bỏ None/rỗng
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None  # tương thích ngược

# Default fresh training data folder (can be overridden via env var)
from pathlib import Path
FRESH_TRAINING_DATA_DIR = Path(os.getenv("FRESH_TRAINING_DATA_DIR", "data/fresh_training_data_2023_2026"))
