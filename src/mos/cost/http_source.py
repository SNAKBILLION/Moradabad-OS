"""HTTP-backed metal rate source.

Generic by design — the source is configured with a URL and a JSON pointer
(a list of keys descending into the response body) plus a per-alloy
multiplier. This makes the source agnostic to which provider you use:
MCX copper, IBJA, your own quote endpoint, a partner's rate API.

Why a multiplier rather than a direct brass rate:
  Most public commodity feeds quote *copper* (which is liquid and indexed).
  Brass alloys derive from copper + zinc + dealer margin. Real factories
  already think this way: "today's copper is ₹X, so brass-70/30 is roughly
  0.74 * X plus dealer margin." We mirror that.

The multiplier and offset are configured per alloy in ``labor_rates.yaml``
under a new ``metal_rate_indicator`` block. Loaded by the existing
``load_cost_rates`` machinery — see rates.py.

Caching, staleness, and DB persistence live in CachedMetalRateSource
(separate file) so this module stays focused on the HTTP fetch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from mos.schemas import BrassAlloy, MetalRate


_DEFAULT_TIMEOUT_SECONDS = 15.0


class MetalRateFetchError(RuntimeError):
    """Raised when the indicator endpoint fails or returns malformed data.

    Wrappers (e.g. CachedMetalRateSource) catch this to fall back to cached
    rates. Direct callers see this as a hard error.
    """


@dataclass(frozen=True)
class AlloyMultiplier:
    """Per-alloy mapping from indicator price to brass rate.

    Final rate (INR/kg) = max(0, indicator * multiplier + offset_inr_per_kg).

    Both fields are required; offset defaults to 0 if you only want a pure
    multiplier. The clamp at 0 prevents a wildly low indicator + negative
    offset combination from producing a negative rate that would corrupt
    the cost sheet.
    """

    multiplier: float
    offset_inr_per_kg: float = 0.0


def _extract_indicator(payload: Any, json_pointer: list[str]) -> float:
    """Walk a JSON response by a list of keys, return the leaf as float.

    Kept tiny on purpose — we don't need a full JSONPath here. If the
    structure of a real provider's response calls for it later, swap in
    jsonpath-ng then.
    """
    cur = payload
    for key in json_pointer:
        if isinstance(cur, dict):
            if key not in cur:
                raise MetalRateFetchError(
                    f"JSON pointer key {key!r} not found in response; "
                    f"available keys: {sorted(cur.keys())[:10]}"
                )
            cur = cur[key]
        elif isinstance(cur, list):
            try:
                idx = int(key)
            except ValueError as e:
                raise MetalRateFetchError(
                    f"non-integer index {key!r} for list in JSON pointer"
                ) from e
            if not (0 <= idx < len(cur)):
                raise MetalRateFetchError(
                    f"index {idx} out of range for list of length {len(cur)}"
                )
            cur = cur[idx]
        else:
            raise MetalRateFetchError(
                f"cannot descend into {type(cur).__name__} with key {key!r}"
            )
    if not isinstance(cur, (int, float)):
        raise MetalRateFetchError(
            f"value at JSON pointer is {type(cur).__name__}, not numeric"
        )
    return float(cur)


class HttpMetalRateSource:
    """Fetch a generic indicator rate over HTTP and convert to brass.

    Constructor params:
      url         : full URL of the indicator endpoint
      json_pointer: list of keys to descend into the JSON response, e.g.
                    ["data", "copper", "spot_inr_per_kg"]
      multipliers : per-alloy AlloyMultiplier
      source_name : tag stored on the returned MetalRate.source field, used
                    to identify this source in the cache table and audit logs
      http_client : optional httpx.Client for testing or custom transports
      timeout_s   : request timeout
    """

    def __init__(
        self,
        *,
        url: str,
        json_pointer: list[str],
        multipliers: dict[BrassAlloy, AlloyMultiplier],
        source_name: str,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not url:
            raise ValueError("url is required")
        if not source_name or len(source_name) > 64:
            raise ValueError("source_name must be 1..64 chars")
        if not multipliers:
            raise ValueError("at least one alloy multiplier is required")
        self._url = url
        self._json_pointer = list(json_pointer)
        self._multipliers = dict(multipliers)
        self._source_name = source_name
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds)

    @property
    def source_name(self) -> str:
        return self._source_name

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def fetch(self, alloy: BrassAlloy) -> MetalRate:
        if alloy not in self._multipliers:
            raise KeyError(
                f"no multiplier configured for {alloy.value} on "
                f"source {self._source_name}"
            )
        try:
            resp = self._http.get(self._url)
        except httpx.HTTPError as e:
            raise MetalRateFetchError(f"HTTP error fetching indicator: {e}") from e
        if resp.status_code >= 400:
            raise MetalRateFetchError(
                f"indicator endpoint returned {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as e:
            raise MetalRateFetchError(
                f"indicator response is not JSON: {e}"
            ) from e

        indicator = _extract_indicator(payload, self._json_pointer)
        m = self._multipliers[alloy]
        rate = max(0.0, indicator * m.multiplier + m.offset_inr_per_kg)
        if rate <= 0.0:
            raise MetalRateFetchError(
                f"computed rate <= 0 for {alloy.value} "
                f"(indicator={indicator}, multiplier={m.multiplier}, "
                f"offset={m.offset_inr_per_kg})"
            )
        return MetalRate(
            rate_per_kg_inr=round(rate, 2),
            source=self._source_name,
            fetched_at=datetime.now(timezone.utc),
            stale=False,
        )
