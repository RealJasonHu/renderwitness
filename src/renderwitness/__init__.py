"""RenderWitness: explainable visual-regression review for screenshots."""

from .analyzer import AnalysisError, analyze, compare_and_analyze
from .capture import CaptureError, CaptureOptions, CaptureResult, capture_page
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
from .policy import GatePolicy, GateResult, evaluate_policy
from .providers import (
    DemoProvider,
    OpenAICompatibleProvider,
    ProviderError,
    VisionProvider,
    create_provider,
)
from .report import ReportError, ReportPaths, render_html, write_report
from .suite import SuiteConfig, SuiteError, SuiteResult, load_suite, run_suite

__all__ = [
    "AnalysisError",
    "AnalysisResult",
    "BoundingBox",
    "CaptureError",
    "CaptureOptions",
    "CaptureResult",
    "ComparisonError",
    "ComparisonResult",
    "DemoProvider",
    "DiffRegion",
    "Finding",
    "GatePolicy",
    "GateResult",
    "ImageInfo",
    "ImageSafetyError",
    "OpenAICompatibleProvider",
    "ProviderError",
    "ProviderResult",
    "ReportError",
    "ReportPaths",
    "Severity",
    "SuiteConfig",
    "SuiteError",
    "SuiteResult",
    "Verdict",
    "VisionProvider",
    "analyze",
    "capture_page",
    "compare_and_analyze",
    "compare_images",
    "create_provider",
    "evaluate_policy",
    "load_suite",
    "render_html",
    "run_suite",
    "write_report",
]

__version__ = "0.2.0"
