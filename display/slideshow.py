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
import subprocess
import signal
import re

# --- CONFIGURATION PAR DÉFAUT ---
INFO_BUTTON_DEFAULT = 289
MODE_BUTTON_DEFAULT = 304 
IMAGE_FOLDER = "/recalbox/share/userscripts/slideshow/images" 
VIDEO_PERSO_FOLDER = "/recalbox/share/userscripts/slideshow/videos"
ROMS_FOLDER = "/recalbox/share/roms"
SETTINGS_FILE = "/recalbox/share/userscripts/slideshow/slideshow_settings.json"

DEFAULT_DISPLAY_TIME = 15 
MIN_DISPLAY_TIME = 1
MAX_DISPLAY_TIME = 120
ZOOM_SPEED = 0.00015
FADE_SPEED = 8

# Modes
MODE_PHOTOS = 1
MODE_VIDEOS_PERSO = 2
MODE_VIDEOS_GAMES = 3
MODE_CYCLE = 4
CYCLE_INTERVAL = 60 

# Input event constants
EV_KEY = 1
EV_ABS = 3
ABS_X = 0
ABS_Y = 1
ABS_HAT0X = 16
ABS_HAT0Y = 17

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception: pass
    return {"display_time": DEFAULT_DISPLAY_TIME, "info_button": INFO_BUTTON_DEFAULT, "mode_button": MODE_BUTTON_DEFAULT, "current_mode": MODE_PHOTOS, "is_muted": False}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception: pass

def get_sidecar_data(file_path):
    txt_path = os.path.splitext(file_path)[0] + ".txt"
    data = {"label": u"", "info": u"", "source_path": u""}
    if os.path.exists(txt_path):
        try:
            with open(txt_path, 'r') as f:
                content = f.read()
                if hasattr(content, 'decode'): content = content.decode('utf-8', 'ignore')
                lines = [l.strip() for l in content.split('\n')]
                if len(lines) >= 1: data["label"] = lines[0]
                if len(lines) >= 2: data["info"] = lines[1]
                if len(lines) >= 3: data["source_path"] = lines[2]
        except Exception: pass
    return data

def clean_game_name(name):
    cleaned = re.sub(r'[\(\[].*?[\)\]]', '', name)
    cleaned = cleaned.replace('_', ' ').strip()
    # Gestion du suffixe ", The"
    if cleaned.lower().endswith(", the"):
        cleaned = "The " + cleaned[:-5].strip()
    return cleaned.title()

def parse_game_metadata(file_path):
    parts = file_path.split('/')
    console = u"Inconnu"
    try:
        if "roms" in parts:
            idx = parts.index("roms")
            if len(parts) > idx + 1: console = parts[idx+1].upper()
    except Exception: pass
    bname = os.path.splitext(os.path.basename(file_path))[0]
    if hasattr(bname, 'decode'): bname = bname.decode('utf-8', 'ignore')
    game_name = clean_game_name(bname)
    return {"console": console, "game": game_name}

def get_input_devices():
    return glob.glob('/dev/input/event*')

def stop_video(proc):
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
        except: pass

def draw_wrapped_text(screen, text, font, color, rect):
    parts = re.split(r'([/\\ _-])', text)
    y = rect.top
    line = ""
    for part in parts:
        test_line = line + part
        if font.size(test_line)[0] < rect.width:
            line = test_line
        else:
            if line:
                txt_surface = font.render(line, True, color)
                screen.blit(txt_surface, (rect.left, y))
                y += font.get_linesize()
            line = part
            if y > rect.bottom - font.get_linesize(): break
    if line and y <= rect.bottom - font.get_linesize():
        txt_surface = font.render(line, True, color)
        screen.blit(txt_surface, (rect.left, y))

