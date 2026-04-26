"""Render stage: STL -> PNG via headless Blender subprocess.

Single public entry point: ``render_stl``. Lower-level helpers are exposed
for testing only.
"""

from .runner import (
    BlenderNotFoundError,
    BlenderRenderError,
    Engine,
    RenderOptions,
    build_command,
    find_blender,
    render_stl,
)

__all__ = [
    "BlenderNotFoundError",
    "BlenderRenderError",
    "Engine",
    "RenderOptions",
    "build_command",
    "find_blender",
    "render_stl",
]
