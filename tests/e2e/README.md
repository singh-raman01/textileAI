# E2E Tests — Setup Guide

These tests use [Playwright](https://playwright.dev/) to drive the full Electron app.

## What you need before running

The E2E tests require **real fabric images**. The stubs below will fail without them.

### Required test fixture images

Create this folder structure before running:

```
tests/e2e/fixtures/
├── fabric_images/
│   ├── wool_001.jpg        Any fabric swatch photo (~200×200px or larger)
│   ├── wool_002.jpg        A different angle or colour of similar fabric
│   ├── cotton_001.jpg      A clearly different fabric type
│   ├── cotton_002.jpg
│   ├── synthetic_001.jpg
│   ├── labelled_001.jpg    Image with a visible text label (supplier, composition)
│   └── labelled_002.jpg    Another labelled image
├── labels/
│   ├── fafa_label.jpg      Clear photo of: "FAFA TEXTILES CO. LTD / ITEM NO: H4-7103WY / 87/10/2/1 POLYSTEER/RAYON/LUREX/SPANDEX TWEED / WIDTH/HEIGHT: 61/63 *250g/m^2"
│   └── spun_label.jpg      Clear photo of: "100% SPUNPOLYSTER TWO LAYER FABRIC / 66/68\" 286G/YD (170GSM) +-3%"
└── query/
    └── search_query.jpg    The image to use as a search query (should match wool_001.jpg closely)
```

### Image quality guidelines

- **Resolution:** Minimum 200×200 pixels. 512×512 or higher recommended.
- **Format:** JPEG or PNG. Avoid highly compressed files.
- **Content:** The images must be of actual fabric swatches, not patterns or colour charts.
- **Labels:** `labelled_001.jpg` and `labelled_002.jpg` should have visible text labels in the frame.
- **Search query:** `query/search_query.jpg` should be visually similar to one or more images in `fabric_images/` so the search test can verify results.

### Why real images are required

The AI model (FashionCLIP) is trained on textile images. Test images that are not fabric photos will produce unpredictable embeddings and unreliable search results. The E2E tests verify end-to-end behaviour including the AI pipeline, which cannot be meaningfully tested with synthetic data.

## Running the tests

```bash
# Install Playwright (one-time)
npm install --save-dev @playwright/test
npx playwright install

# Run all E2E tests
npx playwright test tests/e2e/

# Run a specific test
npx playwright test tests/e2e/import.spec.ts

# Run with UI (see the browser)
npx playwright test --ui
```

## CI notes

E2E tests run on the `windows-latest` GitHub Actions runner only (in `release.yml`), because they require the full Electron app with real model weights. They are not run on every push — only on release tags.

To add E2E tests to every push, add a `TEXTILE_E2E_FIXTURES` secret pointing to a cloud storage bucket containing the fixture images.
