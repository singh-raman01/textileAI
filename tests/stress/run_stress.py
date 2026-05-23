"""
TextileSearch — Stress test runner.

Tests performance targets from the Phase 4 specification.
Requires a large dataset of real images — see README.md.

Usage:
    uv run python tests/stress/run_stress.py --test import --image-dir /path/to/images
    uv run python tests/stress/run_stress.py --test search --n-queries 100
    uv run python tests/stress/run_stress.py --test all --image-dir /path/to/images
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Targets (from Phase 4 spec)
# ─────────────────────────────────────────────────────────────────────────────

TARGETS = {
    "import_throughput_cpu":   5.0,    # images/sec minimum
    "search_latency_ms":       200.0,  # ms maximum for top-50 search at 50k images
    "browse_latency_ms":       100.0,  # ms maximum for browse query at 50k images
    "startup_seconds":         5.0,    # seconds from launch to ready
}

BASE_URL = "http://127.0.0.1:8765"


def check_sidecar_running() -> bool:
    """Verify the backend sidecar is running before tests."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Import throughput test
# ─────────────────────────────────────────────────────────────────────────────

def test_import_throughput(image_dir: Path) -> None:
    """
    STUB — requires real images.

    Measures images indexed per second during bulk import.

    Full implementation steps:
    1. POST /import/folder with image_dir
    2. Poll GET /import/status every second until is_running=False
    3. Calculate: total_done / elapsed_seconds
    4. Assert result >= TARGETS["import_throughput_cpu"]

    To implement: uncomment and adapt the code below when image_dir is populated.
    """
    print(f"\n{'='*60}")
    print("IMPORT THROUGHPUT TEST")
    print(f"{'='*60}")

    if not image_dir.exists():
        print(f"SKIP — image directory not found: {image_dir}")
        print("See tests/stress/README.md for how to get test images.")
        return

    image_count = sum(1 for f in image_dir.rglob("*")
                     if f.suffix.lower() in {'.jpg','.jpeg','.png','.webp'})
    if image_count < 100:
        print(f"SKIP — only {image_count} images found (minimum 100 required)")
        return

    print(f"Found {image_count:,} images in {image_dir}")
    print("NOTE: Ensure backend is running: TEXTILE_USE_MOCK_ML=false uv run python main.py")
    print()

    # STUB: Replace with real implementation
    # import json, urllib.request
    # data = json.dumps({"folder_path": str(image_dir), "display_name": "stress-test"}).encode()
    # req = urllib.request.Request(f"{BASE_URL}/import/folder",
    #                              data=data, headers={"Content-Type": "application/json"})
    # urllib.request.urlopen(req)
    # t0 = time.monotonic()
    # while True:
    #     with urllib.request.urlopen(f"{BASE_URL}/import/status") as r:
    #         status = json.loads(r.read())
    #     if not status["is_running"]:
    #         break
    #     time.sleep(1.0)
    # elapsed = time.monotonic() - t0
    # throughput = status["done"] / elapsed
    # ...

    print("STUB: Import throughput test not yet implemented.")
    print(f"Target: >= {TARGETS['import_throughput_cpu']} images/sec")


# ─────────────────────────────────────────────────────────────────────────────
# Search latency test
# ─────────────────────────────────────────────────────────────────────────────

