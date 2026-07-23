"""Offline training-only APIs. This namespace must not be imported by live execution."""
from ..meta_model_v3 import MetaModelV3Config, train_from_dataset_v3
from ..timegan_trainer import train_timegan_adversarial, run_stage3_pipeline

__all__ = ["MetaModelV3Config", "train_from_dataset_v3", "train_timegan_adversarial", "run_stage3_pipeline"]
