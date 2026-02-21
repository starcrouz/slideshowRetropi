#!/usr/bin/python
# -*- coding: utf-8 -*-

import pygame
import os
import time
import sys
import argparse
import glob
import fcntl
import struct
import random
import json

# --- CONFIGURATION (Peut être modifié ici ou via le fichier settings) ---
INFO_BUTTON_DEFAULT = 289  # Code du bouton pour afficher les détails (Configuré pour votre branche)
IMAGE_FOLDER = "/recalbox/share/userscripts/slideshow/images" 
SETTINGS_FILE = "/recalbox/share/userscripts/slideshow/slideshow_settings.json"
DEFAULT_DISPLAY_TIME = 15 
MIN_DISPLAY_TIME = 3
MAX_DISPLAY_TIME = 60
ZOOM_SPEED = 0.00015
FADE_SPEED = 8

# Input event constants
EV_KEY = 1
EV_ABS = 3
ABS_X = 0
ABS_Y = 1
ABS_HAT0X = 16
ABS_HAT0Y = 17

def load_settings():
    """Charge les réglages persistants."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"display_time": DEFAULT_DISPLAY_TIME, "info_button": INFO_BUTTON_DEFAULT}

def save_settings(settings):
    """Sauvegarde les réglages persistants."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception:
        pass

def get_sidecar_data(image_path):
    """Lit les métadonnées multi-lignes du fichier .txt associé."""
    txt_path = os.path.splitext(image_path)[0] + ".txt"
    data = {"label": u"", "full_date": u"", "source_path": u""}
    if os.path.exists(txt_path):
        try:
            with open(txt_path, 'r') as f:
                lines = f.readlines()
                # En Python 2, on décode explicitement chaque ligne
                if len(lines) >= 1: data["label"] = lines[0].strip().decode('utf-8', 'ignore')
                if len(lines) >= 2: data["full_date"] = lines[1].strip().decode('utf-8', 'ignore')
                if len(lines) >= 3: data["source_path"] = lines[2].strip().decode('utf-8', 'ignore')
        except Exception:
            pass
    return data

def get_input_devices():
    return glob.glob('/dev/input/event*')

