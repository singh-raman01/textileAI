import os
import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='TextileSearch backend sidecar')
    parser.add_argument('--port',     type=int, default=8765,  help='Port to listen on')
    parser.add_argument('--data-dir', type=str, default=None,  help='App data directory')
    return parser.parse_args()


class AppConfig:
    """
    Central config object built from CLI args.
    All paths are derived from data_dir so nothing is hardcoded.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.port: int = args.port

        # Data directory — mirrors what Electron's app.getPath('userData') returns
        # Linux:   ~/.config/TextileSearch
        # Windows: %APPDATA%\TextileSearch
        # Fallback for running backend standalone in development:
        if args.data_dir:
            self.data_dir = Path(args.data_dir)
        else:
            self.data_dir = Path.home() / '.config' / 'TextileSearch'

        # Derived paths
        self.db_path        = self.data_dir / 'textile.db'
        self.log_dir        = self.data_dir / 'logs'
        self.thumbnail_dir  = self.data_dir / 'thumbnails'
        self.faiss_dir      = self.data_dir / 'index'
        self.models_dir     = self.data_dir / 'models'   # phase 1
        self.backup_dir     = self.data_dir / 'backups'

        # Ensure all directories exist
        for d in [self.data_dir, self.log_dir, self.thumbnail_dir,
                  self.faiss_dir, self.backup_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # SQLAlchemy database URL
        self.database_url = f'sqlite:///{self.db_path}'

        # App metadata
        self.app_version   = '1.0.0'
        self.model_version = 'fashionclip-vit-b32-v1'

    def __repr__(self) -> str:
        return (
            f'AppConfig(port={self.port}, data_dir={self.data_dir}, '
            f'db_path={self.db_path})'
        )


# Module-level singleton — set in main.py before the app starts
_config: AppConfig | None = None


def set_config(config: AppConfig) -> None:
    global _config
    _config = config


def get_config() -> AppConfig:
    if _config is None:
        raise RuntimeError('Config not initialised — call set_config() first')
    return _config
