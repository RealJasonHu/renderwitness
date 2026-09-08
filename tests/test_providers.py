from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from renderwitness.diff import compare_images
from renderwitness.models import BoundingBox
from renderwitness.providers import (
    DemoProvider,
    OpenAICompatibleProvider,
    ProviderError,
    create_provider,
)


class FakeClient:
    response: httpx.Response
    calls: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, "timeout": self.timeout, **kwargs})
        return self.response


def response_with_content(content: object, *, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://vlm.test/v1/chat/completions")
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": content}}]},
        request=request,
    )


def test_demo_provider_is_offline_deterministic_and_grounded(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    provider = DemoProvider()

    first = provider.analyze(comparison, baseline, candidate)
    second = provider.analyze(comparison, baseline, candidate)

    assert first == second
    assert first.provider == "demo"
    assert first.model == "deterministic-pixel-heuristic-v1"
    assert "No semantic VLM call was made" in first.summary
    assert {finding.region_id for finding in first.findings} <= {
        region.id for region in comparison.regions
    }
    assert all(finding.confidence == 1 for finding in first.findings)


def test_demo_provider_passes_identical_images(tmp_path: Path) -> None:
    from PIL import Image

    image = tmp_path / "same.png"
    Image.new("RGB", (20, 20), "white").save(image)
    comparison = compare_images(image, image)

    result = DemoProvider().analyze(comparison, image, image)

    assert result.verdict.value == "pass"
    assert result.findings == []


def test_demo_provider_keeps_changed_pixels_when_roi_filter_removes_regions(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=10_000)

    result = DemoProvider().analyze(comparison, baseline, candidate)

    assert comparison.changed_pixels > 0
    assert comparison.regions == []
    assert result.verdict.value == "review"
    assert len(result.findings) == 1
    assert result.findings[0].region_id is None
    assert "below ROI size filter" in result.findings[0].title


def test_openai_compatible_provider_sends_grounded_multimodal_request(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    region_id = comparison.regions[0].id
    payload = {
        "summary": "The CTA changed materially.",
        "verdict": "fail",
        "findings": [
            {
                "id": "finding-001",
                "region_id": region_id,
                "category": "text-clipping",
                "severity": "major",
                "title": "CTA is clipped",
                "description": "The final characters are not visible.",
                "confidence": 0.94,
                "suggestion": "Restore intrinsic sizing.",
            }
        ],
    }
    FakeClient.calls = []
    FakeClient.response = response_with_content(f"```json\n{json.dumps(payload)}\n```")
    monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)
    provider = OpenAICompatibleProvider(
        base_url="https://vlm.test/v1/",
        model="qwen-vl-test",
        api_key="test-token",
        timeout=12.5,
    )

    result = provider.analyze(comparison, baseline, candidate)

    assert result.provider == "openai-compatible"
    assert result.model == "qwen-vl-test"
    assert result.findings[0].region_id == region_id
    assert len(FakeClient.calls) == 1
    call = FakeClient.calls[0]
    assert call["url"] == "https://vlm.test/v1/chat/completions"
    assert call["timeout"] == 12.5
    assert call["headers"]["Authorization"] == "Bearer test-token"
    request_body = call["json"]
    assert request_body["temperature"] == 0
    assert request_body["response_format"] == {"type": "json_object"}
    assert "untrusted" in request_body["messages"][0]["content"]
    user_parts = request_body["messages"][1]["content"]
    image_urls = [part["image_url"]["url"] for part in user_parts if part["type"] == "image_url"]
    assert len(image_urls) == 2
    assert all(url.startswith("data:image/png;base64,") for url in image_urls)
    assert region_id in user_parts[0]["text"]


def test_openai_compatible_provider_rejects_unvalidated_output(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    invalid_payload = {
        "summary": "Looks bad",
        "verdict": "definitely",
        "findings": [],
        "unexpected": "provider typo",
    }
    FakeClient.calls = []
    FakeClient.response = response_with_content(json.dumps(invalid_payload))
    monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)

    with pytest.raises(ProviderError, match="schema validation"):
        OpenAICompatibleProvider(base_url="https://vlm.test/v1", model="test").analyze(
            comparison, baseline, candidate
        )


def test_openai_compatible_provider_surfaces_bounded_http_error(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    request = httpx.Request("POST", "https://vlm.test/v1/chat/completions")
    FakeClient.calls = []
    FakeClient.response = httpx.Response(
        503,
        text="temporarily unavailable\nretry later",
        request=request,
    )
    monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)

    with pytest.raises(ProviderError, match="HTTP 503.*temporarily unavailable"):
        OpenAICompatibleProvider(base_url="https://vlm.test/v1", model="test").analyze(
            comparison, baseline, candidate
        )


def test_provider_factory_uses_explicit_values_then_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    demo = create_provider(" demo ")
    remote = create_provider("openai-compatible")
    explicit = create_provider(
        "openai", base_url="https://explicit.test", model="explicit-model", api_key=""
    )

    assert isinstance(demo, DemoProvider)
    assert isinstance(remote, OpenAICompatibleProvider)
    assert remote.endpoint == "https://env.test/v1/chat/completions"
    assert remote.model == "env-model"
    assert remote.api_key == "env-key"
    assert explicit.endpoint == "https://explicit.test/chat/completions"
    assert explicit.model == "explicit-model"
    assert explicit.api_key == ""
    with pytest.raises(ProviderError, match="Unknown provider"):
        create_provider("mystery-vlm")


def test_provider_enforces_local_image_byte_limit(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)

    def network_must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("network should not run for rejected local input")

    monkeypatch.setattr("renderwitness.providers.httpx.Client", network_must_not_run)
    provider = OpenAICompatibleProvider(
        base_url="https://vlm.test/v1", model="test", max_image_bytes=1
    )

    with pytest.raises(ProviderError, match="provider limit"):
        provider.analyze(comparison, baseline, candidate)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_url": "  "}, "base URL"),
        ({"model": "  "}, "model"),
        ({"timeout": 0}, "timeout"),
        ({"timeout": 301}, "timeout"),
        ({"max_image_bytes": 0}, "byte limit"),
    ],
)
def test_remote_provider_configuration_is_bounded(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ProviderError, match=message):
        OpenAICompatibleProvider(**kwargs)


