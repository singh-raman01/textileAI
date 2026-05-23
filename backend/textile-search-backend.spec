# PyInstaller spec file for the TextileSearch Python sidecar.
# Run with: uv run pyinstaller textile-search-backend.spec
#
# Output: dist/textile-search-backend/  (folder bundle, not single exe)
# The electron-builder then packages this folder inside the .exe installer.

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Alembic migrations must travel with the binary
        (str(ROOT / 'migrations'),    'migrations'),
        (str(ROOT / 'alembic.ini'),   '.'),
    ],
    hiddenimports=[
        # Alembic dynamic imports
        'alembic.config',
        'alembic.command',
        'alembic.script',
        'alembic.runtime.migration',
        'alembic.operations.ops',
        # SQLAlchemy dialects
        'sqlalchemy.dialects.sqlite',
        # FastAPI / Pydantic
        'fastapi',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'pydantic_core',
        # App modules
        'app',
        'app.api.health',
        'app.api.images',
        'app.api.import_',
        'app.api.history',
        'app.api.duplicates',
        'app.db.models',
        'app.services.embedder',
        'app.services.faiss_index',
        'app.services.field_parser',
        'app.services.importer',
        'app.services.ocr',
        'app.services.sync',
        'app.services.thumbnail',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'IPython', 'notebook'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zlib_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='textile-search-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # no console window on Windows
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='textile-search-backend',
)
