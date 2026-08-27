"""Self-contained, injection-safe HTML and JSON report generation."""

# HTML and CSS are intentionally kept readable in this Python template.
# ruff: noqa: E501

from __future__ import annotations

import base64
import html
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .diff import DEFAULT_MAX_IMAGE_BYTES
from .models import AnalysisResult, Finding, Severity

_MIME_BY_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class ReportError(RuntimeError):
    """Raised when a safe report cannot be generated."""


@dataclass(frozen=True, slots=True)
class ReportPaths:
    html: Path
    json: Path


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _image_data_uri(path: Path, max_image_bytes: int) -> str:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ReportError(f"Cannot read report image '{path}': {exc.strerror or exc}") from exc
    if not path.is_file() or stat.st_size <= 0:
        raise ReportError(f"Report image is not a non-empty regular file: {path}")
    if stat.st_size > max_image_bytes:
        raise ReportError(f"Report image '{path.name}' exceeds the {max_image_bytes:,}-byte limit")
    try:
        with Image.open(path) as image:
            image.verify()
            mime = _MIME_BY_FORMAT.get((image.format or "").upper())
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ReportError(f"Cannot embed invalid image '{path}': {exc}") from exc
    if mime is None:
        raise ReportError(f"Unsupported report image format: {path.suffix or 'unknown'}")
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise ReportError(f"Cannot read report image '{path}': {exc.strerror or exc}") from exc
    return f"data:{mime};base64,{encoded}"


def _severity_rank(severity: Severity) -> int:
    return {
        Severity.CRITICAL: 0,
        Severity.MAJOR: 1,
        Severity.MINOR: 2,
        Severity.IGNORE: 3,
    }[severity]


def _finding_card(finding: Finding) -> str:
    suggestion = (
        f'<p class="suggestion"><strong>Next:</strong> {_escape(finding.suggestion)}</p>'
        if finding.suggestion
        else ""
    )
    region = _escape(finding.region_id or "whole image")
    return f"""
      <article class="finding severity-{_escape(finding.severity.value)}">
        <div class="finding-head">
          <span class="badge">{_escape(finding.severity.value)}</span>
          <span class="finding-region">{region}</span>
          <span class="confidence">{finding.confidence:.0%} confidence</span>
        </div>
        <h3>{_escape(finding.title)}</h3>
        <p>{_escape(finding.description)}</p>
        {suggestion}
      </article>"""


