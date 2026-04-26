"""M12 batch test: every registered archetype runs through CAD to a
watertight STL with a passing or warning DFM report.

Binary success criterion: all 10 templates produce watertight geometry and
no FAIL-status DFM checks at sensible default parameters.

Two templates intentionally declare undercuts (planter_urn_v1,
vase_baluster_v1) — those WARN on the undercut_detected rule per the M5
declaration-based rule design. WARN does not fail a job; only FAIL does.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from mos.cad import run_cad
from mos.schemas import (
    BrassAlloy,
    CastingMethod,
    DesignSpec,
    FinishSpec,
    MaterialSpec,
    Measurement,
    PolishFinish,
    ProductFamily,
)
from mos.templates import default_registry


# Sensible default params per archetype. Tuned so each produces a sane
# part within all DFM rules (not at the edge of any foundry limit).
ARCHETYPE_DEFAULTS = {
    "candle_holder_classic_v1": (
        ProductFamily.CANDLE_HOLDER,
        {"base_diameter": 80.0, "neck_diameter": 40.0,
         "height": 120.0, "wall_thickness": 3.5},
    ),
    "candle_holder_pillar_v1": (
        ProductFamily.CANDLE_HOLDER,
        {"body_diameter": 60.0, "base_diameter": 90.0,
         "base_height": 15.0, "height": 150.0, "wall_thickness": 4.0},
    ),
    "candle_holder_taperstem_v1": (
        ProductFamily.CANDLE_HOLDER,
        {"base_diameter": 100.0, "stem_min_diameter": 30.0,
         "cup_diameter": 60.0, "height": 200.0, "wall_thickness": 4.0},
    ),
    "planter_bell_v1": (
        ProductFamily.PLANTER,
        {"base_diameter": 120.0, "rim_diameter": 200.0,
         "height": 150.0, "wall_thickness": 4.0},
    ),
    "planter_cylinder_v1": (
        ProductFamily.PLANTER,
        {"diameter": 150.0, "height": 180.0, "wall_thickness": 4.0},
    ),
    "planter_urn_v1": (
        # Smaller dims for the batch test — at max-range the urn would
        # exceed the 5kg foundry mass limit. Real customers can specify
        # bigger and accept the DFM FAIL as guidance.
        ProductFamily.PLANTER,
        {"base_diameter": 80.0, "shoulder_diameter": 160.0,
         "rim_diameter": 110.0, "height": 200.0, "wall_thickness": 4.0},
    ),
    "vase_baluster_v1": (
        ProductFamily.VASE,
        {"base_diameter": 70.0, "body_diameter": 140.0,
         "neck_diameter": 50.0, "rim_diameter": 75.0,
         "height": 250.0, "wall_thickness": 4.0},
    ),
    "vase_trumpet_v1": (
        ProductFamily.VASE,
        {"base_diameter": 60.0, "rim_diameter": 180.0,
         "height": 220.0, "wall_thickness": 4.0},
    ),
    "bowl_spheroid_v1": (
        ProductFamily.BOWL,
        {"rim_diameter": 200.0, "depth": 80.0, "wall_thickness": 4.0},
    ),
    "bowl_footed_v1": (
        ProductFamily.BOWL,
        {"rim_diameter": 200.0, "depth": 70.0,
         "foot_diameter": 100.0, "foot_height": 20.0,
         "wall_thickness": 4.0},
    ),
}


def _spec(template_id: str) -> DesignSpec:
    family, dims = ARCHETYPE_DEFAULTS[template_id]
    return DesignSpec(
        brief_id=uuid4(),
        product_family=family,
        template_id=template_id,
        dimensions={
            k: Measurement(value=v, unit="mm") for k, v in dims.items()
        },
        material=MaterialSpec.for_alloy(
            BrassAlloy.BRASS_70_30, CastingMethod.SAND
        ),
        finish=FinishSpec(polish=PolishFinish.SATIN),
        motif_refs=[],
        quantity=1,
        buyer_notes="",
    )


class TestArchetypeBatch:
    """Every registered archetype must build, watertight + DFM clean."""

    def test_registry_size(self):
        """We declared 10 archetypes for M12 — registry must hold 10."""
        assert len(default_registry()) == 10

    def test_every_archetype_has_default_params(self):
        """Sanity: defaults map covers exactly the registered templates."""
        registered = set(default_registry().keys())
        defaulted = set(ARCHETYPE_DEFAULTS.keys())
        assert registered == defaulted, (
            f"missing defaults: {registered - defaulted}; "
            f"extra defaults: {defaulted - registered}"
        )

    @pytest.mark.parametrize("template_id", list(ARCHETYPE_DEFAULTS))
    def test_archetype_builds_watertight(self, template_id: str):
        """Each archetype must produce a watertight STL."""
        spec = _spec(template_id)
        with tempfile.TemporaryDirectory() as td:
            result = run_cad(spec, default_registry(), Path(td))
        assert result.metrics.stl_is_watertight is True, (
            f"{template_id} produced non-watertight STL"
        )

    @pytest.mark.parametrize("template_id", list(ARCHETYPE_DEFAULTS))
    def test_archetype_dfm_clean(self, template_id: str):
        """No FAIL-status DFM checks at default parameters. WARN is OK
        (e.g. urn and baluster declare undercuts and WARN on that rule)."""
        spec = _spec(template_id)
        with tempfile.TemporaryDirectory() as td:
            result = run_cad(spec, default_registry(), Path(td))
        fails = [
            c for c in result.report.checks
            if c.status.value == "fail"
        ]
        assert not fails, (
            f"{template_id} has FAIL DFM checks: "
            + ", ".join(f"{c.rule_id.value}: {c.message}" for c in fails)
        )

    @pytest.mark.parametrize("template_id", list(ARCHETYPE_DEFAULTS))
    def test_archetype_produces_step_and_stl_files(self, template_id: str):
        """Both STEP and STL artifacts must be produced."""
        spec = _spec(template_id)
        with tempfile.TemporaryDirectory() as td:
            result = run_cad(spec, default_registry(), Path(td))
            assert result.step_path.is_file()
            assert result.stl_path.is_file()
            assert result.step_path.stat().st_size > 0
            assert result.stl_path.stat().st_size > 0

    @pytest.mark.parametrize("template_id", list(ARCHETYPE_DEFAULTS))
    def test_archetype_mass_in_sane_range(self, template_id: str):
        """Mass should be a positive number under the foundry limit (5kg)."""
        spec = _spec(template_id)
        with tempfile.TemporaryDirectory() as td:
            result = run_cad(spec, default_registry(), Path(td))
        assert 100.0 < result.metrics.mass_g < 5000.0, (
            f"{template_id} mass {result.metrics.mass_g}g out of range"
        )


class TestUndercutDeclarations:
    """The undercut WARN behavior is part of the design — verify it triggers
    for the two archetypes that declare undercuts and not for the others."""

    def test_urn_warns_on_undercut(self):
        spec = _spec("planter_urn_v1")
        with tempfile.TemporaryDirectory() as td:
            result = run_cad(spec, default_registry(), Path(td))
        undercut = [
            c for c in result.report.checks
            if c.rule_id.value == "undercut_detected"
        ]
        assert len(undercut) == 1
        assert undercut[0].status.value == "warn"

    def test_baluster_warns_on_undercut(self):
        spec = _spec("vase_baluster_v1")
        with tempfile.TemporaryDirectory() as td:
            result = run_cad(spec, default_registry(), Path(td))
        undercut = [
            c for c in result.report.checks
            if c.rule_id.value == "undercut_detected"
        ]
        assert len(undercut) == 1
        assert undercut[0].status.value == "warn"

    def test_clean_archetypes_pass_undercut(self):
        """Templates that declare no undercuts must not WARN on it."""
        for tid in [
            "candle_holder_classic_v1",
            "candle_holder_pillar_v1",
            "planter_cylinder_v1",
            "vase_trumpet_v1",
            "bowl_spheroid_v1",
            "bowl_footed_v1",
        ]:
            spec = _spec(tid)
            with tempfile.TemporaryDirectory() as td:
                result = run_cad(spec, default_registry(), Path(td))
            undercut = [
                c for c in result.report.checks
                if c.rule_id.value == "undercut_detected"
            ]
            assert len(undercut) == 1
            assert undercut[0].status.value == "pass", (
                f"{tid} unexpectedly warned on undercut"
            )
