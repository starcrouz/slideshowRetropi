# SlideshowRecalbox

A complete solution to manage and display a high-quality photo/video slideshow on a Recalbox-powered Bartop/Raspberry Pi.

The project is divided into two distinct parts:
1. **Photo Selector (PC)**: A Node.js application to prepare and transfer your images & videos.
2. **Screensaver System (RPi)**: A Python-based idle monitor and animated slideshow for Recalbox.

---

## 1. Photo Selector (PC / Node.js)

Maintains a selection of optimized photos from your library and transfers them to the Bartop over the network.

- **Quality Filtering**: Excludes blurry, low-resolution, badly proportioned, or text-heavy images based on customizable thresholds.
- **OCR Detection**: Uses Tesseract to detect and reject images containing too much text (screenshots, documents, memes…).
- **Metadata Enrichment**: Reads EXIF data to generate `.txt` sidecar files with location labels (city/country), date, and source path. Handles HEIC/iPhone photos natively.
- **Video Support**: Validates videos with `ffprobe` (excluding corrupted files and short iPhone Live Photos) and automatically transcodes them with `ffmpeg` into Raspberry Pi hardware-compatible `.mp4` (`H.264 8-bit yuv420p`, `AAC`, max `1280x1024` @ `30fps`).
- **Smart Shuffling**: In-place overwriting of destination files to avoid slideshow downtime.
- **Lock File**: Prevents concurrent runs (via scheduler or dashboard).

### Installation & Usage
1. `npm install`
2. Configure `config.json` (see settings below).
3. Run manually: `node index.js` (or `node index.js --videos-only` to refresh and transcode only videos while keeping existing photos).

### `config.json` Parameters

| Key | Description |
|---|---|
| `SOURCE_DIR` | Source folder for your photos |
| `DEST_DIR` | Network destination on the Bartop (e.g. `\\RECALBOX\share\...`) |
| `VIDEO_DEST_DIR` | Network destination for personal videos |
| `NB_IMAGES` | Number of photos to select (default: `100`) |
| `SCREEN_W` / `SCREEN_H` | Target screen resolution (used for aspect ratio filtering) |
| `VIDEO_LIMIT_MB` | Maximum total size of converted videos to transfer (in MB) |
| `VIDEO_MIN_DURATION_SEC` | Minimum video duration in seconds (default: `4`, excludes iPhone Live Photos) |
| `VIDEO_MAX_PLAY_SEC` | Maximum playback duration per video in seconds (default: `30`, trims longer clips up to 3m and excludes movies > 3m) |
| `CITY_OVERRIDES` | Rename specific detected cities (e.g. suburbs → city center) |
| `COUNTRY_NAMES` | Translate ISO country codes to display names |
| `GENERIC_FOLDERS` | Folder names to ignore when building location labels |
| `ENABLE_QUALITY_FILTERS` | Enable/disable all quality filters (`true`/`false`) |
| `FILTER_MIN_WIDTH` / `FILTER_MIN_HEIGHT` | Minimum image dimensions (e.g. `800` x `600`) |
| `FILTER_ALLOW_PORTRAIT` | Allow or reject portrait-orientation photos |
| `FILTER_MAX_ASPECT_RATIO` | Reject extreme panoramas (e.g. `2.2`) |
| `FILTER_MIN_SHARPNESS` | Blur threshold (Laplacian variance). Higher = stricter (e.g. `300`) |
| `FILTER_FORBIDDEN_KEYWORDS` | Reject files whose name contains these strings (e.g. `screenshot`, `whatsapp`) |
| `FILTER_REJECT_DOCUMENTS` | Reject images that look like documents (OCR-based) |
| `FILTER_REQUIRE_EXIF` | Only accept photos with valid EXIF data |
| `FILTER_OCR_MAX_WORDS` | Max number of detected words before rejection |
| `FILTER_OCR_MAX_CHARS` | Max number of detected characters before rejection |
| `FILTER_OCR_MIN_CONFIDENCE` | Minimum OCR confidence to count a word |

### Background Hourly Execution (Windows Task Scheduler)
To automatically update your photos/videos every hour, but **only if your Bartop is turned on and connected**:
1. Open PowerShell as **Administrator**.
2. Run the creation script:
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force
   .\create_task.ps1
   ```
This registers a task named `BartopPhotoSelector` in your Windows Task Scheduler.
- **Silent operation**: Executes via [run_silent.vbs](run_silent.vbs) to prevent command prompt windows from flashing.
- **Smart detection**: [index.js](index.js) automatically tests connection with the Bartop's network name (TCP port 445) before running. If the Bartop is off, the script exits immediately (within 2 seconds).

To remove the scheduled task:
```powershell
Unregister-ScheduledTask -TaskName "BartopPhotoSelector" -Confirm:$false
```

### Optional Interactive Web Dashboard (PC)
A local web interface to monitor and control the selector. Features:
- View **selected photos** with sharpness scores and metadata labels.
- View **rejected photos** with the reason for rejection (blurry, bad size, portrait, text detected, etc.).
- View **personal videos** selected for transfer.
- See what is **currently displayed on the Bartop** (photo/video name, metadata).
- Edit `config.json` parameters directly from the browser.
- Trigger a new selection run and watch **real-time console logs** (Server-Sent Events).
- **Stop** a running selection at any time.
- **Photo previews** with HEIC/iPhone support (auto-converted on the fly, cached locally).
- **Video playback** with HTTP Range Requests (streaming).

To start the dashboard:
1. Run:
   ```bash
   node server.js
   ```
2. Open your browser at: `http://localhost:3000`
3. Stop it with `Ctrl+C` once you are done.

