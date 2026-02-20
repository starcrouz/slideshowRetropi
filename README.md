# Bartop Slideshow Photo Selector

A Node.js script that automatically selects, resizes, and processes photos (including HEIC) for a Bartop Raspberry Pi slideshow. 

This project is designed to run periodically (e.g., hourly) to refresh the selection of photos shown on a Recalbox/Raspberry Pi screensaver.

## Features

- **Smart Selection**: Picks 100 random photos from a large collection.
- **HEIC Support**: Automatically handle and convert iPhone (HEIC) photos to JPEG.
- **Auto-labeling**:
  - Extracts EXIF data (Date and GPS) when available.
  - Reverse-geocodes GPS coordinates to city names.
  - Fallbacks to folder names (excluding generic names like "DCIM", "Apple", etc.) to extract meaningful descriptions and dates.
- **CPU Efficient**: Processes images sequentially to maintain system performance on the host PC.
- **Optimized for Bartop**: Resizes images to a configurable resolution (default 1280x1024) to reduce the processing load on the Raspberry Pi.

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/starcrouz/slideshowBartopNodeJS.git
   cd slideshowBartopNodeJS
   ```
2. Install dependencies:
   ```bash
   npm install
   ```

## Configuration

Edit [config.json](config.json) to match your setup:

- `SOURCE_DIR`: Path to your photo library (e.g., Google Drive sync folder).
- `DEST_DIR`: Path to the Bartop's network share or local folder.
- `NB_IMAGES`: Number of photos to pick (default 100).
- `SCREEN_W` / `SCREEN_H`: Target resolution for the images.
- `CITY_OVERRIDES`: Manual map for specific city names.

## Usage

Simply run:
```bash
node index.js
```

The script will:
1. Scan for `.jpg` and `.heic` files in the source directory.
2. Select 100 random files.
3. Process each one: extract metadata, resize, and save to the destination.
4. Generate a `.txt` file for each photo containing its label (e.g., "Paris - May 2023").

## License

ISC