def render_html(
    result: AnalysisResult,
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> str:
    """Render a standalone HTML document with embedded screenshots."""

    baseline_uri = _image_data_uri(Path(baseline_path).expanduser(), max_image_bytes)
    candidate_uri = _image_data_uri(Path(candidate_path).expanduser(), max_image_bytes)
    comparison = result.comparison
    overlays = []
    for region in comparison.regions:
        box = region.bbox
        left = box.x / comparison.width * 100
        top = box.y / comparison.height * 100
        width = box.width / comparison.width * 100
        height = box.height / comparison.height * 100
        overlays.append(
            '<span class="roi" '
            f'style="left:{left:.6f}%;top:{top:.6f}%;width:{width:.6f}%;height:{height:.6f}%" '
            f'title="{_escape(region.id)}"></span>'
        )
    overlay_html = "".join(overlays)
    ordered_findings = sorted(
        result.findings, key=lambda item: (_severity_rank(item.severity), item.id)
    )
    findings_html = "".join(_finding_card(item) for item in ordered_findings)
    if not findings_html:
        findings_html = '<p class="empty">No findings were reported.</p>'

    # JSON is shown as escaped text rather than executable script data.
    json_preview = _escape(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    provider_model = result.provider + (f" · {result.model}" if result.model else "")
    if result.prompt_version:
        provider_model += f" · prompt {result.prompt_version}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>RenderWitness visual regression report</title>
  <style>
    :root {{ --bg:#0b1020; --panel:#131a2e; --panel2:#19223a; --text:#edf2ff;
      --muted:#aab5d1; --line:#2b385c; --accent:#7dd3fc; --danger:#fb7185;
      --high:#fb7185; --medium:#fbbf24; --low:#60a5fa; --info:#a78bfa; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 ui-sans-serif,
      system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1440px, calc(100% - 32px)); margin:32px auto 64px; }}
    h1,h2,h3,p {{ margin-top:0; }} h1 {{ font-size:clamp(26px,4vw,44px); margin-bottom:6px; }}
    h2 {{ margin-top:36px; font-size:22px; }} h3 {{ margin-bottom:8px; }}
    .eyebrow {{ color:var(--accent); text-transform:uppercase; letter-spacing:.14em; font-weight:800; }}
    .muted,.confidence,.finding-region {{ color:var(--muted); }}
    .summary-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:24px 0; }}
    .metric,.finding,.image-card,.summary,.details {{ background:var(--panel); border:1px solid var(--line);
      border-radius:14px; box-shadow:0 14px 40px rgb(0 0 0 / .14); }}
    .metric {{ padding:16px; }} .metric strong {{ display:block; font-size:24px; }}
    .metric span {{ color:var(--muted); }} .verdict {{ color:var(--accent); text-transform:uppercase; }}
    .summary {{ padding:18px 20px; }} .summary p:last-child {{ margin-bottom:0; }}
    .images {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    .image-card {{ padding:14px; overflow:hidden; }} .image-card h3 {{ font-size:15px; }}
    .image-wrap {{ position:relative; line-height:0; background:#fff; overflow:auto; border-radius:8px; }}
    .image-wrap img {{ display:block; width:100%; height:auto; }}
    .roi {{ position:absolute; border:2px solid var(--danger); background:rgb(251 113 133 / .16);
      box-shadow:0 0 0 1px rgb(255 255 255 / .7) inset; pointer-events:none; }}
    .findings {{ display:grid; gap:12px; }} .finding {{ padding:18px 20px; border-left:5px solid var(--info); }}
    .severity-critical,.severity-major {{ border-left-color:var(--high); }}
    .severity-minor {{ border-left-color:var(--medium); }} .severity-ignore {{ border-left-color:var(--low); }}
    .finding-head {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:12px; }}
    .badge {{ padding:2px 9px; border-radius:999px; background:var(--panel2); text-transform:uppercase;
      font-size:11px; font-weight:800; letter-spacing:.08em; }}
    .confidence {{ margin-left:auto; }} .suggestion {{ color:var(--muted); margin-bottom:0; }}
    .details {{ margin-top:32px; overflow:hidden; }} details summary {{ cursor:pointer; padding:16px 20px; font-weight:700; }}
    pre {{ margin:0; padding:20px; overflow:auto; max-height:520px; background:#080c18; color:#d8e1fa; font-size:12px; }}
    .empty {{ color:var(--muted); }}
    @media (max-width:900px) {{ .summary-grid {{ grid-template-columns:1fr 1fr; }} .images {{ grid-template-columns:1fr; }} }}
    @media (max-width:520px) {{ main {{ width:min(100% - 20px,1440px); margin-top:18px; }}
      .summary-grid {{ grid-template-columns:1fr; }} .confidence {{ margin-left:0; width:100%; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">RenderWitness</div>
    <h1>Visual regression report</h1>
    <p class="muted">Generated {_escape(result.generated_at.isoformat())} · {_escape(provider_model)} · {result.analysis_ms:.1f} ms</p>
  </header>
  <section class="summary-grid" aria-label="Comparison summary">
    <div class="metric"><span>Verdict</span><strong class="verdict">{_escape(result.verdict.value)}</strong></div>
    <div class="metric"><span>Changed pixels</span><strong>{comparison.changed_pixels:,}</strong></div>
    <div class="metric"><span>Change ratio</span><strong>{comparison.change_ratio:.2%}</strong></div>
    <div class="metric"><span>Regions / findings</span><strong>{len(comparison.regions)} / {len(result.findings)}</strong></div>
  </section>
  <section class="summary"><h2>Assessment</h2><p>{_escape(result.summary)}</p></section>
  <h2>Screenshots</h2>
  <section class="images">
    <article class="image-card"><h3>Baseline · {_escape(comparison.baseline.filename)}</h3>
      <div class="image-wrap"><img src="{baseline_uri}" alt="Baseline screenshot"></div></article>
    <article class="image-card"><h3>Candidate · {_escape(comparison.candidate.filename)}</h3>
      <div class="image-wrap"><img src="{candidate_uri}" alt="Candidate screenshot">{overlay_html}</div></article>
  </section>
  <h2>Findings</h2>
  <section class="findings">{findings_html}</section>
  <section class="details"><details><summary>Structured result</summary><pre>{json_preview}</pre></details></section>
</main>
</body>
</html>
"""


def _safe_output_name(value: str, expected_suffix: str) -> str:
    candidate = Path(value)
    if candidate.name != value or value in {"", ".", ".."}:
        raise ReportError("Report filenames must be simple names without directories")
    if candidate.suffix.lower() != expected_suffix:
        raise ReportError(f"Report filename must end in '{expected_suffix}'")
    return value


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ReportError(f"Cannot write report '{path}': {exc.strerror or exc}") from exc


def write_report(
    result: AnalysisResult,
    baseline_path: str | Path,
    candidate_path: str | Path,
    output_dir: str | Path,
    *,
    html_name: str = "index.html",
    json_name: str = "report.json",
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> ReportPaths:
    """Write a standalone HTML report and canonical structured JSON."""

    html_name = _safe_output_name(html_name, ".html")
    json_name = _safe_output_name(json_name, ".json")
    output = Path(output_dir).expanduser()
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReportError(
            f"Cannot create output directory '{output}': {exc.strerror or exc}"
        ) from exc
    if not output.is_dir():
        raise ReportError(f"Output path is not a directory: {output}")

    html_document = render_html(
        result,
        baseline_path,
        candidate_path,
        max_image_bytes=max_image_bytes,
    )
    json_document = result.model_dump_json(indent=2) + "\n"
    html_path = output / html_name
    json_path = output / json_name
    _atomic_write(html_path, html_document)
    _atomic_write(json_path, json_document)
    return ReportPaths(html=html_path.resolve(), json=json_path.resolve())