def run_slideshow(enable_animation=True, target_info_button=INFO_BUTTON_DEFAULT):
    # Paramètres Recalbox / FBcon
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_NOMOUSE"] = "1"
    
    settings = load_settings()
    display_time = settings.get("display_time", DEFAULT_DISPLAY_TIME)
    info_button_code = settings.get("info_button", target_info_button)
    
    pygame.init()
    if pygame.joystick.get_count() > 0:
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            pygame.joystick.Joystick(i).init()
    
    # Surveillance des entrées bas-niveau (/dev/input)
    devices = get_input_devices()
    input_files = []
    for dev in devices:
        try:
            f = open(dev, 'rb')
            fd = f.fileno()
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            input_files.append(f)
        except Exception:
            pass

    # Taille de la structure input_event (32-bit sur RPi 3)
    event_format = 'llHHi' 
    event_size = struct.calcsize(event_format)

    # Résolution écran
    info = pygame.display.Info()
    sw, sh = info.current_w, info.current_h
    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    
    # Polices
    font_main = pygame.font.Font(None, int(sh * 0.05))
    font_small = pygame.font.Font(None, int(sh * 0.03))

    # Filtrage des fichiers JPEG
    all_files = sorted([os.path.join(IMAGE_FOLDER, f) for f in os.listdir(IMAGE_FOLDER) if f.lower().endswith('.jpg')])
    if not all_files:
        print("Aucune image trouvee dans " + IMAGE_FOLDER)
        return

    # Mélange aléatoire (Indices)
    indices = range(len(all_files))
    random.shuffle(indices)
    current_idx_ptr = 0

    idx = indices[current_idx_ptr]
    running = True
    need_load = True
    last_switch = time.time()
    
    # Variables d'état
    current_img_raw = None
    zoom_factor = 1.0
    alpha = 0
    meta_data = {}
    
    # Superpositions (Overlays)
    show_info = False
    info_timer = 0
    INFO_DURATION = 15 

    speed_overlay_timer = 0
    SPEED_OVERLAY_DURATION = 2

    # Anti-rebond
    last_nav_time = 0
    last_speed_time = 0

    try:
        while running:
            now = time.time()
            
            # --- 1. GESTION DES ENTRÉES BAS-NIVEAU (Réactivité maximale) ---
            for f in input_files:
                try:
                    data = f.read(event_size)
                    while data:
                        _, _, ev_type, ev_code, ev_value = struct.unpack(event_format, data)
                        if ev_type == EV_KEY and ev_value == 1: # Bouton Pressé
                            if ev_code == info_button_code:
                                show_info = not show_info
                                if show_info: 
                                    info_timer = now + INFO_DURATION
                            else: 
                                running = False
                                break
                        data = f.read(event_size)
                except Exception:
                    pass
            
            if not running: break
            
            # --- 2. GESTION DES ÉVÉNEMENTS SDL (Navigation et Vitesse) ---
            for event in pygame.event.get():
                if event.type in (pygame.QUIT, pygame.KEYDOWN):
                    running = False
                
                # Réglage de la Vitesse (Vertical)
                if now - last_speed_time > 0.15:
                    change = 0
                    if event.type == pygame.JOYAXISMOTION and event.axis == 1:
                        if event.value < -0.6: change = -3 # Haut -> Plus rapide (- temps)
                        elif event.value > 0.6: change = 3 # Bas -> Plus lent (+ temps)
                    elif event.type == pygame.JOYHATMOTION and event.value[1] != 0:
                        change = -event.value[1] * 3

                    if change != 0:
                        display_time = max(MIN_DISPLAY_TIME, min(MAX_DISPLAY_TIME, display_time + change))
                        last_speed_time = now
                        speed_overlay_timer = now + SPEED_OVERLAY_DURATION
                        save_settings({"display_time": display_time, "info_button": info_button_code})

                # Navigation (Horizontal)
                if now - last_nav_time > 0.4:
                    if event.type == pygame.JOYAXISMOTION and event.axis == 0:
                        if event.value > 0.6: # Suivant
                            current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                            idx = indices[current_idx_ptr]
                            need_load = True
                            last_nav_time = now
                        elif event.value < -0.6: # Précédent
                            current_idx_ptr = (current_idx_ptr - 1) % len(indices)
                            idx = indices[current_idx_ptr]
                            need_load = True
                            last_nav_time = now
                    elif event.type == pygame.JOYHATMOTION and event.value[0] != 0:
                        if event.value[0] == 1: current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                        else: current_idx_ptr = (current_idx_ptr - 1) % len(indices)
                        idx = indices[current_idx_ptr]
                        need_load = True
                        last_nav_time = now

            # --- 3. LOGIQUE DES DIAPOS ---
            if show_info:
                # On fige le temps pendant l'affichage des infos
                last_switch = now - display_time + (max(0, info_timer - now))
                if now > info_timer: show_info = False

            if not need_load and not show_info and now - last_switch > display_time:
                current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                idx = indices[current_idx_ptr]
                need_load = True

            if need_load:
                try:
                    img = pygame.image.load(all_files[idx]).convert()
                    img_w, img_h = img.get_size()
                    ratio = min(float(sw)/img_w, float(sh)/img_h)
                    current_img_raw = pygame.transform.scale(img, (int(img_w*ratio), int(img_h*ratio)))
                    meta_data = get_sidecar_data(all_files[idx])
                    zoom_factor = 1.0
                    alpha = 0
                    need_load = False
                    last_switch = now
                except Exception:
                    current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                    idx = indices[current_idx_ptr]

            # --- 4. AFFICHAGE (RENDERING) ---
            if current_img_raw:
                screen.fill((0, 0, 0))
                
                if enable_animation and not show_info:
                    zoom_factor += ZOOM_SPEED
                
                z_w, z_h = int(current_img_raw.get_width() * zoom_factor), int(current_img_raw.get_height() * zoom_factor)
                img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                
                if alpha < 255: alpha += FADE_SPEED
                img_to_draw.set_alpha(min(alpha, 255))
                screen.blit(img_to_draw, ((sw - z_w) // 2, (sh - z_h) // 2))
                
                # Overlays
                if show_info:
                    # Panneau d'informations détaillées
                    overlay = pygame.Surface((sw * 0.85, sh * 0.5))
                    overlay.set_alpha(200)
                    overlay.fill((20, 20, 20))
                    ox, oy = (sw - overlay.get_width()) // 2, (sh - overlay.get_height()) // 2
                    screen.blit(overlay, (ox, oy))
                    
                    info_lines = [
                        u"DÉTAILS PHOTO [%d/%d]" % (current_idx_ptr + 1, len(all_files)),
                        u"Lieu      : %s" % meta_data.get("label", u"N/A"),
                        u"Date      : %s" % meta_data.get("full_date", u"N/A"),
                        u"Fichier   : %s" % meta_data.get("source_path", u"N/A"),
                        u"",
                        u"Retour auto dans %ds..." % int(max(0, info_timer - now))
                    ]
                    for i, line in enumerate(info_lines):
                        c = (255, 255, 0) if i == 0 else (255, 255, 255)
                        txt = font_small.render(line, True, c)
                        screen.blit(txt, (ox + 30, oy + 30 + i * 40))
                else:
                    # Libellé normal (Label)
                    if meta_data.get("label"):
                        txt = font_main.render(meta_data["label"], True, (255, 255, 255))
                        shd = font_main.render(meta_data["label"], True, (0, 0, 0))
                        tx, ty = sw - txt.get_width() - 40, sh - txt.get_height() - 40
                        screen.blit(shd, (tx+2, ty+2))
                        screen.blit(txt, (tx, ty))
                    
                    # Indicateur de Vitesse (au changement)
                    if now < speed_overlay_timer:
                        # Calcul d'un score de vitesse de 1 à 20
                        vitesse_score = (MAX_DISPLAY_TIME - display_time) // 3 + 1
                        s_txt = u"Vitesse : %d / 20" % vitesse_score
                        txt = font_small.render(s_txt, True, (255, 255, 0))
                        screen.blit(txt, (30, 30))

                pygame.display.flip()
            
            time.sleep(0.04 if enable_animation and not show_info else 0.1)

    finally:
        for f in input_files: f.close()
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-animation", action="store_true")
    parser.add_argument("--info-button", type=int, default=INFO_BUTTON_DEFAULT)
    args = parser.parse_args()
    run_slideshow(enable_animation=not args.no_animation, target_info_button=args.info_button)
