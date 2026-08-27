FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim

LABEL org.opencontainers.image.title="RenderWitness" \
      org.opencontainers.image.description="Evidence-first VLM visual regression review" \
      org.opencontainers.image.authors="Zhexun Hu <huzhexun1@gmail.com>" \
      org.opencontainers.image.licenses="MIT"

RUN useradd --create-home --uid 10001 renderwitness
WORKDIR /workspace
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

USER renderwitness
ENTRYPOINT ["renderwitness"]
CMD ["--help"]
