# Architecture

RenderWitness separates measured image differences, provider-authored interpretations, and
explicit CI decisions. Each has a different contract.

```text
capture.py (optional) ── PNG + capture metadata
                                │
diff.py ──────────── ComparisonResult
                                │
providers.py ─────── ProviderResult
                                │
analyzer.py ──────── AnalysisResult
                        │              │
                 report.py        policy.py
                 HTML + JSON      GateResult
                        └──────┬───────┘
                           suite.py
                              │
                       suite_report.py
                 HTML / JSON / Markdown / JUnit
```

## Deterministic evidence

`compare_images` validates file size and decoded image limits, applies EXIF orientation, composites
transparency onto white, and converts both images to RGB. Dimensions must match after orientation.

For each pixel, it computes the largest absolute RGB-channel delta. A pixel enters the binary
change mask only when that delta is strictly greater than the configured threshold. Ignore
rectangles clear the relevant pixels from the mask. Their union is excluded from the denominator:

```text
changed_pixels / (width × height - ignored_pixels)
```

Region extraction uses a bounded occupancy grid, local dilation, and eight-neighbor connected
components. It expands component boxes for context, filters by changed-pixel count, sorts the
regions, and keeps at most `max_regions`. Bounding boxes use screenshot coordinates and exclusive
right/bottom edges. Grid coarsening and the capped grouping kernel make these approximate regions,
not precise object segmentation or an exact geometric merge-distance guarantee.

The global changed-pixel ratio is independent of region filtering and truncation. Overlapping
padded regions may count some pixels more than once locally; their counts should not be summed.
A region's mean delta is measured over its changed pixels, not its entire rectangle.

`ComparisonResult` records source metadata and SHA-256 hashes, dimensions, diff settings, ignored
rectangles and pixel count, global metrics, algorithm version, and retained regions. These are
measurements for the current inputs and configuration, not claims about user impact.

## Provider boundary

A `VisionProvider` implements the synchronous `analyze(comparison, baseline_path, candidate_path)`
interface and returns a validated `ProviderResult`.

| Provider | Inputs used | Interpretation |
|---|---|---|
| `demo` | Deterministic comparison metrics | Synthetic pixel-change observations and heuristic severity |
| `openai-compatible` | Normalized screenshot pair with ignored areas covered, region metadata, and schema | Vision-model review requiring independent validation |

The remote adapter verifies source hashes against the comparison, normalizes images using the same
orientation/RGB rules, covers ignored rectangles with identical gray, and sends PNG data URIs to a
Chat Completions endpoint. The prompt lists those exclusions and asks the model not to report them.
It requests
JSON output and includes a schema in the prompt. It supports plain JSON, a JSON code fence, and
common text/parsed response envelopes. It does not retry the model or repair malformed JSON.

Schema validation rejects unknown fields, invalid enum values, out-of-range confidence, and
oversized text. The analyzer rejects duplicate finding IDs and references to nonexistent regions.
A finding may use `region_id: null` for an image-level observation. A valid region reference
links a claim to evidence; it does not prove the claim.

The prompt tells the model to treat screenshot text as untrusted content and use visible evidence.
This is a prompt boundary, not a demonstrated defense against all visual prompt injection.

## Policy boundary

`evaluate_policy` consumes an analysis and a `GatePolicy`. It evaluates the measured change budget
and any enabled provider-based rules, then returns `passed`, the effective policy, and explicit
failure reasons. The provider's verdict does not automatically decide the process exit status.

An empty policy allows a completed comparison. Operational errors remain errors even when every
gate is disabled. The exact rules and confidence semantics are documented in [CI integration](ci.md).

## Reports and evidence

A case report contains a self-contained HTML viewer with embedded images and a canonical JSON
analysis record. The viewer supports split, blend, and diff inspection, region overlays, and finding
filters. Provider-authored text is escaped before insertion into HTML.

A normal `compare` command also writes independent `comparison.json` and `gate.json` records.
A suite adds copied source images and organizes reports under `cases/<scenario-id>/`.
Its summary formats expose each case's status, metrics, optional report path, gate reasons,
operational error, and duration. JUnit uses failures for gate violations and errors for operational
failures.

The single-comparison CLI invalidates previous result files with incomplete-run markers at the
start of a rerun, so an early input failure does not leave a stale passing report. Suites instead
require a new or empty output directory.

Individual output files use atomic replacement. The output directory as a whole is not an atomic
transaction. HTML embeds the source images, while JSON records their metadata; sharing JSON alone
does not carry image pixels. A suite's index links to case directories, so distribute the entire
suite directory to preserve navigation.

## Failure behavior

| Failure stage | Behavior |
|---|---|
| Invalid suite configuration or unsafe output directory | Reject the run before cases execute |
| Unreadable, corrupt, mismatched, or oversized input | Case/command error; no valid comparison exists |
| Provider call or semantic validation after a successful diff | Attempt a fallback report labeled `unavailable`, preserve deterministic evidence, return an error |
| Report storage or rendering | Return an error; some earlier artifacts may exist |
| Policy violation after a completed analysis | Preserve the completed report and return a gate failure |

For provider failures, the fallback uses verdict `review`, no fabricated findings, and an explicit
unavailable-analysis summary. It is not a successful model review. Suites continue to later cases
and prioritize error exit code 2 over gate-failure exit code 1. Provider initialization or invalid
global configuration can fail before per-case evidence is created.

The in-process `analyze` and `compare_and_analyze` APIs raise errors to their caller; automatic
fallback reporting is implemented by the CLI/suite orchestration, not every library function.

## Capture and reproducibility

Capture is a separate optional dependency. Each invocation opens a fresh Chromium context,
applies explicit browser settings, waits for readiness, then writes PNG plus capture provenance.
The browser version and image hash make a run inspectable; they do not freeze dependencies.
The caller still controls browser installation, application data, fonts, and server state.

Capture metadata omits URL credentials, query strings, and fragments. Paths, selector strings,
and visible page data remain. Comparison ignore rectangles cover the corresponding pixels in the
built-in model adapter's input, but do not alter the originals embedded in reports.

## Deliberate scope

There is no database, hosted dashboard, model runtime, baseline approval service, or background
capture worker. Suites run sequentially and use one selected provider per run. Screenshot evidence
can support visual review, but does not establish functional correctness, accessibility compliance,
model accuracy, or the root cause of a change.
