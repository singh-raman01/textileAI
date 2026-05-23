# TextileSearch — Developer Guide

This document covers architecture decisions, adding features, debugging, and understanding the codebase.

---

## Architecture overview

TextileSearch is split into two processes that talk over HTTP on localhost.

### Electron main process (`src/main/`)

Runs in Node.js. Responsible for:
- Creating the browser window
- Spawning and monitoring the Python sidecar
- Registering all `ipcMain.handle()` handlers
- Running the chokidar file watcher
- Using Electron APIs (dialog, shell, app)

The renderer **never** has direct access to Node.js or Electron APIs. All cross-process calls go through `ipcRenderer.invoke()` → preload → `ipcMain.handle()`.

### Preload (`src/preload/index.ts`)

The bridge. Uses `contextBridge.exposeInMainWorld` to expose a typed `window.api` object to the renderer. Every method is explicitly listed — nothing implicit.

### Renderer (`src/renderer/src/`)

Standard React + Tailwind. Knows nothing about Electron, Node, or Python. Calls `window.api.X()` and receives typed responses.

### Python sidecar (`backend/`)

FastAPI server running on localhost:8765. Handles all ML, DB, file operations, and OCR. Has no browser dependency.

---

## Backend strict rules

Every Python file follows these rules:

- `from __future__ import annotations` at the top of every file
- No bare `except:` — all exceptions caught by specific type
- All function parameters and return types explicitly annotated
- No `Any` in type annotations
- Database sessions always via `with get_session() as session:` context manager
  - Commits automatically on clean exit
  - Rolls back automatically on any exception
  - No session ever leaves the `with` block
- All file writes atomic: write to `.tmp`, then `os.replace()` (never partial writes)
- Services are injected via FastAPI `Depends()` — never accessed as globals in route handlers

---

## Database schema

14 tables. Key relationships:

```
watched_folders
    └── images (root_folder_id)
            ├── textile_metadata (1:1)
            │       └── fabric_composition (1:many)
            ├── image_tags (many:many via tags)
            ├── duplicates (image_id_a, image_id_b)
            └── search_history.top_result_ids
```

The FAISS vector index stores a parallel `faiss_id` → embedding mapping. `images.faiss_id` is the bridge between SQLite and FAISS. Images with `faiss_id IS NULL` are indexed by metadata only (model not yet available).

### Three-tier confidence system

Every extracted metadata field carries a tier:

| Tier | OCR Confidence | Stored | Filter default |
|---|---|---|---|
| 1 | ≥ 90% | Yes | Always included |
| 2 | 65–89% | Yes | Included, amber ⚠ badge |
| 3 | < 65% | NULL | Never extracted |

**Exception (hardcoded):** If composition percentages do not sum to 100% (±2% tolerance), the composition is always Tier 2 regardless of OCR confidence. This is a design decision — it always requires user confirmation.

---

## Import pipeline

When a folder is added:

```
1. POST /import/folder
   → WatchedFolder record created
   → startup_sync() scans folder, inserts Image rows (status='queued')
   → Importer.start() launches background thread

Background thread loop:
   → fetch batch of 32 queued images
   → for each image:
       a. compute MD5 hash (duplicate detection + rename resilience)
       b. embed with FashionCLIP → add to FAISS
       c. run PaddleOCR → parse label fields
       d. generate 256×256 JPEG thumbnail
       e. write all results to DB (status='done')
   → save FAISS index to disk (atomic)
   → check disk space (pause if < 500 MB free)
   → repeat until queue empty
```

**Crash recovery:** Any image with `status='processing'` at startup is reset to `status='queued'`. The loop resumes exactly where it left off.

**Model not available:** If FashionCLIP weights are missing, `faiss_id` is left NULL and OCR + metadata parsing still runs. The image appears in Browse/Filter mode but not in visual search results.

---

## File system sync

Two entry points:

**`startup_sync()`** — runs once on launch:
1. Parallel existence check for all non-orphaned images (16 threads)
2. If >80% of a folder's images are missing → folder flagged "unavailable" (not mass-orphaned)
3. Scan watched folders for new files → queue for import

**`handle_batch(added, removed)`** — called by chokidar via Electron IPC:
1. Compute MD5 of added files
2. Match against MD5 of removed files → if match, it's a rename (update path, keep all data)
3. Genuinely removed files → marked orphaned
4. Genuinely new files → queued for import

