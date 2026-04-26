"""Unit tests for HttpMetalRateSource. No network — uses httpx.MockTransport.

Coverage:
  - happy path with multiplier-only and multiplier+offset
  - missing alloy in multipliers
  - HTTP error paths (4xx, 5xx, network exception)
  - malformed responses (non-JSON, wrong shape, non-numeric leaf)
  - JSON pointer descent into nested dicts and list indices
  - protocol conformance (HttpMetalRateSource matches MetalRateSource)
"""

from __future__ import annotations

import httpx
import pytest

from mos.cost import (
    AlloyMultiplier,
    HttpMetalRateSource,
    MetalRateFetchError,
    MetalRateSource,
)
from mos.cost.http_source import _extract_indicator
from mos.schemas import BrassAlloy


def _make_source(handler, **kwargs) -> HttpMetalRateSource:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, timeout=5.0)
    defaults = dict(
        url="http://example.com/rates",
        json_pointer=["data", "copper", "inr_per_kg"],
        multipliers={
            BrassAlloy.BRASS_70_30: AlloyMultiplier(multiplier=0.74),
        },
        source_name="test_indicator",
        http_client=http,
    )
    defaults.update(kwargs)
    return HttpMetalRateSource(**defaults)


class TestProtocolConformance:
    def test_matches_metal_rate_source_protocol(self):
        src = _make_source(lambda r: httpx.Response(200, json={}))
        assert isinstance(src, MetalRateSource)
        src.close()


class TestHappyPath:
    def test_multiplier_only(self):
        # copper indicator = 950 INR/kg, brass-70/30 = 950 * 0.74 = 703.0
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"copper": {"inr_per_kg": 950.0}}}
            )
        )
        result = src.fetch(BrassAlloy.BRASS_70_30)
        assert result.rate_per_kg_inr == 703.0
        assert result.source == "test_indicator"
        assert result.stale is False
        src.close()

    def test_multiplier_with_offset(self):
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"copper": {"inr_per_kg": 1000.0}}}
            ),
            multipliers={
                BrassAlloy.BRASS_70_30: AlloyMultiplier(
                    multiplier=0.7, offset_inr_per_kg=20.0
                ),
            },
        )
        result = src.fetch(BrassAlloy.BRASS_70_30)
        assert result.rate_per_kg_inr == 720.0
        src.close()

    def test_rounds_to_two_decimals(self):
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"copper": {"inr_per_kg": 950.123456}}}
            )
        )
        result = src.fetch(BrassAlloy.BRASS_70_30)
        # 950.123456 * 0.74 = 703.0913... -> 703.09
        assert result.rate_per_kg_inr == 703.09
        src.close()


class TestErrorPaths:
    def test_http_5xx_raises_typed_error(self):
        src = _make_source(lambda r: httpx.Response(503, text="down"))
        with pytest.raises(MetalRateFetchError, match="503"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()

    def test_http_4xx_raises_typed_error(self):
        src = _make_source(lambda r: httpx.Response(404, text="not found"))
        with pytest.raises(MetalRateFetchError, match="404"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()

    def test_network_exception_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        src = _make_source(handler)
        with pytest.raises(MetalRateFetchError, match="HTTP error"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()

    def test_non_json_response(self):
        src = _make_source(
            lambda r: httpx.Response(
                200, content=b"<html>not json</html>",
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(MetalRateFetchError, match="not JSON"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()

    def test_pointer_key_missing(self):
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"silver": {"inr_per_kg": 900.0}}}
            )
        )
        with pytest.raises(MetalRateFetchError, match="copper"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()

    def test_non_numeric_leaf(self):
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"copper": {"inr_per_kg": "lots"}}}
            )
        )
        with pytest.raises(MetalRateFetchError, match="not numeric"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()

    def test_unknown_alloy_raises_keyerror(self):
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"copper": {"inr_per_kg": 950.0}}}
            )
        )
        # Multipliers only configured for BRASS_70_30
        with pytest.raises(KeyError, match="brass_85_15"):
            src.fetch(BrassAlloy.BRASS_85_15)
        src.close()

    def test_negative_computed_rate_rejected(self):
        # Indicator * multiplier + offset should not be allowed to go <=0
        # even if the math says it would.
        src = _make_source(
            lambda r: httpx.Response(
                200, json={"data": {"copper": {"inr_per_kg": 100.0}}}
            ),
            multipliers={
                BrassAlloy.BRASS_70_30: AlloyMultiplier(
                    multiplier=0.74, offset_inr_per_kg=-200.0
                ),
            },
        )
        with pytest.raises(MetalRateFetchError, match="rate <= 0"):
            src.fetch(BrassAlloy.BRASS_70_30)
        src.close()


class TestExtractIndicator:
    """Direct tests on the JSON pointer helper."""

    def test_dict_descent(self):
        assert _extract_indicator(
            {"a": {"b": {"c": 42.0}}}, ["a", "b", "c"]
        ) == 42.0

    def test_list_descent(self):
        assert _extract_indicator(
            {"items": [{"price": 10.0}, {"price": 20.0}]},
            ["items", "1", "price"],
        ) == 20.0

    def test_int_value_coerced_to_float(self):
        assert _extract_indicator({"x": 7}, ["x"]) == 7.0
        assert isinstance(_extract_indicator({"x": 7}, ["x"]), float)

    def test_dict_missing_key(self):
        with pytest.raises(MetalRateFetchError, match="not found"):
            _extract_indicator({"a": 1}, ["b"])

    def test_list_index_out_of_range(self):
        with pytest.raises(MetalRateFetchError, match="out of range"):
            _extract_indicator({"items": [1, 2]}, ["items", "5"])

    def test_list_non_integer_index(self):
        with pytest.raises(MetalRateFetchError, match="non-integer index"):
            _extract_indicator({"items": [1, 2]}, ["items", "first"])

    def test_descent_into_scalar(self):
        with pytest.raises(MetalRateFetchError, match="cannot descend"):
            _extract_indicator({"x": 5}, ["x", "y"])


class TestConstructorValidation:
    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="url"):
            HttpMetalRateSource(
                url="",
                json_pointer=["x"],
                multipliers={
                    BrassAlloy.BRASS_70_30: AlloyMultiplier(multiplier=1.0),
                },
                source_name="t",
            )

    def test_empty_multipliers_rejected(self):
        with pytest.raises(ValueError, match="multiplier"):
            HttpMetalRateSource(
                url="http://x.test",
                json_pointer=["x"],
                multipliers={},
                source_name="t",
            )

    def test_long_source_name_rejected(self):
        with pytest.raises(ValueError, match="source_name"):
            HttpMetalRateSource(
                url="http://x.test",
                json_pointer=["x"],
                multipliers={
                    BrassAlloy.BRASS_70_30: AlloyMultiplier(multiplier=1.0),
                },
                source_name="x" * 100,
            )