def test_search_latency(n_queries: int, query_image_dir: Path | None) -> None:
    """
    STUB — requires 50,000+ images indexed and real query images.

    Measures p50 and p95 search latency at scale.

    Full implementation:
    1. Pick n_queries random images from the indexed library as queries
    2. POST each to /images/search with k=50
    3. Record latency per query
    4. Assert p95 latency <= TARGETS["search_latency_ms"]

    Note: Search latency on a flat index (< 20k images) will be fast.
    The target applies at 50k images using the IVF+PQ index.
    """
    print(f"\n{'='*60}")
    print("SEARCH LATENCY TEST")
    print(f"{'='*60}")

    if not check_sidecar_running():
        print("SKIP — backend sidecar not running")
        print("Start it with: TEXTILE_USE_MOCK_ML=false uv run python main.py --port 8765 --data-dir /path/to/data")
        return

    # Check indexed count
    import json, urllib.request
    with urllib.request.urlopen(f"{BASE_URL}/db/status") as r:
        status = json.loads(r.read())
    indexed = status.get("indexed_count", 0)
    print(f"Indexed images: {indexed:,}")

    if indexed < 1_000:
        print(f"SKIP — only {indexed:,} images indexed (target is 50,000 for meaningful results)")
        print("Run the import test first to build up the index.")
        return

    if indexed < 20_000:
        print(f"WARNING — {indexed:,} images indexed. IVF+PQ migration occurs at 20,000.")
        print("Results at this scale may not reflect production latency.")

    print(f"Running {n_queries} search queries...")
    print("STUB: Requires query images. Provide --query-image-dir with fabric photos.")
    print(f"Target: p95 latency <= {TARGETS['search_latency_ms']} ms")

    # STUB: Real implementation would:
    # 1. Collect query image paths from query_image_dir
    # 2. For each query: POST multipart /images/search and time the round trip
    # 3. Report p50, p95, p99 latencies


# ─────────────────────────────────────────────────────────────────────────────
# Crash recovery test  (no real images needed)
# ─────────────────────────────────────────────────────────────────────────────

def test_crash_recovery(data_dir: Path) -> None:
    """
    Verify FAISS index corruption is detected and recovered automatically.
    This test does NOT require real images — it corrupts the index file directly.
    """
    print(f"\n{'='*60}")
    print("CRASH RECOVERY TEST")
    print(f"{'='*60}")

    index_path = data_dir / "index" / "faiss.index"
    if not index_path.exists():
        print(f"SKIP — no FAISS index found at {index_path}")
        print("Run an import first to create the index.")
        return

    # Corrupt the index file
    backup = index_path.with_suffix(".bak")
    import shutil
    shutil.copy(index_path, backup)

    try:
        with open(index_path, "wb") as f:
            f.write(b"CORRUPTED_BY_STRESS_TEST" * 100)
        print(f"Corrupted index at {index_path}")

        # The app should detect this on next load and rebuild
        # In a real test: restart the app and verify it launches without crashing
        print("STUB: Restart the app and verify it shows 'index rebuilt' in logs.")
        print("Expected log entry: {\"level\":\"INFO\",\"msg\":\"FAISS index rebuilt from DB\"}")
        print(f"Target: App starts and is functional within {TARGETS['startup_seconds']} seconds")
    finally:
        shutil.copy(backup, index_path)
        backup.unlink()
        print(f"Index restored from backup")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="TextileSearch stress tests")
    parser.add_argument("--test", choices=["import", "search", "recovery", "all"],
                        default="all", help="Which test to run")
    parser.add_argument("--image-dir", type=Path,
                        default=Path("tests/stress/fixtures/fabric_images"),
                        help="Directory containing fabric images for import test")
    parser.add_argument("--query-image-dir", type=Path,
                        default=None,
                        help="Directory containing query images for search test")
    parser.add_argument("--data-dir", type=Path,
                        default=Path.home() / ".config" / "TextileSearch",
                        help="TextileSearch data directory (for recovery test)")
    parser.add_argument("--n-queries", type=int, default=100,
                        help="Number of search queries for latency test")
    args = parser.parse_args()

    print("TextileSearch Stress Tests")
    print(f"Backend: {BASE_URL}")
    print(f"Data dir: {args.data_dir}")

    if args.test in ("import", "all"):
        test_import_throughput(args.image_dir)

    if args.test in ("search", "all"):
        test_search_latency(args.n_queries, args.query_image_dir)

    if args.test in ("recovery", "all"):
        test_crash_recovery(args.data_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