---

## 2. Screensaver System (RPi / Python)

A two-script system to turn your Recalbox into a photo frame when idle.

### Components
- **[idle_monitor.py](display/idle_monitor.py)**: The "brain". Monitors joysticks/buttons and stops EmulationStation when no activity is detected, then launches the slideshow. Restarts ES when the user exits.
- **[slideshow.py](display/slideshow.py)**: The "display". Shows photos and videos with animated transitions and metadata overlays.

### Slideshow Features
- **4 Display Modes** (cycled with the Mode Button):
  - `Photos` — Displays selected photos from the images folder.
  - `Vidéos` — Plays personal videos from the videos folder.
  - `Jeux` — Plays game video snaps from the Recalbox roms folder.
  - `Cycle Auto` — Rotates through all three modes automatically every 60 seconds.
- **7 Photo Display Styles** (cycled at any time with the Style Button `291`):
  - `Mix Artistique (Auto)` (`auto_art`, *default*) — Automatically alternates between all 5 artistic styles below from photo to photo.
  - `Ambilight & Duo` (`modern`) — Displays the full photo (`96% × 95%`) inside a sleek frame with drop shadow over a color-matched blurred background, and pairs vertical photos side-by-side (`Duo`).
  - `Mosaïque Bento (3 Photos)` (`bento`) — Dynamic 3-photo Bento grid collage with simultaneous smooth pan animations and individual location badges.
  - `Polaroid Vintage` (`polaroid`) — Tilted instant-film Polaroids (`rotozoom`) with warm Kodak color grading, thick cream border, ink-style captions on the bottom chin, and previous Polaroids resting on the background table.
  - `Magazine Plein Écran` (`magazine`) — 100% edge-to-edge full-screen cover (or 50/50 split-screen for portraits) with a dark bottom cinema gradient and bold XXL editorial typography.
  - `Néon Bartop (Arcade)` (`arcade`) — Synthwave purple/indigo backdrop with CRT scanlines and glowing Cyan & Magenta neon frames.
  - `Classique (Origine)` (`classic`) — Original behavior with black background, Ken Burns zoom/pan, and vertical scrolling (`scroll_v`) on portrait photos.
- **Persistent Settings**: Speed, mode, photo style (`modern`/`classic`), button IDs, and mute state are saved to `slideshow_settings.json` and restored on next launch.
- **Current state export**: Writes `current.json` at each media change (including active style and Duo photo info) so the web dashboard can display what's currently playing on the Bartop.

### Controls
| Input | Action |
|---|---|
| **Any Front Button** (Façade: Start / Select / Coin) | Exit slideshow immediately |
| **Any Top Button — 1 click** (Panel J1/J2) | Toggle **Media Details & Command Tooltips** (10s auto-close; 1 click again closes) |
| **Any Top Button — Double-click** (Panel J1/J2) | Open the **Settings Menu** (Mode, Photo Style, Video Sound, Photo Cadence; 12s auto-close) |
| **Joystick Left / Right (`◀ / ▶`)** | Outside menu: Previous / Next media (`2x` fast tap in `Cycle Auto` skips to next/previous cycle phase) • Inside menu: Change value |
| **Joystick Up / Down (`▲ / ▼`)** | Outside menu: Change **Photo Style** (when viewing a photo) or toggle **Video Sound** (when playing a video) • Inside menu: Navigate rows |

### Idle Monitor Configuration
Edit the constants at the top of [idle_monitor.py](display/idle_monitor.py):

| Variable | Description |
|---|---|
| `TIMEOUT_SECONDS` | Idle time before launching the screensaver (default: `60`) |
| `GAME_PROCESSES` | List of emulator process names that pause the idle timer |
| `SLIDESHOW_SCRIPT` | Path to `slideshow.py` on the Raspberry Pi |
| `ES_START_SCRIPT` | Path to the EmulationStation init script |

### Installation on Recalbox
1. Copy the `display` folder to `/recalbox/share/userscripts/`.
2. To start the monitor automatically on boot:
   - Edit `/recalbox/share/system/custom.sh`:
     ```bash
     python /recalbox/share/userscripts/slideshow/idle_monitor.py &
     ```
   - Ensure it's executable: `chmod +x /recalbox/share/system/custom.sh`

---

## Advanced Options

### Disable Animation
If your Raspberry Pi struggles with the Ken Burns animations, disable them by passing `--no-animation` to the slideshow call in `idle_monitor.py`:
```python
subprocess.call(["python", SLIDESHOW_SCRIPT, "--no-animation"])
```

### Slideshow Settings File
The slideshow saves its state to `/recalbox/share/userscripts/slideshow/slideshow_settings.json`. You can edit this file manually to pre-configure:
- `display_time`: Default duration per photo in seconds.
- `info_button`: Button ID for the Info/Mute action (default: `289`).
- `mode_button`: Button ID for cycling modes (default: `304`).
- `style_button`: Button ID for toggling between `modern` and `classic` photo styles (default: `291`).
- `photo_style`: Photo display style (`"modern"` or `"classic"`, default: `"modern"`).
- `current_mode`: Starting mode (`1`=Photos, `2`=Videos, `3`=Games, `4`=Cycle).
- `is_muted`: Whether audio starts muted (`true`/`false`).

---

## License
ISC
