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

# --- CONFIGURATION PAR DÉFAUT ---
INFO_BUTTON_DEFAULT = 289
MODE_BUTTON_DEFAULT = 304 
IMAGE_FOLDER = "/recalbox/share/userscripts/slideshow/images" 
VIDEO_PERSO_FOLDER = "/recalbox/share/userscripts/slideshow/videos"
ROMS_FOLDER = "/recalbox/share/roms"
SETTINGS_FILE = "/recalbox/share/userscripts/slideshow/slideshow_settings.json"

DEFAULT_DISPLAY_TIME = 15 
MIN_DISPLAY_TIME = 2
MAX_DISPLAY_TIME = 120
ZOOM_SPEED = 0.00015
FADE_SPEED = 8

# Modes
MODE_PHOTOS = 1
MODE_VIDEOS_PERSO = 2
MODE_VIDEOS_GAMES = 3

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
        except Exception:
            pass
    return {"display_time": DEFAULT_DISPLAY_TIME, "info_button": INFO_BUTTON_DEFAULT, "mode_button": MODE_BUTTON_DEFAULT, "current_mode": MODE_PHOTOS, "is_muted": False}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception:
        pass

def get_sidecar_data(file_path):
    """Lit le fichier .txt associé pour obtenir Label, Date/Durée, Source."""
    txt_path = os.path.splitext(file_path)[0] + ".txt"
    data = {"label": u"", "info": u"", "source_path": u""}
    if os.path.exists(txt_path):
        try:
            with open(txt_path, 'r') as f:
                lines = f.readlines()
                if len(lines) >= 1: data["label"] = lines[0].strip().decode('utf-8', 'ignore')
                if len(lines) >= 2: data["info"] = lines[1].strip().decode('utf-8', 'ignore')
                if len(lines) >= 3: data["source_path"] = lines[2].strip().decode('utf-8', 'ignore')
        except Exception: pass
    return data

def parse_game_metadata(file_path):
    parts = file_path.split('/')
    console = u"Inconnu"
    try:
        if "roms" in parts:
            idx = parts.index("roms")
            if len(parts) > idx + 1:
                console = parts[idx+1].upper()
    except Exception: pass
    game_name = os.path.splitext(os.path.basename(file_path))[0]
    if hasattr(game_name, 'decode'): game_name = game_name.decode('utf-8', 'ignore')
    return {"console": console, "game": game_name}

def get_input_devices():
    return glob.glob('/dev/input/event*')

def stop_video(proc):
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
        except Exception: pass

