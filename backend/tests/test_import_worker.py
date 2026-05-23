"""ImportWorker unit tests: lifecycle, processing, error handling."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from PIL import Image as PilImage

from app.db.models import Image as ImageModel, TextileMetadata, FabricComposition
from app.db.session import get_session
from app.services.embedder import MockEmbedder
from app.services.ocr import MockOcrService
from app.services.faiss_index import FaissIndexManager
from app.services.thumbnail import ThumbnailService
from app.services.importer import ImportWorker, ImportProgress


VECTOR_DIM = 512


def _make_image(directory: Path, name: str = "test.jpg") -> Path:
    p = directory / name
    img = PilImage.new("RGB", (64, 64), color=(128, 64, 32))
    img.save(p, format="JPEG")
    return p


@pytest.fixture
def data_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def faiss_mgr(data_dir: Path) -> FaissIndexManager:
    m = FaissIndexManager(data_dir / "faiss", vector_dim=VECTOR_DIM)
    m.initialise()
    return m


@pytest.fixture
def embedder() -> MockEmbedder:
    return MockEmbedder()


@pytest.fixture
def ocr_service() -> MockOcrService:
    return MockOcrService()


@pytest.fixture
def thumbnail_svc(data_dir: Path) -> ThumbnailService:
    return ThumbnailService(data_dir / "thumbnails")


@pytest.fixture
def worker(
    embedder: MockEmbedder,
    ocr_service: MockOcrService,
    thumbnail_svc: ThumbnailService,
    faiss_mgr: FaissIndexManager,
    data_dir: Path,
) -> ImportWorker:
    return ImportWorker(
        embedder=embedder,
        ocr=ocr_service,
        thumbnail_svc=thumbnail_svc,
        faiss_mgr=faiss_mgr,
        data_dir=data_dir,
    )


class TestLifecycle:
    def test_start_is_idempotent(self, worker: ImportWorker) -> None:
        worker.start()
        worker.start()  # second call should be no-op
        worker.stop()

    def test_progress_defaults(self, worker: ImportWorker) -> None:
        prog = worker.get_progress()
        assert prog.total_queued == 0
        assert prog.processed == 0
        assert prog.failed == 0
        assert prog.skipped == 0
        assert prog.is_running is False
        assert prog.is_paused is False

    def test_pause_and_resume(self, worker: ImportWorker) -> None:
        worker.start()
        worker.pause()
        prog1 = worker.get_progress()
        assert prog1.is_paused is True
        worker.resume()
        prog2 = worker.get_progress()
        assert prog2.is_paused is False
        worker.stop()

    def test_stop_clears_running(self, worker: ImportWorker) -> None:
        worker.start()
        worker.stop()
        prog = worker.get_progress()
        assert prog.is_running is False

    def test_progress_snapshot_independent(self, worker: ImportWorker) -> None:
        p1 = worker.get_progress()
        p1.processed = 999
        p2 = worker.get_progress()
        assert p2.processed != 999


class TestProcessOne:
    def test_success_processes_image(
        self,
        worker: ImportWorker,
        db_ready: bool,
        tmp_path: Path,
    ) -> None:
        img_path = _make_image(tmp_path)
        with get_session() as session:
            img = ImageModel(
                file_path=str(img_path),
                filename=img_path.name,
                import_status="queued",
            )
            session.add(img)
            session.flush()
            image_id = img.id

        worker._process_one(image_id)

        with get_session() as session:
            processed = session.get(ImageModel, image_id)
        assert processed is not None
        assert processed.import_status == "done"
        assert processed.faiss_id is not None
        assert processed.thumbnail_path is not None

    def test_failed_on_missing_file(self, worker: ImportWorker, db_ready: bool) -> None:
        with get_session() as session:
            img = ImageModel(
                file_path="/tmp/nonexistent.jpg",
                filename="nonexistent.jpg",
                import_status="queued",
            )
            session.add(img)
            session.flush()
            image_id = img.id

        worker._process_one(image_id)

        with get_session() as session:
            processed = session.get(ImageModel, image_id)
        assert processed is not None
        assert processed.import_status == "failed"
        assert processed.is_orphaned is True

    def test_persists_metadata_when_ocr_succeeds(
        self,
        worker: ImportWorker,
        db_ready: bool,
        tmp_path: Path,
    ) -> None:
        label = "FAFA TEXTILES\n100% COTTON\nWIDTH: 60\""
        img_path = _make_image(tmp_path)
        worker._ocr.add_text(img_path, label)
        with get_session() as session:
            img = ImageModel(
                file_path=str(img_path),
                filename=img_path.name,
                import_status="queued",
            )
            session.add(img)
            session.flush()
            image_id = img.id

        worker._process_one(image_id)

        with get_session() as session:
            meta = session.query(TextileMetadata).filter(
                TextileMetadata.image_id == image_id
            ).first()
        assert meta is not None
        assert meta.supplier == "FAFA TEXTILES"

    def test_persists_composition(
        self,
        worker: ImportWorker,
        db_ready: bool,
        tmp_path: Path,
    ) -> None:
        label = "100% COTTON DENIM"
        img_path = _make_image(tmp_path)
        worker._ocr.add_text(img_path, label)
        with get_session() as session:
            img = ImageModel(
                file_path=str(img_path),
                filename=img_path.name,
                import_status="queued",
            )
            session.add(img)
            session.flush()
            image_id = img.id

        worker._process_one(image_id)

        with get_session() as session:
            meta = session.query(TextileMetadata).filter(
                TextileMetadata.image_id == image_id
            ).first()
        assert meta is not None
        comps = session.query(FabricComposition).filter(
            FabricComposition.metadata_id == meta.id
        ).all()
        assert len(comps) == 1
        assert comps[0].material == "COTTON"
        assert comps[0].percentage == pytest.approx(100.0)

    def test_image_without_ocr_still_indexed(
        self,
        worker: ImportWorker,
        db_ready: bool,
        tmp_path: Path,
    ) -> None:
        img_path = _make_image(tmp_path)
        with get_session() as session:
            img = ImageModel(
                file_path=str(img_path),
                filename=img_path.name,
                import_status="queued",
            )
            session.add(img)
            session.flush()
            image_id = img.id

        worker._process_one(image_id)

        with get_session() as session:
            processed = session.get(ImageModel, image_id)
        assert processed is not None
        assert processed.import_status == "done"
        assert processed.faiss_id is not None

    def test_failed_embed_sets_status_to_failed(
        self,
        worker: ImportWorker,
        db_ready: bool,
        tmp_path: Path,
    ) -> None:
        img_path = _make_image(tmp_path)
        # Simulate an embed failure by using a non-existent file
        # The embedder will fail to open the image
        with get_session() as session:
            img = ImageModel(
                file_path=str(img_path.parent / "no_such_file.jpg"),
                filename="no_such_file.jpg",
                import_status="queued",
            )
            session.add(img)
            session.flush()
            image_id = img.id

        worker._process_one(image_id)

        with get_session() as session:
            processed = session.get(ImageModel, image_id)
        assert processed is not None
        assert processed.import_status == "failed"


class TestFetchBatch:
    def test_fetch_batch_returns_queued_ids(
        self,
        worker: ImportWorker,
        db_ready: bool,
        tmp_path: Path,
    ) -> None:
        for i in range(3):
            with get_session() as session:
                session.add(ImageModel(
                    file_path=str(tmp_path / f"batch_{i}.jpg"),
                    filename=f"batch_{i}.jpg",
                    import_status="queued",
                ))
        with get_session() as session:
            batch = worker._fetch_batch(session)
        # At least 3 — other tests may also leave queued images
        assert len(batch) >= 3

    def test_fetch_batch_skips_non_queued(
        self,
        worker: ImportWorker,
        db_ready: bool,
    ) -> None:
        # Clean any queued images left by other tests
        with get_session() as session:
            session.query(ImageModel).filter(
                ImageModel.import_status == "queued"
            ).delete()
        with get_session() as session:
            session.add(ImageModel(
                file_path="/tmp/done.jpg",
                filename="done.jpg",
                import_status="done",
            ))
            session.add(ImageModel(
                file_path="/tmp/failed.jpg",
                filename="failed.jpg",
                import_status="failed",
            ))
        with get_session() as session:
            batch = worker._fetch_batch(session)
        assert len(batch) == 0


class TestCrashRecovery:
    def test_recover_interrupted_resets_processing(
        self,
        worker: ImportWorker,
        db_ready: bool,
    ) -> None:
        with get_session() as session:
            session.add(ImageModel(
                file_path="/tmp/stuck.jpg",
                filename="stuck.jpg",
                import_status="processing",
            ))
        worker.recover_interrupted()
        with get_session() as session:
            img = session.query(ImageModel).filter(
                ImageModel.file_path == "/tmp/stuck.jpg"
            ).first()
        assert img is not None
        assert img.import_status == "queued"

    def test_recover_no_processing_rows(self, worker: ImportWorker) -> None:
        worker.recover_interrupted()
