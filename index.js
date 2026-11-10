const fs = require('fs');
const path = require('path');
const { Jimp } = require('jimp');
const { globSync } = require('glob');
const convert = require('heic-convert');
const { execSync, execFileSync } = require('child_process');
const net = require('net');
const crypto = require('crypto');
const { createWorker } = require('tesseract.js');

const config = require('./config.json');

// Augmenter la limite mémoire pour les grosses photos HEIC/iPhone 15
Jimp.maxMemoryUsageInMB = 2048;

const lockFilePath = path.join(__dirname, 'selection.lock');

function acquireLock() {
    if (fs.existsSync(lockFilePath)) {
        try {
            const pidStr = fs.readFileSync(lockFilePath, 'utf8').trim();
            const pid = parseInt(pidStr, 10);
            if (!isNaN(pid)) {
                try {
                    process.kill(pid, 0);
                    console.error(`[ERREUR] Un autre tirage est déjà en cours (PID: ${pid}).`);
                    return false;
                } catch (e) {
                    console.log(`[INFO] Un verrou obsolète (PID: ${pid}) a été détecté et sera ignoré.`);
                }
            }
        } catch (e) {
            console.log(`[INFO] Impossible de lire le fichier de verrouillage, écriture par-dessus.`);
        }
    }
    
    try {
        fs.writeFileSync(lockFilePath, process.pid.toString(), 'utf8');
        return true;
    } catch (e) {
        console.error(`[ERREUR] Impossible de créer le fichier de verrouillage : ${e.message}`);
        return false;
    }
}

function releaseLock() {
    try {
        if (fs.existsSync(lockFilePath)) {
            const pidStr = fs.readFileSync(lockFilePath, 'utf8').trim();
            const pid = parseInt(pidStr, 10);
            if (pid === process.pid) {
                fs.unlinkSync(lockFilePath);
            }
        }
    } catch (e) {
        console.error(`[AVERTISSEMENT] Erreur lors de la suppression du fichier de verrouillage : ${e.message}`);
    }
}

// Nettoyage automatique à la sortie du processus
process.on('exit', () => {
    releaseLock();
});
process.on('SIGINT', () => {
    process.exit(2);
});
process.on('SIGTERM', () => {
    process.exit(2);
});

const { getBestLocation, getDistance } = require('./geo');
const { getPhotoMetadata, getBestFolderLabel, capitalize, extractDateFromPath } = require('./metadata');

function writeCommandStatus(statusObj) {
    try {
        const statusPath = path.join(path.dirname(config.DEST_DIR), 'command_status.json');
        const payload = {
            ...statusObj,
            timestamp: Date.now()
        };
        fs.writeFileSync(statusPath, JSON.stringify(payload, null, 2), 'utf8');
    } catch (e) {
        // Ignorer si partage réseau momentanément indisponible
    }
}

function getCachePath(filePath) {
    const cacheDir = path.join(__dirname, '.cache');
    if (!fs.existsSync(cacheDir)) {
        fs.mkdirSync(cacheDir, { recursive: true });
    }
    try {
        const stats = fs.statSync(filePath);
        const mtime = stats.mtimeMs;
        const hash = crypto.createHash('md5').update(`${filePath}_${mtime}`).digest('hex');
        return path.join(cacheDir, `${hash}.jpg`);
    } catch (e) {
        const hash = crypto.createHash('md5').update(filePath).digest('hex');
        return path.join(cacheDir, `${hash}.jpg`);
    }
}

async function loadImage(photoPath) {
    const isHeic = photoPath.toLowerCase().endsWith('.heic');
    let imageBuffer;
    if (isHeic) {
        const inputBuffer = fs.readFileSync(photoPath);
        imageBuffer = await convert({
            buffer: inputBuffer,
            format: 'JPEG',
            quality: 1
        });
    } else {
        imageBuffer = fs.readFileSync(photoPath);
    }
    return await Jimp.fromBuffer(imageBuffer, {
        'image/jpeg': {
            maxMemoryUsageInMB: 2048
        }
    });
}

function calculateSharpness(image) {
    try {
        // Redimensionne à 512x512 et convertit en niveaux de gris pour une analyse fidèle du flou
        const gray = image.clone().resize({ w: 512, h: 512 }).greyscale();
        const { data, width, height } = gray.bitmap;
        const laps = [];
        
        for (let y = 1; y < height - 1; y++) {
            for (let x = 1; x < width - 1; x++) {
                const idx = (y * width + x) * 4;
                const val = data[idx];
                const valLeft = data[((y) * width + (x - 1)) * 4];
                const valRight = data[((y) * width + (x + 1)) * 4];
                const valUp = data[((y - 1) * width + (x)) * 4];
                const valDown = data[((y + 1) * width + (x)) * 4];
                
                // Noyau Laplacien 3x3 simple
                const lap = valLeft + valRight + valUp + valDown - 4 * val;
                laps.push(lap);
            }
        }
        
        const mean = laps.reduce((a, b) => a + b, 0) / laps.length;
        const variance = laps.reduce((a, b) => a + (b - mean) ** 2, 0) / laps.length;
        return variance;
    } catch (e) {
        return 999; // Fallback en cas d'erreur
    }
}

function computeImageLabel(meta) {
    if (!meta) return "";
    let locationStr = "";
    if (meta.coords) {
        const geo = getBestLocation(meta.coords.lat, meta.coords.lon, config);
        if (geo) {
            locationStr = geo.label;
        }
    }
    if (!locationStr) {
        locationStr = meta.folderLabel;
    }
    let finalLabel = "";
    if (locationStr && meta.dateStr) {
        finalLabel = `${capitalize(locationStr)} - ${meta.dateStr}`;
    } else if (locationStr) {
        finalLabel = capitalize(locationStr);
    } else if (meta.dateStr) {
        finalLabel = meta.dateStr;
    }
    return finalLabel;
}

let tesseractWorker = null;

async function getTesseractWorker() {
    if (!tesseractWorker) {
        tesseractWorker = await createWorker('fra+eng');
    }
    return tesseractWorker;
}

async function terminateTesseractWorker() {
    if (tesseractWorker) {
        await tesseractWorker.terminate();
        tesseractWorker = null;
    }
}