def run_slideshow(enable_animation=True):
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_NOMOUSE"] = "1"
    
    settings = load_settings()
    display_time = settings.get("display_time", DEFAULT_DISPLAY_TIME)
    info_button_code = settings.get("info_button", INFO_BUTTON_DEFAULT)
    mode_button_code = settings.get("mode_button", MODE_BUTTON_DEFAULT)
    current_mode = settings.get("current_mode", MODE_PHOTOS)
    is_muted = settings.get("is_muted", False)
    
    internal_mode = current_mode if current_mode != MODE_CYCLE else MODE_PHOTOS
    last_cycle_time = time.time()

    pygame.init()
    if pygame.joystick.get_count() > 0:
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            pygame.joystick.Joystick(i).init()
    
    devices = get_input_devices()
    input_files = []
    for dev in devices:
        try:
            f = open(dev, 'rb')
            fd = f.fileno()
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            input_files.append(f)
        except: pass

    event_format = 'llHHi' 
    event_size = struct.calcsize(event_format)
    info = pygame.display.Info()
    sw, sh = info.current_w, info.current_h
    if sw == 0 or sh == 0: sw, sh = 1280, 1024 
    
    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    
    font_main = pygame.font.Font(None, int(sh * 0.05))
    font_small = pygame.font.Font(None, int(sh * 0.03))
    font_tiny = pygame.font.Font(None, int(sh * 0.022))

    def get_files_for_mode(mode):
        if mode == MODE_PHOTOS:
            return sorted([os.path.join(IMAGE_FOLDER, f) for f in os.listdir(IMAGE_FOLDER) if f.lower().endswith('.jpg')])
        elif mode == MODE_VIDEOS_PERSO:
            if not os.path.exists(VIDEO_PERSO_FOLDER): return []
            return sorted([os.path.join(VIDEO_PERSO_FOLDER, f) for f in os.listdir(VIDEO_PERSO_FOLDER) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov'))])
        elif mode == MODE_VIDEOS_GAMES:
            vids = []
            if os.path.exists(ROMS_FOLDER):
                for root, dirs, files in os.walk(ROMS_FOLDER):
                    if any(x in root.lower() for x in ["media/videos", "downloaded_images", "videos"]):
                        for f in files:
                            if f.lower().endswith(('.mp4', '.mkv', '.avi')): vids.append(os.path.join(root, f))
            return sorted(vids)
        return []

    all_files = get_files_for_mode(internal_mode)
    indices = list(range(len(all_files)))
    random.shuffle(indices)
    current_idx_ptr = 0

    running = True; need_load = True; last_switch = time.time()
    current_img_raw = None; zoom_factor = 1.0; alpha = 0; meta_data = {}
    
    show_info = False; info_timer = 0; INFO_DURATION = 15
    last_detected_code = 0; code_timer = 0
    speed_overlay_timer = 0; mode_overlay_timer = 0; mute_overlay_timer = 0
    OVERLAY_DURATION = 3

    last_nav_time = 0; last_speed_time = 0; video_proc = None

    try:
        while running:
            now = time.time()
            
            # --- 1. LOGIQUE TIMERS & CYCLE ---
            if current_mode == MODE_CYCLE and now - last_cycle_time > CYCLE_INTERVAL:
                internal_mode = (internal_mode % 3) + 1
                all_files = get_files_for_mode(internal_mode)
                indices = list(range(len(all_files)))
                random.shuffle(indices)
                current_idx_ptr = 0; need_load = True; last_cycle_time = now
                if video_proc: stop_video(video_proc); video_proc = None

            if show_info and now > info_timer:
                show_info = False

            # --- 2. ENTRÉES ---
            for f in input_files:
                try:
                    data = f.read(event_size)
                    while data:
                        _, _, ev_type, ev_code, ev_value = struct.unpack(event_format, data)
                        if ev_type == EV_KEY and ev_value == 1: 
                            if ev_code not in (info_button_code, mode_button_code):
                                last_detected_code = ev_code
                                code_timer = now + 4
                            
                            if show_info:
                                if ev_code == info_button_code: show_info = False
                                else: info_timer = now + INFO_DURATION
                            else:
                                if ev_code == info_button_code:
                                    if internal_mode == MODE_PHOTOS:
                                        show_info = True; info_timer = now + INFO_DURATION
                                    else:
                                        is_muted = not is_muted
                                        mute_overlay_timer = now + OVERLAY_DURATION
                                        settings["is_muted"] = is_muted; save_settings(settings)
                                        if video_proc: stop_video(video_proc); video_proc = None; need_load = True
                                elif ev_code == mode_button_code:
                                    # Feedback immédiat : on lance la transition
                                    current_mode = (current_mode % 4) + 1
                                    internal_mode = current_mode if current_mode != MODE_CYCLE else MODE_PHOTOS
                                    all_files = get_files_for_mode(internal_mode)
                                    indices = list(range(len(all_files)))
                                    random.shuffle(indices)
                                    current_idx_ptr = 0
                                    
                                    # Reset visuel immédiat pour éviter superposition
                                    screen.fill((0, 0, 0))
                                    current_img_raw = None
                                    alpha = 0
                                    
                                    mode_overlay_timer = now + OVERLAY_DURATION
                                    settings["current_mode"] = current_mode; save_settings(settings)
                                    last_cycle_time = now; need_load = True
                                    if video_proc: stop_video(video_proc); video_proc = None
                                else:
                                    running = False; break
                        data = f.read(event_size)
                except: pass
            
            if not running: break
            
            # --- 3. ÉVÉNEMENTS SDL ---
            for event in pygame.event.get():
                if event.type in (pygame.QUIT, pygame.KEYDOWN): running = False
                
                if not show_info:
                    if internal_mode == MODE_PHOTOS and now - last_speed_time > 0.2:
                        change = 0
                        if event.type == pygame.JOYAXISMOTION and event.axis == 1:
                            if event.value < -0.6: change = 1
                            elif event.value > 0.6: change = -1
                        elif event.type == pygame.JOYHATMOTION and event.value[1] != 0:
                            change = event.value[1]
                        
                        if change != 0:
                            img_per_min = int(round(60.0 / display_time)) + change
                            img_per_min = max(1, min(60, img_per_min))
                            display_time = 60.0 / img_per_min
                            last_speed_time = now; speed_overlay_timer = now + OVERLAY_DURATION
                            settings["display_time"] = display_time; save_settings(settings)

                    if now - last_nav_time > 0.4:
                        steer = 0
                        if event.type == pygame.JOYAXISMOTION and event.axis == 0:
                            if abs(event.value) > 0.6: steer = 1 if event.value > 0.6 else -1
                        elif event.type == pygame.JOYHATMOTION and event.value[0] != 0: steer = event.value[0]
                        if steer != 0:
                            current_idx_ptr = (current_idx_ptr + steer) % len(indices)
                            need_load = True; last_nav_time = now
                            if video_proc: stop_video(video_proc); video_proc = None

            # --- 4. LOGIQUE CHARGEMENT ---
            if video_proc and video_proc.poll() is not None:
                video_proc = None; current_idx_ptr = (current_idx_ptr + 1) % len(indices); need_load = True

            # Dans le cas du chargement suite à un bouton de mode, on attend que l'overlay disparaisse pour charger
            if need_load and now < mode_overlay_timer:
                # On reste sur le nom du mode sans charger l'image/video
                pass
            elif need_load:
                if not indices:
                    screen.fill((0, 0, 0))
                    msg = u"Aucun fichier trouvé"
                    txt = font_main.render(msg, True, (255, 100, 100))
                    screen.blit(txt, ((sw-txt.get_width())//2, (sh-txt.get_height())//2))
                    pygame.display.flip(); time.sleep(2); need_load = False; continue

                file_path = all_files[indices[current_idx_ptr]]

                if internal_mode == MODE_PHOTOS:
                    try:
                        img = pygame.image.load(file_path).convert()
                        img_w, img_h = img.get_size()
                        ratio = min(float(sw)/img_w, float(sh)/img_h)
                        current_img_raw = pygame.transform.scale(img, (int(img_w*ratio), int(img_h*ratio)))
                        meta_data = get_sidecar_data(file_path)
                        zoom_factor = 1.0; alpha = 0; need_load = False; last_switch = now
                    except: current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                else:
                    screen.fill((0, 0, 0))
                    margin_h = 60
                    if internal_mode == MODE_VIDEOS_GAMES:
                        vm = parse_game_metadata(file_path)
                        t1 = font_small.render(vm["game"], True, (255, 255, 255))
                        t2 = font_small.render(vm["console"], True, (0, 255, 255)) # Uniformisé
                        sh1 = font_small.render(vm["game"], True, (0, 0, 0))
                        sh2 = font_small.render(vm["console"], True, (0, 0, 0))
                        screen.blit(sh1, (sw - t1.get_width() - 18, sh - 43))
                        screen.blit(t1, (sw - t1.get_width() - 20, sh - 45))
                        screen.blit(sh2, (22, sh - 43))
                        screen.blit(t2, (20, sh - 45))
                    else:
                        vm = get_sidecar_data(file_path)
                        label = vm.get("label", u"Vidéo Perso")
                        t1 = font_small.render(label, True, (255, 255, 255))
                        sh1 = font_small.render(label, True, (0, 0, 0))
                        screen.blit(sh1, (sw - t1.get_width() - 18, sh - 43))
                        screen.blit(t1, (sw - t1.get_width() - 20, sh - 45))
                        if vm.get("info"):
                            t2 = font_tiny.render(u"Durée : %s" % vm["info"], True, (200, 200, 200))
                            sh2 = font_tiny.render(u"Durée : %s" % vm["info"], True, (0, 0, 0))
                            screen.blit(sh2, (22, sh - 43))
                            screen.blit(t2, (20, sh - 45))
                    pygame.display.flip()
                    cmd = ["omxplayer", "-o", "both", "--no-osd", "--aspect-mode", "letterbox", "--win", "0,0,%d,%d" % (sw, sh - margin_h)]
                    if is_muted: cmd += ["--vol", "-6000"]
                    cmd.append(file_path)
                    video_proc = subprocess.Popen(cmd, preexec_fn=os.setsid); need_load = False

            if not need_load and not show_info and internal_mode == MODE_PHOTOS and now - last_switch > display_time:
                current_idx_ptr = (current_idx_ptr + 1) % len(indices); need_load = True

            # --- 5. AFFICHAGE ---
            if internal_mode == MODE_PHOTOS and current_img_raw and not need_load:
                screen.fill((0, 0, 0))
                if enable_animation and not show_info: zoom_factor += ZOOM_SPEED
                z_w, z_h = int(current_img_raw.get_width()*zoom_factor), int(current_img_raw.get_height()*zoom_factor)
                img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                if alpha < 255: alpha += FADE_SPEED
                img_to_draw.set_alpha(min(alpha, 255))
                screen.blit(img_to_draw, ((sw-z_w)//2, (sh-z_h)//2))
                
                if show_info:
                    ov_w, ov_h = sw * 0.7, sh * 0.12
                    overlay = pygame.Surface((ov_w, ov_h)); overlay.set_alpha(200); overlay.fill((15, 15, 15))
                    ox, oy = (sw-ov_w)//2, sh-ov_h-120
                    screen.blit(overlay, (ox, oy))
                    
                    label_raw = meta_data.get("label", u"Sans titre")
                    clean_label = label_raw.split(" - ")[0]
                    precise_date = meta_data.get("info", u"")
                    line1 = u"%s  (%s)" % (clean_label, precise_date)
                    screen.blit(font_small.render(line1, True, (255, 255, 255)), (ox + 15, oy + 10))
                    
                    path_rect = pygame.Rect(ox + 15, oy + 40, ov_w - 30, ov_h - 45)
                    draw_wrapped_text(screen, meta_data.get("source_path", u""), font_tiny, (170, 170, 170), path_rect)
                    
                    cnt = u"%ds" % int(max(0, info_timer - now))
                    ctxt = font_tiny.render(cnt, True, (200, 200, 100))
                    screen.blit(ctxt, (ox + ov_w - ctxt.get_width() - 10, oy + ov_h - 22))
                    
                    if last_detected_code and now < code_timer:
                        d_txt = font_tiny.render(u"Code: %d" % last_detected_code, True, (255, 215, 0))
                        screen.blit(d_txt, (ox + 15, oy + ov_h - 22))
                else:
                    if meta_data.get("label"):
                        label = meta_data["label"]
                        txt = font_small.render(label, True, (255, 255, 255)) # Uniformisé
                        shd = font_small.render(label, True, (0, 0, 0))
                        tx, ty = sw-txt.get_width()-30, sh-txt.get_height()-30
                        screen.blit(shd, (tx+2, ty+2)); screen.blit(txt, (tx, ty))

                    hy = sh - 35
                    if now < speed_overlay_timer:
                        img_per_min = int(round(60.0 / display_time))
                        screen.blit(font_small.render(u"%d images / min" % img_per_min, True, (255, 230, 0)), (20, hy))

            # OVERLAYS CENTRÉS
            if now < mode_overlay_timer:
                screen.fill((0, 0, 0)) # S'assurer que le fond est noir pendant la transition
                mns = {MODE_PHOTOS: u"Photos", MODE_VIDEOS_PERSO: u"Vidéos", MODE_VIDEOS_GAMES: u"Jeux", MODE_CYCLE: u"Cycle Auto"}
                txt = font_main.render(u"Mode : %s" % mns.get(current_mode), True, (0, 255, 255))
                screen.blit(txt, ((sw - txt.get_width()) // 2, (sh - txt.get_height()) // 2))
                
            if now < mute_overlay_timer:
                mtx = u"Son : Coupé" if is_muted else u"Son : Actif"
                txt = font_main.render(mtx, True, (255, 100, 100))
                screen.blit(txt, ((sw - txt.get_width()) // 2, sh // 2 + 50))

            pygame.display.flip()
            time.sleep(0.04)
    finally:
        if video_proc: stop_video(video_proc)
        for f in input_files: f.close()
        pygame.quit(); sys.exit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-animation", action="store_true")
    args = parser.parse_args()
    run_slideshow(enable_animation=not args.no_animation)
