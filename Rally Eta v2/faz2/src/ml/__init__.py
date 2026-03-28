"""Machine Learning modules for Rally ETA v2.0."""

__all__ = [
    'FeatureEngineer',
    'GeometricCorrectionModel',
    'ModelWithFallback',
    'SHAPExplainer',
    'PredictionExplanation',
    'FeatureContribution',
    'ExplanationGenerator',
    'PredictionBreakdown',
    'StageExplanationReport',
]


def __getattr__(name):
    """Lazily import heavy ML modules only when requested."""
    if name == 'FeatureEngineer':
        from src.ml.feature_engineering import FeatureEngineer
        return FeatureEngineer
    if name in {'GeometricCorrectionModel', 'ModelWithFallback'}:
        from src.ml.geometric_correction_model import GeometricCorrectionModel, ModelWithFallback
        return {
            'GeometricCorrectionModel': GeometricCorrectionModel,
            'ModelWithFallback': ModelWithFallback,
        }[name]
    if name in {'SHAPExplainer', 'PredictionExplanation', 'FeatureContribution'}:
        from src.ml.shap_explainer import SHAPExplainer, PredictionExplanation, FeatureContribution
        return {
            'SHAPExplainer': SHAPExplainer,
            'PredictionExplanation': PredictionExplanation,
            'FeatureContribution': FeatureContribution,
        }[name]
    if name in {'ExplanationGenerator', 'PredictionBreakdown', 'StageExplanationReport'}:
        from src.ml.explanation_generator import (
            ExplanationGenerator,
            PredictionBreakdown,
            StageExplanationReport,
        )
        return {
            'ExplanationGenerator': ExplanationGenerator,
            'PredictionBreakdown': PredictionBreakdown,
            'StageExplanationReport': StageExplanationReport,
        }[name]

    raise AttributeError(f"module 'src.ml' has no attribute {name!r}")
