"""Self-contained, injection-safe HTML and JSON evidence workbench."""

# HTML and CSS are intentionally kept readable in this Python template.
# ruff: noqa: E501

from __future__ import annotations

import base64
import html
import io
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw

from .diff import (
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_PIXELS,
    ComparisonError,
    _load_image,
    _pixel_mask,
)
from .models import AnalysisResult, ComparisonResult, Finding, ImageInfo, Severity


class ReportError(RuntimeError):
    """Raised when a safe report cannot be generated."""


@dataclass(frozen=True, slots=True)
class ReportPaths:
    html: Path
    json: Path


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _verified_image(path: Path, expected: ImageInfo, max_image_bytes: int) -> Image.Image:
    """Use exactly the same orientation/alpha rules as the measured comparison."""
    try:
        image, actual = _load_image(
            path,
            max_image_bytes=max_image_bytes,
            max_pixels=max(DEFAULT_MAX_PIXELS, expected.width * expected.height),
        )
    except (ComparisonError, OSError) as exc:
        raise ReportError(f"Cannot embed invalid image '{path}': {exc}") from exc
    if actual.sha256 != expected.sha256:
        raise ReportError(
            f"Report image '{path.name}' has changed since comparison (SHA-256 mismatch). "
            "Run the comparison again before generating this report."
        )
    if image.size != (expected.width, expected.height):
        raise ReportError(f"Report image '{path.name}' dimensions no longer match the comparison")
    return image


def _png_data_uri(image: Image.Image) -> str:
    # Re-encoding also strips EXIF and embeds only the normalized, measured frame.
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _heatmap(
    baseline: Image.Image, candidate: Image.Image, comparison: ComparisonResult
) -> Image.Image:
    """Show threshold-qualified deltas, with ignored rectangles removed."""
    maximum, mask = _pixel_mask(ImageChops.difference(baseline, candidate), comparison.threshold)
    ignored_regions = getattr(comparison, "ignored_regions", [])
    if ignored_regions:
        drawer = ImageDraw.Draw(mask)
        for box in ignored_regions:
            drawer.rectangle((box.x, box.y, box.right - 1, box.bottom - 1), fill=0)
    # Quiet unchanged pixels make even small, threshold-qualified changes legible.
    quiet = Image.new("RGB", baseline.size, "#f0ede6")
    ramp = Image.merge(
        "RGB",
        (
            maximum.point(lambda value: 232 - round(value * 0.28)),
            maximum.point(lambda value: 174 - round(value * 0.48)),
            maximum.point(lambda value: 68 - round(value * 0.13)),
        ),
    )
    return Image.composite(ramp, quiet, mask)


def _severity_rank(severity: Severity) -> int:
    return {
        Severity.CRITICAL: 0,
        Severity.MAJOR: 1,
        Severity.MINOR: 2,
        Severity.IGNORE: 3,
    }[severity]


def _finding_card(finding: Finding, index: int) -> str:
    suggestion = (
        f'<div class="suggestion"><span>Suggested next step</span><p>{_escape(finding.suggestion)}</p></div>'
        if finding.suggestion
        else ""
    )
    region = finding.region_id or ""
    return f"""
      <article class="finding severity-{_escape(finding.severity.value)}" data-severity="{_escape(finding.severity.value)}" data-region="{_escape(region)}">
        <div class="finding-meta"><span class="issue-number">{index:02d}</span><span class="severity-badge">{_escape(finding.severity.value)}</span><span class="confidence">{finding.confidence:.0%} confidence</span></div>
        <h3><button type="button" class="finding-select" aria-pressed="false" data-region="{_escape(region)}">{_escape(finding.title)}<span aria-hidden="true">↗</span></button></h3>
        <p>{_escape(finding.description)}</p>
        {suggestion}
        <div class="finding-foot"><span>{_escape(finding.category)}</span><span>{_escape(region or "Whole image")}</span></div>
      </article>"""


