# Model guide

[README](../README.md) · [Provider architecture](architecture.md#provider-boundary)

RenderWitness keeps model inference outside the Python process. The core package uses an HTTP
adapter; it does not install model weights, PyTorch, Ollama, or vLLM.

## Select a provider

| Provider | Use it for | What it cannot establish |
|---|---|---|
| `demo` | Offline onboarding, deterministic tests, pixel evidence | Semantic defect detection or VLM accuracy |
| `openai-compatible` | Review with your local or hosted vision model | Correctness without labeled evaluation and human review |

The default `demo` provider derives its findings from pixel metrics alone. Its confidence value
describes its synthetic metric observation, not certainty that an interface is broken.

## Endpoint requirements

Your server/model must accept:

- Chat Completions at `<base-url>/chat/completions`;
- two `image_url` inputs encoded as PNG data URIs;
- system and user messages, `temperature: 0`, and `response_format: {"type": "json_object"}`;
- a JSON object matching the schema included in the prompt.

A base URL already ending in `/chat/completions` is used as supplied. A server described as
"OpenAI-compatible" may still differ in its image or JSON capabilities. RenderWitness does not
negotiate unsupported options or fall back to another API format.

## Local server example

Start your own vision-capable server and install a model through that server's tooling. Then set
its endpoint and exact model name:

```bash
export RENDERWITNESS_BASE_URL=http://localhost:11434/v1
export RENDERWITNESS_MODEL=your-vision-model
export RENDERWITNESS_API_KEY=ollama

renderwitness compare examples/baseline.png examples/candidate.png \
  --provider openai-compatible \
  --output reports/local-model
```

The model name is a placeholder, not a bundled model. The example API key is suitable only for a
local server configured to accept it. For a hosted service, supply that service's endpoint, model
identifier, and actual key through the environment.

## Configuration precedence

| Setting | Resolution order |
|---|---|
| Base URL | `--base-url` → `RENDERWITNESS_BASE_URL` → `OPENAI_BASE_URL` → adapter default |
| Model | `--model` → `RENDERWITNESS_MODEL` → `OPENAI_MODEL` → adapter default |
| API key | Environment variable selected by `--api-key-env`; if unset, `RENDERWITNESS_API_KEY` → `OPENAI_API_KEY` |
| Timeout | `--timeout` → `RENDERWITNESS_TIMEOUT` → 60 seconds |

The adapter's current defaults are `https://api.openai.com/v1` and `gpt-4.1-mini`.
These are implementation defaults, not a promise of account access or model availability.
Set both explicitly for a reproducible run. The provider timeout must be greater than 0 and no
more than 300 seconds. It is separate from browser capture's `--timeout-ms`.

```bash
renderwitness compare baseline.png candidate.png \
  --provider openai-compatible \
  --base-url http://localhost:8001/v1 \
  --model my-vision-model \
  --api-key-env MY_VISION_API_KEY \
  --timeout 120 \
  --output reports/model-review
```

Do not place API keys inside suite JSON. Suites take provider settings from the command and
environment, and use one selected provider for the run.

## Response handling

The adapter accepts plain JSON, JSON surrounded by one code fence, common text content blocks,
or an already parsed object in the response message. It validates fields, enum values, confidence
bounds, and text lengths. The analyzer then checks finding ID uniqueness and region references.

A typical finding has this shape:

```json
{
  "id": "finding-001",
  "region_id": "region-001",
  "category": "text",
  "severity": "major",
  "title": "Action label appears clipped",
  "description": "The candidate label ends inside a narrower button.",
  "confidence": 0.85,
  "suggestion": "Check intrinsic button sizing at this viewport."
}
```

This is a schema illustration, not output measured from a particular model.
`region_id` may be `null` for a whole-image observation. Schema validity does not establish that
a claim is visually correct, and a confidence score is not calibrated by RenderWitness.

There is no automatic model retry, JSON repair, or fallback to another model. An HTTP error,
malformed response, unknown region reference, or schema failure produces an operational error.
If deterministic comparison has already succeeded, the CLI and suite attempt an
`unavailable` fallback report and still return exit 2. Library callers receive an exception.

## Data sent and retained

The request includes normalized RGB versions of both images, diff metrics, and region metadata.
The adapter checks image hashes against the comparison and covers ignored rectangles with the
same gray in both model inputs. The prompt lists these exclusions. Original screenshots are still
embedded in reports: ignoring rectangles is not a way to redact a report. Use synthetic data or
create appropriately masked source screenshots when content should not be retained at all.

The prompt treats text within screenshots as untrusted and asks for visible evidence.
This instruction reduces accidental instruction-following but is not a proven prompt-injection
guarantee. Report text is escaped for HTML rendering.

Reports record provider/model identity, prompt version, latency, source hashes, and timestamps.
They do not record your API key or automatically pin the server version, model weights, or
inference runtime. Keep those details with your experiment notes. Reports also retain image paths
and screenshot contents, so inspect them before sharing.

## Evaluate before gating releases

Use labeled examples from the actual product: unchanged screenshots, intended redesigns,
subtle defects, dynamic content, different viewports, and relevant writing systems. Measure
false positives, missed defects, invalid-response frequency, latency, and run-to-run agreement.
Include a pixel-only baseline using the same screenshot pairs.

Pin the model identifier and server version where possible. Temperature zero alone does not
guarantee identical model responses. Inspect whether confidence thresholds help on your labeled
cases before enabling a semantic CI gate.

The bundled fixtures exercise software behavior. They are not a published multi-model accuracy
benchmark or evidence that any specific VLM understands your interface.
