"""Tests for the render stage's non-fatal contract.

Render is decorative; it must never fail a job. These tests exercise
_stage_render directly with a controlled storage backend, ensuring that
missing-Blender, missing-STL, and render errors all return a skip_reason
rather than raising.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock
from uuid import uuid4

import pytest

from mos.render import (
    BlenderNotFoundError,
    BlenderRenderError,
    RenderOptions,
)
from mos.schemas import ArtifactBundle
from mos.storage import InMemoryObjectStore
from mos.worker.pipeline import _stage_render


class _FakeSpec:
    """Tiny stand-in for DesignSpec.spec_id only — _stage_render only
    uses spec.spec_id for the storage key."""

    def __init__(self) -> None:
        self.spec_id = uuid4()


class TestStageRenderSkipReasons:
    def test_no_stl_returns_skip(self):
        bundle = ArtifactBundle()
        out, reason = _stage_render(
            _FakeSpec(),
            uuid4(),
            stl_uri=None,
            store=InMemoryObjectStore(),
            bundle=bundle,
            options=RenderOptions(),
        )
        assert reason is not None and "no STL" in reason
        assert out.render_png_uris == []

    def test_blender_not_found_returns_skip(self, tmp_path: Path):
        store = InMemoryObjectStore()
        # Put a fake STL in storage so the function gets past the first guard.
        stl_uri = store.put_bytes(
            b"solid x\nendsolid x\n", "stl/x.stl",
            content_type="application/sla",
        )
        with mock.patch(
            "mos.worker.pipeline.render_stl",
            side_effect=BlenderNotFoundError("not on PATH"),
        ):
            out, reason = _stage_render(
                _FakeSpec(),
                uuid4(),
                stl_uri=stl_uri,
                store=store,
                bundle=ArtifactBundle(),
                options=RenderOptions(),
            )
        assert reason is not None and "Blender not available" in reason
        assert out.render_png_uris == []

    def test_render_error_returns_skip(self):
        store = InMemoryObjectStore()
        stl_uri = store.put_bytes(
            b"solid x\nendsolid x\n", "stl/x.stl",
            content_type="application/sla",
        )
        with mock.patch(
            "mos.worker.pipeline.render_stl",
            side_effect=BlenderRenderError(2, "segfault"),
        ):
            out, reason = _stage_render(
                _FakeSpec(),
                uuid4(),
                stl_uri=stl_uri,
                store=store,
                bundle=ArtifactBundle(),
                options=RenderOptions(),
            )
        assert reason is not None and "render failed" in reason

    def test_success_uploads_png(self, tmp_path: Path):
        store = InMemoryObjectStore()
        stl_uri = store.put_bytes(
            b"solid x\nendsolid x\n", "stl/x.stl",
            content_type="application/sla",
        )
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal PNG-ish

        def _fake_render(stl_path: Path, out_path: Path, *, options=None):
            out_path.write_bytes(png_bytes)
            return out_path

        with mock.patch(
            "mos.worker.pipeline.render_stl", side_effect=_fake_render,
        ):
            out, reason = _stage_render(
                _FakeSpec(),
                uuid4(),
                stl_uri=stl_uri,
                store=store,
                bundle=ArtifactBundle(),
                options=RenderOptions(),
            )
        assert reason is None
        assert len(out.render_png_uris) == 1
        # Round-trip the upload.
        assert store.get_bytes(out.render_png_uris[0]) == png_bytes
