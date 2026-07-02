try:
    from .timegan import (
        OHLCVScaler,
        AltcoinSequenceDataset,
        build_timegan_dataloader,
        load_historical_15m_sequences,
    )
except Exception as exc:
    OHLCVScaler = None
    AltcoinSequenceDataset = None
    build_timegan_dataloader = None
    load_historical_15m_sequences = None
    TIMEGAN_IMPORT_ERROR = exc
else:
    TIMEGAN_IMPORT_ERROR = None

try:
    from .timegan_model import Embedder, Recovery, Generator, Supervisor, Discriminator
except Exception as exc:
    Embedder = None
    Recovery = None
    Generator = None
    Supervisor = None
    Discriminator = None
    TIMEGAN_MODEL_IMPORT_ERROR = exc
else:
    TIMEGAN_MODEL_IMPORT_ERROR = None

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
