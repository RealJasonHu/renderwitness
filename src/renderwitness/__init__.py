"""RenderWitness: explainable visual-regression review for screenshots."""

from .analyzer import AnalysisError, analyze, compare_and_analyze
from .diff import ComparisonError, ImageSafetyError, compare_images
from .models import (
    AnalysisResult,
    BoundingBox,
    ComparisonResult,
    DiffRegion,
    Finding,
    ImageInfo,
    ProviderResult,
    Severity,
    Verdict,
)
from .providers import (
    DemoProvider,
    OpenAICompatibleProvider,
    ProviderError,
    VisionProvider,
    create_provider,
)
from .report import ReportError, ReportPaths, render_html, write_report

__all__ = [
    "AnalysisError",
    "AnalysisResult",
    "BoundingBox",
    "ComparisonError",
    "ComparisonResult",
    "DemoProvider",
    "DiffRegion",
    "Finding",
    "ImageInfo",
    "ImageSafetyError",
    "OpenAICompatibleProvider",
    "ProviderError",
    "ProviderResult",
    "ReportError",
    "ReportPaths",
    "Severity",
    "Verdict",
    "VisionProvider",
    "analyze",
    "compare_and_analyze",
    "compare_images",
    "create_provider",
    "render_html",
    "write_report",
]

__version__ = "0.1.0"
