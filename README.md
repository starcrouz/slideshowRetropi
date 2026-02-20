# SlideshowRecalbox

A multi-platform project to manage and display a high-quality photo slideshow on a Recalbox-powered Bartop.

The project consists of two parts:
1. **Photo Selector (Node.js)**: Runs on your PC to select, resize, and prepare photos.
2. **Slideshow Display (Python/Pygame)**: Runs on the Raspberry Pi (Recalbox) to display the photos with a Ken Burns animation.

---

## 1. Photo Selector (PC / Node.js)

Automatically selects, resizes, and processes photos (JPG, HEIC) from your library to keep the bartop's storage efficient and responsive.

### Features
- **Smart Selection**: Picks 100 random photos from your collection.
- **HEIC Support**: Converts iPhone photos to JPEG on-the-fly.
- **Auto-labeling**: Extracts EXIF data and reverse-geocodes locations.
- **CPU Efficient**: Sequential processing to avoid background lag.

### Usage
1. Install dependencies: `npm install`
2. Configure your paths in `config.json`.
3. Run: `node index.js`

---

## 2. Slideshow Display (RPi / Python)

A Python script designed for Recalbox (compatible with Python 2.7 and 3.x) using Pygame to display the prepared photos.

### Features
- **Ken Burns Effect**: Gentle zoom animation for a dynamic display.
- **Fade-in**: Smooth transitions between photos.
- **Metadata Overlay**: Displays the date and location extracted by the Node.js script.
- **Low Resource**: Optimized to run smoothly on older Raspberry Pi models.

### Installation on Recalbox
1. Copy the `display/slideshow.py` file to your Recalbox.
2. Ensure you have Pygame installed (standard on Recalbox).
3. Run the script:
   ```bash
   python display/slideshow.py
   ```

---

## Configuration

Edit `config.json` on your PC to set your source/destination folders and screen resolution.

## License
ISC
