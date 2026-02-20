#!/usr/bin/python
# -*- coding: utf-8 -*-

import pygame
import os
import time
import sys

# --- CONFIGURATION ---
IMAGE_FOLDER = "/recalbox/share/userscripts/slideshow/images" 
DISPLAY_TIME = 15 
ZOOM_SPEED = 0.0002  # Zoom speed (per frame)

def get_sidecar_text(image_path):
    """Reads the associated .txt file for a given image."""
    txt_path = os.path.splitext(image_path)[0] + ".txt"
    if os.path.exists(txt_path):
        try:
            with open(txt_path, 'r') as f:
                content = f.read()
                # Python 2/3 compatibility for decoding
                if hasattr(content, 'decode'):
                    return content.decode('utf-8').strip()
                return content.strip()
        except Exception:
            pass
    return ""

def run_slideshow():
    # Recalbox / FBcon specific settings
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_NOMOUSE"] = "1"
    
    pygame.init()
    
    # Get screen resolution
    info = pygame.display.Info()
    sw, sh = info.current_w, info.current_h
    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    
    # Load font
    font = pygame.font.Font(None, int(sh * 0.05))

    # List only JPEG images
    files = sorted([os.path.join(IMAGE_FOLDER, f) for f in os.listdir(IMAGE_FOLDER) if f.lower().endswith('.jpg')])
    if not files:
        print("No images found in " + IMAGE_FOLDER)
        return

    idx = 0
    running = True
    need_load = True
    last_switch = time.time()
    
    # Animation variables
    current_img_raw = None
    zoom_factor = 1.0
    alpha = 0
    txt_surf = None
    txt_shadow = None
    txt_str = ""

    while running:
        now = time.time()
        
        # Event handling
        for event in pygame.event.get():
            if event.type in (pygame.QUIT, pygame.JOYBUTTONDOWN, pygame.KEYDOWN):
                running = False

        # Switch image after DISPLAY_TIME
        if not need_load and now - last_switch > DISPLAY_TIME:
            idx = (idx + 1) % len(files)
            need_load = True

        if need_load:
            try:
                # Load and initial scale (Fit to screen)
                img = pygame.image.load(files[idx]).convert()
                img_w, img_h = img.get_size()
                ratio = min(float(sw)/img_w, float(sh)/img_h)
                current_img_raw = pygame.transform.scale(img, (int(img_w*ratio), int(img_h*ratio)))
                
                # Metadata text
                txt_str = get_sidecar_text(files[idx])
                if txt_str:
                    txt_surf = font.render(txt_str, True, (255, 255, 255))
                    txt_shadow = font.render(txt_str, True, (0, 0, 0))
                
                zoom_factor = 1.0
                alpha = 0
                need_load = False
                last_switch = now
            except Exception as e:
                print("Error loading image: " + str(e))
                idx = (idx + 1) % len(files)

        # Rendering & Animation
        if current_img_raw:
            screen.fill((0, 0, 0))
            
            # Subtle Ken Burns effect (Zoom)
            zoom_factor += ZOOM_SPEED
            z_w = int(current_img_raw.get_width() * zoom_factor)
            z_h = int(current_img_raw.get_height() * zoom_factor)
            
            # Rescale for zoom
            img_zoomed = pygame.transform.scale(current_img_raw, (z_w, z_h))
            
            # Center on screen
            pos_x = (sw - z_w) // 2
            pos_y = (sh - z_h) // 2
            
            # Fade-in effect
            if alpha < 255:
                alpha += 10
            img_zoomed.set_alpha(min(alpha, 255))
            
            screen.blit(img_zoomed, (pos_x, pos_y))
            
            # Draw metadata text with shadow
            if txt_str and txt_surf:
                tx = sw - txt_surf.get_width() - 30
                ty = sh - txt_surf.get_height() - 30
                screen.blit(txt_shadow, (tx+2, ty+2))
                screen.blit(txt_surf, (tx, ty))

            pygame.display.flip()
        
        time.sleep(0.02) # Target ~50 FPS

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    run_slideshow()
