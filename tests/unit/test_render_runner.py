"""Unit tests for the render runner.

These tests do NOT invoke Blender. They exercise:
  - command construction (pure function)
  - Blender lookup logic
  - argparse on the standalone Blender script (importable as a module — bpy
    is imported lazily inside main(), so we can import the module without it)
  - error paths in the runner

A live render test (Blender required) lives in
tests/integration/test_render_blender.py and skips cleanly without Blender.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest import mock

import pytest

from mos.render import (
    BlenderNotFoundError,
    RenderOptions,
    build_command,
    find_blender,
)


class TestRenderOptions:
    def test_defaults(self):
        opts = RenderOptions()
        assert opts.samples == 64
        assert opts.engine == "CYCLES"
        assert opts.width == 1024
        assert opts.height == 1024


class TestBuildCommand:
    def test_includes_essentials(self, tmp_path: Path):
        cmd = build_command(
            blender_bin="/usr/bin/blender",
            stl_path=tmp_path / "x.stl",
            out_path=tmp_path / "y.png",
            options=RenderOptions(samples=32, seed=7, engine="BLENDER_EEVEE_NEXT",
                                  width=512, height=512),
        )
        assert cmd[0] == "/usr/bin/blender"
        assert "--background" in cmd
        # factory-startup keeps environment deterministic across hosts
        assert "--factory-startup" in cmd
        # script comes before -- separator; args after
        sep = cmd.index("--")
        assert "--python" in cmd[:sep]
        assert "--stl" in cmd[sep:]
        assert "--out" in cmd[sep:]
        assert str(tmp_path / "x.stl") in cmd
        assert str(tmp_path / "y.png") in cmd
        # numeric args round-tripped as strings
        assert "32" in cmd
        assert "7" in cmd
        assert "BLENDER_EEVEE_NEXT" in cmd
        assert "512" in cmd

    def test_python_script_path_passed(self, tmp_path: Path):
        cmd = build_command(
            blender_bin="blender",
            stl_path=tmp_path / "x.stl",
            out_path=tmp_path / "y.png",
            options=RenderOptions(),
        )
        # The script path is the third arg-pair; verify it exists on disk so
        # we'd actually find it at runtime.
        py_idx = cmd.index("--python")
        script_path = Path(cmd[py_idx + 1])
        assert script_path.is_file(), f"script not found: {script_path}"
        assert script_path.name == "blender_script.py"


class TestFindBlender:
    def test_explicit_env_var_used(self, tmp_path: Path, monkeypatch):
        fake = tmp_path / "blender"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        monkeypatch.setenv("MOS_BLENDER_BIN", str(fake))
        assert find_blender() == str(fake)

    def test_explicit_env_var_must_be_a_file(self, monkeypatch):
        monkeypatch.setenv("MOS_BLENDER_BIN", "/nonexistent/blender")
        with pytest.raises(BlenderNotFoundError, match="not a file"):
            find_blender()

    def test_falls_back_to_path(self, monkeypatch, tmp_path: Path):
        monkeypatch.delenv("MOS_BLENDER_BIN", raising=False)
        with mock.patch.object(shutil, "which", return_value="/opt/blender/blender"):
            assert find_blender() == "/opt/blender/blender"

    def test_raises_when_not_found(self, monkeypatch):
        monkeypatch.delenv("MOS_BLENDER_BIN", raising=False)
        with mock.patch.object(shutil, "which", return_value=None):
            with pytest.raises(BlenderNotFoundError):
                find_blender()


class TestBlenderScriptArgparse:
    """Importing blender_script as a regular module — the bpy import inside
    main() is deferred, so this works without bpy installed.
    """

    def test_argparse_accepts_required(self):
        from mos.render import blender_script

        ns = blender_script._parse([
            "--stl", "/tmp/x.stl",
            "--out", "/tmp/y.png",
        ])
        assert ns.samples == 64
        assert ns.engine == "CYCLES"
        assert ns.width == 1024

    def test_argparse_rejects_bad_engine(self):
        from mos.render import blender_script

        with pytest.raises(SystemExit):
            blender_script._parse([
                "--stl", "/tmp/x.stl",
                "--out", "/tmp/y.png",
                "--engine", "RAYTRACE_42",  # not a valid choice
            ])

    def test_split_argv_handles_no_separator(self):
        from mos.render import blender_script

        with mock.patch.object(blender_script.sys, "argv",
                               ["blender_script.py"]):
            assert blender_script._split_argv() == []

    def test_split_argv_returns_args_after_separator(self):
        from mos.render import blender_script

        with mock.patch.object(
            blender_script.sys, "argv",
            ["blender", "--background", "--", "--stl", "/x.stl", "--out", "/y.png"],
        ):
            assert blender_script._split_argv() == [
                "--stl", "/x.stl", "--out", "/y.png",
            ]


class TestRenderStlValidation:
    def test_missing_stl_raises_filenotfound(self, tmp_path: Path):
        from mos.render import render_stl

        with pytest.raises(FileNotFoundError):
            render_stl(
                tmp_path / "does_not_exist.stl",
                tmp_path / "out.png",
            )

    def test_missing_blender_raises_typed_error(self, tmp_path: Path, monkeypatch):
        # STL exists but Blender doesn't.
        stl = tmp_path / "fake.stl"
        stl.write_bytes(b"solid x\nendsolid x\n")
        monkeypatch.delenv("MOS_BLENDER_BIN", raising=False)
        with mock.patch.object(shutil, "which", return_value=None):
            from mos.render import render_stl

            with pytest.raises(BlenderNotFoundError):
                render_stl(stl, tmp_path / "out.png")
