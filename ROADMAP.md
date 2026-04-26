# Roadmap

## Phase 1 — Brass, 10 templates, end-to-end

Each milestone ends with a binary success criterion. A milestone is complete
when its criterion passes; partial completion does not count.

| # | Milestone | Success criterion | Status |
|---|---|---|---|
| 1 | Dockerized dev env | `docker compose config` parses; `pytest` exits 0 on empty suite | ✅ |
| 2 | Schemas + fixtures | 5 valid + 5 invalid specs pass/fail as expected | ✅ |
| 3 | DB migrations + repos | create/read/list `Job` test passes against real Postgres | ✅ |
| 4 | First parametric template | STEP opens in FreeCAD; STL is watertight | ✅ |
| 5 | CAD runner + DFM checks | Known-bad params trigger `min_wall_thickness: fail` | ✅ |
| 6 | Cost engine | Hand-calculated sample matches engine output to the paisa | ✅ |
| 7 | Metal rate fetcher | Source-outage test falls back to cache and flags `stale: true` | ✅ |
| 8 | SOP + shop drawing | Devanagari renders; dimensions match CAD | ✅ (English only; bilingual structure ready) |
| 9 | Blender headless render | Golden-image diff within tolerance | ✅ |
| 10 | FastAPI + Celery glue | `POST /jobs` → `GET /jobs/{id}` → bundle URI end-to-end | ✅ |
| 11 | Intent layer (Groq + Llama 3.1 70B) | Brief text → validated DesignSpec; failed intent → AWAITING_REVIEW; every call logged | ✅ |
| 11a | Feedback endpoints | All 5 payload types post-and-retrieve round-trip | ✅ |
| 12 | 10 templates | Batch runs all 10; every job reaches `COMPLETE` | ✅ |

Phase 1 ships when all 12 are green **and** the factory partner executes one
generated SOP on the shop floor without calling the designer.

## Phase 2 — Breadth + first feedback calibration

- Wood (Saharanpur): carving, turning, joinery. New template family.
- Diffusion-based lifestyle renders (SDXL on GPU). Keep Blender PBR as the
  deterministic pipeline.
- Feedback-driven cost calibration: use accumulated `FeedbackRecord`s to
  adjust labor-band defaults per process.
- Basic web UI for factory owners (Next.js).

## Phase 3 — Glass, mixed-material assemblies, multi-tenant

- Glass (Firozabad): mouth-blowing constraints, cutting/etching output.
- Mixed-material products: wood + brass + glass assemblies with cross-material
  tolerance and assembly SOPs.
- Multi-tenancy: one system serves multiple factories with isolated data.
- Hybrid deployment option: critical compute on-prem, orchestration in cloud.

## Explicitly parked (not in any current phase)

These came up in earlier scope documents. Each is real work, each has a real
use case, each is deferred because Phase 1 must ship first:

- **Geometric draft-angle check**: requires parting-line detection + per-face
  angle-to-pull-direction analysis. M5 ships with a declaration-based WARN
  instead. Phase 2 work.
- **Geometric undercut detector**: same story — pull-direction silhouette
  analysis. Declaration-based in M5.
- CorelDRAW replacement (web-based SVG editor). Separate product.
- ArtCAM replacement (relief toolpath generation). Wood-carving era (Phase 2+).
- Matrix / MM3D replacement (jewelry-focused CAD). Out of scope unless we
  add jewelry as a product family.
- BeSuite replacement (nesting optimization). Useful for sheet-metal / laser
  cutting; Moradabad is primarily casting.
- CLIP / BLIP / YOLO / SAM image-in pipeline. Needs labeled training data
  we do not have. Revisit in Phase 2 after feedback accumulates.
- Billing, quotas, A/B testing. Product-stage concerns, not MVP concerns.
- Context memory / embeddings. `pgvector` is enabled in migrations from day
  one so this is a code-only change when we get here.
