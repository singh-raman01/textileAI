# TextileSearch — User Manual

**Version 1.0 · English**

繁體中文版請見 [USER_MANUAL_zhTW.md](./USER_MANUAL_zhTW.md)

---

## What is TextileSearch?

TextileSearch is a desktop application for searching your fabric image library by visual similarity. Drag any fabric photo onto the app and it finds the most visually similar fabrics in your collection — instantly, without an internet connection.

It also reads the text labels on fabric samples (supplier name, composition, width, weight) and lets you filter results by those values.

Everything runs on your computer. No data is sent anywhere.

---

## Installation

1. Download `TextileSearch-Setup-*.exe` from the Releases page
2. Double-click the installer. If Windows shows a security warning, click **More info** → **Run anyway**. This warning appears because the app is not yet registered with Microsoft; it is safe.
3. Follow the installer steps. The default installation path is fine for most users.
4. Launch TextileSearch from the Start menu or desktop shortcut.

**First launch is slower than subsequent launches.** The app is setting up its database and loading AI models for the first time. This takes about 30–60 seconds. Subsequent launches take under 5 seconds.

**Installer size: ~1.3 GB.** This is expected — all AI models for fabric matching and label reading are included. No further downloads are needed.

---

## The interface

The app has six sections, accessible from the left sidebar:

| Section | What it does |
|---|---|
| **Search** | Find fabrics visually similar to a query image |
| **Gallery** | Browse your entire library with filters |
| **Import** | Add folders of fabric images |
| **History** | Re-open past searches |
| **Duplicates** | Review flagged duplicate images |
| **Settings** | Language, search defaults, display options |

---

## Step 1: Import your images

Before you can search, the app needs to index your fabric images.

1. Click **Import** in the sidebar
2. Click **Add folder**
3. Select the root folder that contains your fabric images

The app scans the folder and all subfolders automatically. You do not need to organise your images beforehand — any folder structure works.

**What happens during import:**
- Each image is read and a visual fingerprint (embedding) is computed
- Label text is extracted from each image using OCR
- A small thumbnail is generated for display
- Everything is stored in a local database

**How long does import take?**
- CPU only: approximately 5 images per second
- With GPU: approximately 30 images per second
- A library of 10,000 images takes about 30–35 minutes on CPU

You can use the app during import — search and browse are available immediately for images that have already been indexed.

**Adding more folders:** You can add as many folders as you like. Click **Add folder** again and select another location. Each folder is watched independently.

**The app never deletes images.** It reads images but does not modify or move them. To remove images from your library, delete or move them in File Explorer — the app will detect the change automatically.

---

## Step 2: Search by image

1. Click **Search** in the sidebar
2. Either:
   - **Drag** a fabric image from File Explorer onto the drop zone, or
   - **Click** the drop zone to open a file picker
3. The app finds the most visually similar fabrics and displays them as a grid

**Adjusting the number of results:** Use the **Top results** slider to show 5–100 results. A higher number finds more matches but may include less similar items.

**Similarity badges:**
- 🟢 Green (≥ 90%) — very similar
- 🟡 Amber (70–89%) — moderately similar
- 🔴 Red (< 70%) — somewhat similar

**Clicking a result card** opens the detail panel on the right, showing:
- Full metadata extracted from the label (supplier, composition, width, weight)
- Confidence indicators (green = high confidence, amber = review recommended)
- Tags derived from the folder structure
- **Search similar** — use this result as a new query
- **Show in folder** — open File Explorer with this file highlighted

---

## Step 3: Browse and filter

Click **Gallery** to browse your full library without a query image.

**Available filters:**
- Type text to filter by item number or folder tag
- Sort by date, filename, or weight
- Toggle to show or hide orphaned files (files that have been moved or deleted)

**Multi-select:** Click images to select them. Selected images are highlighted with a checkmark. (Bulk tag assignment coming in a future version.)

**Pagination:** The gallery shows 100 images per page. Use the ← → arrows at the bottom to navigate.

---

## Understanding metadata badges

When the app reads label text, it assigns a confidence level to each extracted field.

| Badge | Meaning | What to do |
|---|---|---|
| No badge | High confidence (≥ 90%) | Trust it |
| **Review** amber badge | Medium confidence (65–89%) | Verify the value manually |
| Not shown | Low confidence (< 65%) | Field was not extracted |

**Composition sum check:** If the composition percentages do not add up to 100% (within ±2%), the field is always marked for review regardless of OCR confidence. This is intentional — a label that says 87%+10%+2%+5% = 104% is likely a misread.

---

## Folder tags

The app automatically creates tags from your folder structure. For example:

```
/Fabrics/
    Wool/
        Winter 2025/
            swatch_001.jpg    → tags: Wool, Winter 2025
    Cotton/
        Summer/
            swatch_002.jpg    → tags: Cotton, Summer
```

These tags appear as grey pills in the detail panel and can be used to filter the gallery. They are read-only — the tag changes when you move the file in File Explorer.

---

## Duplicates

Click **Duplicates** to review images the app has flagged as duplicates.

Two types of duplicates are detected:

- **Exact** — identical files (same pixel content, different filenames or locations)
- **Visual** — visually very similar (≥ 97% similarity score by default)

For each pair, you can:
- View both images side by side
- See file sizes and dates to decide which to keep
- Click **Show in folder** to open File Explorer
- Click **Mark resolved** to dismiss the pair from the list

**The app does not delete files.** To actually remove a duplicate, delete it in File Explorer. The app will detect the deletion at next launch and remove the orphaned record.

---

## Search history

Click **History** to see all past searches with their query image and top results. Click **Re-run** to repeat any search.

History is kept for 12 months by default. You can clear it at any time from the History page.

---

## Settings

| Setting | Default | Notes |
|---|---|---|
| Language | English | Switches instantly, no restart needed |
| Default results (k) | 20 | How many results Search shows by default |
| Duplicate threshold | 0.97 | Lower value = more duplicate matches found |
| Show orphaned images | Off | Shows images whose files have been moved/deleted |
| Thumbnail cache | 2 GB | Disk space used for generated thumbnails |

---

## Automatic file watching

Once a folder is added, the app watches it continuously. Any image you copy, move, or save into the folder is indexed automatically within a few seconds. You never need to manually re-import.

If you rename or move a folder, the app detects the change and updates its records — no data is lost.

---

## Language

Switch between English and 繁體中文 using the button in the top-right corner of the app. The change is instant and requires no restart.

---

## If something goes wrong

**The app will not start:**
- Make sure you installed it by running the `.exe` installer, not by copying the folder
- Try restarting your computer

**Images are not appearing after import:**
- Check the status bar at the bottom — if it shows "Importing" the process is still running
- If import seems stuck, click **Import** → **Pause** → **Resume**

**Search results look wrong:**
- Make sure the query image is a fabric photo, not a pattern or document
- The AI model works best with fabric samples photographed against a plain background

**Text labels are not being read:**
- OCR works best on clear, flat labels photographed straight-on
- Very small, blurry, or highly rotated text may not be read correctly
- You can view the raw OCR text in the detail panel to see what was extracted

**Log files:**
- Click Settings → **Open log folder** to view detailed logs
- Logs are plain text and reset every 30 days

---

## Privacy and data

- All data is stored on your computer only
- No images, metadata, or usage data is sent to any server
- The AI models run entirely locally — no internet connection needed after installation
- Uninstalling the app does not delete your images or the TextileSearch data folder. To remove all data, delete `%APPDATA%\TextileSearch` after uninstalling.
