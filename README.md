# TextileSearch

Offline Windows desktop application for searching a fabric image library by visual similarity and label metadata. Runs entirely on your machine — no cloud, no internet required after installation.

---

## What it does

- Drop any fabric image → find visually similar fabrics in your library instantly
- Filter results by supplier, composition, width, weight, fabric type
- Auto-reads label text from images (OCR) and extracts structured fields
- Watches folders for new images — no manual re-import
- All data stored locally in SQLite. Nothing ever leaves your machine.

---

## Requirements

| Tool    | Version | Download                                                |
| ------- | ------- | ------------------------------------------------------- |
| Node.js | 20+     | https://nodejs.org                                      |
| Python  | 3.12+   | https://python.org                                      |
| uv      | any     | https://docs.astral.sh/uv/getting-started/installation/ |
| Git     | any     | https://git-scm.com                                     |

Install uv:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

## First-time setup

```bash
git clone <repo-url>
cd textile-search

# JavaScript dependencies (Electron, React, build tools)
npm install

# Python dependencies
cd backend
uv sync
cd ..
```

---

## Development

**Terminal 1 — run the full app:**

```bash
npm run dev
```

**Terminal 2 — run backend tests:**

```bash
cd backend
uv run pytest tests/ -v
```

Expected: `120 passed`

---

## Running the backend alone (API testing)

```bash
cd backend
TEXTILE_USE_MOCK_ML=true uv run python main.py --port 8765 --data-dir /tmp/textile-test
# API docs: http://localhost:8765/docs
```

`TEXTILE_USE_MOCK_ML=true` skips loading the AI models. The app starts in under a second and uses deterministic fake embeddings — good for development and testing.

---

## Installing AI models (optional for dev, required for production)

```bash
cd backend
uv sync --extra ml    # FashionCLIP visual embedder (~2 GB download)
uv sync --extra ocr   # PaddleOCR label reader
```

Without models: images are indexed by metadata only. Visual similarity search shows a "model not available" message. Everything else works normally.

---

## Project layout

```
textile-search/
│
├── src/                        Electron + React (TypeScript)
│   ├── main/                   Electron main process (Node.js)
│   │   ├── index.ts            Window creation, lifecycle, single-instance lock
│   │   ├── ipc.ts              All IPC handlers — bridges UI to Python sidecar
│   │   ├── watcher.ts          chokidar folder watcher (500 ms debounce)
│   │   ├── sidecar.ts          Spawns and monitors the Python process
│   │   └── logger.ts           Structured JSON logging (electron-log)
│   ├── preload/
│   │   └── index.ts            contextBridge — typed window.api for renderer
│   └── renderer/src/           React UI
│       ├── App.tsx             Shell, navigation, startup health poll
│       ├── pages/              Six pages: Search, Gallery, Import, History,
│       │                         Duplicates, Settings
│       ├── components/         Shared UI components
│       ├── i18n/locales/       en.json + zh-TW.json (complete translations)
│       └── window.d.ts         TypeScript types for window.api
│
├── shared/types/ipc.ts         Single source of truth for all IPC channels
│
├── backend/                    Python FastAPI sidecar
│   ├── pyproject.toml          Python dependencies (managed by uv)
│   ├── main.py                 Startup: migrations → DB → ML → import → uvicorn
│   ├── app/
│   │   ├── __init__.py         FastAPI app factory (all routers registered here)
│   │   ├── exceptions.py       Typed exception hierarchy
│   │   ├── api/                HTTP endpoints:
│   │   │   ├── health.py         GET /health, /db/status, GET+PATCH /settings
│   │   │   ├── images.py         POST /images/search, /browse; GET /images/{id}
│   │   │   ├── import_.py        POST /import/folder, /pause, /resume, /sync-batch
│   │   │   ├── history.py        POST/GET/DELETE /history
│   │   │   └── duplicates.py     GET /duplicates, POST /duplicates/{id}/resolve
│   │   ├── core/               Config, logging setup
│   │   ├── db/                 SQLAlchemy models + context-manager session
│   │   └── services/           Business logic:
│   │       ├── embedder.py       FashionCLIP (lazy) + MockEmbedder (tests)
│   │       ├── faiss_index.py    Vector index: thread-safe, atomic save
│   │       ├── field_parser.py   OCR text → structured fields + confidence tiers
│   │       ├── importer.py       Resumable import queue
│   │       ├── ocr.py            PaddleOCR (lazy) + MockOcrService (tests)
│   │       ├── sync.py           Startup sync + chokidar event handler
│   │       ├── thumbnail.py      Thumbnail generation (atomic write)
│   │       └── duplicate_scanner.py  Cosine similarity background scan
│   ├── migrations/             Alembic schema migrations (auto-run on startup)
│   └── tests/                  120 tests (pytest)
│
├── docs/                       Developer docs + user manual
│   ├── DEVELOPER.md            Architecture, adding features, debugging
│   ├── USER_MANUAL.md          End-user guide (EN + 繁中 note)
│   └── MAINTAINER_RUNBOOK.md   Release process, updating models, troubleshooting
│
├── resources/
│   └── installer.nsh           NSIS script (writes Windows long-path registry key)
│
└── .github/workflows/
    ├── ci.yml                  Linux: pytest + typecheck on every push
    └── release.yml             Windows: .exe installer on git tag
```