---

## FAISS index

The vector index auto-migrates between two modes:

| Mode | When | Accuracy | RAM |
|---|---|---|---|
| `IndexFlatIP` (exact) | ≤ 20,000 images | 100% recall | Higher |
| `IndexIVFPQ` (approximate) | > 20,000 images | ~95% recall | ~8× less |

Migration is transparent — happens automatically when the threshold is crossed. The index is written atomically (`.tmp` → `os.replace()`), so a crash during save cannot corrupt it.

All vectors are L2-normalised before insert. Inner-product search on normalised vectors = cosine similarity.

---

## Field parser

Handles three composition label formats:

| Format | Example | Notes |
|---|---|---|
| A | `87/10/2/1 POLYSTEER/RAYON/LUREX/SPANDEX` | Positional zip |
| B | `100% SPUNPOLYSTER TWO LAYER FABRIC` | Single material + descriptor |
| C | `POLYESTER 60% COTTON 40%` | Material-first |

Material normalisation is seeded with ~30 common OCR errors (POLYSTEER→POLYESTER, SP→SPANDEX, etc.) and extended at runtime from the `material_aliases` DB table.

---

## Adding a new backend endpoint

1. Create or add to a file in `backend/app/api/`
2. Add the router to `backend/app/__init__.py`:
   ```python
   from app.api.my_feature import router as my_router
   app.include_router(my_router, tags=["my-feature"])
   ```
3. Add an IPC handler in `src/main/ipc.ts`
4. Expose via `src/preload/index.ts`
5. Write tests in `backend/tests/`

---

## Adding a database table

1. Add the model class to `backend/app/db/models.py`
2. Generate a migration: `uv run alembic revision --autogenerate -m "add my_table"`
3. Review the generated file in `migrations/versions/`
4. Run `uv run alembic upgrade head` to apply locally

Migrations run automatically when the app starts. Never edit an applied migration — always create a new one.

---

## Testing

```bash
cd backend

# All tests
uv run pytest tests/ -v

# One file
uv run pytest tests/test_field_parser.py -v

# One test
uv run pytest tests/test_field_parser.py::TestCompositionExtraction::test_format_a_fafa -v

# With coverage
uv run pytest tests/ --cov=app --cov-report=term-missing
```

### Test doubles

**MockEmbedder** — deterministic unit vectors derived from path hash. Same path always gives the same vector. No GPU, no model weights, no network.

**MockOcrService** — returns configurable canned text per image path. Use `ocr.add_text(path, text)` to configure.

```python
ocr = MockOcrService()
ocr.add_text("/path/to/label.jpg", """
FAFA TEXTILES CO. LTD
ITEM NO: H4-7103WY
87/10/2/1 POLYSTEER/RAYON/LUREX/SPANDEX TWEED
WIDTH/HEIGHT: 61/63 *250g/m^2
""")
```

---

## Debugging

### Backend crashes on startup

Check the log file:
```
Linux:   ~/.config/TextileSearch/logs/
Windows: %APPDATA%\TextileSearch\logs\
```

Logs are structured JSON. Search for `"level":"ERROR"` or `"level":"CRITICAL"`.

### FAISS index corrupted

Delete `%APPDATA%\TextileSearch\index\faiss.index` and restart. The app detects `IndexCorruptedError` on load and rebuilds the index from stored embeddings in the DB. This takes ~1 second per 1,000 images.

### Database migration failed

Check for `"level":"CRITICAL"` + `"component":"alembic"` in the log. Common cause: a column was added to a model without a matching migration. Fix: generate the migration and restart.

### Port conflict

If another process is using port 8765, `sidecar.ts` will try the next 10 ports automatically (8765–8775). The chosen port is logged at startup.

---

## Performance notes (Phase 4 targets)

| Metric | Target | How it's achieved |
|---|---|---|
| Search latency (50k images) | < 200 ms | FAISS IVF+PQ, indexed DB columns |
| Import throughput (CPU) | ≥ 5 img/sec | Batched embedding (32/batch) |
| Import throughput (GPU) | ≥ 30 img/sec | CUDA auto-detected |
| Startup to ready | < 5 sec | Lazy model loading |
| RAM at 50k images | < 400 MB | IVF+PQ ~8× smaller than flat index |
| Gallery scroll (50k thumbs) | 60 fps | Paginated (100/page), pre-generated thumbnails |
