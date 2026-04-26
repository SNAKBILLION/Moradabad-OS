"""Blender headless render script.

Invoked by the orchestrator via:

    blender --background --python blender_script.py -- \
        --stl <path> --out <path> --samples 64 --seed 0 --engine CYCLES

Runs inside Blender's bundled Python, NOT the project venv. That means:

  - `bpy` is available; nothing else from the project is.
  - This script must not import any `mos.*` module.
  - Communication with the orchestrator is via argv + exit code + stderr.

Output: a single PNG at --out. Exit code 0 on success, non-zero on failure.

Determinism notes:
  - Eevee (raster) is far more deterministic than Cycles (path-traced).
    Tests use Eevee + a fixed seed; production uses Cycles for quality.
  - We import the STL, clear default scene objects, set fixed camera + light,
    apply a brass PBR material, render. No animation, no compositing.
"""

# ruff: noqa: E402  (bpy must be imported after argv mangling; Blender quirk)

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


def _split_argv() -> list[str]:
    """Blender forwards args after `--` to the script. Anything before `--`
    is consumed by Blender itself."""
    if "--" in sys.argv:
        idx = sys.argv.index("--")
        return sys.argv[idx + 1 :]
    return []


def _parse(args: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--stl", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--engine",
        choices=["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
        default="CYCLES",
    )
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--height", type=int, default=1024)
    return p.parse_args(args)


def _clear_scene(bpy) -> None:
    """Wipe the default scene so we start from a known state."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # Also clear orphan data so repeated calls in the same Blender process
    # (which we don't do today, but might in future for batch renders) start
    # fresh.
    for collection in (
        bpy.data.meshes, bpy.data.materials, bpy.data.lights,
        bpy.data.cameras, bpy.data.images,
    ):
        for item in list(collection):
            collection.remove(item)


def _import_stl(bpy, stl_path: Path):
    """Import the STL and return the imported mesh object."""
    if not stl_path.exists():
        raise FileNotFoundError(f"STL not found: {stl_path}")

    # Make sure the STL importer is available. In Blender 4.x it's a
    # built-in operator (bpy.ops.wm.stl_import). In older builds it ships
    # as the io_mesh_stl addon and must be enabled before use.
    import addon_utils
    try:
        addon_utils.enable("io_mesh_stl")
    except Exception:
        pass  # operator may already be a built-in; not fatal

    before = set(bpy.data.objects)

    try:
        bpy.ops.wm.stl_import(filepath=str(stl_path))
    except Exception:
        try:
            bpy.ops.import_mesh.stl(filepath=str(stl_path))
        except Exception as e:
            raise RuntimeError(
                f"No STL import operator available: {e}"
            ) from e

    new = [o for o in bpy.data.objects if o not in before]
    if not new:
        raise RuntimeError("STL import produced no objects")

    obj = new[0]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    obj.location = (0.0, 0.0, 0.0)

    return obj

def _make_brass_material(bpy):
    """Return a Principled BSDF material approximating polished brass.

    Numbers are conservative: brass IOR ~ 0.44 + 2.42i (color-dependent), but
    Principled BSDF takes Metallic+Roughness+BaseColor. The values below match
    references for a satin yellow brass — production users can tune later.
    """
    mat = bpy.data.materials.new("Brass")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.85, 0.65, 0.20, 1.0)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.35  # satin
    return mat


def _setup_camera(bpy, target):
    """Place a camera looking at the target's bounding-box center."""
    cam_data = bpy.data.cameras.new("Cam")
    cam_obj = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    # Distance keyed off the object's bbox so we frame any size sensibly.
    bb = [target.matrix_world @ v.co for v in target.data.vertices]
    if not bb:
        # Mesh has no vertices — fall back to a default radius
        radius = 0.1
    else:
        xs = [p.x for p in bb]; ys = [p.y for p in bb]; zs = [p.z for p in bb]
        # Bbox half-diagonal as a robust size scalar.
        radius = 0.5 * math.sqrt(
            (max(xs) - min(xs)) ** 2
            + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2
        )
        radius = max(radius, 1e-3)

    cam_obj.location = (radius * 2.5, -radius * 2.5, radius * 1.5)
    cam_obj.rotation_euler = (
        math.radians(65),
        0.0,
        math.radians(45),
    )


def _setup_lighting(bpy):
    """Three-point-ish lighting. Same lights every render so reproducibility
    of the test golden image is preserved."""
    key = bpy.data.lights.new("Key", type="AREA")
    key.energy = 1000.0
    key.size = 2.0
    key_obj = bpy.data.objects.new("Key", key)
    bpy.context.collection.objects.link(key_obj)
    key_obj.location = (3.0, -3.0, 4.0)
    key_obj.rotation_euler = (math.radians(45), 0.0, math.radians(45))

    fill = bpy.data.lights.new("Fill", type="AREA")
    fill.energy = 300.0
    fill.size = 3.0
    fill_obj = bpy.data.objects.new("Fill", fill)
    bpy.context.collection.objects.link(fill_obj)
    fill_obj.location = (-3.0, -2.0, 2.0)
    fill_obj.rotation_euler = (math.radians(60), 0.0, math.radians(-30))

    # Plain world background — no HDRI dependency.
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
        bg.inputs["Strength"].default_value = 1.0


def _configure_render(bpy, args: argparse.Namespace) -> None:
    scene = bpy.context.scene

    # SAFE ENGINE DETECTION
    try:
        available = {e.identifier for e in scene.bl_rna.properties["engine"].enum_items}
    except Exception:
        available = {"CYCLES", "BLENDER_EEVEE"}

    requested = args.engine

    if requested in available:
        engine = requested
    elif "BLENDER_EEVEE" in available:
        engine = "BLENDER_EEVEE"
    else:
        engine = "CYCLES"

    scene.render.engine = engine

    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(args.out)

    if engine == "CYCLES":
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = True
        scene.cycles.seed = args.seed
        scene.cycles.device = "CPU"
    else:
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = args.samples

def main() -> int:
    args = _parse(_split_argv())

    import bpy  # imported here so non-Blender callers can import this module

    _clear_scene(bpy)
    obj = _import_stl(bpy, args.stl)
    mat = _make_brass_material(bpy)
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    _setup_camera(bpy, obj)
    _setup_lighting(bpy)
    _configure_render(bpy, args)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)

    if not args.out.exists():
        print(f"render failed: output not created at {args.out}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
