from __future__ import annotations

import json
from pathlib import Path

import pytest

from renderwitness.cli import main


def test_demo_command_runs_offline_and_writes_auditable_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "demo"

    status = main(["demo", "--output", str(output)])

    captured = capsys.readouterr()
    assert status == 0
    assert "no vlm or network call" in captured.out.lower()
    assert (output / "images" / "baseline.png").is_file()
    assert (output / "images" / "candidate.png").is_file()
    assert (output / "index.html").is_file()
    report_path = output / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["provider"] == "demo"
    assert payload["comparison"]["changed_pixels"] > 0


def test_compare_command_writes_report_and_prints_metrics(
    image_pair: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline, candidate = image_pair
    output = tmp_path / "compare"

    status = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--provider",
            "demo",
            "--min-region-area",
            "1",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Verdict:" in captured.out
    assert "Changed:" in captured.out
    assert f"HTML: {(output / 'index.html').resolve()}" in captured.out
    assert (output / "report.json").is_file()


def test_fail_on_change_is_a_ci_friendly_exit_status(
    image_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    baseline, candidate = image_pair

    changed_status = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--min-region-area",
            "1",
            "--output",
            str(tmp_path / "changed"),
            "--fail-on-change",
        ]
    )
    identical_status = main(
        [
            "compare",
            str(baseline),
            str(baseline),
            "--output",
            str(tmp_path / "identical"),
            "--fail-on-change",
        ]
    )

    assert changed_status == 1
    assert identical_status == 0


def test_operational_errors_return_two_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.png"

    status = main(
        [
            "compare",
            str(missing),
            str(missing),
            "--output",
            str(tmp_path / "report"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "renderwitness: error:" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["compare", "a.png", "b.png", "--threshold", "256"],
        ["compare", "a.png", "b.png", "--min-region-area", "0"],
        ["compare", "a.png", "b.png", "--max-regions", "not-a-number"],
    ],
)
def test_cli_rejects_invalid_numeric_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    assert exc_info.value.code == 2


def test_cli_version_is_available_without_reading_images(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == "RenderWitness 0.2.0"
