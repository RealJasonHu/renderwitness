"""Portable suite summaries for humans and CI services."""

# HTML/CSS are kept inline so suite reports have no runtime assets.
# ruff: noqa: E501
from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

from .report import _atomic_write

if TYPE_CHECKING:
    from .suite import SuiteResult


def _markdown(value: str) -> str:
    return html.escape(value).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def _xml_safe(value: str) -> str:
    return "".join(
        char
        if char in "\t\n\r"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
        else "\ufffd"
        for char in value
    )


def write_suite_report(result: SuiteResult, output: Path) -> None:
    """Write machine-readable, browser, Markdown, and JUnit summaries."""
    counts = {
        status: sum(c.status == status for c in result.cases)
        for status in ("passed", "failed", "error")
    }
    payload = result.model_dump(mode="json")
    payload.update(counts=counts, exit_code=result.exit_code)
    _atomic_write(output / "summary.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    lines = [
        f"# {_markdown(result.name)}",
        "",
        f"{counts['passed']} passed · {counts['failed']} failed · {counts['error']} errors",
        "",
        "| Scenario | CI gate | Changed | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    rows: list[str] = []
    junit = ET.Element(
        "testsuite",
        {
            "name": _xml_safe(result.name),
            "tests": str(len(result.cases)),
            "failures": str(counts["failed"]),
            "errors": str(counts["error"]),
            "time": f"{sum(case.duration_seconds for case in result.cases):.6f}",
        },
    )
    for case in result.cases:
        ratio = f"{case.change_ratio:.2%}" if case.change_ratio is not None else "—"
        evidence = f"[Report]({case.report})" if case.report else "—"
        lines.append(f"| {_markdown(case.name)} | {case.status} | {ratio} | {evidence} |")
        reasons = case.error or (" ".join(case.gate.reasons) if case.gate else "")
        link = (
            f'<a href="{html.escape(case.report, quote=True)}">Open report ↗</a>'
            if case.report
            else "—"
        )
        rows.append(
            f"<tr><td><strong>{html.escape(case.name)}</strong><small>{html.escape(case.id)}</small></td>"
            f'<td><span class="status {case.status}">{case.status}</span></td>'
            f"<td>{ratio}</td><td>{link}</td></tr>"
            + (
                f'<tr class="reason"><td colspan="4">{html.escape(reasons)}</td></tr>'
                if reasons
                else ""
            )
        )
        element = ET.SubElement(
            junit,
            "testcase",
            {
                "name": _xml_safe(case.name),
                "classname": _xml_safe(result.name),
                "time": f"{case.duration_seconds:.6f}",
            },
        )
        if case.status != "passed":
            failure = ET.SubElement(
                element,
                "error" if case.status == "error" else "failure",
                {"message": _xml_safe(reasons)},
            )
            failure.text = _xml_safe(reasons)
        if case.report:
            ET.SubElement(element, "system-out").text = case.report
    _atomic_write(output / "summary.md", "\n".join(lines) + "\n")
    ET.indent(junit)
    _atomic_write(output / "junit.xml", ET.tostring(junit, encoding="unicode") + "\n")
    style = """
    *{box-sizing:border-box}body{margin:0;background:#f6f5f1;color:#242923;font:15px/1.6 system-ui,sans-serif}
    main{max-width:1100px;margin:64px auto;padding:0 24px}header{border-bottom:1px solid #d8dcd5;padding-bottom:28px}
    .brand{letter-spacing:.16em;font-size:12px;font-weight:750;color:#397058}h1{font-size:clamp(28px,5vw,46px);line-height:1.15}
    p,small{color:#647064}small{display:block;font-size:12px}nav{display:flex;gap:20px;margin:24px 0}a{color:#215940}
    .metrics{display:flex;gap:12px;margin:28px 0;flex-wrap:wrap}.metric{background:white;border:1px solid #dce0d8;border-radius:12px;padding:20px;flex:1;min-width:140px}
    .metric strong{display:block;font-size:32px}.table{overflow:auto;background:white;border:1px solid #dce0d8;border-radius:12px}
    table{border-collapse:collapse;width:100%;min-width:600px}th,td{text-align:left;padding:18px;border-bottom:1px solid #eceee8}
    th{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#647064}.status{border-radius:20px;padding:4px 10px;font-size:12px}
    .passed{background:#e5f2e9;color:#285b3e}.failed{background:#fff0dc;color:#7c5115}.error{background:#ffe8e5;color:#912e29}
    .reason td{padding-top:0;color:#725d47;font-size:13px;overflow-wrap:anywhere}
    """
    cards = "".join(
        f'<div class="metric"><strong>{count}</strong>{status}</div>'
        for status, count in counts.items()
    )
    document = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(result.name)} · RenderWitness</title><style>{style}</style>
<main><header><div class="brand">RENDERWITNESS / SUITE</div><h1>{html.escape(result.name)}</h1>
<p>Every scenario, its CI decision, and the evidence behind it.</p></header>
<div class="metrics">{cards}</div><nav><a href="summary.json">JSON</a><a href="summary.md">Markdown</a><a href="junit.xml">JUnit XML</a></nav>
<div class="table"><table><thead><tr><th>Scenario</th><th>CI gate</th><th>Changed</th><th>Evidence</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p>CI gates use your configured thresholds. Provider verdicts remain available inside each report.</p></main></html>"""
    _atomic_write(output / "index.html", document)
