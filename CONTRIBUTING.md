# Contributing to RenderWitness

Thanks for helping make visual regression review more useful and more auditable.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make test
make lint
```

Generate deterministic fixtures after changing the demo renderer:

```bash
python scripts/generate_demo_assets.py
renderwitness demo --output reports/demo
```

## Pull requests

- Add a focused test for behavioral changes.
- Keep the `demo` provider deterministic and network-free.
- Do not commit screenshots containing private product or customer data.
- Describe model, prompt, and threshold changes in the pull request.
- Never present a model judgment as proof; reports must retain the source pixels.

By contributing, you agree that your contribution is licensed under the MIT License.
