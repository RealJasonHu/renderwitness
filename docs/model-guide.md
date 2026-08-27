# Model guide

RenderWitness keeps models out of the Python process. This makes the core installation small and
lets the same adapter target an Apple Silicon laptop, an NVIDIA inference server, or a hosted API.

## Ollama (recommended local path)

Qwen3-VL has strong multilingual OCR and GUI grounding, making the 4B variant a practical local
starting point:

```bash
ollama pull qwen3-vl:4b
ollama serve

export RENDERWITNESS_BASE_URL=http://localhost:11434/v1
export RENDERWITNESS_API_KEY=ollama
export RENDERWITNESS_MODEL=qwen3-vl:4b
renderwitness compare examples/baseline.png examples/candidate.png \
  --provider openai-compatible --output reports/qwen3-vl
```

See the official [Qwen3-VL repository](https://github.com/QwenLM/Qwen3-VL),
[Ollama model page](https://ollama.com/library/qwen3-vl), and
[OpenAI compatibility reference](https://docs.ollama.com/api/openai-compatibility).

## vLLM or a hosted endpoint

Point the same three variables at the server. The adapter uses image data URIs and the common
`/chat/completions` contract. Servers differ in their structured-output extensions, so
RenderWitness still validates and repairs the returned JSON locally.

## Choosing a model

Prefer instruction-tuned models with multi-image input, JSON output, multilingual OCR, and spatial
grounding. For reliable comparisons, record the exact model tag and server version; floating tags
make regression history difficult to reproduce.
