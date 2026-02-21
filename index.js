const fs = require('fs');
const path = require('path');
const { Jimp } = require('jimp');
const { globSync } = require('glob');
const convert = require('heic-convert');

const config = require('./config.json');

// Augmenter la limite mémoire pour les grosses photos HEIC/iPhone 15
Jimp.maxMemoryUsageInMB = 1024;

const { getBestLocation } = require('./geo');
const { getPhotoMetadata } = require('./metadata');

async function processImage(photoPath, id, total) {
    const isHeic = photoPath.toLowerCase().endsWith('.heic');

    // 1. Get Metadata (Async with exifr)
    const meta = await getPhotoMetadata(photoPath, config);
    let locationStr = "";
    let gpsStatus = meta.gpsStatus;

    if (meta.coords) {
        const geo = getBestLocation(meta.coords.lat, meta.coords.lon, config);
        if (geo) {
            locationStr = geo.label;
            gpsStatus = geo.status;
        }
    }

    if (!locationStr) {
        locationStr = meta.folderLabel;
    }

    let finalLabel = "";
    if (locationStr && meta.dateStr) {
        finalLabel = `${meta.capitalize(locationStr)} - ${meta.dateStr}`;
    } else if (locationStr) {
        finalLabel = meta.capitalize(locationStr);
    } else if (meta.dateStr) {
        finalLabel = meta.dateStr;
    }

    console.log(`[Photo ${id}/${total}]`);
    console.log(`  Source : ${photoPath}`);
    console.log(`  Label  : ${finalLabel}`);

    try {
        let imageBuffer;
        if (isHeic) {
            const inputBuffer = fs.readFileSync(photoPath);
            imageBuffer = await convert({
                buffer: inputBuffer,
                format: 'JPEG',
                quality: 1
            });
        } else {
            imageBuffer = photoPath;
        }

        const image = await Jimp.read(imageBuffer);
        image.scaleToFit({ w: config.SCREEN_W, h: config.SCREEN_H });
        await image.write(path.join(config.DEST_DIR, `${id}.jpg`));

        const sidecarContent = [
            finalLabel,
            meta.fullDateStr || meta.dateStr,
            meta.rawPath
        ].join('\n');

        fs.writeFileSync(path.join(config.DEST_DIR, `${id}.txt`), sidecarContent, 'utf8');
    } catch (e) {
        console.error(`  ! Erreur image : ${e.message}`);
    }
}

async function processVideos(allVideoFiles) {
    console.log(`\n--- Tirage Vidéos (Limite ${config.VIDEO_LIMIT_MB} Mo) ---`);

    if (!fs.existsSync(config.VIDEO_DEST_DIR)) {
        fs.mkdirSync(config.VIDEO_DEST_DIR, { recursive: true });
    } else {
        // Nettoyage dossier video
        const oldVids = fs.readdirSync(config.VIDEO_DEST_DIR);
        for (const f of oldVids) fs.unlinkSync(path.join(config.VIDEO_DEST_DIR, f));
    }

    const shuffled = allVideoFiles.sort(() => 0.5 - Math.random());
    let currentSizeByte = 0;
    const limitByte = config.VIDEO_LIMIT_MB * 1024 * 1024;
    let count = 0;

    for (const vidPath of shuffled) {
        const stats = fs.statSync(vidPath);
        if (currentSizeByte + stats.size <= limitByte) {
            const ext = path.extname(vidPath);
            const destName = `${(++count).toString().padStart(3, '0')}${ext}`;
            const destPath = path.join(config.VIDEO_DEST_DIR, destName);

            console.log(`[Video ${count}] ${path.basename(vidPath)} (${(stats.size / 1024 / 1024).toFixed(1)} Mo)`);
            fs.copyFileSync(vidPath, destPath);
            currentSizeByte += stats.size;
        }
        if (currentSizeByte >= limitByte) break;
    }
    console.log(`Total Vidéos : ${count} (${(currentSizeByte / 1024 / 1024).toFixed(1)} Mo)`);
}

async function start() {
    console.log("--- Lancement du tirage intelligent ---");

    if (!fs.existsSync(config.DEST_DIR)) {
        console.error(`Erreur : Destination Photos inaccessible : ${config.DEST_DIR}`);
        return;
    }

    // 1. Photos
    const photoPattern = config.SOURCE_DIR.replace(/\\/g, '/') + '/**/*.{jpg,JPG,jpeg,JPEG,heic,HEIC}';
    const allPhotos = globSync(photoPattern);
    console.log(`Photos trouvées : ${allPhotos.length}`);

    if (allPhotos.length > 0) {
        const selection = allPhotos.sort(() => 0.5 - Math.random()).slice(0, config.NB_IMAGES);
        for (let i = 0; i < selection.length; i++) {
            const id = (i + 1).toString().padStart(3, '0');
            await processImage(selection[i], id, selection.length);
        }
    }

    // 2. Vidéos
    const videoPattern = config.SOURCE_DIR.replace(/\\/g, '/') + '/**/*.{mp4,MP4,mkv,MKV,avi,AVI,mov,MOV}';
    const allVideos = globSync(videoPattern);
    console.log(`Vidéos trouvées : ${allVideos.length}`);

    if (allVideos.length > 0) {
        await processVideos(allVideos);
    }

    console.log("\n--- Terminé ! ---");
}

start();