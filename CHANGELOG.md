# Changelog

User-facing changes are recorded here. The project remains alpha; pin a version and review
configuration/output changes when upgrading.

## 0.2.0

### Added

- Optional Chromium browser capture with viewport, locale, readiness selectors, repeated masks,
  and full-page capture.
- Capture sidecar metadata with browser settings/version, image dimensions, hash, and redacted URLs.
- JSON screenshot suites with per-scenario diff and policy overrides, configuration validation,
  relative image paths, and independent case execution.
- Explicit CI policies for changed-pixel budgets, severity/confidence thresholds, and review verdicts.
- Suite HTML overview, JSON and Markdown summaries, JUnit XML, and per-case evidence directories.
- Ignore rectangles with union counting, bounds validation, and nonignored-pixel ratio accounting.
- Normalized model inputs with ignored rectangles covered consistently in both screenshots.
- Interactive report inspection with split/blend/diff modes and finding filters.
- A bilingual browser fixture and expanded workflow, CI, architecture, and contributor guides.

### Changed

- Provider verdicts and process exit decisions are explicitly separated.
- Single comparisons save deterministic comparison evidence and a separate gate record.
- Provider failures after successful comparison attempt an explicitly unavailable fallback report;
  they remain operational errors with exit code 2.
- Suite execution continues after a case error and reports errors separately from gate failures.
- Suite output must be a new or empty directory to avoid stale reports from prior runs.
- Comparison reruns invalidate earlier result files before processing new inputs.
- Documentation distinguishes synthetic demo behavior from real-model capabilities and evaluation.

### Compatibility notes

- The existing `demo`, `compare`, provider options, and `--fail-on-change` workflow remain available.
- Browser dependencies are optional; screenshot comparison does not require Playwright.
- With ignore rectangles, `change_ratio` uses nonignored pixels as its denominator.
- The executable suite format is JSON version 1. The earlier `examples/scenarios.yaml` file is
  a design sketch and is not executed.
- No real-model accuracy claim or production-readiness certification is introduced.

## 0.1.0

- Initial screenshot comparison with bounded deterministic regions of interest.
- Metric-only offline provider and an OpenAI-compatible vision adapter.
- Validated finding schemas and region-reference checks.
- Self-contained HTML and JSON reports, bilingual synthetic screenshots, Python test workflow,
  and an OCI container definition.