async function detectText(image) {
    try {
        // Redimensionner pour l'OCR rapide (max 800px)
        const resized = image.clone().scaleToFit({ w: 800, h: 800 });
        const buffer = await resized.getBuffer('image/jpeg', { quality: 85 });
        const worker = await getTesseractWorker();
        const { data: ocrData } = await worker.recognize(buffer, {}, { blocks: true });
        
        const words = [];
        if (ocrData && ocrData.blocks) {
            for (const block of ocrData.blocks) {
                if (block.paragraphs) {
                    for (const para of block.paragraphs) {
                        if (para.lines) {
                            for (const line of para.lines) {
                                if (line.words) {
                                    for (const word of line.words) {
                                        words.push(word);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        return {
            text: ocrData.text,
            confidence: ocrData.confidence,
            words: words
        };
    } catch (err) {
        console.warn(`  [Avertissement] Échec de l'analyse OCR : ${err.message}`);
        return null;
    }
}

function validateMetadata(filePath, meta) {
    // 0. Mots-clés exclus (exclut les captures d'écran, etc.)
    if (config.FILTER_FORBIDDEN_KEYWORDS && config.FILTER_FORBIDDEN_KEYWORDS.length > 0) {
        const pathLower = filePath.toLowerCase();
        for (const kw of config.FILTER_FORBIDDEN_KEYWORDS) {
            if (pathLower.includes(kw.toLowerCase())) {
                return { valid: false, reason: `Chemin/Nom de fichier contient le mot-clé exclu '${kw}'` };
            }
        }
    }

    // 0b. Exclure les images sans EXIF si configuré
    if (config.FILTER_REQUIRE_EXIF && meta && !meta.hasExif) {
        return { valid: false, reason: "Aucune métadonnée EXIF trouvée (capture d'écran ou téléchargement probable)" };
    }

    // 1. Résolution et orientation si les dimensions EXIF sont disponibles
    if (config.ENABLE_QUALITY_FILTERS && meta && typeof meta.width === 'number' && typeof meta.height === 'number') {
        const width = meta.width;
        const height = meta.height;

        // Si rotation de 90 ou 270 degrés, les dimensions affichées sont inversées
        const isRotated = meta.rotationDeg === 90 || meta.rotationDeg === 270;
        const displayWidth = isRotated ? height : width;
        const displayHeight = isRotated ? width : height;

        // Résolution minimale
        if (displayWidth < config.FILTER_MIN_WIDTH || displayHeight < config.FILTER_MIN_HEIGHT) {
            return { valid: false, reason: `Résolution insuffisante (${displayWidth}x${displayHeight} < ${config.FILTER_MIN_WIDTH}x${config.FILTER_MIN_HEIGHT})` };
        }

        // Format portrait
        const isPortrait = displayHeight > displayWidth;
        if (isPortrait && !config.FILTER_ALLOW_PORTRAIT) {
            return { valid: false, reason: "Format portrait exclu par la configuration" };
        }

        // Ratio d'aspect maximum
        const ratio = displayWidth / displayHeight;
        const maxRatio = config.FILTER_MAX_ASPECT_RATIO;
        if (ratio > maxRatio || (1 / ratio) > maxRatio) {
            return { valid: false, reason: `Ratio d'aspect trop extrême (${ratio.toFixed(2)} > ${maxRatio})` };
        }
    }

    return { valid: true };
}

function validateImageQuality(image, filePath, meta) {
    if (!config.ENABLE_QUALITY_FILTERS) return { valid: true };

    const width = image.bitmap.width;
    const height = image.bitmap.height;

    // 0. Mots-clés exclus (exclut les captures d'écran, etc.)
    if (config.FILTER_FORBIDDEN_KEYWORDS && config.FILTER_FORBIDDEN_KEYWORDS.length > 0) {
        const pathLower = filePath.toLowerCase();
        for (const kw of config.FILTER_FORBIDDEN_KEYWORDS) {
            if (pathLower.includes(kw.toLowerCase())) {
                return { valid: false, reason: `Chemin/Nom de fichier contient le mot-clé exclu '${kw}'` };
            }
        }
    }

    // 0b. Exclure les images sans EXIF si configuré
    if (config.FILTER_REQUIRE_EXIF && meta && !meta.hasExif) {
        return { valid: false, reason: "Aucune métadonnée EXIF trouvée (capture d'écran ou téléchargement probable)" };
    }

    // 1. Résolution minimale
    if (width < config.FILTER_MIN_WIDTH || height < config.FILTER_MIN_HEIGHT) {
        return { valid: false, reason: `Résolution insuffisante (${width}x${height} < ${config.FILTER_MIN_WIDTH}x${config.FILTER_MIN_HEIGHT})` };
    }

    // 2. Format portrait
    const isPortrait = height > width;
    if (isPortrait && !config.FILTER_ALLOW_PORTRAIT) {
        return { valid: false, reason: "Format portrait exclu par la configuration" };
    }

    // 3. Ratio d'aspect maximum (exclut les panoramas extrêmes)
    const ratio = width / height;
    const maxRatio = config.FILTER_MAX_ASPECT_RATIO;
    if (ratio > maxRatio || (1 / ratio) > maxRatio) {
        return { valid: false, reason: `Ratio d'aspect trop extrême (${ratio.toFixed(2)} > ${maxRatio})` };
    }

    // 4. Netteté (Variance de Laplacien)
    const sharpness = calculateSharpness(image);
    if (sharpness < config.FILTER_MIN_SHARPNESS) {
        return { valid: false, reason: `Image trop floue ou plate (Netteté: ${Math.round(sharpness)} < ${config.FILTER_MIN_SHARPNESS})` };
    }

    return { valid: true, sharpness };
}

function getHostFromPath(p) {
    if (!p) return null;
    // Gère les chemins UNC Windows comme \\RECALBOX\share\images ou //RECALBOX/share/images
    if (p.startsWith('\\\\')) {
        const parts = p.slice(2).split('\\');
        return parts[0];
    }
    if (p.startsWith('//')) {
        const parts = p.slice(2).split('/');
        return parts[0];
    }
    return null;
}

function isHostOnline(host, port = 445, timeout = 2000) {
    return new Promise((resolve) => {
        const socket = new net.Socket();
        let resolved = false;

        socket.setTimeout(timeout);

        socket.connect(port, host, () => {
            resolved = true;
            socket.destroy();
            resolve(true);
        });

        socket.on('error', () => {
            if (!resolved) {
                resolved = true;
                socket.destroy();
                resolve(false);
            }
        });

        socket.on('timeout', () => {
            if (!resolved) {
                resolved = true;
                socket.destroy();
                resolve(false);
            }
        });
    });
}

function probeVideo(filePath) {
    try {
        const output = execFileSync(
            'ffprobe',
            [
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,pix_fmt,duration:format=duration:format_tags=creation_time',
                '-of', 'json',
                filePath
            ],
            { stdio: ['ignore', 'pipe', 'ignore'], timeout: 15000 }
        ).toString().trim();

        const data = JSON.parse(output);
        if (!data || !Array.isArray(data.streams) || data.streams.length === 0) {
            return { valid: false, reason: "Aucun flux vidéo détecté" };
        }

        const stream = data.streams[0];
        const rawDuration = (data.format && data.format.duration) ? data.format.duration : stream.duration;
        const durationSec = parseFloat(rawDuration);

        if (isNaN(durationSec) || durationSec <= 0) {
            return { valid: false, reason: "Durée invalide ou fichier corrompu" };
        }

        const mins = Math.floor(durationSec / 60);
        const secs = Math.round(durationSec % 60);
        const durationStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

        let creationTimestampMs = null;
        if (data.format && data.format.tags && data.format.tags.creation_time) {
            const parsed = new Date(data.format.tags.creation_time);
            if (!isNaN(parsed.getTime())) {
                creationTimestampMs = parsed.getTime();
            }
        }

        return {
            valid: true,
            durationSec,
            durationStr,
            creationTimestampMs,
            codec: stream.codec_name || "inconnu",
            width: stream.width || 0,
            height: stream.height || 0,
            pixFmt: stream.pix_fmt || "inconnu"
        };
    } catch (e) {
        return { valid: false, reason: "Fichier corrompu ou illisible par ffprobe" };
    }
}

function convertVideoForBartop(inputPath, outputPath, maxPlaySec = 30) {
    const maxW = config.SCREEN_W || 1280;
    const maxH = config.SCREEN_H || 1024;
    // Redimensionne sans dépasser l'écran, force des dimensions paires, 30 fps constants et format 8-bit yuv420p (requis par omxplayer RPi)
    const vf = `scale='min(${maxW},iw)':'min(${maxH},ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30,format=yuv420p`;

    const args = [
        '-y',
        '-v', 'error'
    ];
    if (typeof maxPlaySec === 'number' && maxPlaySec > 0) {
        args.push('-t', String(maxPlaySec));
    }
    args.push(
        '-i', inputPath,
        '-map', '0:v:0',
        '-map', '0:a:0?',
        '-dn',
        '-sn',
        '-vf', vf,
        '-c:v', 'libx264',
        '-profile:v', 'high',
        '-level:v', '4.1',
        '-preset', 'veryfast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ac', '2',
        '-ar', '44100',
        '-movflags', '+faststart',
        outputPath
    );

    execFileSync(
        'ffmpeg',
        args,
        { stdio: ['ignore', 'ignore', 'pipe'], timeout: 180000 }
    );

    if (!fs.existsSync(outputPath) || fs.statSync(outputPath).size < 1024) {
        throw new Error("Fichier MP4 converti vide ou invalide");
    }
}

async function processImage(photoPath, image, id, total, checkResult, meta) {
    const finalMeta = meta || await getPhotoMetadata(photoPath, config);
    const finalLabel = computeImageLabel(finalMeta);

    const sharpnessInfo = checkResult && checkResult.sharpness ? ` [Netteté: ${Math.round(checkResult.sharpness)}]` : "";
    console.log(`[Photo ${id}/${total}]${sharpnessInfo}`);
    console.log(`  Source : ${photoPath}`);
    console.log(`  Label  : ${finalLabel}`);

    try {
        const isPortrait = image.bitmap.height > image.bitmap.width;
        const maxW = config.SCREEN_W;
        const maxH = isPortrait ? Math.max(config.SCREEN_W, config.SCREEN_H) : config.SCREEN_H;
        image.scaleToFit({ w: maxW, h: maxH });
        await image.write(path.join(config.DEST_DIR, `${id}.jpg`));

        // Écrire également dans le cache local du PC pour un affichage Web instantané
        try {
            const cachePath = getCachePath(photoPath);
            const cacheImage = image.clone().scaleToFit({ w: 1000, h: 1000 });
            await cacheImage.write(cachePath);
        } catch (cacheErr) {
            // Ignorer les erreurs d'écriture de cache
        }

        const sidecarContent = [
            finalLabel,
            finalMeta.fullDateStr || finalMeta.dateStr,
            photoPath // On utilise le chemin absolu du PC pour le diagnostic
        ].join('\n');

        fs.writeFileSync(path.join(config.DEST_DIR, `${id}.txt`), sidecarContent, 'utf8');
        return finalLabel;
    } catch (e) {
        console.error(`  ! Erreur image : ${e.message}`);
        return null;
    }
}

async function processVideos(allVideoFiles, onProgress) {
    const minDurationSec = typeof config.VIDEO_MIN_DURATION_SEC === 'number' ? config.VIDEO_MIN_DURATION_SEC : 4;
    const maxPlaySec = typeof config.VIDEO_MAX_PLAY_SEC === 'number' ? config.VIDEO_MAX_PLAY_SEC : 30;
    const maxDurationSec = 180; // Max 3 minutes par vidéo source pour éviter les longs films
    console.log(`\n--- Tirage & Conversion Vidéos (Limite ${config.VIDEO_LIMIT_MB} Mo, durée min ${minDurationSec}s, coupées à ${maxPlaySec}s max) ---`);

    if (!fs.existsSync(config.VIDEO_DEST_DIR)) {
        fs.mkdirSync(config.VIDEO_DEST_DIR, { recursive: true });
    }

    const cacheDir = path.join(__dirname, '.cache');
    if (!fs.existsSync(cacheDir)) {
        fs.mkdirSync(cacheDir, { recursive: true });
    }
    const tempMp4Path = path.join(cacheDir, `tmp_bartop_vid_${process.pid}.mp4`);

    const filteredFiles = allVideoFiles.filter(v => {
        try {
            if (config.ENABLE_QUALITY_FILTERS && Array.isArray(config.FILTER_FORBIDDEN_KEYWORDS)) {
                const lower = v.toLowerCase();
                for (const kw of config.FILTER_FORBIDDEN_KEYWORDS) {
                    if (lower.includes(kw.toLowerCase())) return false;
                }
            }
            const stats = fs.statSync(v);
            // Au moins 500 Ko et max 500 Mo en source (une vidéo 4K iPhone de 200 Mo fera ~15 Mo après conversion H.264)
            return stats.size >= 512 * 1024 && stats.size <= 500 * 1024 * 1024;
        } catch (e) {
            return false;
        }
    });

    const shuffled = filteredFiles.sort(() => 0.5 - Math.random());
    let currentSizeByte = 0;
    const limitByte = config.VIDEO_LIMIT_MB * 1024 * 1024;
    let count = 0;
    let oversizeSkips = 0;
    const selectedVideosResult = [];

    try {
        for (const vidPath of shuffled) {
            if (limitByte - currentSizeByte < 1 * 1024 * 1024) break;

            const probe = probeVideo(vidPath);
            if (!probe.valid) {
                console.log(`  [Vidéo écartée] ${path.basename(vidPath)} : ${probe.reason}`);
                continue;
            }

            if (probe.durationSec < minDurationSec) {
                console.log(`  [Vidéo écartée] ${path.basename(vidPath)} : Trop courte (${probe.durationSec.toFixed(1)}s < ${minDurationSec}s, Live Photo probable)`);
                continue;
            }

            if (probe.durationSec > maxDurationSec) {
                console.log(`  [Vidéo écartée] ${path.basename(vidPath)} : Trop longue (${probe.durationStr} > 3m)`);
                continue;
            }

            const srcStats = fs.statSync(vidPath);
            const isTrimmed = probe.durationSec > maxPlaySec;
            const finalDurationStr = isTrimmed ? `${maxPlaySec}s` : probe.durationStr;
            const trimNote = isTrimmed ? ` -> coupée à ${maxPlaySec}s` : '';
            console.log(`  [Conversion] ${path.basename(vidPath)} (${probe.codec.toUpperCase()} ${probe.width}x${probe.height}, ${probe.durationStr}${trimNote}, ${(srcStats.size / 1024 / 1024).toFixed(1)} Mo) -> MP4 H.264...`);

            try {
                convertVideoForBartop(vidPath, tempMp4Path, maxPlaySec);
            } catch (convErr) {
                console.log(`  [Vidéo écartée] Échec conversion FFmpeg pour ${path.basename(vidPath)} : ${convErr.message}`);
                continue;
            }

            const convStats = fs.statSync(tempMp4Path);
            if (currentSizeByte + convStats.size > limitByte) {
                try { fs.unlinkSync(tempMp4Path); } catch (e) {}
                oversizeSkips++;
                console.log(`  [Quota] ${path.basename(vidPath)} (${(convStats.size / 1024 / 1024).toFixed(1)} Mo convertie) dépasse l'espace restant (${((limitByte - currentSizeByte) / 1024 / 1024).toFixed(1)} Mo).`);
                if (oversizeSkips >= 3 || (limitByte - currentSizeByte) < 3 * 1024 * 1024) {
                    break;
                }
                continue;
            }

            oversizeSkips = 0;
            let writtenId = null;
            let destName = "";
            let destPath = "";

            // Trouver le premier index disponible non verrouillé sur le partage SMB du Bartop
            for (let attempt = 0; attempt < 20; attempt++) {
                const candidateId = (++count).toString().padStart(3, '0');
                const candidateName = `${candidateId}.mp4`;
                const candidatePath = path.join(config.VIDEO_DEST_DIR, candidateName);

                try {
                    const oldFiles = fs.readdirSync(config.VIDEO_DEST_DIR);
                    for (const f of oldFiles) {
                        if (f.startsWith(candidateId + '.')) {
                            try { fs.unlinkSync(path.join(config.VIDEO_DEST_DIR, f)); } catch (e) {}
                        }
                    }
                } catch (err) {}

                try {
                    fs.writeFileSync(candidatePath, fs.readFileSync(tempMp4Path));
                    writtenId = candidateId;
                    destName = candidateName;
                    destPath = candidatePath;
                    break;
                } catch (writeErr) {
                    console.warn(`  [Info] Emplacement ${candidateName} verrouillé sur le réseau (${writeErr.code || writeErr.message}), essai de l'emplacement suivant...`);
                }
            }

            if (!writtenId) {
                try { fs.unlinkSync(tempMp4Path); } catch (e) {}
                console.warn(`  [Avertissement] Impossible d'écrire la vidéo sur le Bartop après plusieurs tentatives.`);
                break;
            }

            const id = writtenId;
            try {
                fs.copyFileSync(tempMp4Path, path.join(cacheDir, `video_${id}.mp4`));
            } catch (e) {}
            try { fs.unlinkSync(tempMp4Path); } catch (e) {}

            // Extraction Metadata Vidéo
            const label = getBestFolderLabel(vidPath, config);
            const date = extractDateFromPath(vidPath, config);
            const duration = finalDurationStr;

            let finalLabel = "";
            if (label && date) finalLabel = `${capitalize(label)} - ${date}`;
            else if (label) finalLabel = capitalize(label);
            else if (date) finalLabel = date;

            const sidecarContent = [
                finalLabel || "Vidéo Perso",
                duration || "Durée inconnue",
                vidPath // Chemin PC original
            ].join('\n');

            try {
                fs.writeFileSync(path.join(config.VIDEO_DEST_DIR, `${id}.txt`), sidecarContent, 'utf8');
            } catch (e) {}
            currentSizeByte += convStats.size;

            const sizeMb = parseFloat((convStats.size / 1024 / 1024).toFixed(1));
            console.log(`[Video ${id}] ${path.basename(vidPath)} -> ${destName} (${sizeMb} Mo, ${duration})`);

            selectedVideosResult.push({
                path: vidPath,
                label: finalLabel || "Vidéo Perso",
                duration: duration || "Durée inconnue",
                sizeMb: sizeMb,
                id: id,
                filename: path.basename(vidPath)
            });

            if (typeof onProgress === 'function') {
                onProgress(selectedVideosResult);
            }

            if (currentSizeByte >= limitByte) break;
        }
    } finally {
        try {
            if (fs.existsSync(tempMp4Path)) {
                fs.unlinkSync(tempMp4Path);
            }
        } catch (e) {}
    }

    // Nettoyage des anciennes vidéos en trop
    try {
        const oldFiles = fs.readdirSync(config.VIDEO_DEST_DIR);
        for (const f of oldFiles) {
            const match = f.match(/^(\d+)\./);
            if (match) {
                const fileIndex = parseInt(match[1], 10);
                if (fileIndex > count) {
                    try { fs.unlinkSync(path.join(config.VIDEO_DEST_DIR, f)); } catch (e) {}
                }
            }
        }
    } catch (err) {
        console.warn(`Attention : Impossible de nettoyer les fichiers vidéos superflus : ${err.message}`);
    }

    console.log(`Total Vidéos : ${count} (${(currentSizeByte / 1024 / 1024).toFixed(1)} Mo)`);
    return selectedVideosResult;
}

function extractSeqNumber(filePath) {
    const base = path.basename(filePath, path.extname(filePath));
    // Exclure les formats date pure YYYYMMDD_HHMMSS
    if (/^\d{8}[_-]\d{6}/.test(base)) {
        return null;
    }
    const matches = base.match(/(\d{3,6})/g);
    if (!matches || matches.length === 0) return null;
    return parseInt(matches[matches.length - 1], 10);
}

function extractTimestampFromFilename(filePath) {
    const base = path.basename(filePath, path.extname(filePath));
    // Format YYYYMMDD_HHMMSS ou IMG_YYYYMMDD_HHMMSS
    const m1 = base.match(/((?:19|20)\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})/);
    if (m1) {
        const d = new Date(
            parseInt(m1[1], 10),
            parseInt(m1[2], 10) - 1,
            parseInt(m1[3], 10),
            parseInt(m1[4], 10),
            parseInt(m1[5], 10),
            parseInt(m1[6], 10)
        );
        if (!isNaN(d.getTime())) return d.getTime();
    }
    // Format YYYY-MM-DD HH.MM.SS ou similaire
    const m2 = base.match(/((?:19|20)\d{2})[-.](\d{2})[-.](\d{2})[\s_-]+(\d{2})[.:-](\d{2})[.:-](\d{2})/);
    if (m2) {
        const d = new Date(
            parseInt(m2[1], 10),
            parseInt(m2[2], 10) - 1,
            parseInt(m2[3], 10),
            parseInt(m2[4], 10),
            parseInt(m2[5], 10),
            parseInt(m2[6], 10)
        );
        if (!isNaN(d.getTime())) return d.getTime();
    }
    return null;
}

function isCatchAllDumpFolder(folderPath, totalFilesCount) {
    const folderName = path.basename(folderPath).toLowerCase();
    const dumpRegex = /(iphone|ipad|android|samsung|pixel|huawei|xiaomi|ann[eé]e|dcim|camera|appareil|pellicule|export|vrac|carte|backup|sauvegarde|toutes|divers|tri\b)/i;
    if (dumpRegex.test(folderName)) return true;
    if (/^(photos?|images?|videos?|m[eé]dias?)(\s|$|[-_])/i.test(folderName)) return true;
    if (totalFilesCount > 120) return true;
    return false;
}

async function runFocusMoment(targetSourcePath, cmdId = null) {
    const effectiveCmdId = cmdId || `focus_${Date.now()}`;
    console.log(`\n=== [Focus Moment] Cible : ${targetSourcePath} (cmdId: ${effectiveCmdId}) ===`);

    if (!acquireLock()) {
        writeCommandStatus({
            id: effectiveCmdId,
            action: 'focus',
            state: 'error',
            ready: false,
            message: 'Un tirage PC est deja en cours, patientez...'
        });
        return;
    }

    try {
        if (!targetSourcePath || !fs.existsSync(targetSourcePath)) {
            console.error(`[Focus Moment] Fichier source introuvable : ${targetSourcePath}`);
            writeCommandStatus({
                id: effectiveCmdId,
                action: 'focus',
                state: 'error',
                ready: false,
                message: 'Fichier original introuvable sur le PC'
            });
            return;
        }

        const parentDir = path.dirname(targetSourcePath);
        const photoExts = new Set(['.jpg', '.jpeg', '.heic']);
        const videoExts = new Set(['.mp4', '.mov', '.avi', '.mkv']);
        const targetExt = path.extname(targetSourcePath).toLowerCase();
        const isTargetPhoto = photoExts.has(targetExt);
        const isTargetVideo = videoExts.has(targetExt);

        writeCommandStatus({
            id: effectiveCmdId,
            action: 'focus',
            state: 'searching',
            ready: false,
            message: 'Recherche des photos et videos de ce moment...'
        });

        // 1. Extraire l'empreinte spatio-temporelle du média cible
        let targetTimestampMs = extractTimestampFromFilename(targetSourcePath);
        let targetCoords = null;
        let momentLabel = '';
        let targetMeta = null;
        let targetStat = null;
        try {
            targetStat = fs.statSync(targetSourcePath);
        } catch (e) {}

        if (isTargetPhoto) {
            targetMeta = await getPhotoMetadata(targetSourcePath, config);
            if (targetMeta) {
                if (targetMeta.timestampMs) targetTimestampMs = targetMeta.timestampMs;
                if (targetMeta.coords) targetCoords = targetMeta.coords;
                momentLabel = computeImageLabel(targetMeta);
            }
        } else if (isTargetVideo) {
            const vProbe = probeVideo(targetSourcePath);
            if (vProbe && vProbe.creationTimestampMs) {
                targetTimestampMs = vProbe.creationTimestampMs;
            }
            const fl = getBestFolderLabel(targetSourcePath, config);
            const dt = extractDateFromPath(targetSourcePath, config);
            if (fl && dt) momentLabel = `${capitalize(fl)} - ${dt}`;
            else if (fl) momentLabel = capitalize(fl);
            else if (dt) momentLabel = dt;
        }

        if (!momentLabel) {
            momentLabel = getBestFolderLabel(targetSourcePath, config) || extractDateFromPath(targetSourcePath, config) || 'Ce moment';
        }

        const targetSeq = extractSeqNumber(targetSourcePath);
        const targetMtimeMs = targetStat ? targetStat.mtimeMs : Date.now();

        // 2. Lister les fichiers frères du dossier parent
        let dirEntries = [];
        try {
            dirEntries = fs.readdirSync(parentDir);
        } catch (e) {
            console.error(`[Focus Moment] Impossible de lire le dossier ${parentDir}: ${e.message}`);
        }

        const rawPhotos = [];
        const rawVideos = [];
        for (const name of dirEntries) {
            const fullP = path.join(parentDir, name);
            const ext = path.extname(name).toLowerCase();
            if (config.ENABLE_QUALITY_FILTERS && Array.isArray(config.FILTER_FORBIDDEN_KEYWORDS)) {
                const lower = fullP.toLowerCase();
                if (config.FILTER_FORBIDDEN_KEYWORDS.some(kw => lower.includes(kw.toLowerCase()))) {
                    continue;
                }
            }
            if (photoExts.has(ext)) rawPhotos.push(fullP);
            else if (videoExts.has(ext)) rawVideos.push(fullP);
        }

        const totalInFolder = rawPhotos.length + rawVideos.length;
        const isDump = isCatchAllDumpFolder(parentDir, totalInFolder);
        console.log(`[Focus Moment] Dossier "${path.basename(parentDir)}" (${rawPhotos.length} photos, ${rawVideos.length} vidéos) -> Type: ${isDump ? 'VRAC / DUMP' : 'THÉMATIQUE'}`);
        console.log(`[Focus Moment] Cible timestamp=${targetTimestampMs ? new Date(targetTimestampMs).toISOString() : 'N/A'}, seq=${targetSeq}, GPS=${targetCoords ? `${targetCoords.lat.toFixed(3)},${targetCoords.lon.toFixed(3)}` : 'N/A'}`);

        // 3. Pré-classement ultra-rapide des candidats (pour éviter de parser 5000 EXIF dans un dossier vrac iPhone)
        const scoreCandidateFast = (filePath) => {
            if (path.resolve(filePath) === path.resolve(targetSourcePath)) return -1;
            const seq = extractSeqNumber(filePath);
            const fnTs = extractTimestampFromFilename(filePath);
            let mtimeDistHours = 999999;
            try {
                const st = fs.statSync(filePath);
                const refTs = targetTimestampMs || targetMtimeMs;
                mtimeDistHours = Math.abs(st.mtimeMs - refTs) / (3600 * 1000);
            } catch (e) {}

            let score = 100000;
            if (targetTimestampMs && fnTs) {
                score = Math.abs(fnTs - targetTimestampMs) / (60 * 1000); // minutes d'écart
            } else if (targetSeq !== null && seq !== null) {
                score = Math.abs(seq - targetSeq) * 2; // proximité numéro IMG_xxxx
            } else {
                score = mtimeDistHours * 10;
            }
            return score;
        };

        const preRankedPhotos = rawPhotos
            .map(p => ({ path: p, fastScore: scoreCandidateFast(p) }))
            .sort((a, b) => a.fastScore - b.fastScore)
            .slice(0, isDump ? 140 : 200);

        const preRankedVideos = rawVideos
            .map(v => ({ path: v, fastScore: scoreCandidateFast(v) }))
            .sort((a, b) => a.fastScore - b.fastScore)
            .slice(0, isDump ? 20 : 30);

        // 4. Analyse EXIF des meilleures photos candidates
        const tier1Photos = []; // Même moment / journée (<= 36h ou GPS proche <= 72h)
        const tier2Photos = []; // Même week-end / séjour (<= 96h ou GPS proche <= 10j)
        const tier3Photos = []; // Même dossier thématique ou séquence très proche
        let targetCandidateObj = null;

        for (const cand of preRankedPhotos) {
            const isSelf = path.resolve(cand.path) === path.resolve(targetSourcePath);
            const meta = (isSelf && targetMeta) ? targetMeta : await getPhotoMetadata(cand.path, config);
            const candTs = (meta && meta.timestampMs) || extractTimestampFromFilename(cand.path);
            const candCoords = meta ? meta.coords : null;
            const candSeq = extractSeqNumber(cand.path);

            let diffHours = null;
            if (targetTimestampMs && candTs) {
                diffHours = Math.abs(candTs - targetTimestampMs) / (3600 * 1000);
            }

            let distKm = null;
            if (targetCoords && candCoords) {
                distKm = getDistance(targetCoords.lat, targetCoords.lon, candCoords.lat, candCoords.lon);
            }

            const itemObj = {
                type: 'photo',
                path: cand.path,
                meta,
                timestampMs: candTs || targetTimestampMs || targetMtimeMs,
                diffHours: diffHours !== null ? diffHours : 9999,
                distKm,
                fastScore: cand.fastScore,
                isSelf
            };

            if (isSelf) {
                targetCandidateObj = itemObj;
                continue;
            }

            if (diffHours !== null) {
                if (diffHours <= 36 || (distKm !== null && distKm <= 20 && diffHours <= 72)) {
                    tier1Photos.push(itemObj);
                } else if (diffHours <= 96 || (distKm !== null && distKm <= 25 && diffHours <= 240)) {
                    tier2Photos.push(itemObj);
                } else if (!isDump) {
                    tier3Photos.push(itemObj);
                }
            } else {
                // Pas de date EXIF disponible : on utilise la proximité de numéro de séquence ou le dossier thématique
                if (!isDump) {
                    tier3Photos.push(itemObj);
                } else if (targetSeq !== null && candSeq !== null && Math.abs(candSeq - targetSeq) <= 35) {
                    tier2Photos.push(itemObj);
                }
            }
        }

        tier1Photos.sort((a, b) => a.diffHours - b.diffHours || a.fastScore - b.fastScore);
        tier2Photos.sort((a, b) => a.diffHours - b.diffHours || a.fastScore - b.fastScore);
        tier3Photos.sort((a, b) => a.fastScore - b.fastScore);

        const MAX_FOCUS_PHOTOS = 18;
        const chosenPhotos = [];
        if (targetCandidateObj) {
            chosenPhotos.push(targetCandidateObj);
        }

        // Fonction d'échantillonnage harmonieux si une tranche contient beaucoup de photos (évite 18 rafales de la même seconde)
        const pickSpread = (arr, maxCount) => {
            if (arr.length <= maxCount) return arr;
            // Toujours garder les 4 plus proches immédiatement, puis répartir sur le reste du moment
            const immediate = arr.slice(0, Math.min(4, maxCount));
            const rest = arr.slice(immediate.length);
            const needed = maxCount - immediate.length;
            const picked = [...immediate];
            const step = rest.length / needed;
            for (let i = 0; i < needed; i++) {
                picked.push(rest[Math.min(rest.length - 1, Math.floor(i * step))]);
            }
            return picked;
        };

        const need1 = MAX_FOCUS_PHOTOS - chosenPhotos.length;
        chosenPhotos.push(...pickSpread(tier1Photos, need1));

        if (chosenPhotos.length < MAX_FOCUS_PHOTOS && tier2Photos.length > 0) {
            const need2 = MAX_FOCUS_PHOTOS - chosenPhotos.length;
            chosenPhotos.push(...pickSpread(tier2Photos, need2));
        }

        if (chosenPhotos.length < MAX_FOCUS_PHOTOS && tier3Photos.length > 0) {
            const need3 = MAX_FOCUS_PHOTOS - chosenPhotos.length;
            chosenPhotos.push(...pickSpread(tier3Photos, need3));
        }

        // 5. Sélection des vidéos associées à ce moment (max 3 vidéos)
        const chosenVideos = [];
        const MAX_FOCUS_VIDEOS = 3;
        const minDurationSec = typeof config.VIDEO_MIN_DURATION_SEC === 'number' ? config.VIDEO_MIN_DURATION_SEC : 4;

        for (const vCand of preRankedVideos) {
            if (chosenVideos.length >= MAX_FOCUS_VIDEOS) break;
            const isSelf = path.resolve(vCand.path) === path.resolve(targetSourcePath);
            try {
                const st = fs.statSync(vCand.path);
                if (!isSelf && (st.size < 512 * 1024 || st.size > 500 * 1024 * 1024)) continue;
            } catch (e) {
                continue;
            }

            const vSeq = extractSeqNumber(vCand.path);
            const fnTs = extractTimestampFromFilename(vCand.path);

            // Dans un dossier vrac, pré-filtrer avant de lancer ffprobe
            if (isDump && !isSelf) {
                const seqClose = (targetSeq !== null && vSeq !== null && Math.abs(vSeq - targetSeq) <= 45);
                const fnClose = (targetTimestampMs && fnTs && Math.abs(fnTs - targetTimestampMs) <= 72 * 3600 * 1000);
                if (!seqClose && !fnClose && vCand.fastScore > 480) {
                    continue;
                }
            }

            const probe = probeVideo(vCand.path);
            if (!probe.valid) continue;
            if (!isSelf && (probe.durationSec < minDurationSec || probe.durationSec > 180)) continue;

            const vidTs = probe.creationTimestampMs || fnTs;
            if (isDump && !isSelf && targetTimestampMs && vidTs) {
                const diffH = Math.abs(vidTs - targetTimestampMs) / (3600 * 1000);
                if (diffH > 72) continue;
            }

            chosenVideos.push({
                type: 'video',
                path: vCand.path,
                probe,
                timestampMs: vidTs || targetTimestampMs || targetMtimeMs,
                isSelf
            });
        }

        // Trier les photos (en gardant la photo cible en 1er, puis ordre chronologique pour le reste)
        const selfPhotos = chosenPhotos.filter(x => x.isSelf);
        const otherPhotos = chosenPhotos.filter(x => !x.isSelf).sort((a, b) => (a.timestampMs || 0) - (b.timestampMs || 0));
        const orderedPhotos = [...selfPhotos, ...otherPhotos];

        console.log(`[Focus Moment] Sélection finale : ${orderedPhotos.length} photos et ${chosenVideos.length} vidéos pour "${momentLabel}"`);

        // 6. Préparation du dossier /recalbox/share/userscripts/slideshow/focus
        const focusDir = path.join(path.dirname(config.DEST_DIR), 'focus');
        if (!fs.existsSync(focusDir)) {
            fs.mkdirSync(focusDir, { recursive: true });
        } else {
            try {
                for (const f of fs.readdirSync(focusDir)) {
                    try { fs.unlinkSync(path.join(focusDir, f)); } catch (e) {}
                }
            } catch (e) {}
        }

        let writtenCount = 0;
        let readySignaled = false;
        const readyThreshold = Math.min(3, Math.max(1, orderedPhotos.length));

        // Écrire d'abord toutes les photos (très rapide, ~1.5s pour les 3 premières)
        for (const item of orderedPhotos) {
            try {
                const img = await loadImage(item.path);
                const meta = item.meta || await getPhotoMetadata(item.path, config);
                const itemLabel = computeImageLabel(meta) || momentLabel;

                const isPortrait = img.bitmap.height > img.bitmap.width;
                const maxW = config.SCREEN_W || 1280;
                const maxH = isPortrait ? Math.max(config.SCREEN_W || 1280, config.SCREEN_H || 1024) : (config.SCREEN_H || 1024);
                img.scaleToFit({ w: maxW, h: maxH });

                writtenCount++;
                const id = writtenCount.toString().padStart(3, '0');
                await img.write(path.join(focusDir, `${id}.jpg`));

                const sidecarContent = [
                    itemLabel,
                    (meta && (meta.fullDateStr || meta.dateStr)) || '',
                    item.path
                ].join('\n');
                fs.writeFileSync(path.join(focusDir, `${id}.txt`), sidecarContent, 'utf8');
                console.log(`  [Focus Photo ${id}] ${path.basename(item.path)} (${itemLabel})`);

                if (!readySignaled && writtenCount >= readyThreshold) {
                    readySignaled = true;
                    writeCommandStatus({
                        id: effectiveCmdId,
                        action: 'focus',
                        state: 'ready',
                        ready: true,
                        count: writtenCount,
                        label: momentLabel,
                        message: `Moment pret : ${momentLabel}`
                    });
                }
            } catch (err) {
                console.warn(`  [Focus Ignoré] ${path.basename(item.path)} : ${err.message}`);
            }
        }

        // Convertir ensuite les vidéos du moment
        if (chosenVideos.length > 0) {
            const cacheDir = path.join(__dirname, '.cache');
            if (!fs.existsSync(cacheDir)) fs.mkdirSync(cacheDir, { recursive: true });
            const tempMp4 = path.join(cacheDir, `tmp_focus_vid_${process.pid}.mp4`);
            const maxPlaySec = typeof config.VIDEO_MAX_PLAY_SEC === 'number' ? config.VIDEO_MAX_PLAY_SEC : 30;

            for (const vItem of chosenVideos) {
                try {
                    if (!readySignaled) {
                        writeCommandStatus({
                            id: effectiveCmdId,
                            action: 'focus',
                            state: 'converting_video',
                            ready: false,
                            count: writtenCount,
                            label: momentLabel,
                            message: `Conversion video du moment (${path.basename(vItem.path)})...`
                        });
                    }
                    convertVideoForBartop(vItem.path, tempMp4, maxPlaySec);
                    writtenCount++;
                    const id = writtenCount.toString().padStart(3, '0');
                    fs.writeFileSync(path.join(focusDir, `${id}.mp4`), fs.readFileSync(tempMp4));
                    try { fs.unlinkSync(tempMp4); } catch (e) {}

                    const fl = getBestFolderLabel(vItem.path, config);
                    const dt = extractDateFromPath(vItem.path, config);
                    let vLabel = momentLabel;
                    if (fl && dt) vLabel = `${capitalize(fl)} - ${dt}`;
                    else if (fl) vLabel = capitalize(fl);

                    const isTrimmed = vItem.probe.durationSec > maxPlaySec;
                    const durStr = isTrimmed ? `${maxPlaySec}s` : vItem.probe.durationStr;

                    const sidecarContent = [
                        vLabel || 'Video du moment',
                        durStr || '',
                        vItem.path
                    ].join('\n');
                    fs.writeFileSync(path.join(focusDir, `${id}.txt`), sidecarContent, 'utf8');
                    console.log(`  [Focus Video ${id}] ${path.basename(vItem.path)} (${durStr})`);

                    if (!readySignaled) {
                        readySignaled = true;
                        writeCommandStatus({
                            id: effectiveCmdId,
                            action: 'focus',
                            state: 'ready',
                            ready: true,
                            count: writtenCount,
                            label: momentLabel,
                            message: `Moment pret : ${momentLabel}`
                        });
                    }
                } catch (vErr) {
                    console.warn(`  [Focus Vidéo Ignorée] ${path.basename(vItem.path)} : ${vErr.message}`);
                }
            }
        }

        if (writtenCount === 0) {
            writeCommandStatus({
                id: effectiveCmdId,
                action: 'focus',
                state: 'error',
                ready: false,
                count: 0,
                label: momentLabel,
                message: 'Aucun media lisible trouve pour ce moment'
            });
        } else {
            writeCommandStatus({
                id: effectiveCmdId,
                action: 'focus',
                state: 'done',
                ready: true,
                count: writtenCount,
                label: momentLabel,
                message: `Moment : ${momentLabel} (${writtenCount} medias)`
            });
        }
        console.log(`=== [Focus Moment] Terminé (${writtenCount} médias écrits dans focus/) ===\n`);
    } finally {
        releaseLock();
    }
}

async function start(options = {}) {
    const videosOnly = Boolean(options.videosOnly || process.argv.includes('--videos-only'));
    const cmdIdIdx = process.argv.indexOf('--cmd-id');
    const cmdId = options.cmdId || (cmdIdIdx !== -1 && process.argv[cmdIdIdx + 1] ? process.argv[cmdIdIdx + 1] : null);

    if (!acquireLock()) {
        console.log("Fin du script car un autre tirage est actif.");
        if (cmdId) {
            writeCommandStatus({
                id: cmdId,
                action: 'new_draw',
                state: 'error',
                ready: false,
                message: 'Un tirage PC est deja en cours...'
            });
        }
        return;
    }
    console.log(videosOnly ? "--- Lancement du tirage Vidéos uniquement ---" : "--- Lancement du tirage intelligent ---");
    if (cmdId) {
        writeCommandStatus({
            id: cmdId,
            action: 'new_draw',
            state: 'running',
            ready: false,
            message: 'Nouveau tirage PC demarre...'
        });
    }

    try {
        const host = getHostFromPath(config.DEST_DIR);
        if (host) {
            console.log(`Vérification de la connexion avec le Bartop (${host})...`);
            const online = await isHostOnline(host);
            if (!online) {
                console.log(`[INFO] Le Bartop (${host}) est éteint ou injoignable sur le réseau.`);
                console.log("Fin du script sans modification.");
                return;
            }
            console.log("Le Bartop est en ligne !");
        }

        if (!fs.existsSync(config.DEST_DIR)) {
            console.error(`Erreur : Destination Photos inaccessible : ${config.DEST_DIR}`);
            return;
        }

        // Synchronisation automatique des scripts Python (slideshow.py / idle_monitor.py) vers le Bartop
        try {
            const bartopScriptDir = path.dirname(config.DEST_DIR);
            for (const scriptName of ['slideshow.py', 'idle_monitor.py']) {
                const localScript = path.join(__dirname, 'display', scriptName);
                const remoteScript = path.join(bartopScriptDir, scriptName);
                if (fs.existsSync(localScript)) {
                    const localBuf = fs.readFileSync(localScript);
                    let needCopy = true;
                    if (fs.existsSync(remoteScript)) {
                        const remoteBuf = fs.readFileSync(remoteScript);
                        if (localBuf.equals(remoteBuf)) needCopy = false;
                    }
                    if (needCopy) {
                        fs.writeFileSync(remoteScript, localBuf);
                        console.log(`[Sync Bartop] Script mis à jour sur le Bartop : ${scriptName}`);
                    }
                }
            }
        } catch (syncErr) {
            console.warn(`[Avertissement] Impossible de synchroniser les scripts Bartop : ${syncErr.message}`);
        }

        const photoPattern = config.SOURCE_DIR.replace(/\\/g, '/') + '/**/*.{jpg,JPG,jpeg,JPEG,heic,HEIC}';
        const allPhotos = globSync(photoPattern);
        console.log(`Photos trouvées : ${allPhotos.length}`);

        const videoPattern = config.SOURCE_DIR.replace(/\\/g, '/') + '/**/*.{mp4,MP4,mkv,MKV,avi,AVI,mov,MOV}';
        const allVideos = globSync(videoPattern);
        console.log(`Vidéos trouvées : ${allVideos.length}`);

        let previousSelected = [];
        let previousRejected = [];
        let previousVideos = [];
        const reportFilePath = path.join(__dirname, 'last_run.json');
        if (fs.existsSync(reportFilePath)) {
            try {
                const prevData = JSON.parse(fs.readFileSync(reportFilePath, 'utf8'));
                if (Array.isArray(prevData.selected)) previousSelected = prevData.selected;
                if (Array.isArray(prevData.rejected)) previousRejected = prevData.rejected;
                if (Array.isArray(prevData.videos)) previousVideos = prevData.videos;
            } catch (e) {
                // Ignorer si illisible
            }
        }

        const runReport = {
            timestamp: Date.now(),
            stats: {
                totalPhotos: allPhotos.length,
                totalVideos: allVideos.length,
                selected: previousSelected.length,
                rejected: videosOnly ? previousRejected.length : 0
            },
            selected: [...previousSelected],
            rejected: videosOnly ? [...previousRejected] : [],
            videos: [...previousVideos]
        };

        const writeReport = () => {
            try {
                runReport.timestamp = Date.now();
                fs.writeFileSync(reportFilePath, JSON.stringify(runReport, null, 2), 'utf8');
            } catch (err) {
                // Sourd aux erreurs d'écriture temporaire
            }
        };

        // Écriture initiale conservant les photos déjà présentes sur le Bartop
        writeReport();
        
        if (!videosOnly && allPhotos.length > 0) {
            const shuffled = allPhotos.sort(() => 0.5 - Math.random());
            let count = 0;
            const maxAttempts = Math.min(shuffled.length, config.NB_IMAGES * 5);
            
            console.log(`\n--- Sélection de ${config.NB_IMAGES} photos de qualité ---`);
            if (config.ENABLE_QUALITY_FILTERS) {
                console.log(`Filtres actifs :`);
                console.log(`  - Résolution min : ${config.FILTER_MIN_WIDTH}x${config.FILTER_MIN_HEIGHT}`);
                console.log(`  - Autoriser portrait : ${config.FILTER_ALLOW_PORTRAIT}`);
                console.log(`  - Ratio max : ${config.FILTER_MAX_ASPECT_RATIO}`);
                console.log(`  - Netteté min : ${config.FILTER_MIN_SHARPNESS}`);
                if (config.FILTER_REJECT_DOCUMENTS) {
                    console.log(`  - Rejet des documents (OCR Tesseract.js) : Actif`);
                }
            }

            for (let i = 0; i < shuffled.length && count < config.NB_IMAGES; i++) {
                if (i >= maxAttempts) {
                    console.log(`\n[Avertissement] Limite de tentatives atteinte (${maxAttempts}). Arrêt de la sélection.`);
                    break;
                }

                const photoPath = shuffled[i];
                let meta = null;
                try {
                    // 1. Lire les métadonnées en premier pour optimiser et récupérer l'orientation
                    meta = await getPhotoMetadata(photoPath, config);

                    // Validation préliminaire rapide via les métadonnées (évite de charger et décoder l'image inutilement)
                    const preCheck = validateMetadata(photoPath, meta);
                    if (!preCheck.valid) {
                        console.log(`  [Rejeté (Pre-EXIF)] ${path.basename(photoPath)} : ${preCheck.reason}`);
                        runReport.rejected.push({
                            path: photoPath,
                            reason: preCheck.reason,
                            sharpness: 0,
                            width: meta ? (meta.width || 0) : 0,
                            height: meta ? (meta.height || 0) : 0,
                            rotationDeg: meta ? (meta.rotationDeg || 0) : 0,
                            label: meta ? computeImageLabel(meta) : ""
                        });
                        runReport.stats.rejected++;
                        writeReport();
                        continue;
                    }

                    // 2. Charger l'image (l'auto-orientation est gérée en natif par Jimp et heic-convert)
                    const image = await loadImage(photoPath);
                    
                    // 3. Valider la qualité
                    const check = validateImageQuality(image, photoPath, meta);
                    
                    if (!check.valid) {
                        console.log(`  [Rejeté] ${path.basename(photoPath)} : ${check.reason}`);
                        
                        // Écrire également dans le cache local du PC pour un affichage Web instantané
                        try {
                            const cachePath = getCachePath(photoPath);
                            if (!fs.existsSync(cachePath)) {
                                const cacheImage = image.clone().scaleToFit({ w: 800, h: 800 });
                                await cacheImage.write(cachePath);
                            }
                        } catch (cacheErr) {
                            // Ignorer les erreurs d'écriture de cache
                        }

                        runReport.rejected.push({
                            path: photoPath,
                            reason: check.reason,
                            sharpness: Math.round(check.sharpness || 0),
                            width: meta ? (meta.width || image.bitmap.width) : image.bitmap.width,
                            height: meta ? (meta.height || image.bitmap.height) : image.bitmap.height,
                            rotationDeg: meta ? (meta.rotationDeg || 0) : 0,
                            label: meta ? computeImageLabel(meta) : ""
                        });
                        runReport.stats.rejected++;
                        writeReport();
                        continue;
                    }

                    // 4. Détecter si c'est un document (OCR Tesseract)
                    let ocrWords = 0;
                    let ocrChars = 0;
                    if (config.FILTER_REJECT_DOCUMENTS) {
                        console.log(`  [OCR] Analyse de texte pour ${path.basename(photoPath)}...`);
                        const ocrData = await detectText(image);
                        if (ocrData && ocrData.words) {
                            const minConfidence = typeof config.FILTER_OCR_MIN_CONFIDENCE === 'number'
                                ? config.FILTER_OCR_MIN_CONFIDENCE
                                : 70;
                            const validWords = ocrData.words.filter(w => {
                                const clean = w.text.replace(/[^a-zA-Z0-9àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]/g, '');
                                return w.confidence >= minConfidence && clean.length >= 2;
                            });

                            ocrWords = validWords.length;
                            ocrChars = validWords.reduce((sum, w) => sum + w.text.length, 0);

                            const maxWords = typeof config.FILTER_OCR_MAX_WORDS === 'number' ? config.FILTER_OCR_MAX_WORDS : 15;
                            const maxChars = typeof config.FILTER_OCR_MAX_CHARS === 'number' ? config.FILTER_OCR_MAX_CHARS : 100;

                            if (ocrWords >= maxWords || ocrChars >= maxChars) {
                                const reason = `Contient trop de texte (OCR : ${ocrWords} mots, ${ocrChars} caract.)`;
                                console.log(`  [Rejeté (OCR)] ${path.basename(photoPath)} : ${reason}`);

                                try {
                                    const cachePath = getCachePath(photoPath);
                                    if (!fs.existsSync(cachePath)) {
                                        const cacheImage = image.clone().scaleToFit({ w: 800, h: 800 });
                                        await cacheImage.write(cachePath);
                                    }
                                } catch (cacheErr) {
                                    // Ignorer
                                }

                                runReport.rejected.push({
                                    path: photoPath,
                                    reason: reason,
                                    sharpness: Math.round(check.sharpness || 0),
                                    width: meta ? (meta.width || image.bitmap.width) : image.bitmap.width,
                                    height: meta ? (meta.height || image.bitmap.height) : image.bitmap.height,
                                    rotationDeg: meta ? (meta.rotationDeg || 0) : 0,
                                    ocrWords: ocrWords,
                                    ocrChars: ocrChars,
                                    label: meta ? computeImageLabel(meta) : ""
                                });
                                runReport.stats.rejected++;
                                writeReport();
                                continue;
                            }
                        }
                    }

                    const originalWidth = image.bitmap.width;
                    const originalHeight = image.bitmap.height;

                    count++;
                    const id = count.toString().padStart(3, '0');
                    const label = await processImage(photoPath, image, id, config.NB_IMAGES, check, meta);
                    if (cmdId && (count === 1 || count % 5 === 0 || count === config.NB_IMAGES)) {
                        writeCommandStatus({
                            id: cmdId,
                            action: 'new_draw',
                            state: 'running',
                            ready: false,
                            count: count,
                            message: `Tirage PC : ${count}/${config.NB_IMAGES} photos...`
                        });
                    }
                    
                    const newPhotoEntry = {
                        path: photoPath,
                        label: label || "Sans label",
                        sharpness: Math.round(check.sharpness),
                        width: meta ? (meta.width || originalWidth) : originalWidth,
                        height: meta ? (meta.height || originalHeight) : originalHeight,
                        rotationDeg: meta ? (meta.rotationDeg || 0) : 0,
                        ocrWords: ocrWords,
                        ocrChars: ocrChars
                    };
                    if (count - 1 < runReport.selected.length) {
                        runReport.selected[count - 1] = newPhotoEntry;
                    } else {
                        runReport.selected.push(newPhotoEntry);
                    }
                    runReport.stats.selected = runReport.selected.length;
                    writeReport();
                } catch (err) {
                    console.log(`  [Rejeté] Erreur chargement ${path.basename(photoPath)} : ${err.message}`);
                    runReport.rejected.push({
                        path: photoPath,
                        reason: `Erreur chargement : ${err.message}`,
                        sharpness: 0,
                        width: 0,
                        height: 0,
                        rotationDeg: 0,
                        label: meta ? computeImageLabel(meta) : ""
                    });
                    runReport.stats.rejected++;
                    writeReport();
                }
            }
            
            if (count > 0 && runReport.selected.length > count) {
                runReport.selected.length = count;
                runReport.stats.selected = count;
                writeReport();
            }

            // Nettoyage des anciennes images en trop à la fin de la sélection (ex: 101.jpg à 120.jpg si le nombre a baissé)
            try {
                const oldFiles = fs.readdirSync(config.DEST_DIR);
                for (const f of oldFiles) {
                    const match = f.match(/^(\d+)\.(jpg|txt)$/i);
                    if (match) {
                        const fileIndex = parseInt(match[1], 10);
                        if (fileIndex > count) {
                            fs.unlinkSync(path.join(config.DEST_DIR, f));
                        }
                    }
                }
            } catch (err) {
                console.warn(`Attention : Impossible de nettoyer les fichiers d'images superflus : ${err.message}`);
            }

            console.log(`\nTotal Photos sélectionnées : ${count}/${config.NB_IMAGES}`);

            // Nettoyage final du cache d'aperçus (supprime les vignettes des anciennes sessions)
            try {
                const cacheDir = path.join(__dirname, '.cache');
                if (fs.existsSync(cacheDir)) {
                    const validCacheFiles = new Set();
                    const allPhotosReport = [...runReport.selected, ...runReport.rejected];
                    for (const photo of allPhotosReport) {
                        validCacheFiles.add(path.basename(getCachePath(photo.path)));
                    }
                    const files = fs.readdirSync(cacheDir);
                    for (const file of files) {
                        if (file.endsWith('.jpg') && !validCacheFiles.has(file)) {
                            fs.unlinkSync(path.join(cacheDir, file));
                        }
                    }
                }
            } catch (cacheErr) {
                console.warn(`[Avertissement] Impossible de nettoyer le cache : ${cacheErr.message}`);
            }
        }

        if (allVideos.length > 0) {
            if (cmdId) {
                writeCommandStatus({
                    id: cmdId,
                    action: 'new_draw',
                    state: 'running',
                    ready: false,
                    message: 'Tirage PC : conversion videos...'
                });
            }
            const selectedVids = await processVideos(allVideos, (currentVids) => {
                runReport.videos = [...currentVids];
                writeReport();
            });
            runReport.videos = selectedVids || [];
            writeReport();
        }

        if (cmdId) {
            writeCommandStatus({
                id: cmdId,
                action: 'new_draw',
                state: 'done',
                ready: true,
                count: runReport.stats.selected,
                message: `Nouveau tirage termine ! (${runReport.stats.selected} photos)`
            });
        }

        console.log("\n--- Terminé ! ---");
    } finally {
        await terminateTesseractWorker();
        releaseLock();
    }
}

if (require.main === module) {
    const focusIdx = process.argv.indexOf('--focus');
    const cmdIdIdx = process.argv.indexOf('--cmd-id');
    const cmdId = (cmdIdIdx !== -1 && process.argv[cmdIdIdx + 1]) ? process.argv[cmdIdIdx + 1] : null;
    if (focusIdx !== -1 && process.argv[focusIdx + 1]) {
        runFocusMoment(process.argv[focusIdx + 1], cmdId);
    } else {
        start({ cmdId });
    }
}

module.exports = {
    start,
    runFocusMoment,
    loadImage,
    validateImageQuality,
    calculateSharpness
};