def _region_overlays(comparison: ComparisonResult) -> str:
    overlays = []
    for index, region in enumerate(comparison.regions, 1):
        box = region.bbox
        overlays.append(
            '<span class="roi" '
            f'data-region="{_escape(region.id)}" '
            f'style="left:{box.x / comparison.width * 100:.6f}%;top:{box.y / comparison.height * 100:.6f}%;width:{box.width / comparison.width * 100:.6f}%;height:{box.height / comparison.height * 100:.6f}%" '
            f'title="{_escape(region.id)}: {box.width} × {box.height} px"><span>{index:02d}</span></span>'
        )
    for box in getattr(comparison, "ignored_regions", []):
        overlays.append(
            '<span class="excluded" '
            f'style="left:{box.x / comparison.width * 100:.6f}%;top:{box.y / comparison.height * 100:.6f}%;width:{box.width / comparison.width * 100:.6f}%;height:{box.height / comparison.height * 100:.6f}%" '
            'title="Excluded from comparison"></span>'
        )
    return "".join(overlays)


_STYLES = """
:root { color-scheme:light; --paper:#f6f5f1; --surface:#fffefa; --ink:#252921; --muted:#72766c; --line:#e3e5db; --green:#46633b; --green-soft:#e9efdf; --red:#a94434; --red-soft:#f8e8e1; --amber:#95651c; --mono:ui-monospace,SFMono-Regular,Consolas,monospace; }
* { box-sizing:border-box; } [hidden] { display:none !important; }
body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
button,input,select { font:inherit; } button { color:inherit; cursor:pointer; } button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible,a:focus-visible { outline:3px solid #718450; outline-offset:4px; }
a { color:inherit; } h1,h2,h3,p,figure { margin:0; } button { touch-action:manipulation; }
.skip-link { position:absolute; top:-80px; left:24px; z-index:10; padding:10px 14px; background:var(--ink); color:white; }.skip-link:focus { top:8px; }
.topbar { height:76px; padding:0 40px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:20px; background:var(--surface); }
.brand { display:flex; gap:11px; align-items:center; font-weight:700; font-size:17px; letter-spacing:-.6px; }.brand-mark { display:grid; place-items:center; width:30px; height:30px; background:var(--ink); border-radius:9px; color:#ebf0db; font-size:23px; font-weight:500; }
.top-meta { display:flex; align-items:center; gap:18px; font:11px var(--mono); color:var(--muted); }.offline { display:flex; align-items:center; gap:7px; }.offline::before { content:""; width:6px; height:6px; border-radius:50%; background:#728853; }
main { width:min(1680px,calc(100% - 80px)); margin:38px auto 40px; }
.eyebrow { font:10px var(--mono); text-transform:uppercase; letter-spacing:1.7px; color:var(--muted); }
.hero { display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin-bottom:28px; }
h1 { font-size:clamp(30px,3.4vw,46px); line-height:1.18; font-weight:550; letter-spacing:-1.8px; margin:10px 0; }.subtitle { color:var(--muted); font-size:13px; }.run-info { color:var(--muted); font:10px/1.8 var(--mono); text-align:right; flex-shrink:0; }
.summary-grid { display:grid; grid-template-columns:1.08fr 1fr 1fr 1fr; background:var(--surface); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.metric { padding:20px 24px; border-right:1px solid var(--line); }.metric:last-child { border:0; }.metric-label { color:var(--muted); font-size:11px; }.metric-value { display:flex; align-items:center; gap:10px; font-size:28px; font-weight:500; letter-spacing:-1px; margin:4px 0; line-height:1.3; }.metric-note { font:10px var(--mono); color:var(--muted); }.verdict-value { text-transform:capitalize; }.verdict-dot { width:9px; height:9px; border-radius:50%; background:var(--green); }.verdict-fail .verdict-dot { background:var(--red); }.verdict-review .verdict-dot { background:var(--amber); }
.assessment { display:flex; gap:16px; padding:18px 2px 24px; align-items:flex-start; }.assessment .eyebrow { flex-shrink:0; margin-top:5px; }.assessment p { font-size:13px; color:#555c4e; max-width:1050px; overflow-wrap:anywhere; }
.workspace { display:grid; grid-template-columns:minmax(0,1fr) 350px; align-items:start; border:1px solid var(--line); border-radius:12px; background:var(--surface); overflow:hidden; }.viewer { min-width:0; }.section-head { min-height:73px; display:flex; justify-content:space-between; align-items:center; gap:12px; padding:18px 22px; border-bottom:1px solid var(--line); }.section-head h2 { font-size:14px; font-weight:650; letter-spacing:-.25px; }.section-head p { font:10px var(--mono); color:var(--muted); margin-top:2px; }
.toolbar { display:flex; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:10px; padding:16px 20px; }.view-tabs { display:flex; border:1px solid var(--line); background:#f3f4ee; padding:3px; border-radius:7px; gap:2px; }.view-tab { border:0; background:transparent; color:var(--muted); font-size:11px; padding:6px 12px; border-radius:4px; white-space:nowrap; }.view-tab[aria-selected="true"] { color:var(--ink); background:white; box-shadow:0 1px 4px #27341a17; }.roi-control { display:flex; align-items:center; gap:7px; font-size:11px; color:#565e4e; cursor:pointer; }.roi-control input { width:13px; height:13px; accent-color:var(--green); }
.blend-controls { display:flex; align-items:center; gap:12px; padding:0 22px 15px; font:10px var(--mono); color:var(--muted); }.blend-controls label { white-space:nowrap; }.blend-controls input { flex:1; max-width:240px; min-width:50px; accent-color:var(--green); }.blend-controls output { min-width:34px; }
.stage-shell { padding:0 20px 20px; }.stage { position:relative; display:grid; grid-template-columns:1fr 1fr; gap:12px; align-items:start; }.image-panel { min-width:0; border:1px solid #dfe2d7; border-radius:7px; overflow:hidden; background:white; }.image-label { display:flex; align-items:center; justify-content:space-between; gap:8px; font:9px var(--mono); color:var(--muted); background:#f8f9f4; padding:10px 11px; border-bottom:1px solid var(--line); }.image-label strong { color:#4b5542; font:inherit; font-weight:600; }.image-label span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.image-wrap { position:relative; line-height:0; }.image-wrap img { display:block; width:100%; height:auto; }.heatmap-panel { grid-column:1/-1; display:none; }
.roi { position:absolute; border:1.5px solid #b9573d; background:#dd795111; pointer-events:none; box-shadow:0 0 0 1px #ffffff70 inset; transition:background .15s,border-color .15s; }.roi>span { position:absolute; top:0; left:0; color:white; background:#b9573d; font:8px/1.4 var(--mono); padding:1px 3px; }.roi.is-selected { z-index:2; border:3px solid #486337; background:#63813c20; box-shadow:0 0 0 2px #ffffffcf; }.roi.is-selected>span { background:#486337; }.excluded { position:absolute; border:1px dashed #818b92; background:repeating-linear-gradient(135deg,#6d778e16 0 4px,#ffffff36 4px 8px); pointer-events:none; }.hide-regions .roi,.hide-regions .excluded { display:none; }
.stage[data-view="blend"] { display:block; }.stage[data-view="blend"] .image-label { display:none; }.stage[data-view="blend"] .candidate-panel { position:absolute; inset:0; background:transparent; }.stage[data-view="blend"] .candidate-panel img { opacity:var(--blend,.5); }.stage[data-view="blend"] .baseline-panel .roi,.stage[data-view="blend"] .baseline-panel .excluded { visibility:hidden; }.stage[data-view="heatmap"] { display:block; }.stage[data-view="heatmap"] .baseline-panel,.stage[data-view="heatmap"] .candidate-panel { display:none; }.stage[data-view="heatmap"] .heatmap-panel { display:block; }
.viewer-note { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; padding:0 22px 18px; font:9px/1.6 var(--mono); color:var(--muted); }.legend { display:flex; gap:12px; align-items:center; }.legend span { display:flex; align-items:center; gap:5px; }.legend i { width:7px; height:7px; background:#b9573d; display:inline-block; border-radius:1px; }.legend .ignored-key { background:#a4adb1; }.selection-bar { padding:12px 22px; border-top:1px solid var(--line); display:flex; gap:10px; align-items:center; justify-content:space-between; background:#fafbf6; min-height:44px; font-size:11px; color:var(--muted); }.selection-bar button { border:0; background:transparent; padding:0; text-decoration:underline; font-size:11px; }
.findings-panel { border-left:1px solid var(--line); align-self:stretch; }.findings-panel .section-head { padding:18px 20px; }.count-pill { font:10px var(--mono); background:#edf0e5; border:1px solid #dfe5d3; color:#536348; padding:2px 7px; border-radius:4px; }.filter-bar { padding:12px 20px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:10px; justify-content:space-between; }.filter-bar label { font:10px var(--mono); color:var(--muted); }.filter-bar select { border:1px solid var(--line); border-radius:5px; padding:5px 22px 5px 8px; background:white; color:#505a46; font-size:10px; max-width:175px; }.findings-list { max-height:720px; overflow:auto; scrollbar-width:thin; }.finding { padding:20px; border-bottom:1px solid var(--line); }.finding:last-child { border-bottom:0; }.finding.is-selected { background:#f0f3e8; box-shadow:inset 3px 0 #6a7e4c; }.finding-meta { display:flex; align-items:center; gap:8px; margin-bottom:10px; }.issue-number { color:#8a8e81; font:9px var(--mono); }.severity-badge { font-size:9px; font-weight:650; background:#eef0e9; color:#6e785c; border-radius:3px; padding:2px 6px; text-transform:capitalize; }.severity-critical .severity-badge,.severity-major .severity-badge { background:var(--red-soft); color:var(--red); }.severity-minor .severity-badge { background:#f6eedc; color:var(--amber); }.confidence { margin-left:auto; color:var(--muted); font:9px var(--mono); }.finding h3 { margin-bottom:8px; }.finding-select { display:flex; justify-content:space-between; gap:8px; text-align:left; width:100%; padding:0; border:0; background:transparent; font-size:13px; font-weight:650; line-height:1.45; overflow-wrap:anywhere; }.finding-select span { color:#8a947c; }.finding p { color:#73796c; font-size:11px; line-height:1.7; overflow-wrap:anywhere; }.suggestion { margin-top:14px; padding:10px 11px; border-radius:5px; border:1px solid #e6e9df; background:#f7f8f2; }.suggestion>span { color:#526547; display:block; font-size:9px; font-weight:650; margin-bottom:4px; }.suggestion p { color:#66745a; font-size:10px; }.finding-foot { display:flex; flex-wrap:wrap; justify-content:space-between; gap:6px; font:8px var(--mono); color:#8a8f80; margin-top:13px; overflow-wrap:anywhere; }.empty { padding:24px 20px; color:var(--muted); font-size:12px; }
.evidence { margin-top:22px; border:1px solid var(--line); border-radius:9px; background:var(--surface); overflow:hidden; }.evidence summary { cursor:pointer; list-style:none; padding:16px 20px; display:flex; justify-content:space-between; align-items:center; gap:12px; font-size:12px; font-weight:600; }.evidence summary::-webkit-details-marker { display:none; }.evidence summary::after { content:"+"; font-size:18px; color:var(--muted); }.evidence[open] summary::after { content:"−"; }.evidence-meta { padding:0 20px 16px; display:grid; grid-template-columns:1fr 1fr; gap:14px; font:10px/1.8 var(--mono); color:var(--muted); }.evidence-meta strong { display:block; color:#515d45; font-weight:500; }.evidence-meta code { overflow-wrap:anywhere; }.json-head { display:flex; justify-content:space-between; padding:12px 20px; border-top:1px solid var(--line); background:#f2f4ec; font-size:11px; }.download-json { background:transparent; border:0; padding:0; font:10px var(--mono); text-decoration:underline; }.evidence pre { margin:0; padding:20px; background:#252b22; color:#dce4d3; overflow:auto; max-height:400px; font:10px/1.75 var(--mono); }
.footer { display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-top:25px; color:#83897a; font:9px/1.8 var(--mono); }.footer strong { font-weight:500; color:#657357; } noscript p { margin:0 20px 16px; color:var(--muted); font-size:11px; }
@media (min-width:1800px) { .findings-list { max-height:900px; } }
@media (max-width:1100px) { main { width:calc(100% - 40px); }.topbar { padding:0 20px; }.workspace { grid-template-columns:minmax(0,1fr) 310px; }.metric { padding:17px 18px; }.metric-value { font-size:25px; }.toolbar,.stage-shell { padding-left:14px; padding-right:14px; }.view-tab { padding:6px 9px; } }
@media (max-width:850px) { .workspace { grid-template-columns:1fr; }.findings-panel { border-left:0; border-top:1px solid var(--line); }.findings-list { max-height:none; display:grid; grid-template-columns:1fr 1fr; }.finding { border-right:1px solid var(--line); }.finding:last-child { border-bottom:1px solid var(--line); }.run-info { display:none; }.assessment { display:block; }.assessment .eyebrow { margin:0 0 8px; }.top-meta .report-id { display:none; } }
@media (max-width:520px) { main { width:calc(100% - 24px); margin-top:25px; }.topbar { height:62px; padding:0 16px; }.brand { font-size:15px; }.top-meta { font-size:9px; }.summary-grid { grid-template-columns:1fr 1fr; }.metric:nth-child(2) { border-right:0; }.metric:nth-child(-n+2) { border-bottom:1px solid var(--line); }.metric { padding:15px; }.metric-value { font-size:25px; } h1 { font-size:32px; }.subtitle { font-size:12px; }.hero { margin-bottom:20px; }.findings-list { display:block; }.stage[data-view="split"] { grid-template-columns:1fr; }.section-head { padding:16px; }.image-label { padding:8px 10px; }.evidence-meta { grid-template-columns:1fr; }.selection-bar { padding:12px 16px; }.viewer-note { padding:0 16px 16px; }.finding { border-right:0; }.view-tab { padding:6px 10px; } }
@media (prefers-reduced-motion:reduce) { * { transition:none !important; scroll-behavior:auto !important; } }
@media print { .topbar,.toolbar,.blend-controls,.filter-bar,.selection-bar,.download-json { display:none !important; } main { width:100%; margin:0; }.workspace { display:block; }.findings-panel { border-left:0; }.findings-list { max-height:none; overflow:visible; }.finding { break-inside:avoid; }.stage { break-inside:avoid; }.evidence:not([open]) { display:none; } }
"""

