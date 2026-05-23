# TextileSearch — Maintainer Runbook

This document is for whoever maintains the project: cutting releases, updating models, reading logs, fixing schema issues.

---

## Cutting a release

```bash
# 1. Make sure tests pass locally
cd backend && uv run pytest tests/ -q   # must show 120 passed

# 2. Update the version in package.json
# (edit "version": "1.0.0" to the new version)

# 3. Commit
git add -A && git commit -m "Release v1.1.0"

# 4. Tag — this triggers the Windows build on GitHub Actions
git tag v1.1.0
git push origin main --tags
```

The GitHub Actions `release.yml` workflow runs on the `windows-latest` runner. It:
1. Installs uv and Python 3.12
2. Runs `uv sync --extra ml --extra ocr` to install FashionCLIP + PaddleOCR
3. Bundles the Python sidecar with PyInstaller
4. Runs `npm ci && npm run build:win` to build the Electron app
5. Attaches the `.exe` to a GitHub Release automatically

**Watch the build:** Go to the repository → Actions → the triggered workflow. Build takes ~15 minutes.

**If the build fails:**
- Check the Actions log — the most common failure is a missing secret or a dependency that changed upstream
- The PyInstaller step occasionally fails if a hidden import is missing — add it to `backend/textile-search-backend.spec` under `hiddenimports`

---

## Adding a translation key

All UI strings live in two files:

```
src/renderer/src/i18n/locales/en.json      English (source of truth)
src/renderer/src/i18n/locales/zh-TW.json  Traditional Chinese
```

Steps:
1. Add the key + English string to `en.json`
2. Add the translated string to `zh-TW.json`
3. Use in a component: `const { t } = useTranslation(); t('section.key')`

Keys are dot-separated: `nav.search`, `import.addFolder`, `settings.title`. Match the existing structure.

**Never leave a key in `en.json` without a matching entry in `zh-TW.json`** — missing keys fall back to the raw key string, which looks broken to users.

---

## Updating the AI models

### FashionCLIP (visual embedder)

The model is downloaded from HuggingFace on first run and cached locally. To update to a new version:

1. Update the model ID in `backend/app/services/embedder.py`:
   ```python
   _MODEL_ID: Final[str] = "patrickjohncyh/fashion-clip"   # change this
   _MODEL_VERSION: Final[str] = "fashionclip-vit-b32-v1"   # bump this
   ```
2. Change `_MODEL_VERSION` — this causes a warning banner on next launch prompting users to re-index

**Re-indexing after a model change:**
- The app detects that stored embeddings were made with an older model version
- A persistent banner appears: "AI model updated. Re-index your library for best results."
- Users click the banner to start re-indexing (replaces all FAISS embeddings)
- This is manual and deliberate — never automatic (D2 design decision)

### PaddleOCR

PaddleOCR model weights are downloaded and cached automatically. To update:
1. Bump the version in `backend/pyproject.toml`: `paddleocr>=2.7.3`
2. Test with representative labels from your collection before releasing

---

## Updating the PyInstaller spec

The spec file is `backend/textile-search-backend.spec`. Edit `hiddenimports` when you add a new module that PyInstaller cannot discover automatically.

Common causes of missing imports:
- New `app/api/*.py` file not imported by `app/__init__.py`
- New SQLAlchemy dialect or Alembic component
- New service module that is only imported conditionally

Test the spec locally on Windows (or the GitHub Actions runner):
```powershell
uv run pyinstaller textile-search-backend.spec --clean
# Check that dist\textile-search-backend\textile-search-backend.exe starts without errors
```

---

## Reading logs

Logs are structured JSON at:
- Windows: `%APPDATA%\TextileSearch\logs\`
- Linux: `~/.config/TextileSearch/logs\`

Two log files:
- `app-YYYY-MM-DD.log` — Electron main process (window lifecycle, IPC, sidecar start)
- `backend-YYYY-MM-DD.log` — Python sidecar (imports, searches, OCR, database)

Each line is a JSON object:
```json
{"ts":"2025-05-21T09:14:33Z","level":"INFO","component":"import","msg":"Batch complete","indexed":32,"failed":1,"elapsed_ms":27441}
```

**Useful search patterns:**
```bash
# All errors
grep '"level":"ERROR"' backend-2025-05-21.log

# Import failures with reasons
grep '"component":"import"' backend-2025-05-21.log | grep '"level":"ERROR"'

# FAISS operations
grep '"component":"faiss"' backend-2025-05-21.log

# OCR results for a specific file
grep '"path":"/path/to/image.jpg"' backend-2025-05-21.log
```

---

## Fixing schema migration issues

**Never edit an applied migration.** Always create a new one.

If the database schema and models are out of sync:
```bash
cd backend

# See current migration state
uv run alembic current

# See all migrations
uv run alembic history --verbose

# Generate a new migration from model changes
uv run alembic revision --autogenerate -m "describe the change"

# Review and apply
uv run alembic upgrade head
```

**If alembic autogenerate produces an empty migration:** The model change may not be detected automatically (e.g., index changes, column defaults). Add the operations manually to the generated migration file.

**If the DB is corrupted or migration fails:**
```bash
# The app takes a backup before every migration at:
# %APPDATA%\TextileSearch\backups\textile_YYYYMMDD_HHMMSS.db.bak

# To restore:
cp backups/textile_20250521_091433.db.bak textile.db
```

---

## Monitoring import health

Check the import summary in the DB:
```sql
SELECT import_status, COUNT(*) FROM images GROUP BY import_status;
```

Expected steady state after a complete import: all rows have `import_status = 'done'`.

If many rows are stuck in `import_status = 'failed'`:
```sql
SELECT import_error, COUNT(*) FROM images WHERE import_status = 'failed' GROUP BY import_error;
```

Common errors and fixes:

| Error | Cause | Fix |
|---|---|---|
| `File not found on disk` | File was moved/deleted before indexing | Normal — delete the record or leave it |
| `Cannot read file: Permission denied` | File locked by another process | Retry after closing the locking process |
| `OCR failed: out of memory` | Very large image | The image is >25 MB; it will be downsampled on retry |
| `Embed failed: CUDA out of memory` | GPU VRAM full | Reduce batch size in `BATCH_SIZE` constant in `importer.py` |

---

## Recovering from a corrupted FAISS index

Symptoms: app crashes on launch with `IndexCorruptedError` in logs, or searches return nonsense results.

1. Delete the index file:
   - Windows: `%APPDATA%\TextileSearch\index\faiss.index`
2. Restart the app
3. The app detects the missing file and rebuilds the index from stored embeddings in the database
4. Rebuild time: ~1 second per 1,000 images

---

## Adding a new watched folder programmatically

Via the API (for automation or scripting):
```bash
curl -X POST http://localhost:8765/import/folder \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "/path/to/fabrics", "display_name": "Fabric Archive"}'
```

---

## Checking API health

```bash
curl http://localhost:8765/health
# {"status":"ok","version":"1.0.0","uptime_s":142}

curl http://localhost:8765/db/status
# {"schema_version":1,"image_count":8432,"indexed_count":8430,"queued_count":2,"failed_count":0}
```