def run_slideshow(enable_animation=True):
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_NOMOUSE"] = "1"
    
    settings = load_settings()
    display_time = settings.get("display_time", DEFAULT_DISPLAY_TIME)
    info_button_code = settings.get("info_button", INFO_BUTTON_DEFAULT)
    mode_button_code = settings.get("mode_button", MODE_BUTTON_DEFAULT)
    current_mode = settings.get("current_mode", MODE_PHOTOS)
    is_muted = settings.get("is_muted", False)
    
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
        except Exception: pass

    event_format = 'llHHi' 
    event_size = struct.calcsize(event_format)

    info = pygame.display.Info()
    sw, sh = info.current_w, info.current_h
    if sw == 0 or sh == 0: sw, sh = 1280, 1024 
    
    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    
    font_main = pygame.font.Font(None, int(sh * 0.05))
    font_small = pygame.font.Font(None, int(sh * 0.03))
    font_tiny = pygame.font.Font(None, int(sh * 0.025))

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
                            if f.lower().endswith(('.mp4', '.mkv', '.avi')):
                                vids.append(os.path.join(root, f))
            return sorted(vids)
        return []

    all_files = get_files_for_mode(current_mode)
    indices = range(len(all_files))
    random.shuffle(indices)
    current_idx_ptr = 0

    running = True
    need_load = True
    last_switch = time.time()
    
    current_img_raw = None
    zoom_factor = 1.0; alpha = 0; meta_data = {}
    
    show_info = False; info_timer = 0; INFO_DURATION = 15
    last_detected_code = 0; code_timer = 0
    speed_overlay_timer = 0; mode_overlay_timer = 0; mute_overlay_timer = 0
    OVERLAY_DURATION = 3

    last_nav_time = 0; last_speed_time = 0
    video_proc = None

    try:
        while running:
            now = time.time()
            
            # --- 1. ENTRÉES ---
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
                                    if current_mode == MODE_PHOTOS:
                                        show_info = True
                                        info_timer = now + INFO_DURATION
                                    else:
                                        is_muted = not is_muted
                                        mute_overlay_timer = now + OVERLAY_DURATION
                                        settings["is_muted"] = is_muted
                                        save_settings(settings)
                                        if video_proc: 
                                            stop_video(video_proc)
                                            video_proc = None
                                            need_load = True
                                elif ev_code == mode_button_code:
                                    current_mode = (current_mode % 3) + 1
                                    all_files = get_files_for_mode(current_mode)
                                    indices = range(len(all_files))
                                    random.shuffle(indices)
                                    current_idx_ptr = 0
                                    need_load = True
                                    mode_overlay_timer = now + OVERLAY_DURATION
                                    settings["current_mode"] = current_mode
                                    save_settings(settings)
                                    if video_proc:
                                        stop_video(video_proc)
                                        video_proc = None
                                else:
                                    running = False
                                    break
                        data = f.read(event_size)
                except Exception: pass
            
            if not running: break
            
            # --- 2. ÉVÉNEMENTS SDL ---
            for event in pygame.event.get():
                if event.type in (pygame.QUIT, pygame.KEYDOWN):
                    running = False
                
                if not show_info:
                    if current_mode == MODE_PHOTOS and now - last_speed_time > 0.15:
                        change = 0
                        if event.type == pygame.JOYAXISMOTION and event.axis == 1:
                            if event.value < -0.6: change = -1
                            elif event.value > 0.6: change = 1
                        elif event.type == pygame.JOYHATMOTION and event.value[1] != 0:
                            change = -event.value[1]
                        if change != 0:
                            display_time = max(MIN_DISPLAY_TIME, min(MAX_DISPLAY_TIME, display_time + change))
                            last_speed_time = now
                            speed_overlay_timer = now + OVERLAY_DURATION
                            settings["display_time"] = display_time
                            save_settings(settings)

                    if now - last_nav_time > 0.4:
                        steer = 0
                        if event.type == pygame.JOYAXISMOTION and event.axis == 0:
                            if abs(event.value) > 0.6: steer = 1 if event.value > 0.6 else -1
                        elif event.type == pygame.JOYHATMOTION and event.value[0] != 0:
                            steer = event.value[0]
                        if steer != 0:
                            current_idx_ptr = (current_idx_ptr + steer) % len(indices)
                            need_load = True
                            last_nav_time = now
                            if video_proc:
                                stop_video(video_proc)
                                video_proc = None

            # --- 3. LOGIQUE ---
            if video_proc:
                if video_proc.poll() is not None:
                    video_proc = None
                    current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                    need_load = True

            if not need_load and not show_info and current_mode == MODE_PHOTOS and now - last_switch > display_time:
                current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                need_load = True

            if need_load:
                if not indices:
                    screen.fill((0, 0, 0))
                    msg = u"Mode %d : Aucun fichier" % current_mode
                    txt = font_main.render(msg, True, (255, 100, 100))
                    screen.blit(txt, ((sw - txt.get_width())//2, (sh - txt.get_height())//2))
                    pygame.display.flip(); time.sleep(2); need_load = False; continue

                file_path = all_files[indices[current_idx_ptr]]

                if current_mode == MODE_PHOTOS:
                    try:
                        img = pygame.image.load(file_path).convert()
                        img_w, img_h = img.get_size()
                        ratio = min(float(sw)/img_w, float(sh)/img_h)
                        current_img_raw = pygame.transform.scale(img, (int(img_w*ratio), int(img_h*ratio)))
                        meta_data = get_sidecar_data(file_path)
                        zoom_factor = 1.0; alpha = 0; need_load = False; last_switch = now
                    except Exception: current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                else:
                    # VIDEO
                    screen.fill((0, 0, 0))
                    margin_h = 60
                    if current_mode == MODE_VIDEOS_GAMES:
                        vm = parse_game_metadata(file_path)
                        t1 = font_small.render(vm["game"], True, (255, 255, 255))
                        t2 = font_tiny.render(vm["console"], True, (0, 255, 255))
                        screen.blit(t1, (sw - t1.get_width() - 20, sh - 55))
                        screen.blit(t2, (20, sh - 45))
                    else:
                        # Mode 2 : Vidéos Perso - Utilisation du sidecar généré par le RPi
                        vm = get_sidecar_data(file_path)
                        label = vm.get("label", u"Vidéo Perso")
                        duration = vm.get("info", u"")
                        t1 = font_small.render(label, True, (255, 255, 255))
                        screen.blit(t1, (sw - t1.get_width() - 20, sh - 55))
                        if duration:
                            t2 = font_tiny.render(u"Durée : %s" % duration, True, (200, 200, 200))
                            screen.blit(t2, (20, sh - 45))
                    
                    pygame.display.flip()
                    
                    cmd = ["omxplayer", "-o", "both", "--no-osd", "--win", "0,0,%d,%d" % (sw, sh - margin_h)]
                    if is_muted: cmd += ["--vol", "-6000"]
                    cmd.append(file_path)
                    
                    video_proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
                    need_load = False

            # --- 4. AFFICHAGE ---
            if current_mode == MODE_PHOTOS and current_img_raw:
                screen.fill((0, 0, 0))
                if enable_animation and not show_info: zoom_factor += ZOOM_SPEED
                z_w, z_h = int(current_img_raw.get_width()*zoom_factor), int(current_img_raw.get_height()*zoom_factor)
                img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                if alpha < 255: alpha += FADE_SPEED
                img_to_draw.set_alpha(min(alpha, 255))
                screen.blit(img_to_draw, ((sw-z_w)//2, (sh-z_h)//2))
                
                if show_info:
                    ov_w, ov_h = sw * 0.5, sh * 0.25
                    overlay = pygame.Surface((ov_w, ov_h)); overlay.set_alpha(200); overlay.fill((15, 15, 15))
                    ox, oy = (sw-ov_w)//2, sh-ov_h-120
                    screen.blit(overlay, (ox, oy))
                    lines = [meta_data.get("label", u"Sans lieu"), meta_data.get("info", u"Date inconnue"), u"Retour auto : %ds" % int(max(0, info_timer-now))]
                    for i, line in enumerate(lines):
                        c = (255,255,255) if i < 2 else (200,200,100)
                        txt = font_small.render(line, True, c)
                        screen.blit(txt, (ox+20, oy+20+i*35))
                    if last_detected_code and now < code_timer:
                        d_txt = font_tiny.render(u"Touche : %d" % last_detected_code, True, (255, 255, 0))
                        screen.blit(d_txt, (ox+ov_w-d_txt.get_width()-15, oy+ov_h-25))
                else:
                    if meta_data.get("label"):
                        txt = font_main.render(meta_data["label"], True, (255, 255, 255))
                        shd = font_main.render(meta_data["label"], True, (0, 0, 0))
                        tx, ty = sw-txt.get_width()-30, sh-txt.get_height()-30
                        screen.blit(shd, (tx+2, ty+2)); screen.blit(txt, (tx, ty))
                    hy = sh - 35
                    if now < speed_overlay_timer:
                        img_per_min = int(60.0 / display_time)
                        screen.blit(font_small.render(u"%d images / min" % img_per_min, True, (255, 230, 0)), (20, hy)); hy -= 35
                    if now < mode_overlay_timer:
                        mn = {MODE_PHOTOS: u"PHOTOS", MODE_VIDEOS_PERSO: u"VIDÉOS", MODE_VIDEOS_GAMES: u"JEUX"}
                        screen.blit(font_small.render(u"MODE : %s" % mn.get(current_mode), True, (0, 255, 255)), (20, hy))
                pygame.display.flip()

            elif current_mode != MODE_PHOTOS:
                hy = sh - 35
                if (now < mute_overlay_timer) or (now < mode_overlay_timer):
                    if now < mute_overlay_timer:
                        m_txt = u"SON : COUPE" if is_muted else u"SON : ACTIF"
                        screen.blit(font_small.render(m_txt, True, (255, 100, 100)), (20, hy)); hy -= 35
                    if now < mode_overlay_timer:
                        mn = {MODE_VIDEOS_PERSO: u"VIDÉOS", MODE_VIDEOS_GAMES: u"JEUX"}
                        screen.blit(font_small.render(u"MODE : %s" % mn.get(current_mode), True, (0, 255, 255)), (20, hy))
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