@pytest.mark.parametrize("kind", ["missing", "empty", "unsupported"])
def test_remote_provider_validates_image_before_network(
    image_pair: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    invalid = tmp_path / ("invalid.txt" if kind == "unsupported" else "invalid.png")
    if kind == "empty":
        invalid.touch()
    elif kind == "unsupported":
        invalid.write_bytes(baseline.read_bytes())

    def network_must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("network should not run for invalid local input")

    monkeypatch.setattr("renderwitness.providers.httpx.Client", network_must_not_run)

    with pytest.raises(ProviderError, match="Cannot read|non-empty|only accepts"):
        OpenAICompatibleProvider(model="test").analyze(comparison, invalid, candidate)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(
                200,
                text="not an envelope",
                request=httpx.Request("POST", "https://vlm.test/v1/chat/completions"),
            ),
            "envelope was not valid JSON",
        ),
        (
            httpx.Response(
                200,
                json=["not", "an", "object"],
                request=httpx.Request("POST", "https://vlm.test/v1/chat/completions"),
            ),
            "envelope must be a JSON object",
        ),
        (
            httpx.Response(
                200,
                json={"choices": []},
                request=httpx.Request("POST", "https://vlm.test/v1/chat/completions"),
            ),
            r"choices\[0\]\.message",
        ),
        (response_with_content([]), "did not contain textual JSON"),
        (response_with_content("not-json"), "invalid JSON"),
        (response_with_content("[1, 2, 3]"), "JSON must be an object"),
    ],
)
def test_remote_provider_rejects_malformed_response_envelopes(
    image_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
    message: str,
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    FakeClient.calls = []
    FakeClient.response = response
    monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)

    with pytest.raises(ProviderError, match=message):
        OpenAICompatibleProvider(base_url="https://vlm.test/v1", model="test").analyze(
            comparison, baseline, candidate
        )


