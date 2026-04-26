"""Tests for the CAD runner.

These tests actually build geometry (through CadQuery/OCCT) and export STEP
and STL files. They are slower than pure unit tests (multi-second) but they
are the only way to verify determinism, shrinkage math, and watertight
export end-to-end. Ran on every CI commit; skip with ``-m "not slow"`` if
needed when a marker is added.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import trimesh

from mos.cad import (
    CadResult,
    TemplateNotRegisteredError,
    load_dfm_rules,
    run_cad,
)
from mos.schemas import (
    BrassAlloy,
    CastingMethod,
    DesignSpec,
    FinishSpec,
    MaterialSpec,
    Measurement,
    Plating,
    PolishFinish,
    ProductFamily,
)
from mos.templates import default_registry
from mos.templates.brass.candle_holder_classic import CandleHolderClassic


# --- Spec builder --------------------------------------------------------

def _spec(
    *,
    template_id: str | None = "candle_holder_classic_v1",
    base_diameter: float = 80.0,
    neck_diameter: float = 40.0,
    height: float = 120.0,
    wall_thickness: float = 3.5,
) -> DesignSpec:
    dims: dict[str, Measurement] = (
        {}
        if template_id is None
        else {
            "base_diameter": Measurement(value=base_diameter, unit="mm"),
            "neck_diameter": Measurement(value=neck_diameter, unit="mm"),
            "height": Measurement(value=height, unit="mm"),
            "wall_thickness": Measurement(value=wall_thickness, unit="mm"),
        }
    )
    return DesignSpec(
        brief_id=uuid4(),
        product_family=ProductFamily.CANDLE_HOLDER,
        template_id=template_id,
        dimensions=dims,
        material=MaterialSpec.for_alloy(
            BrassAlloy.BRASS_70_30, CastingMethod.SAND
        ),
        finish=FinishSpec(
            polish=PolishFinish.SATIN,
            plating=Plating.NONE,
            lacquer=False,
            patina=None,
        ),
        motif_refs=[],
        quantity=100,
        target_unit_cost=None,
        buyer_notes="",
    )


def _stl_geometry_hash(path: Path) -> str:
    """Hash the STL *geometry* — vertices and faces — rather than raw bytes.
    OCCT tessellation order is not guaranteed to be stable across runs even
    with identical inputs, so we canonicalize by sorting vertices and
    reconstructing faces before hashing. Two runs that produce the same
    underlying mesh get the same hash.
    """
    mesh = trimesh.load(str(path))
    # Round vertices to 1e-6 mm so floating-point jitter doesn't differentiate
    # otherwise-identical meshes.
    verts = np.round(mesh.vertices, decimals=6)
    sort_idx = np.lexsort(verts.T)
    inv_perm = np.argsort(sort_idx)
    sorted_verts = verts[sort_idx]
    remapped_faces = inv_perm[mesh.faces]
    # Canonicalize each face's vertex ordering, then sort the faces themselves.
    canon_faces = np.sort(remapped_faces, axis=1)
    face_sort = np.lexsort(canon_faces.T)
    canon_faces = canon_faces[face_sort]
    h = hashlib.sha256()
    h.update(sorted_verts.tobytes())
    h.update(canon_faces.tobytes())
    return h.hexdigest()


# --- Happy path ----------------------------------------------------------

class TestHappyPath:
    def test_valid_spec_produces_passed_report(self, tmp_path: Path):
        result = run_cad(_spec(), default_registry(), tmp_path)
        assert isinstance(result, CadResult)
        assert result.report.passed
        assert result.step_path.exists()
        assert result.stl_path.exists()
        assert result.step_path.stat().st_size > 0
        assert result.stl_path.stat().st_size > 0
        assert result.metrics.stl_is_watertight is True
        assert result.shrinkage_applied is True

    def test_exported_files_named_by_spec_id(self, tmp_path: Path):
        spec = _spec()
        result = run_cad(spec, default_registry(), tmp_path)
        assert result.step_path.name == f"{spec.spec_id}.step"
        assert result.stl_path.name == f"{spec.spec_id}.stl"

    def test_mass_matches_hand_computed(self, tmp_path: Path):
        # Sanity check: the final-part mass reported in metrics should roughly
        # match volume * density. The runner uses spec.material.density and
        # solid.val().Volume() internally — this test guards against a
        # density or unit error (g vs kg, cm^3 vs mm^3).
        result = run_cad(_spec(), default_registry(), tmp_path)
        # brass 70/30 density is 8.53 g/cm^3. Volume is in mm^3 so divide
        # by 1000 to get cm^3. A hollow ~80mm OD, ~120mm tall brass candle
        # holder should land somewhere between 400g and 1500g.
        assert 400.0 < result.metrics.mass_g < 1500.0


# --- Error paths ---------------------------------------------------------

class TestErrorPaths:
    def test_null_template_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="template_id=None"):
            run_cad(_spec(template_id=None), default_registry(), tmp_path)

    def test_unknown_template_raises(self, tmp_path: Path):
        spec = _spec(template_id="does_not_exist_v99")
        with pytest.raises(TemplateNotRegisteredError):
            run_cad(spec, default_registry(), tmp_path)

    def test_out_of_range_param_raises(self, tmp_path: Path):
        # CandleHolderClassic declares wall_thickness in [3, 8]. 10mm is over.
        # Note: Measurement itself doesn't know about template ranges — the
        # runner's validate_params does.
        spec = _spec(wall_thickness=10.0)
        from mos.templates import TemplateParamError

        with pytest.raises(TemplateParamError, match="wall_thickness"):
            run_cad(spec, default_registry(), tmp_path)


# --- Shrinkage -----------------------------------------------------------

class TestShrinkage:
    def test_shrinkage_scales_bbox(self, tmp_path: Path):
        """With shrinkage on, the *exported STL* bbox should be
        (1 + shrinkage) times larger than without.
        Both reports' metrics still reflect the FINAL PART size (by design).
        """
        rules = load_dfm_rules()
        s = rules.brass_sand.shrinkage_linear

        r_on = run_cad(_spec(), default_registry(), tmp_path / "on")
        r_off = run_cad(
            _spec(), default_registry(), tmp_path / "off",
            apply_shrinkage=False,
        )

        mesh_on = trimesh.load(str(r_on.stl_path))
        mesh_off = trimesh.load(str(r_off.stl_path))
        extents_on = mesh_on.bounding_box.extents
        extents_off = mesh_off.bounding_box.extents

        ratio = extents_on / extents_off
        # Every axis should match (1 + s) within mesh tessellation tolerance.
        assert np.allclose(ratio, 1.0 + s, rtol=1e-3)

    def test_report_flags_shrinkage_state(self, tmp_path: Path):
        r = run_cad(_spec(), default_registry(), tmp_path, apply_shrinkage=False)
        shrink_result = next(
            c for c in r.report.checks if c.rule_id.value == "shrinkage_applied"
        )
        assert shrink_result.status.value == "warn"
        assert "final-part size" in shrink_result.message


# --- Determinism ---------------------------------------------------------

class TestDeterminism:
    def test_two_runs_produce_same_geometry_hash(self, tmp_path: Path):
        spec_a = _spec()
        # Force identical spec_id so file names collide in separate dirs.
        spec_b = spec_a.model_copy()

        r_a = run_cad(spec_a, default_registry(), tmp_path / "a")
        r_b = run_cad(spec_b, default_registry(), tmp_path / "b")

        hash_a = _stl_geometry_hash(r_a.stl_path)
        hash_b = _stl_geometry_hash(r_b.stl_path)
        assert hash_a == hash_b

    def test_different_params_produce_different_geometry(self, tmp_path: Path):
        r_a = run_cad(_spec(height=120.0), default_registry(), tmp_path / "a")
        r_b = run_cad(_spec(height=140.0), default_registry(), tmp_path / "b")
        assert _stl_geometry_hash(r_a.stl_path) != _stl_geometry_hash(
            r_b.stl_path
        )
