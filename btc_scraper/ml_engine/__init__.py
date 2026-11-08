"""ML Engine package initialization with lazy loading for heavy offline GAN dependencies."""

__all__ = [
    "OHLCVScaler",
    "AltcoinSequenceDataset",
    "build_timegan_dataloader",
    "load_historical_15m_sequences",
    "Embedder",
    "Recovery",
    "Generator",
    "Supervisor",
    "Discriminator",
    "TIMEGAN_IMPORT_ERROR",
    "TIMEGAN_MODEL_IMPORT_ERROR",
]

TIMEGAN_IMPORT_ERROR = None
TIMEGAN_MODEL_IMPORT_ERROR = None

_TIMEGAN_SYMBOLS = {
    "OHLCVScaler",
    "AltcoinSequenceDataset",
    "build_timegan_dataloader",
    "load_historical_15m_sequences",
}
_TIMEGAN_MODEL_SYMBOLS = {
    "Embedder",
    "Recovery",
    "Generator",
    "Supervisor",
    "Discriminator",
}


def __getattr__(name: str):
    global TIMEGAN_IMPORT_ERROR, TIMEGAN_MODEL_IMPORT_ERROR
    if name in _TIMEGAN_SYMBOLS:
        try:
            from . import timegan
            val = getattr(timegan, name)
            globals()[name] = val
            return val
        except Exception as exc:
            TIMEGAN_IMPORT_ERROR = exc
            globals()[name] = None
            return None
    elif name in _TIMEGAN_MODEL_SYMBOLS:
        try:
            from . import timegan_model
            val = getattr(timegan_model, name)
            globals()[name] = val
            return val
        except Exception as exc:
            TIMEGAN_MODEL_IMPORT_ERROR = exc
            globals()[name] = None
            return None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
