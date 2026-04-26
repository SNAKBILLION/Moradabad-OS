"""Unit tests for the DFM rule engine.

Each test constructs a minimal template with specific declared properties,
pairs it with handcrafted GeometryMetrics, and asserts the resulting
CheckResult for one rule at a time. This keeps failures isolated to the
rule under test.

Rule coverage (7 rules from CheckRule):
- MIN_WALL_THICKNESS: pass / fail
- DRAFT_ANGLE: pass / warn (declaration-based; warn replaces fail — see
  audit decision in the M5 conversation)
- MAX_BOUNDING_BOX: pass / fail for each axis
- MAX_MASS: pass / fail
- UNDERCUT_DETECTED: pass (declared no undercuts) / warn (declared unknown)
- CLOSED_SHELL: pass (watertight) / fail (not watertight)
- SHRINKAGE_APPLIED: pass / warn
"""

from __future__ import annotations

from uuid import uuid4

import cadquery as cq
import pytest

from mos.cad import GeometryMetrics, check, load_dfm_rules
from mos.cad.rules import DfmRules, SandCastingRules
from mos.schemas import CheckRule, CheckStatus
from mos.templates import ParamSpec


# --- Test fixtures -------------------------------------------------------

def _rules(
    *,
    min_wall: float = 3.0,
    min_draft: float = 1.5,
    bbox_x: float = 400.0,
    bbox_y: float = 400.0,
    bbox_z: float = 400.0,
    max_mass: float = 5000.0,
    shrinkage: float = 0.015,
) -> DfmRules:
    return DfmRules(
        version="test",
        content_hash="sha256:test",
        brass_sand=SandCastingRules(
            min_wall_mm=min_wall,
            min_draft_deg=min_draft,
            max_bbox_x_mm=bbox_x,
            max_bbox_y_mm=bbox_y,
            max_bbox_z_mm=bbox_z,
            max_mass_g=max_mass,
            shrinkage_linear=shrinkage,
        ),
    )


def _metrics(
    *,
    mass: float = 500.0,
    bbox: tuple[float, float, float] = (100.0, 100.0, 150.0),
    watertight: bool = True,
) -> GeometryMetrics:
    return GeometryMetrics(
        volume_mm3=mass * 1000 / 8.53,  # reverse of mass=V*density
        mass_g=mass,
        bbox_x_mm=bbox[0],
        bbox_y_mm=bbox[1],
        bbox_z_mm=bbox[2],
        stl_is_watertight=watertight,
    )


class _T:
    """Minimal declarable template. Attrs set via kwargs to __init__."""

    template_id = "_dfm_test_v1"
    version = "0.0.1"
    product_family = "test"
    description = ""
    param_schema: tuple[ParamSpec, ...] = ()
    regions: tuple[str, ...] = ("body",)

    def __init__(
        self,
        *,
        min_wall: float = 3.0,
        min_draft: float = 2.0,
        no_undercuts: bool = True,
    ):
        self.declared_min_wall_mm = min_wall
        self.declared_min_draft_deg = min_draft
        self.declared_produces_no_undercuts = no_undercuts

    def build(self, params: dict[str, float]) -> cq.Workplane:  # pragma: no cover
        raise NotImplementedError("not used in DFM tests")


def _find(report, rule_id: CheckRule):
    """Extract a single result by rule_id or raise — makes assertions sharp."""
    matches = [c for c in report.checks if c.rule_id == rule_id]
    assert len(matches) == 1, f"expected exactly 1 {rule_id}, got {matches}"
    return matches[0]


# --- Rule-by-rule tests --------------------------------------------------

class TestMinWallThickness:
    def test_pass_when_declared_meets_foundry(self):
        r = check(
            uuid4(), _T(min_wall=3.0), _metrics(), _rules(min_wall=3.0),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.MIN_WALL_THICKNESS).status == CheckStatus.PASS

    def test_fail_when_declared_below_foundry(self):
        r = check(
            uuid4(), _T(min_wall=1.5), _metrics(), _rules(min_wall=3.0),
            shrinkage_applied=True,
        )
        res = _find(r, CheckRule.MIN_WALL_THICKNESS)
        assert res.status == CheckStatus.FAIL
        assert res.value == 1.5
        assert res.threshold == 3.0


