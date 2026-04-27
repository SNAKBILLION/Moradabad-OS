"""Orchestrator-side wrapper around the Blender subprocess.

Public surface: ``render_stl(stl_path, out_path, ...) -> Path``. The function
locates Blender, builds the command line, invokes it, captures stdout/stderr
on failure, and returns the output path on success.

Blender lookup order:
  1. ``MOS_BLENDER_BIN`` environment variable (explicit override)
  2. ``shutil.which("blender")`` (PATH lookup)
  3. raise BlenderNotFoundError

The Blender script itself lives in ``blender_script.py`` next to this file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_SCRIPT_PATH = Path(__file__).resolve().parent / "blender_script.py"


class BlenderNotFoundError(RuntimeError):
    """Raised when no Blender binary can be located."""


class BlenderRenderError(RuntimeError):
    """Raised when Blender exits non-zero."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(
            f"Blender exited {returncode}: {stderr[:1000]}"
        )
        self.returncode = returncode
        self.stderr = stderr


Engine = Literal["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]


@dataclass(frozen=True)
class RenderOptions:
    samples: int = 32
    seed: int = 0
    engine: Engine = "BLENDER_EEVEE_NEXT"
    width: int = 1024
    height: int = 1024
    timeout_seconds: float = 300.0


def find_blender() -> str:
    """Locate the Blender binary or raise BlenderNotFoundError."""
    explicit = os.environ.get("MOS_BLENDER_BIN")
    if explicit:
        if not Path(explicit).is_file():
            raise BlenderNotFoundError(
                f"MOS_BLENDER_BIN={explicit!r} is not a file"
            )
        return explicit
    found = shutil.which("blender")
    if found:
        return found
    raise BlenderNotFoundError(
        "Blender not found. Install Blender or set MOS_BLENDER_BIN."
    )


def build_command(
    *,
    blender_bin: str,
    stl_path: Path,
    out_path: Path,
    options: RenderOptions,
) -> list[str]:
    """Construct the argv list passed to subprocess.run.

    Pure function — no side effects, no I/O — so it can be unit-tested without
    a real Blender install.
    """
    return [
        blender_bin,
        "--background",
        "--factory-startup",  # ignore user prefs: deterministic environment
        "--python-exit-code", "1",  # exit 1 on Python exception inside Blender
        "--python", str(_SCRIPT_PATH),
        "--",  # everything below is forwarded to blender_script.py
        "--stl", str(stl_path),
        "--out", str(out_path),
        "--samples", str(options.samples),
        "--seed", str(options.seed),
        "--engine", options.engine,
        "--width", str(options.width),
        "--height", str(options.height),
    ]


def render_stl(
    stl_path: Path,
    out_path: Path,
    *,
    options: RenderOptions | None = None,
) -> Path:
    """Render an STL to PNG using a headless Blender subprocess.

    Returns the output path on success. Raises:
      - FileNotFoundError if the STL is missing.
      - BlenderNotFoundError if Blender isn't installed/configured.
      - BlenderRenderError if the subprocess exits non-zero.
      - subprocess.TimeoutExpired if the render exceeds options.timeout_seconds.
    """
    stl_path = Path(stl_path)
    out_path = Path(out_path)
    opts = options or RenderOptions()

    if not stl_path.is_file():
        raise FileNotFoundError(f"STL not found: {stl_path}")

    blender_bin = find_blender()
    cmd = build_command(
        blender_bin=blender_bin,
        stl_path=stl_path,
        out_path=out_path,
        options=opts,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 🔥 FIX: run blender via virtual display
    cmd = ["xvfb-run", "-a"] + cmd

    result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    timeout=opts.timeout_seconds,
    check=False,
    )
    if result.returncode != 0:
        raise BlenderRenderError(
            result.returncode,
            stderr=result.stderr or result.stdout,
        )
    if not out_path.exists():
        raise BlenderRenderError(
            result.returncode,
            stderr=(
                f"Blender exited 0 but output is missing at {out_path}\n"
                f"stdout tail: {result.stdout[-500:]}"
            ),
        )
    return out_path
