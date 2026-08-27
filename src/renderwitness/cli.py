"""Command-line interface for RenderWitness."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import ValidationError

from .analyzer import AnalysisError, analyze
from .diff import ComparisonError, compare_images
from .providers import ProviderError, create_provider
from .report import ReportError, write_report


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _threshold(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 0 <= parsed <= 255:
        raise argparse.ArgumentTypeError("must be between 0 and 255")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renderwitness",
        description=(
            "Explain screenshot regressions with deterministic ROIs and optional VLM analysis."
        ),
    )
    parser.add_argument("--version", action="version", version="RenderWitness 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    compare = commands.add_parser("compare", help="Compare baseline and candidate screenshots")
    compare.add_argument("baseline", type=Path, help="Baseline screenshot")
    compare.add_argument("candidate", type=Path, help="Candidate screenshot")
    compare.add_argument("-o", "--output", type=Path, default=Path("renderwitness-report"))
    compare.add_argument("--provider", choices=("demo", "openai-compatible"), default="demo")
    compare.add_argument("--base-url", help="OpenAI-compatible API base URL")
    compare.add_argument("--model", help="Vision model name")
    compare.add_argument(
        "--api-key-env",
        default="RENDERWITNESS_API_KEY",
        help="Environment variable containing the API key (default: RENDERWITNESS_API_KEY)",
    )
    compare.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Provider timeout in seconds (default: RENDERWITNESS_TIMEOUT or 60)",
    )
    compare.add_argument("--threshold", type=_threshold, default=24)
    compare.add_argument("--min-region-area", type=_positive_int, default=16)
    compare.add_argument("--max-regions", type=_positive_int, default=20)
    compare.add_argument("--grouping-distance", type=_threshold, default=8)
    compare.add_argument(
        "--region-padding",
        type=_threshold,
        default=24,
        help="Context pixels added around each raw diff region",
    )
    compare.add_argument("--max-image-mb", type=_positive_int, default=25)
    compare.add_argument("--max-pixels", type=_positive_int, default=40_000_000)
    compare.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Exit with status 1 when any pixel exceeds the threshold",
    )

    demo = commands.add_parser("demo", help="Generate and analyze a deterministic local example")
    demo.add_argument("-o", "--output", type=Path, default=Path("renderwitness-demo"))
    return parser


def _draw_demo_screen(path: Path, *, candidate: bool) -> None:
    image = Image.new("RGB", (960, 540), "#eef3fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 959, 72), fill="#111827")
    draw.text((34, 25), "RenderWitness Shop", fill="white")
    draw.rectangle((32, 104, 928, 504), fill="white", outline="#d7deea", width=2)
    draw.text((64, 136), "Summer collection", fill="#111827")
    draw.text((64, 168), "Visual checks before every release", fill="#5b6472")
    cards = [(64, 224, 304, 432), (360, 224, 600, 432), (656, 224, 896, 432)]
    colors = ("#dbeafe", "#ede9fe", "#dcfce7")
    for index, (box, color) in enumerate(zip(cards, colors, strict=True), start=1):
        draw.rounded_rectangle(box, radius=14, fill=color)
        draw.text((box[0] + 18, box[1] + 148), f"Product {index}", fill="#111827")
    button_box = (738, 126, 896, 178)
    button_color = "#dc2626" if candidate else "#2563eb"
    draw.rounded_rectangle(button_box, radius=10, fill=button_color)
    draw.text((777, 144), "View cart", fill="white")
    if candidate:
        draw.rectangle((378, 244, 582, 350), fill="#fef3c7")
        draw.text((407, 286), "Image unavailable", fill="#92400e")
        draw.text((378, 380), "Product two - sold out", fill="#7f1d1d")
    else:
        draw.ellipse((422, 247, 538, 363), fill="#8b5cf6")
    image.save(path, format="PNG", optimize=False)


def _run_compare(args: argparse.Namespace) -> int:
    max_image_bytes = args.max_image_mb * 1024 * 1024
    api_key = os.getenv(args.api_key_env) if args.api_key_env else None
    provider = create_provider(
        args.provider,
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        timeout=args.timeout,
        max_image_bytes=max_image_bytes,
    )
    comparison = compare_images(
        args.baseline,
        args.candidate,
        threshold=args.threshold,
        min_region_area=args.min_region_area,
        max_regions=args.max_regions,
        grouping_distance=args.grouping_distance,
        region_padding=args.region_padding,
        max_image_bytes=max_image_bytes,
        max_pixels=args.max_pixels,
    )
    result = analyze(
        comparison,
        args.baseline,
        args.candidate,
        provider=provider,
    )
    paths = write_report(
        result,
        args.baseline,
        args.candidate,
        args.output,
        max_image_bytes=max_image_bytes,
    )
    print(f"Verdict: {result.verdict.value}")
    print(
        f"Changed: {comparison.changed_pixels:,}/{comparison.total_pixels:,} "
        f"pixels ({comparison.change_ratio:.2%})"
    )
    print(f"HTML: {paths.html}")
    print(f"JSON: {paths.json}")
    return 1 if args.fail_on_change and not comparison.identical else 0


def _run_demo(args: argparse.Namespace) -> int:
    output = args.output.expanduser()
    images = output / "images"
    images.mkdir(parents=True, exist_ok=True)
    baseline = images / "baseline.png"
    candidate = images / "candidate.png"
    package_assets = Path(__file__).with_name("assets")
    repository_examples = Path(__file__).resolve().parents[2] / "examples"
    source_directory = next(
        (
            directory
            for directory in (package_assets, repository_examples)
            if (directory / "baseline.png").is_file() and (directory / "candidate.png").is_file()
        ),
        None,
    )
    if source_directory is not None:
        source_baseline = source_directory / "baseline.png"
        source_candidate = source_directory / "candidate.png"
        shutil.copyfile(source_baseline, baseline)
        shutil.copyfile(source_candidate, candidate)
        fixture_name = "bundled bilingual dashboard fixture"
    else:
        _draw_demo_screen(baseline, candidate=False)
        _draw_demo_screen(candidate, candidate=True)
        fixture_name = "generated fallback fixture"

    comparison = compare_images(baseline, candidate)
    result = analyze(comparison, baseline, candidate)
    paths = write_report(result, baseline, candidate, output)
    print(f"Created deterministic offline demo from the {fixture_name}.")
    print("No VLM or network call was made.")
    print(f"HTML: {paths.html}")
    print(f"JSON: {paths.json}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns an exit status for easy testing."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            return _run_compare(args)
        if args.command == "demo":
            return _run_demo(args)
        parser.error(f"unknown command: {args.command}")
    except (ComparisonError, ProviderError, AnalysisError, ReportError, ValidationError) as exc:
        print(f"renderwitness: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"renderwitness: error: {exc.strerror or exc}", file=sys.stderr)
        return 2
    return 2
