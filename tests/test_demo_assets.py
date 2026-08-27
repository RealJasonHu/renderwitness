from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from PIL import Image, ImageChops

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_generator() -> ModuleType:
    script = REPOSITORY_ROOT / "scripts" / "generate_demo_assets.py"
    spec = importlib.util.spec_from_file_location("generate_demo_assets", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_demo_assets_match_benchmark_contract() -> None:
    benchmark_path = REPOSITORY_ROOT / "benchmarks" / "demo.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assets = benchmark["assets"]
    baseline_path = (benchmark_path.parent / assets["baseline"]).resolve()
    candidate_path = (benchmark_path.parent / assets["candidate"]).resolve()

    with Image.open(baseline_path) as baseline, Image.open(candidate_path) as candidate:
        assert baseline.size == candidate.size == (assets["width"], assets["height"])
        assert baseline.mode == candidate.mode == "RGB"
        assert ImageChops.difference(baseline, candidate).getbbox() is not None

        for mutation in benchmark["ground_truth"]:
            expected = mutation["expected_region"]
            box = (
                expected["x"],
                expected["y"],
                expected["x"] + expected["width"],
                expected["y"] + expected["height"],
            )
            localized_diff = ImageChops.difference(baseline.crop(box), candidate.crop(box))
            assert localized_diff.getbbox() is not None, mutation["id"]


def test_demo_generator_is_byte_deterministic(tmp_path: Path) -> None:
    generator = load_generator()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first_paths = generator.write_assets(first_dir)
    second_paths = generator.write_assets(second_dir)

    assert [path.read_bytes() for path in first_paths] == [
        path.read_bytes() for path in second_paths
    ]
