const express = require('express');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const convert = require('heic-convert');
const { Jimp } = require('jimp');
const exifr = require('exifr');
const crypto = require('crypto');
const { getPhotoMetadata } = require('./metadata');

// Augmenter la limite mémoire pour les grosses photos HEIC/iPhone 15
Jimp.maxMemoryUsageInMB = 2048;

const app = express();
const PORT = 3000;

// Dossier cache pour les aperçus d'images
const cacheDir = path.join(__dirname, '.cache');
if (!fs.existsSync(cacheDir)) {
    fs.mkdirSync(cacheDir, { recursive: true });
}

function getCachePath(filePath) {
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

const lockFilePath = path.join(__dirname, 'selection.lock');

function isSelectionRunning() {
    if (fs.existsSync(lockFilePath)) {
        try {
            const pidStr = fs.readFileSync(lockFilePath, 'utf8').trim();
            const pid = parseInt(pidStr, 10);
            if (!isNaN(pid)) {
                try {
                    process.kill(pid, 0);
                    return true;
                } catch (e) {
                    // Lock obsolète
                }
            }
        } catch (e) {
            // Ignorer
        }
    }
    return false;
}



app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

let activeProcess = null;
let logBuffer = [];
let clients = [];

// API: Lire la configuration
app.get('/api/config', (req, res) => {
    try {
        const configData = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
        res.json(configData);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// API: Enregistrer la configuration
app.post('/api/config', (req, res) => {
    try {
        const newConfig = req.body;
        const configPath = path.join(__dirname, 'config.json');
        const currentConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));

        // Fusionner et forcer les types de données appropriés
        const merged = { ...currentConfig };
        for (const key in newConfig) {
            if (typeof currentConfig[key] === 'number') {
                merged[key] = Number(newConfig[key]);
            } else if (typeof currentConfig[key] === 'boolean') {
                merged[key] = newConfig[key] === true || newConfig[key] === 'true';
            } else {
                merged[key] = newConfig[key];
            }
        }

        fs.writeFileSync(configPath, JSON.stringify(merged, null, 4), 'utf8');
        res.json({ message: 'Configuration enregistrée avec succès' });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// API: Obtenir l'historique du dernier tirage
app.get('/api/history', (req, res) => {
    const historyPath = path.join(__dirname, 'last_run.json');
    if (!fs.existsSync(historyPath)) {
        return res.status(404).json({ error: 'Aucun historique disponible' });
    }
    try {
        const historyData = JSON.parse(fs.readFileSync(historyPath, 'utf8'));
        res.json(historyData);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// API: Lancer un tirage
app.post('/api/run', (req, res) => {
    if (activeProcess || isSelectionRunning()) {
        return res.status(400).json({ error: 'Un tirage est déjà en cours de traitement (via le serveur ou la tâche planifiée)' });
    }

    const videosOnly = Boolean(req.body && req.body.videosOnly);
    const args = videosOnly ? ['index.js', '--videos-only'] : ['index.js'];

    logBuffer = [];
    activeProcess = spawn('node', args, { cwd: __dirname });

    const handleData = (data) => {
        const text = data.toString();
        logBuffer.push(text);
        sendLogsToClients(text);
    };

    activeProcess.stdout.on('data', handleData);
    activeProcess.stderr.on('data', handleData);

    activeProcess.on('close', (code) => {
        const msg = `\n--- Terminé ! Code de sortie : ${code} ---\n`;
        logBuffer.push(msg);
        sendLogsToClients(msg);
        activeProcess = null;
    });

    res.json({ message: 'Tirage démarré' });
});

// API: Interrompre un tirage en cours
app.post('/api/stop', (req, res) => {
    try {
        let processKilled = false;

        // 1. Interrompre le processus enfant géré par le serveur Express
        if (activeProcess) {
            activeProcess.kill('SIGTERM');
            processKilled = true;
        }

        // 2. Fallback: Lire le PID depuis selection.lock pour arrêter le processus (tâche planifiée, execution console, etc.)
        if (fs.existsSync(lockFilePath)) {
            const pidStr = fs.readFileSync(lockFilePath, 'utf8').trim();
            const pid = parseInt(pidStr, 10);
            if (!isNaN(pid)) {
                try {
                    process.kill(pid, 'SIGTERM');
                    processKilled = true;
                } catch (e) {
                    // Ignorer si le processus est déjà mort
                }
            }
        }

        if (processKilled) {
            res.json({ message: 'Tirage interrompu avec succès' });
        } else {
            res.status(400).json({ error: 'Aucun tirage actif à interrompre' });
        }
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});


// API: Obtenir le statut actuel de l'exécution
app.get('/api/status', (req, res) => {
    res.json({ running: isSelectionRunning() });
});

// API: Obtenir l'élément actuellement affiché sur le Bartop
app.get('/api/bartop-current', (req, res) => {
    try {
        const configPath = path.join(__dirname, 'config.json');
        if (!fs.existsSync(configPath)) {
            return res.status(404).json({ error: 'Config introuvable' });
        }
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
        const currentFilePath = path.join(path.dirname(config.DEST_DIR), 'current.json');
        
        if (fs.existsSync(currentFilePath)) {
            const data = JSON.parse(fs.readFileSync(currentFilePath, 'utf8'));
            return res.json(data);
        }
        res.json({ error: "Aucun élément en cours de lecture" });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});


// API: Stream de logs temps réel (Server-Sent Events)
app.get('/api/run-logs', (req, res) => {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    // Envoyer les logs déjà accumulés lors de la connexion
    res.write(`data: ${JSON.stringify({ logs: logBuffer.join('') })}\n\n`);

    const client = { res };
    clients.push(client);

    req.on('close', () => {
        clients = clients.filter(c => c !== client);
    });
});

function sendLogsToClients(text) {
    clients.forEach(c => {
        try {
            c.res.write(`data: ${JSON.stringify({ text })}\n\n`);
        } catch (e) {
            // Ignorer les erreurs d'envoi individuel
        }
    });
}

// API: Servir les photos (avec conversion HEIC à la volée et cache local optimisé / auto-orienté)
app.get('/api/photo', async (req, res) => {
    const photoPath = req.query.path;
    if (!photoPath) return res.status(400).send('Chemin manquant');
    if (!fs.existsSync(photoPath)) return res.status(404).send('Fichier introuvable');

    try {
        const cachePath = getCachePath(photoPath);
        if (fs.existsSync(cachePath)) {
            res.contentType('image/jpeg');
            return res.send(fs.readFileSync(cachePath));
        }

        // Sinon, on génère le preview
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

        const image = await Jimp.fromBuffer(imageBuffer, {
            'image/jpeg': {
                maxMemoryUsageInMB: 2048
            }
        });



        // Redimensionner pour le Web (max 1000px pour un affichage rapide et de bonne qualité)
        image.scaleToFit({ w: 1000, h: 1000 });

        // Écrire dans le cache
        const jpegBuffer = await image.getBuffer('image/jpeg', { quality: 80 });
        fs.writeFileSync(cachePath, jpegBuffer);

        res.contentType('image/jpeg');
        res.send(jpegBuffer);
    } catch (e) {
        console.error('Erreur lors de la génération de l\'aperçu :', e);
        if (!photoPath.toLowerCase().endsWith('.heic')) {
            return res.sendFile(photoPath);
        }
        res.status(500).send('Erreur lors de la génération de l\'aperçu : ' + e.message);
    }
});

// API: Servir les vidéos avec Range Requests (HTTP 206)
app.get('/api/video', (req, res) => {
    let videoPath = req.query.path;
    const videoId = req.query.id;
    if (!videoPath) return res.status(400).send('Chemin manquant');

    // Si une version MP4 convertie existe sur le Bartop (particulièrement utile pour les .MOV HEVC / .AVI), l'utiliser en priorité
    if (videoId && /^\d+$/.test(videoId)) {
        try {
            const configData = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
            if (configData.VIDEO_DEST_DIR) {
                const convertedPath = path.join(configData.VIDEO_DEST_DIR, `${videoId}.mp4`);
                if (fs.existsSync(convertedPath)) {
                    videoPath = convertedPath;
                }
            }
        } catch (e) {
            // Fallback sur le chemin original
        }
    }

    if (!fs.existsSync(videoPath)) return res.status(404).send('Fichier introuvable');

    try {
        const stat = fs.statSync(videoPath);
        const fileSize = stat.size;
        const range = req.headers.range;

        // Content-Type par défaut et détection simple selon l'extension
        let contentType = 'video/mp4';
        const ext = path.extname(videoPath).toLowerCase();
        if (ext === '.mov') {
            contentType = 'video/quicktime';
        } else if (ext === '.avi') {
            contentType = 'video/x-msvideo';
        } else if (ext === '.mkv') {
            contentType = 'video/x-matroska';
        }

        if (range) {
            const parts = range.replace(/bytes=/, "").split("-");
            const start = parseInt(parts[0], 10);
            const end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;

            if (start >= fileSize) {
                res.status(416).send('Requested range not satisfiable\n' + start + ' >= ' + fileSize);
                return;
            }

            const chunksize = (end - start) + 1;
            const file = fs.createReadStream(videoPath, { start, end });
            const head = {
                'Content-Range': `bytes ${start}-${end}/${fileSize}`,
                'Accept-Ranges': 'bytes',
                'Content-Length': chunksize,
                'Content-Type': contentType,
            };

            res.writeHead(206, head);
            file.pipe(res);
        } else {
            const head = {
                'Content-Length': fileSize,
                'Content-Type': contentType,
            };
            res.writeHead(200, head);
            fs.createReadStream(videoPath).pipe(res);
        }
    } catch (e) {
        console.error('Erreur lors de la diffusion de la vidéo :', e);
        res.status(500).send('Erreur lors de la diffusion de la vidéo : ' + e.message);
    }
});


app.listen(PORT, () => {
    console.log(`==================================================`);
    console.log(` Serveur Dashboard Bartop démarré sur :`);
    console.log(` http://localhost:${PORT}`);
    console.log(`==================================================`);
});