# Static code only. Provider content is escaped HTML text/data attributes, never JS.
_SCRIPT = """
(() => {
  'use strict';
  const stage = document.getElementById('comparison-stage');
  const tabs = Array.from(document.querySelectorAll('.view-tab'));
  const blend = document.getElementById('blend-controls');
  const blendInput = document.getElementById('blend-range');
  const blendOutput = document.getElementById('blend-value');
  const viewDescription = document.getElementById('view-description');
  const regionToggle = document.getElementById('region-toggle');
  const selection = document.getElementById('selection-status');
  const clear = document.getElementById('clear-selection');
  const cards = Array.from(document.querySelectorAll('.finding'));
  const regions = Array.from(document.querySelectorAll('.roi'));
  const descriptions = {
    split: 'Baseline and candidate, shown at the same scale.',
    blend: 'Baseline beneath candidate. Adjust candidate opacity to compare alignment.',
    heatmap: 'Threshold-qualified change intensity; excluded pixels are omitted.'
  };
  function setView(tab) {
    const view = tab.dataset.view;
    stage.dataset.view = view;
    stage.setAttribute('aria-labelledby', tab.id);
    tabs.forEach(item => {
      item.setAttribute('aria-selected', String(item === tab));
      item.tabIndex = item === tab ? 0 : -1;
    });
    blend.hidden = view !== 'blend';
    viewDescription.textContent = descriptions[view];
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setView(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined) {
        event.preventDefault();
        tabs[next].focus();
        setView(tabs[next]);
      }
    });
  });
  blendInput.addEventListener('input', () => {
    stage.style.setProperty('--blend', String(Number(blendInput.value) / 100));
    blendOutput.value = blendInput.value + '%';
  });
  regionToggle.addEventListener('change', () => {
    stage.classList.toggle('hide-regions', !regionToggle.checked);
  });
  function clearSelection() {
    cards.forEach(card => {
      card.classList.remove('is-selected');
      card.querySelector('.finding-select').setAttribute('aria-pressed', 'false');
    });
    regions.forEach(region => region.classList.remove('is-selected'));
    selection.textContent = 'Select a finding to locate its evidence.';
    clear.hidden = true;
  }
  cards.forEach(card => {
    card.querySelector('.finding-select').addEventListener('click', () => {
      if (card.classList.contains('is-selected')) { clearSelection(); return; }
      clearSelection();
      card.classList.add('is-selected');
      card.querySelector('.finding-select').setAttribute('aria-pressed', 'true');
      const regionId = card.dataset.region;
      const matches = regions.filter(region => regionId && region.dataset.region === regionId);
      matches.forEach(region => region.classList.add('is-selected'));
      regionToggle.checked = true;
      stage.classList.remove('hide-regions');
      selection.textContent = matches.length ? 'Focused evidence: ' + regionId : 'Whole-image finding — review the full comparison.';
      clear.hidden = false;
    });
  });
  clear.addEventListener('click', clearSelection);
  document.getElementById('severity-filter').addEventListener('change', event => {
    const severity = event.target.value;
    let visible = 0;
    cards.forEach(card => {
      card.hidden = severity !== 'all' && card.dataset.severity !== severity;
      if (!card.hidden) visible += 1;
    });
    clearSelection();
    document.getElementById('visible-count').textContent = String(visible);
    document.getElementById('filter-empty').hidden = visible !== 0;
  });
  document.getElementById('download-json').addEventListener('click', () => {
    const content = document.getElementById('structured-result').textContent;
    const url = URL.createObjectURL(new Blob([content + '\\n'], { type:'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'renderwitness-report.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
"""


