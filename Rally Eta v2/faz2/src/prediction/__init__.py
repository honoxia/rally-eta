"""Prediction modules for Rally ETA v2.0.

Modules:
- confidence_scorer: Calculate prediction confidence levels
- notional_time_predictor: 3-stage prediction orchestrator
"""

from src.prediction.confidence_scorer import ConfidenceScorer, ConfidenceResult

__all__ = [
    'ConfidenceScorer',
    'ConfidenceResult',
    'PredictionService',
    'NotionalTimePredictor',
    'PredictionResult'
]


def __getattr__(name):
    """Load heavy predictor modules lazily."""
    if name in {'NotionalTimePredictor', 'PredictionResult'}:
        from src.prediction.notional_time_predictor import (
            NotionalTimePredictor,
            PredictionResult,
        )
        return {
            'NotionalTimePredictor': NotionalTimePredictor,
            'PredictionResult': PredictionResult,
        }[name]
    if name == 'PredictionService':
        from src.prediction.prediction_service import PredictionService

        return PredictionService

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
