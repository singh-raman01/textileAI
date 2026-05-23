# Stress Tests

These tests verify performance targets from the Phase 4 spec. They require a large image dataset.

## Requirements

| Test | Minimum images | Time estimate |
|---|---|---|
| Import throughput | 1,000 | 5 min (CPU) |
| Search latency | 50,000 indexed | 30 min to index |
| Gallery scroll | 50,000 indexed | — |

### Getting 50,000 test images

Options:
1. **Your own fabric library** (recommended) — use your real production image folder
2. **DeepFashion dataset** — contains 800k+ clothing images: https://mmlab.ie.cuhk.edu.hk/projects/DeepFashion.html
3. **Kaggle textile datasets** — search "fabric texture dataset" on Kaggle
4. **Synthetic images** — generate fabric-like images with PIL (acceptable for throughput tests; not for accuracy tests):

```python
# generate_test_images.py
# Creates 1,000 random "fabric texture" JPEG images for throughput testing only.
# DO NOT use these for validating search accuracy — the embeddings will be meaningless.
from PIL import Image
import numpy as np
import pathlib

OUT = pathlib.Path("tests/stress/fixtures/synthetic_fabrics")
OUT.mkdir(parents=True, exist_ok=True)

for i in range(1000):
    # Random noise image — valid for import throughput, not for search accuracy
    arr = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    Image.fromarray(arr).save(OUT / f"synthetic_{i:04d}.jpg", quality=80)
    if i % 100 == 0:
        print(f"{i}/1000")
print("Done. WARNING: These are not real fabric images. Use for throughput testing only.")
```

## Running stress tests

```bash
cd backend
uv run python tests/stress/run_stress.py --test import --image-dir /path/to/50k/images
uv run python tests/stress/run_stress.py --test search --n-queries 100
```
