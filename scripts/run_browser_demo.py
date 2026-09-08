"""Capture real desktop/mobile fixture pages, then run their regression suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from renderwitness.capture import CaptureOptions, capture_page
from renderwitness.suite import run_suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/browser-demo"))
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose a new or empty output directory for this run")
    pages = Path(__file__).resolve().parents[1] / "examples" / "web"
    scenarios = []
    for label, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
        for revision in ("baseline", "candidate"):
            capture_page(
                (pages / f"{revision}.html").as_uri(),
                output / "images" / f"{label}-{revision}.png",
                options=CaptureOptions(
                    width=width,
                    height=height,
                    locale="zh-CN",
                    wait_for="main",
                    mask_selectors=("#live-clock",),
                ),
            )
        scenarios.append(
            {
                "id": f"{label}-regression",
                "name": f"{label.title()} · seeded UI regressions",
                "baseline": f"images/{label}-baseline.png",
                "candidate": f"images/{label}-candidate.png",
            }
        )
    scenarios.append(
        {
            "id": "unchanged-control",
            "name": "Unchanged capture · control",
            "baseline": "images/desktop-baseline.png",
            "candidate": "images/desktop-baseline.png",
        }
    )
    config = output / "suite.json"
    config.write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Browser capture · release review",
                "policy": {"max_change_ratio": 0},
                "scenarios": scenarios,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_suite(config, output / "review")
    expected = ["failed", "failed", "passed"]
    if [case.status for case in result.cases] != expected:
        raise RuntimeError(f"Demo did not produce expected outcomes: {result.model_dump_json()}")
    print("Captured real browser pages. Both seeded regressions failed the configured gate.")
    print("The unchanged control passed. No semantic model or network endpoint was used.")
    print(f"Report: {output / 'review' / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