class TestDraftAngle:
    def test_pass_when_declared_meets_foundry(self):
        r = check(
            uuid4(), _T(min_draft=2.0), _metrics(), _rules(min_draft=1.5),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.DRAFT_ANGLE).status == CheckStatus.PASS

    def test_warn_not_fail_when_declared_below_foundry(self):
        # Declaration-based rules downgrade to WARN rather than FAIL — a
        # declaration is an author assertion, not a geometry fact.
        r = check(
            uuid4(), _T(min_draft=1.0), _metrics(), _rules(min_draft=1.5),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.DRAFT_ANGLE).status == CheckStatus.WARN


class TestBoundingBox:
    def test_pass_within_limits(self):
        r = check(
            uuid4(), _T(), _metrics(bbox=(100.0, 100.0, 150.0)), _rules(),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.MAX_BOUNDING_BOX).status == CheckStatus.PASS

    def test_fail_on_x_axis(self):
        r = check(
            uuid4(), _T(), _metrics(bbox=(500.0, 100.0, 100.0)),
            _rules(bbox_x=400.0),
            shrinkage_applied=True,
        )
        res = _find(r, CheckRule.MAX_BOUNDING_BOX)
        assert res.status == CheckStatus.FAIL
        assert "X=500" in res.message

    def test_fail_on_z_axis(self):
        r = check(
            uuid4(), _T(), _metrics(bbox=(100.0, 100.0, 500.0)),
            _rules(bbox_z=400.0),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.MAX_BOUNDING_BOX).status == CheckStatus.FAIL


class TestMass:
    def test_pass_under_limit(self):
        r = check(
            uuid4(), _T(), _metrics(mass=500.0), _rules(max_mass=5000.0),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.MAX_MASS).status == CheckStatus.PASS

    def test_fail_over_limit(self):
        r = check(
            uuid4(), _T(), _metrics(mass=6000.0), _rules(max_mass=5000.0),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.MAX_MASS).status == CheckStatus.FAIL


class TestUndercut:
    def test_pass_when_declared_none(self):
        r = check(
            uuid4(), _T(no_undercuts=True), _metrics(), _rules(),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.UNDERCUT_DETECTED).status == CheckStatus.PASS

    def test_warn_when_declared_unknown(self):
        r = check(
            uuid4(), _T(no_undercuts=False), _metrics(), _rules(),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.UNDERCUT_DETECTED).status == CheckStatus.WARN


class TestClosedShell:
    def test_pass_watertight(self):
        r = check(
            uuid4(), _T(), _metrics(watertight=True), _rules(),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.CLOSED_SHELL).status == CheckStatus.PASS

    def test_fail_not_watertight(self):
        r = check(
            uuid4(), _T(), _metrics(watertight=False), _rules(),
            shrinkage_applied=True,
        )
        assert _find(r, CheckRule.CLOSED_SHELL).status == CheckStatus.FAIL


class TestShrinkage:
    def test_pass_when_applied(self):
        r = check(uuid4(), _T(), _metrics(), _rules(), shrinkage_applied=True)
        assert _find(r, CheckRule.SHRINKAGE_APPLIED).status == CheckStatus.PASS

    def test_warn_when_not_applied(self):
        r = check(uuid4(), _T(), _metrics(), _rules(), shrinkage_applied=False)
        res = _find(r, CheckRule.SHRINKAGE_APPLIED)
        assert res.status == CheckStatus.WARN
        assert "final-part size" in res.message


class TestReportAggregation:
    def test_passed_true_when_only_warns(self):
        # WARN results should not drop report.passed.
        r = check(
            uuid4(), _T(min_draft=1.0, no_undercuts=False), _metrics(),
            _rules(min_draft=1.5),
            shrinkage_applied=False,
        )
        assert r.passed is True

    def test_passed_false_with_any_fail(self):
        r = check(
            uuid4(), _T(min_wall=1.0), _metrics(),
            _rules(min_wall=3.0),
            shrinkage_applied=True,
        )
        assert r.passed is False


class TestRulesLoader:
    def test_load_defaults(self):
        r = load_dfm_rules()
        assert r.brass_sand.min_wall_mm > 0
        assert r.content_hash.startswith("sha256:")

    def test_content_hash_stable(self):
        # Two consecutive reads of the same file must produce the same hash.
        a = load_dfm_rules()
        b = load_dfm_rules()
        assert a.content_hash == b.content_hash