def render_html(
    result: AnalysisResult,
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> str:
    """Render a portable workbench after verifying the original image evidence."""
    comparison = result.comparison
    baseline = _verified_image(
        Path(baseline_path).expanduser(), comparison.baseline, max_image_bytes
    )
    candidate = _verified_image(
        Path(candidate_path).expanduser(), comparison.candidate, max_image_bytes
    )
    baseline_uri = _png_data_uri(baseline)
    candidate_uri = _png_data_uri(candidate)
    heatmap_uri = _png_data_uri(_heatmap(baseline, candidate, comparison))
    overlay_html = _region_overlays(comparison)
    ordered = sorted(result.findings, key=lambda item: (_severity_rank(item.severity), item.id))
    findings_html = "".join(_finding_card(item, index) for index, item in enumerate(ordered, 1))
    counts = Counter(item.severity.value for item in result.findings)
    options = "".join(
        f'<option value="{severity.value}">{severity.value.capitalize()} ({counts[severity.value]})</option>'
        for severity in sorted(Severity, key=_severity_rank)
    )
    empty_hidden = " hidden" if result.findings else ""
    json_preview = _escape(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    provider_model = result.provider + (f" · {result.model}" if result.model else "")
    if result.prompt_version:
        provider_model += f" · prompt {result.prompt_version}"
    ignored_pixels = getattr(comparison, "ignored_pixels", 0)
    ignored_count = len(getattr(comparison, "ignored_regions", []))
    timestamp = result.generated_at.strftime("%Y-%m-%d · %H:%M:%S %Z")
    run_id = comparison.baseline.sha256[:5] + " → " + comparison.candidate.sha256[:5]
    highest = next(
        (item.severity.value for item in ordered if item.severity != Severity.IGNORE), None
    )
    findings_note = f"Highest severity: {highest}" if highest else "No actionable findings"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>RenderWitness — visual evidence report</title>
  <style>{_STYLES}</style>
</head>
<body>
<a class="skip-link" href="#comparison-workspace">Skip to comparison</a>
<header class="topbar"><div class="brand"><span class="brand-mark" aria-hidden="true">⌗</span>RenderWitness</div><div class="top-meta"><span class="report-id">{run_id}</span><span class="offline">Self-contained report</span></div></header>
<main>
  <section class="hero" aria-labelledby="report-title"><div><div class="eyebrow">Visual quality / evidence review</div><h1 id="report-title">Every change, in context.</h1><p class="subtitle">A visual regression report with the evidence close at hand.</p></div><div class="run-info">{_escape(timestamp)}<br>{_escape(provider_model)}<br>{result.analysis_ms:,.1f} ms analysis</div></section>
  <section class="summary-grid" aria-label="Comparison summary">
    <div class="metric verdict-{_escape(result.verdict.value)}"><div class="metric-label">Review verdict</div><strong class="metric-value verdict-value"><span class="verdict-dot" aria-hidden="true"></span>{_escape(result.verdict.value)}</strong><div class="metric-note">{_escape(findings_note)}</div></div>
    <div class="metric"><div class="metric-label">Changed pixels</div><strong class="metric-value">{comparison.changed_pixels:,}</strong><div class="metric-note">of {comparison.total_pixels - ignored_pixels:,} compared pixels</div></div>
    <div class="metric"><div class="metric-label">Change ratio</div><strong class="metric-value">{comparison.change_ratio:.2%}</strong><div class="metric-note">channel delta &gt; {comparison.threshold} / 255</div></div>
    <div class="metric"><div class="metric-label">Findings to review</div><strong class="metric-value">{len(result.findings):02d}</strong><div class="metric-note">across {len(comparison.regions)} detected regions</div></div>
  </section>
  <section class="assessment" aria-label="Assessment"><div class="eyebrow">Assessment</div><p>{_escape(result.summary)}</p></section>
  <section class="workspace" id="comparison-workspace" aria-label="Visual evidence workbench" tabindex="-1">
    <section class="viewer" aria-labelledby="comparison-heading">
      <div class="section-head"><div><h2 id="comparison-heading">Visual comparison</h2><p>{comparison.width:,} × {comparison.height:,} px · normalized to RGB</p></div><span class="count-pill">{len(comparison.regions):02d} regions</span></div>
      <div class="toolbar"><div class="view-tabs" role="tablist" aria-label="Comparison view"><button type="button" id="view-split" class="view-tab" role="tab" aria-controls="comparison-stage" aria-selected="true" data-view="split">Side by side</button><button type="button" id="view-blend" class="view-tab" role="tab" aria-controls="comparison-stage" aria-selected="false" tabindex="-1" data-view="blend">Blend</button><button type="button" id="view-heatmap" class="view-tab" role="tab" aria-controls="comparison-stage" aria-selected="false" tabindex="-1" data-view="heatmap">Diff map</button></div><label class="roi-control"><input type="checkbox" id="region-toggle" checked> Show regions</label></div>
      <div class="blend-controls" id="blend-controls" hidden><label for="blend-range">Candidate opacity</label><input type="range" id="blend-range" min="0" max="100" value="50" step="1"><output id="blend-value" for="blend-range">50%</output><span>0% baseline · 100% candidate</span></div>
      <noscript><p>JavaScript is disabled. The complete side-by-side evidence, findings, and structured result remain available.</p></noscript>
      <div class="stage-shell"><div class="stage" id="comparison-stage" data-view="split" role="tabpanel" aria-labelledby="view-split" tabindex="0">
        <figure class="image-panel baseline-panel"><figcaption class="image-label"><strong>BASELINE</strong><span>{_escape(comparison.baseline.filename)}</span></figcaption><div class="image-wrap"><img src="{baseline_uri}" alt="Baseline screenshot" width="{comparison.width}" height="{comparison.height}">{overlay_html}</div></figure>
        <figure class="image-panel candidate-panel"><figcaption class="image-label"><strong>CANDIDATE</strong><span>{_escape(comparison.candidate.filename)}</span></figcaption><div class="image-wrap"><img src="{candidate_uri}" alt="Candidate screenshot" width="{comparison.width}" height="{comparison.height}">{overlay_html}</div></figure>
        <figure class="image-panel heatmap-panel"><figcaption class="image-label"><strong>DIFFERENCE INTENSITY</strong><span>Light amber → deep rust · low → high delta</span></figcaption><div class="image-wrap"><img src="{heatmap_uri}" alt="Thresholded pixel difference heatmap with ignored regions excluded" width="{comparison.width}" height="{comparison.height}">{overlay_html}</div></figure>
      </div></div>
      <div class="viewer-note"><span id="view-description" aria-live="polite">Baseline and candidate, shown at the same scale.</span><div class="legend"><span><i></i>Detected region</span><span><i class="ignored-key"></i>{ignored_count} exclusions · {ignored_pixels:,} px</span></div></div>
      <div class="selection-bar"><span id="selection-status" role="status">Select a finding to locate its evidence.</span><button id="clear-selection" type="button" hidden>Clear selection</button></div>
    </section>
    <aside class="findings-panel" aria-labelledby="findings-heading"><div class="section-head"><div><h2 id="findings-heading">Findings</h2><p>Ordered by severity</p></div><span class="count-pill" id="visible-count" aria-live="polite">{len(result.findings)}</span></div><div class="filter-bar"><label for="severity-filter">SEVERITY</label><select id="severity-filter"><option value="all">All findings ({len(result.findings)})</option>{options}</select></div><div class="findings-list">{findings_html}<p class="empty" id="filter-empty" role="status"{empty_hidden}>No findings match this filter.</p></div></aside>
  </section>
  <details class="evidence"><summary>Evidence &amp; structured result</summary><div class="evidence-meta"><div><strong>Baseline SHA-256 · verified at report generation</strong><code>{comparison.baseline.sha256}</code></div><div><strong>Candidate SHA-256 · verified at report generation</strong><code>{comparison.candidate.sha256}</code></div><div><strong>Analysis provenance</strong>{_escape(provider_model)}<br>{_escape(result.generated_at.isoformat())}</div><div><strong>Comparison settings</strong>{_escape(comparison.algorithm_version)} · threshold {comparison.threshold}<br>min area {comparison.min_region_area} · grouping {comparison.grouping_distance} px · padding {comparison.region_padding} px<br>{ignored_count} excluded rectangles · {ignored_pixels:,} ignored pixels</div></div><div class="json-head"><span>Canonical JSON</span><button class="download-json" id="download-json" type="button">Download JSON ↓</button></div><pre id="structured-result">{json_preview}</pre></details>
  <footer class="footer"><span><strong>RenderWitness</strong> / Evidence first. Human judgment always.</span><span>Embedded images · no external assets · source hashes verified</span></footer>
</main>
<script>{_SCRIPT}</script>
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
