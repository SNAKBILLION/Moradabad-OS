# Moradabad AI Design + Production OS

An AI-driven design and manufacturing pipeline for the Moradabad handicraft
export industry. Brass products, Phase 1.

## Status

**All 12 milestones complete.** Phase 1 ships.

### What works today

- Repo skeleton matching the locked architecture.
- `docker-compose.yml` for Postgres + Redis + MinIO local dev.
- All Pydantic data contracts with validation.
- SQLAlchemy 2.x ORM with Alembic migrations 001 (initial schema) and 002
  (`llm_calls` audit log).
- Repositories: `JobRepository`, `BriefRepository`, `DesignSpecRepository`,
  `CostSheetRepository`, `LlmCallRepository`.
- **CAD pipeline**: deterministic CadQuery runner, seven-rule DFM checker.
- **Archetype library**: 10 public product archetypes covering candle
  holders (classic / pillar / taper-stem), planters (bell / cylinder / urn),
  vases (baluster / trumpet), and bowls (spheroid / footed). All
  rotationally-symmetric, all sand-castable except urn and baluster which
  declare undercuts and route to lost-wax or two-piece + weld.
- **Cost engine**: 12-line-item cost sheets with FOB INR/USD and CIF.
- **Metal rate fetcher**: generic `HttpMetalRateSource` (configurable URL
  + JSON pointer + per-alloy multiplier+offset) wrapped by
  `CachedMetalRateSource` for outage fallback. On primary failure, returns
  the most recent cached rate with `stale=True` (surfaced in the cost
  sheet's `assumptions`). Persistence in the existing `metal_rates` table,
  idempotent per (metal, day) via `ON CONFLICT DO NOTHING`.
- **Storage**: `S3ObjectStore` (works with MinIO and AWS S3) +
  `InMemoryObjectStore` for tests.
- **Orchestrator** (`mos.worker.pipeline.run_pipeline`): drives a QUEUED job
  through CAD → COST → BUNDLE.
- **Intent layer** (`mos.intent.build_intent_from_brief`): brief text →
  validated `DesignSpec` via Groq Llama 3.1 70B with retry-on-validation-
  failure. Every LLM call is logged to `llm_calls` with prompt hash + raw
  response for audit and replay. Auth/rate-limit errors bail immediately.
- **Render** (`mos.render.render_stl`): headless Blender subprocess pipeline.
  Loads STL → applies brass PBR material → renders PNG. Cycles for quality,
  Eevee for tests. Render failure does NOT fail the job — stage marks itself
  SKIPPED with a reason if Blender is missing or the render errors out.
- **Shop drawing + SOP PDFs** (`mos.sop`): single-page A4 datasheet with
  title block, three labelled silhouette views, dimensioned parameter
  table, finish/notes block; multi-page SOP document with design summary,
  numbered process routing, per-step instructions/tools/risks. English
  only today; bilingual structure in place (every user-visible string is
  a `BilingualText` with an empty Hindi field) for translation pass.
  PDF generation failure marks SKIPPED rather than failing the job.
- **Feedback API**: `POST /jobs/{id}/feedback`, `GET /jobs/{id}/feedback`,
  `GET /feedback/{id}`. All five payload types (cost actual, can't manufacture,
  DFM violation observed, finish defect, time actual). Append-only by
  convention.
- **FastAPI app**: `POST /jobs` accepts either a prebuilt `design_spec` OR
  just `brief_text` (intent layer auto-runs). `GET /jobs/{id}`. Failed
  intent → `AWAITING_REVIEW` with `intent_reason`.
- **Celery task**: `mos.worker.app.run_pipeline_task` for async execution
  via Redis.
- 313 unit tests + 31 integration tests.

### What is not built

- Auth — API is unauthenticated. Safe only on a trusted network. JWT is M12+.
- Hindi translations — SOP/drawing PDFs are English only; bilingual
  structure ready for a translation pass.

### Known deferred work (documented in ROADMAP)

- **M4**: first factory-supplied SKU template. Deferred until SKU input arrives.
- **Geometric draft check**: `DRAFT_ANGLE` rule is currently declaration-based
  (template author promises, foundry rules enforce). Real geometric check
  requires parting-line analysis; scheduled for post-Phase-1.
- **Geometric undercut detector**: same story as draft. Declaration-based
  until we build pull-direction analysis.

## Locked decisions (from design sessions)

- **Scope**: brass only, rotationally-symmetric products, 10 templates.
- **Intent LLM**: Groq `llama-3.1-70b-versatile`, structured JSON output.
- **Infra**: self-hosted (Postgres + Redis + MinIO), own JWT auth.
- **Pipeline**: `intent → cad → cost → sop → render → bundle`, deterministic
  downstream of `intent`.
- **Reproducibility**: every job carries a `PipelineSnapshot`; same brief +
  same snapshot → identical artifacts (modulo timestamps).

## Developer setup

```bash
# 1. Start dev infra
docker compose up -d postgres redis minio

# 2. Install package (editable) + dev extras
pip install -e ".[dev]"

# 3. Apply migrations
alembic upgrade head

# 4. Run tests
pytest                         # unit + integration
pytest tests/unit              # unit only (no Postgres needed)
pytest tests/integration -v    # integration only (requires Postgres)

# 5. Run the API
uvicorn mos.api.app:app --reload
# Visit http://localhost:8000/docs

# 6. Run a Celery worker (in a separate terminal)
celery -A mos.worker.app worker --loglevel=info
```

Integration tests skip with a clear message if Postgres isn't reachable.
Set `MOS_TEST_DATABASE_URL` to point at a different database if desired.

### End-to-end smoke test

```bash
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d @examples/job_request.json
# => {"job_id":"...","status":"queued", ...}
# Celery worker runs the pipeline; poll GET /jobs/{id} for progress.
```

## Open questions still blocking Phase 1

1. Factory partner's top-10 SKUs → which 10 templates to build.
2. Metal rate source (IBJA vs MCX vs mandi).
3. Source of verified Hindi translations for shop-floor terminology.