def test_remote_provider_accepts_parsed_object_and_text_part_response_shapes(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    payload = {"summary": "No issue.", "verdict": "pass", "findings": []}
    request = httpx.Request("POST", "https://vlm.test/v1/chat/completions")

    for message in (
        {"parsed": payload},
        {"content": [{"type": "output_text", "text": json.dumps(payload)}]},
    ):
        FakeClient.calls = []
        FakeClient.response = httpx.Response(
            200, json={"choices": [{"message": message}]}, request=request
        )
        monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)

        result = OpenAICompatibleProvider(
            base_url="https://vlm.test/v1/chat/completions", model="test"
        ).analyze(comparison, baseline, candidate)

        assert result.verdict.value == "pass"


def test_remote_provider_translates_transport_errors(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)

    class FailingClient(FakeClient):
        def post(self, url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr("renderwitness.providers.httpx.Client", FailingClient)

    with pytest.raises(ProviderError, match="Could not reach provider.*connection refused"):
        OpenAICompatibleProvider(base_url="https://vlm.test/v1", model="test").analyze(
            comparison, baseline, candidate
        )


def test_remote_provider_bounds_response_size(
    image_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    request = httpx.Request("POST", "https://vlm.test/v1/chat/completions")
    FakeClient.response = httpx.Response(
        200,
        content=b"x" * (2 * 1024 * 1024 + 1),
        request=request,
    )
    monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)

    with pytest.raises(ProviderError, match="2 MiB safety limit"):
        OpenAICompatibleProvider(base_url="https://vlm.test/v1", model="test").analyze(
            comparison, baseline, candidate
        )


def test_renderwitness_environment_has_priority_over_openai_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDERWITNESS_BASE_URL", "https://renderwitness.test/v1")
    monkeypatch.setenv("RENDERWITNESS_MODEL", "private-vlm")
    monkeypatch.setenv("RENDERWITNESS_API_KEY", "private-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "fallback-vlm")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")

    provider = create_provider("openai-compatible")

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.endpoint == "https://renderwitness.test/v1/chat/completions"
    assert provider.model == "private-vlm"
    assert provider.api_key == "private-key"


def test_ignored_regions_are_neutralized_in_model_inputs(image_pair, monkeypatch) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(
        baseline, candidate, ignore_regions=[BoundingBox(x=12, y=10, width=20, height=16)]
    )
    FakeClient.calls = []
    FakeClient.response = response_with_content(
        json.dumps({"summary": "Review", "verdict": "review", "findings": []})
    )
    monkeypatch.setattr("renderwitness.providers.httpx.Client", FakeClient)
    OpenAICompatibleProvider(model="test").analyze(comparison, baseline, candidate)
    parts = FakeClient.calls[0]["json"]["messages"][1]["content"]
    assert '"ignored_pixels":320' in parts[0]["text"]
    for part in parts[1:]:
        data = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
        with Image.open(BytesIO(data)) as image:
            assert image.getpixel((12, 10)) == (209, 213, 219)
            assert image.getpixel((31, 25)) == (209, 213, 219)
    with Image.open(baseline) as original:
        assert original.getpixel((12, 10)) == (255, 255, 255)


def test_provider_refuses_changed_evidence_before_network(image_pair, monkeypatch) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate)
    Image.new("RGB", (96, 72), "red").save(candidate)

    def no_network(*args, **kwargs):
        raise AssertionError("Stale evidence must not be sent")

    monkeypatch.setattr("renderwitness.providers.httpx.Client", no_network)
    with pytest.raises(ProviderError, match="changed since comparison"):
        OpenAICompatibleProvider(model="test").analyze(comparison, baseline, candidate)