---

## How the two halves talk

```
Renderer (React)
    ↕  window.api.*  (contextBridge — no direct Node access)
Preload (contextBridge)
    ↕  ipcRenderer.invoke()
Main (Electron/Node)
    ↕  HTTP fetch to localhost:8765
Python sidecar (FastAPI)
    ↕  SQLite + FAISS index on disk
```

The Python process is spawned automatically by Electron on startup and killed when the app closes. Port 8765 is used by default; `sidecar.ts` finds a free port automatically if 8765 is taken.

---

## Common tasks

**Add a Python dependency:**

```bash
cd backend
uv add <package>            # updates pyproject.toml + uv.lock
```

**Add a database column:**

```bash
cd backend
# 1. Edit app/db/models.py
# 2. Generate the migration:
uv run alembic revision --autogenerate -m "add X to images"
# 3. Review migrations/versions/<new>.py
# Migrations run automatically at next app launch — no manual step.
```

**Add an IPC channel:**

1. Add types to `shared/types/ipc.ts`
2. Add `invoke()` call in `src/preload/index.ts`
3. Add `ipcMain.handle()` in `src/main/ipc.ts`
4. Add backend endpoint if needed

**Add a UI translation key:**

1. Add key + English string to `src/renderer/src/i18n/locales/en.json`
2. Add Traditional Chinese to `zh-TW.json`
3. Use in component: `const { t } = useTranslation(); t('your.key')`

**Run only one test file:**

```bash
cd backend
uv run pytest tests/test_field_parser.py -v
```

---

## Building a Windows installer (no Windows machine needed)

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions builds the installer on a Windows runner and attaches it to the release. Takes ~15 minutes. Download the `.exe` from the GitHub Releases page.

---

## Data locations

| Platform    | Path                       |
| ----------- | -------------------------- |
| Windows     | `%APPDATA%\TextileSearch\` |
| Linux (dev) | `~/.config/TextileSearch/` |

Contents:

```
TextileSearch/
├── textile.db          SQLite database
├── logs/               App + backend logs (30-day rotation)
├── thumbnails/         Generated 256×256 JPEG thumbnails
├── index/              FAISS vector index
└── models/             Cached ML model weights
```

---

## Environment variables

| Variable                   | Effect                                                   |
| -------------------------- | -------------------------------------------------------- |
| `TEXTILE_USE_MOCK_ML=true` | Skip AI models — app starts instantly, uses fake vectors |
| `TEXTILE_DEBUG=true`       | Verbose debug logging in the Python backend              |

---

## Installer size

The Windows installer is approximately **1.3 GB**. This is expected — it includes all AI models needed for fabric matching and label recognition. No internet connection is required after installation.
