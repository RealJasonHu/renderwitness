# Architecture

RenderWitness deliberately separates deterministic evidence from probabilistic interpretation.

```text
baseline.png ─┐
              ├─ image validation ─ pixel delta grid ─ connected ROIs ─┐
candidate.png ┘                                                        │
                                                                       ▼
                                       demo heuristic or VLM provider adapter
                                                                       │
                                                                       ▼
                                  validated findings + original evidence bundle
                                                                       │
                                                                       ▼
                                             self-contained HTML + JSON report
```

## 1. Deterministic diff

The diff stage decodes both images, normalizes color mode, and verifies matching dimensions. It
thresholds pixel deltas, aggregates them onto a small grid, merges connected cells, removes tiny
noise regions, and expands the remaining rectangles by a bounded padding. Each region records its
pixel-change ratio and mean color delta.

This stage answers only **where pixels changed**. It is deterministic, testable, and always retained
in the report, regardless of model output.

## 2. Semantic review

The provider receives both full screenshots and the detected regions. It must return a strict JSON
object, and every cited region ID is validated against deterministic evidence. The system prompt
treats screenshot text as untrusted, asks for visible evidence instead of hidden implementation
guesses, and requires calibrated confidence.

Two providers are available:

- `demo`: deterministic and network-free; useful for CI, onboarding, and the bundled fixture. Its
  output is labeled as synthetic and must not be treated as a real model judgment.
- `openai-compatible`: works with Ollama, vLLM, or a compatible hosted endpoint. Model and endpoint
  metadata are recorded in the report.

## 3. Evidence report

The renderer creates a portable directory containing the validated JSON record and a self-contained
HTML viewer. The viewer overlays the same normalized boxes on baseline and candidate screenshots,
links findings back to their source regions, and exposes the deterministic diff metrics.

## Trust model

VLM output is an interpretation, not proof. RenderWitness never discards the original screenshot
pair or deterministic regions, and it distinguishes the provider name from measured metrics. A
reviewer can therefore disagree with the model while retaining all evidence needed to make a human
decision.
