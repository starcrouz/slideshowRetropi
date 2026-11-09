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
import math

# --- CONFIGURATION PAR DÉFAUT ---
# Boutons du dessus (Panel Arcade J1/J2 : A, B, X, Y, L1, R1 -> 288..293 et 304..311)
TOP_BUTTONS_DEFAULT = [288, 289, 290, 291, 292, 293, 304, 305, 306, 307, 308, 309, 310, 311]
# Boutons de devant (Façade : Start, Select, Coin, Hotkey -> 294..299 et 312..318)
FRONT_BUTTONS_DEFAULT = [294, 295, 296, 297, 298, 299, 312, 313, 314, 315, 316, 317, 318]

IMAGE_FOLDER = "/recalbox/share/userscripts/slideshow/images"
VIDEO_PERSO_FOLDER = "/recalbox/share/userscripts/slideshow/videos"
ROMS_FOLDER = "/recalbox/share/roms"
SETTINGS_FILE = "/recalbox/share/userscripts/slideshow/slideshow_settings.json"

DEFAULT_DISPLAY_TIME = 15
MIN_DISPLAY_TIME = 1
MAX_DISPLAY_TIME = 120
DISPLAY_TIME_PRESETS = [5, 8, 10, 12, 15, 20, 30, 45, 60]
ZOOM_SPEED = 0.00015
FADE_SPEED = 8
CROSSFADE_SPEED = 15

# Styles d'affichage des photos
STYLE_AUTO_ART = "auto_art"
STYLE_MODERN = "modern"
STYLE_BENTO = "bento"
STYLE_POLAROID = "polaroid"
STYLE_MAGAZINE = "magazine"
STYLE_ARCADE = "arcade"
STYLE_CLASSIC = "classic"

STYLE_ORDER = [
    STYLE_AUTO_ART,
    STYLE_MODERN,
    STYLE_BENTO,
    STYLE_POLAROID,
    STYLE_MAGAZINE,
    STYLE_ARCADE,
    STYLE_CLASSIC
]

ARTISTIC_POOL = [
    STYLE_MODERN,
    STYLE_BENTO,
    STYLE_POLAROID,
    STYLE_MAGAZINE,
    STYLE_ARCADE
]

STYLE_SHORT_LABELS = {
    STYLE_AUTO_ART: u"Mix Artistique (Auto)",
    STYLE_MODERN: u"Ambilight & Duo",
    STYLE_BENTO: u"Mosaïque Bento (3 photos)",
    STYLE_POLAROID: u"Polaroid Vintage",
    STYLE_MAGAZINE: u"Magazine Plein Écran",
    STYLE_ARCADE: u"Néon Bartop (Arcade)",
    STYLE_CLASSIC: u"Classique (Origine)"
}

STYLE_TITLES = {
    STYLE_AUTO_ART: (u"Style : Mix Artistique (Auto)", u"Varie automatiquement entre tous les styles modernes", (168, 85, 247)),
    STYLE_MODERN: (u"Style : Ambilight & Duo", u"Grand cadre 96% sur fond flouté & Diptyque portraits", (99, 179, 237)),
    STYLE_BENTO: (u"Style : Mosaïque Bento", u"Composition dynamique de 3 photos simultanées", (52, 211, 153)),
    STYLE_POLAROID: (u"Style : Polaroid Vintage", u"Photos instantanées inclinées & teinte chaude", (251, 191, 36)),
    STYLE_MAGAZINE: (u"Style : Magazine Plein Écran", u"Immersion 100% sans bordures & typographie XXL", (244, 114, 182)),
    STYLE_ARCADE: (u"Style : Néon Bartop (Arcade)", u"Cadres néon lumineux Cyan/Magenta & scanlines", (0, 240, 255)),
    STYLE_CLASSIC: (u"Style : Classique (Origine)", u"Affichage historique sur fond noir & scroll vertical", (200, 205, 215))
}

# Probabilité d'afficher un Duo quand une photo verticale est tirée en mode Moderne / Arcade
DUO_PORTRAIT_PROBABILITY = 0.70

# Modes
MODE_PHOTOS = 1
MODE_VIDEOS_PERSO = 2
MODE_VIDEOS_GAMES = 3
MODE_CYCLE = 4
CYCLE_INTERVAL = 60

MODE_NAMES = {
    MODE_PHOTOS: u"Photos",
    MODE_VIDEOS_PERSO: u"Vidéos Perso",
    MODE_VIDEOS_GAMES: u"Jeux (Roms)",
    MODE_CYCLE: u"Cycle Auto (60s)"
}

# Input event constants
EV_KEY = 1
EV_ABS = 3
ABS_X = 0
ABS_Y = 1
ABS_HAT0X = 16
ABS_HAT0Y = 17


def load_settings():
    defaults = {
        "display_time": DEFAULT_DISPLAY_TIME,
        "top_buttons": list(TOP_BUTTONS_DEFAULT),
        "front_buttons": list(FRONT_BUTTONS_DEFAULT),
        "current_mode": MODE_CYCLE,
        "photo_style": STYLE_AUTO_ART,
        "is_muted": True
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
        except Exception:
            pass
    if defaults.get("photo_style") not in STYLE_ORDER:
        defaults["photo_style"] = STYLE_AUTO_ART
    if not isinstance(defaults.get("top_buttons"), list) or not defaults.get("top_buttons"):
        defaults["top_buttons"] = list(TOP_BUTTONS_DEFAULT)
    if not isinstance(defaults.get("front_buttons"), list) or not defaults.get("front_buttons"):
        defaults["front_buttons"] = list(FRONT_BUTTONS_DEFAULT)
    return defaults


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception:
        pass


def get_sidecar_data(file_path):
    txt_path = os.path.splitext(file_path)[0] + ".txt"
    data = {"label": u"", "info": u"", "source_path": u""}
    if os.path.exists(txt_path):
        try:
            with open(txt_path, 'r') as f:
                content = f.read()
                if hasattr(content, 'decode'):
                    content = content.decode('utf-8', 'ignore')
                lines = [l.strip() for l in content.split('\n')]
                if len(lines) >= 1:
                    data["label"] = lines[0]
                if len(lines) >= 2:
                    data["info"] = lines[1]
                if len(lines) >= 3:
                    data["source_path"] = lines[2]
        except Exception:
            pass
    return data


def write_current_state(data):
    current_json_path = "/recalbox/share/userscripts/slideshow/current.json"
    try:
        with open(current_json_path, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def clean_game_name(name):
    cleaned = re.sub(r'[\(\[].*?[\)\]]', '', name)
    cleaned = cleaned.replace('_', ' ').strip()
    if cleaned.lower().endswith(", the"):
        cleaned = "The " + cleaned[:-5].strip()
    return cleaned.title()


def parse_game_metadata(file_path):
    parts = file_path.split('/')
    console = u"Inconnu"
    try:
        if "roms" in parts:
            idx = parts.index("roms")
            if len(parts) > idx + 1:
                console = parts[idx + 1].upper()
    except Exception:
        pass
    bname = os.path.splitext(os.path.basename(file_path))[0]
    if hasattr(bname, 'decode'):
        bname = bname.decode('utf-8', 'ignore')
    game_name = clean_game_name(bname)
    return {"console": console, "game": game_name}


def get_input_devices():
    return glob.glob('/dev/input/event*')


def stop_video(proc):
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
        except Exception:
            pass


def load_best_font(size, bold=False):
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, int(size))
            except Exception:
                pass
    return pygame.font.Font(None, int(size * 1.15))


def draw_rounded_rect(surface, color, rect, radius):
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    if w <= 0 or h <= 0:
        return
    r = int(min(radius, w // 2, h // 2))
    if r <= 1:
        pygame.draw.rect(surface, color, (x, y, w, h))
        return
    pygame.draw.rect(surface, color, (x + r, y, w - 2 * r, h))
    pygame.draw.rect(surface, color, (x, y + r, r, h - 2 * r))
    pygame.draw.rect(surface, color, (x + w - r, y + r, r, h - 2 * r))
    pygame.draw.circle(surface, color, (x + r, y + r), r)
    pygame.draw.circle(surface, color, (x + w - r, y + r), r)
    pygame.draw.circle(surface, color, (x + r, y + h - r), r)
    pygame.draw.circle(surface, color, (x + w - r, y + h - r), r)


def create_rounded_box(w, h, radius, bg_color, border_color=None, alpha=210, border_width=2):
    w, h = max(4, int(w)), max(4, int(h))
    r = int(min(radius, w // 2, h // 2))
    surf = pygame.Surface((w, h)).convert()
    ck = (255, 0, 255)
    surf.fill(ck)
    surf.set_colorkey(ck)

    if border_color and r > border_width:
        draw_rounded_rect(surf, border_color, (0, 0, w, h), r)
        draw_rounded_rect(
            surf,
            bg_color,
            (border_width, border_width, w - 2 * border_width, h - 2 * border_width),
            max(1, r - border_width)
        )
    else:
        draw_rounded_rect(surf, bg_color, (0, 0, w, h), r)

    if alpha < 255:
        surf.set_alpha(alpha)
    return surf


def safe_smoothscale(surf, size):
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    try:
        if surf.get_bitsize() not in (24, 32):
            surf = surf.convert(24)
        return pygame.transform.smoothscale(surf, (w, h))
    except Exception:
        return pygame.transform.scale(surf, (w, h))


def crop_to_aspect(surf, target_w, target_h):
    iw, ih = surf.get_size()
    if iw <= 0 or ih <= 0 or target_w <= 0 or target_h <= 0:
        return surf
    target_ratio = float(target_w) / float(target_h)
    img_ratio = float(iw) / float(ih)
    if img_ratio > target_ratio:
        new_w = max(1, int(ih * target_ratio))
        x0 = (iw - new_w) // 2
        return surf.subsurface((x0, 0, new_w, ih)).copy()
    else:
        new_h = max(1, int(iw / target_ratio))
        y0 = (ih - new_h) // 2
        return surf.subsurface((0, y0, iw, new_h)).copy()


def make_vignette_surface(sw, sh):
    """Pré-calcule une vignette radiale douce (utilisable via BLEND_RGB_MULT)."""
    vw, vh = 64, 48
    small = pygame.Surface((vw, vh), 0, 24)
    cx, cy = vw / 2.0, vh / 2.0
    max_d = math.sqrt(cx * cx + cy * cy)
    for y in range(vh):
        for x in range(vw):
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_d
            val = int(max(115, min(255, 265 - (d ** 1.8) * 145)))
            small.set_at((x, y), (val, val, val))
    return safe_smoothscale(small, (sw, sh)).convert()


def make_bottom_gradient(sw, grad_h):
    """Pré-calcule un dégradé vertical sombre pour le bas de l'écran (style Magazine)."""
    gh = max(16, int(grad_h))
    small = pygame.Surface((16, 64), 0, 24)
    for y in range(64):
        t = float(y) / 63.0
        # Courbe douce : 255 en haut -> 28 en bas
        val = int(255 - (t ** 1.35) * 227)
        small.fill((val, val, int(min(255, val * 1.04))), (0, y, 16, 1))
    return safe_smoothscale(small, (sw, gh)).convert()


def make_scanline_overlay(sw, sh):
    """Pré-calcule une trame subtile de scanlines arcade pour le mode Néon Bartop."""
    surf = pygame.Surface((sw, sh)).convert()
    surf.fill((255, 255, 255))
    for y in range(0, sh, 3):
        pygame.draw.line(surf, (205, 205, 220), (0, y), (sw, y), 1)
    return surf


def make_blurred_background(img1, sw, sh, img2=None, tint=(125, 128, 138), vignette_surf=None):
    """Génère un fond flouté Ambilight (solo ou duo fusionné) rapide et assombri."""
    work_w, work_h = max(16, sw // 6), max(12, sh // 6)
    base24 = pygame.Surface((work_w, work_h), 0, 24)

    if img2 is None:
        cropped = crop_to_aspect(img1, sw, sh)
        scaled = safe_smoothscale(cropped, (work_w, work_h))
        base24.blit(scaled, (0, 0))
    else:
        half_w = work_w // 2
        c1 = crop_to_aspect(img1, sw // 2, sh)
        c2 = crop_to_aspect(img2, sw - sw // 2, sh)
        s1 = safe_smoothscale(c1, (half_w, work_h))
        s2 = safe_smoothscale(c2, (work_w - half_w, work_h))
        base24.blit(s1, (0, 0))
        base24.blit(s2, (half_w, 0))

    tiny1 = safe_smoothscale(base24, (max(8, sw // 32), max(6, sh // 32)))
    tiny2 = safe_smoothscale(tiny1, (max(6, sw // 44), max(5, sh // 44)))
    mid = safe_smoothscale(tiny2, (max(16, sw // 10), max(12, sh // 10)))
    bg = safe_smoothscale(mid, (sw, sh)).convert()

    dark = pygame.Surface((sw, sh)).convert()
    dark.fill(tint)
    bg.blit(dark, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    if vignette_surf is not None:
        bg.blit(vignette_surf, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    return bg


def bake_card_frame_on_bg(bg_surf, fx, fy, fw, fh, border_px=4, frame_color=(242, 244, 248)):
    """Dessine une ombre portée douce et un cadre autour d'un emplacement photo."""
    sh1 = create_rounded_box(fw + 28, fh + 28, 14, (0, 0, 0), alpha=40)
    sh2 = create_rounded_box(fw + 18, fh + 18, 10, (0, 0, 0), alpha=75)
    sh3 = create_rounded_box(fw + 10, fh + 10, 7, (0, 0, 0), alpha=115)
    bg_surf.blit(sh1, (fx - 14, fy - 8))
    bg_surf.blit(sh2, (fx - 9, fy - 3))
    bg_surf.blit(sh3, (fx - 5, fy + 2))

    if border_px > 0:
        frame_rect = (
            fx - border_px,
            fy - border_px,
            fw + 2 * border_px,
            fh + 2 * border_px
        )
        draw_rounded_rect(bg_surf, frame_color, frame_rect, border_px + 2)


def bake_neon_frame_on_bg(bg_surf, fx, fy, fw, fh, neon_color=(0, 240, 255)):
    """Dessine un halo lumineux néon et un double cadre rétro-arcade."""
    g1 = create_rounded_box(fw + 36, fh + 36, 18, neon_color, alpha=28)
    g2 = create_rounded_box(fw + 22, fh + 22, 13, neon_color, alpha=60)
    g3 = create_rounded_box(fw + 12, fh + 12, 9, neon_color, alpha=115)
    bg_surf.blit(g1, (fx - 18, fy - 18))
    bg_surf.blit(g2, (fx - 11, fy - 11))
    bg_surf.blit(g3, (fx - 6, fy - 6))

    draw_rounded_rect(bg_surf, neon_color, (fx - 4, fy - 4, fw + 8, fh + 8), 6)
    draw_rounded_rect(bg_surf, (235, 250, 255), (fx - 2, fy - 2, fw + 4, fh + 4), 4)


def apply_warm_vintage_grade(surf):
    """Applique une teinte pellicule chaude (Kodak Gold) très rapide."""
    graded = surf.copy().convert()
    warm_mult = pygame.Surface(graded.get_size()).convert()
    warm_mult.fill((255, 244, 226))
    graded.blit(warm_mult, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    warm_add = pygame.Surface(graded.get_size()).convert()
    warm_add.fill((12, 7, 0))
    graded.blit(warm_add, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    return graded


def make_polaroid_surface(raw_img, meta, target_w, target_h, angle, font_title, font_sub):
    """Construit un vrai Polaroid (cadre papier crème, photo aux tons chauds, légende sur le bas et rotation)."""
    pad_side = max(10, int(target_w * 0.038))
    pad_top = pad_side
    pad_bot = max(46, int(target_h * 0.145))

    inner_w = max(40, target_w - 2 * pad_side)
    inner_h = max(40, target_h - pad_top - pad_bot)

    cropped = crop_to_aspect(raw_img, inner_w, inner_h)
    photo_scaled = safe_smoothscale(cropped, (inner_w, inner_h)).convert()
    photo_warm = apply_warm_vintage_grade(photo_scaled)

    card_w = inner_w + 2 * pad_side
    card_h = inner_h + pad_top + pad_bot

    # Surface 32-bit RGBA pour que rotozoom produise des bords inclinés parfaitement lissés
    pol = pygame.Surface((card_w + 24, card_h + 24), pygame.SRCALPHA, 32)
    pol.fill((0, 0, 0, 0))

    # Ombre portée douce sous le Polaroid
    pygame.draw.rect(pol, (0, 0, 0, 45), (14, 16, card_w, card_h))
    pygame.draw.rect(pol, (0, 0, 0, 85), (10, 12, card_w, card_h))

    # Papier Polaroid crème/ivoire
    bx, by = 6, 6
    pygame.draw.rect(pol, (246, 243, 234, 255), (bx, by, card_w, card_h))
    pygame.draw.rect(pol, (215, 210, 198, 255), (bx, by, card_w, card_h), 1)

    # Photo + fin liseré intérieur
    px, py = bx + pad_side, by + pad_top
    pol.blit(photo_warm, (px, py))
    pygame.draw.rect(pol, (180, 175, 165, 255), (px - 1, py - 1, inner_w + 2, inner_h + 2), 1)

    # Légende style encre sur le talon inférieur du Polaroid
    label = meta.get("label", u"") if meta else u""
    if label:
        if u" - " in label:
            loc_str, date_str = label.split(u" - ", 1)
        else:
            loc_str, date_str = label, u""
        loc_fit = truncate_text_to_width(loc_str.strip(), font_title, inner_w - 10)
        t_loc = font_title.render(loc_fit, True, (32, 35, 42))
        chin_cy = by + pad_top + inner_h + pad_bot // 2
        if date_str.strip():
            t_date = font_sub.render(date_str.strip(), True, (130, 90, 60))
            total_th = t_loc.get_height() + t_date.get_height() + 2
            y0 = chin_cy - total_th // 2
            pol.blit(t_loc, (bx + (card_w - t_loc.get_width()) // 2, y0))
            pol.blit(t_date, (bx + (card_w - t_date.get_width()) // 2, y0 + t_loc.get_height() + 2))
        else:
            pol.blit(t_loc, (bx + (card_w - t_loc.get_width()) // 2, chin_cy - t_loc.get_height() // 2))

    if abs(angle) > 0.2:
        try:
            return pygame.transform.rotozoom(pol, angle, 1.0)
        except Exception:
            return pol
    return pol


def truncate_text_to_width(text, font, max_w):
    if font.size(text)[0] <= max_w:
        return text
    ellipsis = u"..."
    avail = max_w - font.size(ellipsis)[0]
    if avail <= 0:
        return ellipsis
    trimmed = text
    while len(trimmed) > 1 and font.size(trimmed)[0] > avail:
        trimmed = trimmed[:-1]
    return trimmed.strip() + ellipsis


def build_caption_badge(label, font_loc, font_date, max_width, border_color=(72, 82, 112), dot_color=(99, 179, 237), date_color=(250, 204, 21)):
    """Prépare les éléments visuels d'un cartouche moderne (fond arrondi + textes)."""
    if not label:
        return None

    if u" - " in label:
        parts = label.split(u" - ", 1)
        loc_str = parts[0].strip()
        date_str = parts[1].strip()
    else:
        loc_str = label.strip()
        date_str = u""

    pad_x = 18
    pad_y = 9
    dot_r = 5
    dot_space = dot_r * 2 + 10
    has_sep = bool(loc_str and date_str)
    sep_space = 22 if has_sep else 0

    date_surf = font_date.render(date_str, True, date_color) if date_str else None

    extra_w = pad_x * 2 + dot_space + sep_space
    if date_surf:
        extra_w += date_surf.get_width()

    avail_loc_w = max(60, max_width - extra_w)
    loc_str_fit = truncate_text_to_width(loc_str, font_loc, avail_loc_w)
    loc_surf = font_loc.render(loc_str_fit, True, (255, 255, 255))

    content_h = max(
        loc_surf.get_height(),
        date_surf.get_height() if date_surf else 0
    )
    pill_w = min(max_width, extra_w + loc_surf.get_width())
    pill_h = content_h + pad_y * 2

    pill_bg = create_rounded_box(
        pill_w,
        pill_h,
        pill_h // 2,
        (14, 17, 26),
        border_color=border_color,
        alpha=215,
        border_width=2
    )

    return {
        "bg": pill_bg,
        "w": pill_w,
        "h": pill_h,
        "pad_x": pad_x,
        "dot_r": dot_r,
        "dot_color": dot_color,
        "dot_space": dot_space,
        "has_sep": has_sep,
        "sep_space": sep_space,
        "loc_surf": loc_surf,
        "date_surf": date_surf
    }


def draw_caption_badge(screen, badge, center_x, bottom_y):
    if not badge:
        return
    px = int(center_x - badge["w"] // 2)
    py = int(bottom_y - badge["h"])
    screen.blit(badge["bg"], (px, py))

    cy = py + badge["h"] // 2
    cur_x = px + badge["pad_x"]

    dot_center = (cur_x + badge["dot_r"], cy)
    pygame.draw.circle(screen, badge.get("dot_color", (99, 179, 237)), dot_center, badge["dot_r"])
    pygame.draw.circle(screen, (235, 245, 255), dot_center, max(2, badge["dot_r"] - 3))
    cur_x += badge["dot_space"]

    loc_s = badge["loc_surf"]
    screen.blit(loc_s, (cur_x, cy - loc_s.get_height() // 2))
    cur_x += loc_s.get_width()

    if badge["has_sep"]:
        pygame.draw.circle(screen, (140, 150, 175), (cur_x + badge["sep_space"] // 2, cy), 3)
        cur_x += badge["sep_space"]

    if badge["date_surf"]:
        date_s = badge["date_surf"]
        screen.blit(date_s, (cur_x, cy - date_s.get_height() // 2))


def draw_magazine_editorial(screen, meta, x_left, bottom_y, max_w, font_editorial, font_sub, accent_color=(250, 204, 21)):
    """Dessine un habillage typographique de couverture de magazine en bas à gauche."""
    label = meta.get("label", u"") if meta else u""
    if not label:
        return
    if u" - " in label:
        loc_str, date_str = label.split(u" - ", 1)
    else:
        loc_str, date_str = label, u""

    loc_upper = loc_str.strip().upper()
    loc_fit = truncate_text_to_width(loc_upper, font_editorial, max_w - 28)
    t_loc = font_editorial.render(loc_fit, True, (255, 255, 255))
    sh_loc = font_editorial.render(loc_fit, True, (0, 0, 0))

    sub_text = date_str.strip()
    t_sub = font_sub.render(sub_text, True, (230, 235, 245)) if sub_text else None
    sh_sub = font_sub.render(sub_text, True, (0, 0, 0)) if sub_text else None

    total_h = t_loc.get_height() + (t_sub.get_height() + 6 if t_sub else 0)
    y_top = bottom_y - total_h

    # Barre verticale éditoriale colorée
    pygame.draw.rect(screen, accent_color, (x_left, y_top + 3, 6, total_h - 4))

    tx = x_left + 18
    screen.blit(sh_loc, (tx + 2, y_top + 2))
    screen.blit(t_loc, (tx, y_top))
    if t_sub:
        sy = y_top + t_loc.get_height() + 6
        screen.blit(sh_sub, (tx + 2, sy + 2))
        screen.blit(t_sub, (tx, sy))


def prepare_modern_card(raw_img, fx, fy, fw, fh, allow_zoom=True, overscan=1.10):
    """Prépare une carte photo avec sur-échantillonnage léger pour l'effet Ken Burns interne."""
    ow = max(fw + 2, int(fw * overscan))
    oh = max(fh + 2, int(fh * overscan))
    img_over = safe_smoothscale(raw_img, (ow, oh)).convert()

    if allow_zoom:
        anim_choices = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"]
    else:
        anim_choices = ["pan_left", "pan_right", "pan_up", "pan_down"]

    return {
        "fx": fx,
        "fy": fy,
        "fw": fw,
        "fh": fh,
        "ow": ow,
        "oh": oh,
        "img_over": img_over,
        "img_fit": safe_smoothscale(raw_img, (fw, fh)).convert(),
        "anim": random.choice(anim_choices)
    }


def render_modern_card(screen, card, progress, enable_animation):
    fx, fy, fw, fh = card["fx"], card["fy"], card["fw"], card["fh"]
    if not enable_animation:
        screen.blit(card["img_fit"], (fx, fy))
        return

    p = max(0.0, min(1.0, progress))
    t = p * p * (3.0 - 2.0 * p)

    ow, oh = card["ow"], card["oh"]
    img_over = card["img_over"]
    anim = card["anim"]
    max_dx = max(0, ow - fw)
    max_dy = max(0, oh - fh)

    if anim == "pan_left":
        cx = int(t * max_dx)
        cy = max_dy // 2
        screen.blit(img_over, (fx, fy), pygame.Rect(cx, cy, fw, fh))
    elif anim == "pan_right":
        cx = int((1.0 - t) * max_dx)
        cy = max_dy // 2
        screen.blit(img_over, (fx, fy), pygame.Rect(cx, cy, fw, fh))
    elif anim == "pan_up":
        cx = max_dx // 2
        cy = int(t * max_dy)
        screen.blit(img_over, (fx, fy), pygame.Rect(cx, cy, fw, fh))
    elif anim == "pan_down":
        cx = max_dx // 2
        cy = int((1.0 - t) * max_dy)
        screen.blit(img_over, (fx, fy), pygame.Rect(cx, cy, fw, fh))
    elif anim in ("zoom_in", "zoom_out"):
        z_t = t if anim == "zoom_in" else (1.0 - t)
        sub_w = int(ow - z_t * (ow - fw))
        sub_h = int(oh - z_t * (oh - fh))
        sub_w = max(fw, min(ow, sub_w))
        sub_h = max(fh, min(oh, sub_h))
        sx = (ow - sub_w) // 2
        sy = (oh - sub_h) // 2
        sub = img_over.subsurface((sx, sy, sub_w, sub_h))
        scaled = pygame.transform.scale(sub, (fw, fh))
        screen.blit(scaled, (fx, fy))
    else:
        screen.blit(card["img_fit"], (fx, fy))


def harmonize_duo_portraits(img1, img2, slot_w, slot_h):
    """Ajuste légèrement deux portraits pour qu'ils forment un diptyque grand format aligné."""
    target_card_ratio = float(slot_w) / float(slot_h)
    w1, h1 = img1.get_size()
    r1_aspect = float(w1) / float(h1)
    if r1_aspect > target_card_ratio:
        clamped1 = max(target_card_ratio, r1_aspect * 0.85)
        img1_use = crop_to_aspect(img1, int(clamped1 * 1000), 1000)
    else:
        img1_use = img1

    w2, h2 = img2.get_size()
    r2_aspect = float(w2) / float(h2)
    if r2_aspect > target_card_ratio:
        clamped2 = max(target_card_ratio, r2_aspect * 0.85)
        img2_use = crop_to_aspect(img2, int(clamped2 * 1000), 1000)
    else:
        img2_use = img2

    return img1_use, img2_use


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
            if y > rect.bottom - font.get_linesize():
                break
    if line and y <= rect.bottom - font.get_linesize():
        txt_surface = font.render(line, True, color)
        screen.blit(txt_surface, (rect.left, y))


def draw_centered_toast(screen, sw, sh, title_str, subtitle_str, font_main, font_small, accent_color=(99, 179, 237), y_center=None):
    if y_center is None:
        y_center = sh // 2
    t1 = font_main.render(title_str, True, accent_color)
    t2 = font_small.render(subtitle_str, True, (220, 225, 235)) if subtitle_str else None

    w = max(t1.get_width(), t2.get_width() if t2 else 0) + 64
    h = t1.get_height() + (t2.get_height() + 10 if t2 else 0) + 36
    box = create_rounded_box(w, h, 18, (14, 17, 26), border_color=accent_color, alpha=232, border_width=2)

    bx = (sw - w) // 2
    by = y_center - h // 2
    screen.blit(box, (bx, by))
    if t2:
        screen.blit(t1, ((sw - t1.get_width()) // 2, by + 16))
        screen.blit(t2, ((sw - t2.get_width()) // 2, by + 22 + t1.get_height()))
    else:
        screen.blit(t1, ((sw - t1.get_width()) // 2, by + (h - t1.get_height()) // 2))


def shift_photo_style(curr_style, delta=1):
    try:
        idx = STYLE_ORDER.index(curr_style)
        return STYLE_ORDER[(idx + delta) % len(STYLE_ORDER)]
    except ValueError:
        return STYLE_AUTO_ART


def shift_display_time(curr_time, delta=1):
    best_idx = 0
    best_diff = 999999
    for i, val in enumerate(DISPLAY_TIME_PRESETS):
        diff = abs(curr_time - val)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    new_idx = (best_idx + delta) % len(DISPLAY_TIME_PRESETS)
    return float(DISPLAY_TIME_PRESETS[new_idx])


def format_cadence_label(display_time):
    sec = int(round(display_time))
    per_min = max(1, int(round(60.0 / max(1.0, display_time))))
    return u"%ds (%d/min)" % (sec, per_min)


def draw_corner_toast(screen, sw, sh, text_str, font_small, accent_color=(56, 189, 248)):
    if not text_str:
        return
    txt = font_small.render(text_str, True, (245, 248, 255))
    dot_r = 6
    pad_x = 20
    pad_y = 12
    w = txt.get_width() + pad_x * 2 + dot_r * 2 + 10
    h = txt.get_height() + pad_y * 2
    box = create_rounded_box(w, h, h // 2, (12, 16, 26), border_color=accent_color, alpha=225, border_width=2)
    bx = sw - w - 24
    by = 20
    screen.blit(box, (bx, by))
    pygame.draw.circle(screen, accent_color, (bx + pad_x + dot_r, by + h // 2), dot_r)
    screen.blit(txt, (bx + pad_x + dot_r * 2 + 10, by + (h - txt.get_height()) // 2))


def draw_info_overlay(screen, sw, sh, current_mode, internal_mode, photo_style, active_render_style, is_muted,
                      metas_to_show, video_meta, idx_num, total_count, remain_sec,
                      font_main, font_small, font_regular, font_tiny):
    margin_x = int(sw * 0.04)
    ov_w = sw - 2 * margin_x

    # 1. BANDEAU HAUT : AIDE COMMANDES (TOOLTIPS)
    top_h = int(sh * 0.165)
    top_y = int(sh * 0.022)
    top_box = create_rounded_box(ov_w, top_h, 16, (10, 15, 28), border_color=(34, 211, 238), alpha=232, border_width=2)
    screen.blit(top_box, (margin_x, top_y))

    hdr_txt = font_small.render(u"AIDE COMMANDES  (1 clic bouton dessus = Fermer)", True, (34, 211, 238))
    screen.blit(hdr_txt, (margin_x + 22, top_y + 12))

    timer_str = u"Fermeture : %ds" % int(max(0, math.ceil(remain_sec)))
    timer_txt = font_tiny.render(timer_str, True, (251, 191, 36))
    t_w = timer_txt.get_width() + 20
    t_h = timer_txt.get_height() + 8
    t_box = create_rounded_box(t_w, t_h, 8, (45, 35, 15), border_color=(251, 191, 36), alpha=230, border_width=1)
    screen.blit(t_box, (margin_x + ov_w - t_w - 18, top_y + 10))
    screen.blit(timer_txt, (margin_x + ov_w - t_w - 8, top_y + 14))

    sep_y = top_y + 16 + hdr_txt.get_height()
    pygame.draw.line(screen, (35, 48, 72), (margin_x + 18, sep_y), (margin_x + ov_w - 18, sep_y), 1)

    col1_x = margin_x + 22
    col2_x = margin_x + ov_w // 2 + 10
    row1_y = sep_y + 10
    row2_y = row1_y + font_regular.get_linesize() + 8

    if internal_mode == MODE_PHOTOS:
        st_short = STYLE_SHORT_LABELS.get(photo_style, photo_style)
        updown_str = u"▲ / ▼ Manette : Style (%s)" % st_short
    else:
        snd_short = u"Coupé" if is_muted else u"Actif"
        updown_str = u"▲ / ▼ Manette : Son vidéo (%s)" % snd_short

    screen.blit(font_regular.render(u"◀ / ▶ Manette : Média précédent / suivant", True, (235, 240, 250)), (col1_x, row1_y))
    screen.blit(font_regular.render(updown_str, True, (235, 240, 250)), (col2_x, row1_y))
    screen.blit(font_regular.render(u"2x ◀ / ▶ rapide : Changer phase (en Cycle Auto)", True, (190, 205, 225)), (col1_x, row2_y))
    screen.blit(font_regular.render(u"Double-clic Bouton dessus : Ouvrir Menu Réglages", True, (129, 140, 248)), (col2_x, row2_y))

    # 2. BANDEAU BAS : DÉTAILS DU MÉDIA AFFICHÉ
    if internal_mode == MODE_PHOTOS:
        items = metas_to_show[:3] if metas_to_show else [{}]
        bot_h = min(int(sh * 0.36), int(sh * 0.085) + len(items) * (font_small.get_linesize() + font_tiny.get_linesize() + 14))
    else:
        bot_h = int(sh * 0.175)

    bot_y = sh - bot_h - int(sh * 0.022)
    bot_box = create_rounded_box(ov_w, bot_h, 16, (10, 15, 28), border_color=(52, 211, 153), alpha=234, border_width=2)
    screen.blit(bot_box, (margin_x, bot_y))

    if current_mode == MODE_CYCLE:
        mode_badge_str = u"Mode : Cycle Auto (%s)" % MODE_NAMES.get(internal_mode, u"")
    else:
        mode_badge_str = u"Mode : %s" % MODE_NAMES.get(current_mode, u"")

    if internal_mode == MODE_PHOTOS:
        nb_shown = len(metas_to_show) if metas_to_show else 1
        st_disp = STYLE_SHORT_LABELS.get(active_render_style, active_render_style)
        if nb_shown > 1:
            det_hdr = u"DÉTAILS DES %d PHOTOS AFFICHÉES  [#%d/%d]  •  %s" % (nb_shown, idx_num, total_count, st_disp)
        else:
            det_hdr = u"DÉTAILS DE LA PHOTO  [#%d/%d]  •  %s" % (idx_num, total_count, st_disp)
    elif internal_mode == MODE_VIDEOS_PERSO:
        det_hdr = u"DÉTAILS DE LA VIDÉO PERSO  [#%d/%d]" % (idx_num, total_count)
    else:
        det_hdr = u"DÉTAILS DU JEU RÉTRO  [#%d/%d]" % (idx_num, total_count)

    screen.blit(font_small.render(det_hdr, True, (52, 211, 153)), (margin_x + 22, bot_y + 12))
    mb_txt = font_tiny.render(mode_badge_str, True, (180, 195, 215))
    screen.blit(mb_txt, (margin_x + ov_w - mb_txt.get_width() - 20, bot_y + 15))

    sep2_y = bot_y + 16 + font_small.get_height()
    pygame.draw.line(screen, (35, 48, 72), (margin_x + 18, sep2_y), (margin_x + ov_w - 18, sep2_y), 1)

    cur_y = sep2_y + 10
    if internal_mode == MODE_PHOTOS:
        items = metas_to_show[:3] if metas_to_show else [{}]
        for idx_m, m_item in enumerate(items):
            prefix = (u"%d. " % (idx_m + 1)) if len(items) > 1 else u""
            label_raw = m_item.get("label", u"Sans titre") or u"Sans titre"
            clean_label = label_raw.split(u" - ")[0]
            precise_date = m_item.get("info", u"")
            line1 = u"%s%s  (%s)" % (prefix, clean_label, precise_date) if precise_date else u"%s%s" % (prefix, clean_label)
            screen.blit(font_small.render(line1, True, (255, 255, 255)), (margin_x + 22, cur_y))
            cur_y += font_small.get_linesize() + 1

            src_p = m_item.get("source_path", u"")
            path_rect = pygame.Rect(margin_x + 22, cur_y, ov_w - 44, font_tiny.get_linesize() + 4)
            draw_wrapped_text(screen, src_p, font_tiny, (165, 178, 200), path_rect)
            cur_y += font_tiny.get_linesize() + 7
    elif internal_mode == MODE_VIDEOS_PERSO:
        lbl = video_meta.get("label", u"Vidéo Perso") or u"Vidéo Perso"
        inf = video_meta.get("info", u"")
        line1 = u"%s  (Durée : %s)" % (lbl, inf) if inf else lbl
        screen.blit(font_small.render(line1, True, (255, 255, 255)), (margin_x + 22, cur_y))
        cur_y += font_small.get_linesize() + 4
        path_rect = pygame.Rect(margin_x + 22, cur_y, ov_w - 44, font_tiny.get_linesize() + 4)
        draw_wrapped_text(screen, video_meta.get("source_path", u""), font_tiny, (165, 178, 200), path_rect)
    else:
        g_title = video_meta.get("game", u"Jeu Rétro")
        g_cons = video_meta.get("console", u"")
        line1 = u"%s  —  Console : %s" % (g_title, g_cons)
        screen.blit(font_small.render(line1, True, (251, 191, 36)), (margin_x + 22, cur_y))
        cur_y += font_small.get_linesize() + 4
        path_rect = pygame.Rect(margin_x + 22, cur_y, ov_w - 44, font_tiny.get_linesize() + 4)
        draw_wrapped_text(screen, video_meta.get("source_path", u""), font_tiny, (165, 178, 200), path_rect)


def draw_settings_menu(screen, sw, sh, selected_row, current_mode, internal_mode, photo_style, is_muted, display_time,
                       remain_sec, font_main, font_small, font_regular, font_tiny):
    mw = int(sw * 0.78)
    mh = int(sh * 0.62)
    mx = (sw - mw) // 2
    my = (sh - mh) // 2

    box = create_rounded_box(mw, mh, 20, (10, 14, 26), border_color=(99, 102, 241), alpha=242, border_width=3)
    screen.blit(box, (mx, my))

    # En-tête du menu
    title_txt = font_small.render(u"MENU RÉGLAGES  (▲/▼ : Choisir  •  ◀/▶ : Modifier)", True, (165, 180, 252))
    screen.blit(title_txt, (mx + 28, my + 20))

    timer_str = u"Fermeture : %ds" % int(max(0, math.ceil(remain_sec)))
    timer_txt = font_tiny.render(timer_str, True, (251, 191, 36))
    tw = timer_txt.get_width() + 22
    th = timer_txt.get_height() + 10
    tbox = create_rounded_box(tw, th, 8, (45, 35, 15), border_color=(251, 191, 36), alpha=235, border_width=1)
    screen.blit(tbox, (mx + mw - tw - 24, my + 16))
    screen.blit(timer_txt, (mx + mw - tw - 13, my + 21))

    sep_top = my + 26 + title_txt.get_height()
    pygame.draw.line(screen, (38, 48, 74), (mx + 24, sep_top), (mx + mw - 24, sep_top), 1)

    if current_mode == MODE_CYCLE:
        mode_val = u"◀ Cycle Auto (%s) ▶" % MODE_NAMES.get(internal_mode, u"Photos")
    else:
        mode_val = u"◀ %s ▶" % MODE_NAMES.get(current_mode, u"Photos")

    style_val = u"◀ %s ▶" % STYLE_SHORT_LABELS.get(photo_style, photo_style)
    sound_val = u"◀ Coupé (Muet) ▶" if is_muted else u"◀ Actif (Son) ▶"
    speed_val = u"◀ %s ▶" % format_cadence_label(display_time)
    close_val = u"↩ Reprendre (◀ / ▶)"

    rows = [
        (u"Mode d'affichage", u"2x ◀/▶ en Cycle", mode_val, False),
        (u"Style des photos", u"▲/▼ sur photo", style_val, False),
        (u"Son des vidéos", u"▲/▼ sur vidéo", sound_val, False),
        (u"Cadence des photos", None, speed_val, False),
        (u"Fermer le menu", u"ou 1 clic bouton", close_val, True)
    ]

    area_top = sep_top + 16
    area_bot = my + mh - 56
    row_h = int((area_bot - area_top - 4 * 10) // len(rows))
    row_w = mw - 56

    for idx, (lbl, badge_str, val_str, is_close) in enumerate(rows):
        ry = area_top + idx * (row_h + 10)
        rx = mx + 28
        active = (idx == selected_row)

        if active:
            bg_col = (18, 65, 52) if is_close else (38, 46, 108)
            bd_col = (52, 211, 153) if is_close else (129, 140, 248)
            rbox = create_rounded_box(row_w, row_h, 12, bg_col, border_color=bd_col, alpha=235, border_width=2)
            screen.blit(rbox, (rx, ry))
            prefix = u"▸ "
            lbl_col = (255, 255, 255)
            val_col = (110, 231, 183) if is_close else (251, 191, 36)
        else:
            rbox = create_rounded_box(row_w, row_h, 12, (17, 23, 39), border_color=(32, 42, 64), alpha=190, border_width=1)
            screen.blit(rbox, (rx, ry))
            prefix = u"   "
            lbl_col = (205, 214, 230)
            val_col = (148, 163, 184)

        lbl_surf = font_small.render(prefix + lbl, True, lbl_col)
        ly = ry + (row_h - lbl_surf.get_height()) // 2
        screen.blit(lbl_surf, (rx + 16, ly))

        if badge_str:
            b_surf = font_tiny.render(badge_str, True, (34, 211, 238))
            bw = b_surf.get_width() + 16
            bh = b_surf.get_height() + 6
            bx = rx + 26 + lbl_surf.get_width()
            by = ry + (row_h - bh) // 2
            bbox = create_rounded_box(bw, bh, 6, (15, 30, 50), border_color=(34, 211, 238), alpha=215, border_width=1)
            screen.blit(bbox, (bx, by))
            screen.blit(b_surf, (bx + 8, by + 3))

        val_surf = font_small.render(val_str, True, val_col)
        vy = ry + (row_h - val_surf.get_height()) // 2
        screen.blit(val_surf, (rx + row_w - val_surf.get_width() - 18, vy))

    # Pied du menu
    pygame.draw.line(screen, (38, 48, 74), (mx + 24, my + mh - 44), (mx + mw - 24, my + mh - 44), 1)
    foot_left = font_tiny.render(u"Manette ▲/▼ : Naviguer   |   ◀/▶ : Modifier la valeur", True, (160, 174, 198))
    foot_right = font_tiny.render(u"1 clic bouton dessus : Fermer", True, (165, 180, 252))
    screen.blit(foot_left, (mx + 28, my + mh - 32))
    screen.blit(foot_right, (mx + mw - foot_right.get_width() - 28, my + mh - 32))


def draw_video_backdrop(screen, sw, sh, internal_mode, video_meta, is_muted, font_main, font_small, font_regular):
    screen.fill((10, 14, 24))
    if internal_mode == MODE_VIDEOS_GAMES:
        title = video_meta.get("game", u"Jeu Rétro")
        sub = u"Console : %s" % video_meta.get("console", u"")
        accent = (251, 191, 36)
    else:
        title = video_meta.get("label", u"Vidéo Perso") or u"Vidéo Perso"
        info = video_meta.get("info", u"")
        sub = (u"Durée : %s" % info) if info else u"Vidéo personnelle"
        accent = (56, 189, 248)
    snd_str = u"Son : Coupé (Muet)" if is_muted else u"Son : Actif"
    draw_centered_toast(screen, sw, sh, title, u"%s   •   %s" % (sub, snd_str), font_main, font_regular, accent_color=accent, y_center=sh // 2)


def run_slideshow(enable_animation=True):
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_NOMOUSE"] = "1"

    settings = load_settings()
    display_time = float(settings.get("display_time", DEFAULT_DISPLAY_TIME))
    top_buttons = set(settings.get("top_buttons", TOP_BUTTONS_DEFAULT))
    front_buttons = set(settings.get("front_buttons", FRONT_BUTTONS_DEFAULT))
    current_mode = settings.get("current_mode", MODE_CYCLE)
    photo_style = settings.get("photo_style", STYLE_AUTO_ART)
    is_muted = settings.get("is_muted", True)

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
        except Exception:
            pass

    event_format = 'llHHi'
    event_size = struct.calcsize(event_format)
    info = pygame.display.Info()
    sw, sh = info.current_w, info.current_h
    if sw == 0 or sh == 0:
        sw, sh = 1280, 1024

    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)

    font_editorial = load_best_font(int(sh * 0.048), bold=True)
    font_main = load_best_font(int(sh * 0.040), bold=True)
    font_small = load_best_font(int(sh * 0.025), bold=True)
    font_regular = load_best_font(int(sh * 0.022), bold=False)
    font_tiny = load_best_font(int(sh * 0.018), bold=False)

    # Police classique d'origine
    font_classic_small = pygame.font.Font(None, int(sh * 0.03))

    # Surfaces d'effets pré-calculées une seule fois au démarrage
    vignette_surf = make_vignette_surface(sw, sh)
    bottom_grad_h = int(sh * 0.32)
    bottom_grad_surf = make_bottom_gradient(sw, bottom_grad_h)
    scanline_surf = make_scanline_overlay(sw, sh)

    def get_files_for_mode(mode):
        if mode == MODE_PHOTOS:
            if not os.path.exists(IMAGE_FOLDER):
                return []
            return sorted([os.path.join(IMAGE_FOLDER, f) for f in os.listdir(IMAGE_FOLDER) if f.lower().endswith('.jpg')])
        elif mode == MODE_VIDEOS_PERSO:
            if not os.path.exists(VIDEO_PERSO_FOLDER):
                return []
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

    all_files = get_files_for_mode(internal_mode)
    indices = list(range(len(all_files)))
    random.shuffle(indices)
    current_idx_ptr = 0
    current_step = 1

    running = True
    need_load = True
    force_reload_same = False
    last_switch = time.time()

    # État d'affichage Classique
    current_img_raw = None
    zoom_factor = 1.0
    alpha = 0
    meta_data = {}
    video_meta = {}
    anim_type = "zoom_in"
    scroll_dir = "down"

    # État d'affichage Moderne / Artistique
    modern_scene = None
    active_render_style = STYLE_MODERN
    last_auto_style = None
    prev_screen_snapshot = None
    has_rendered_photo = False
    prev_polaroid_ghost = None

    # Niveau d'overlay : 0 = Écran propre | 1 = Infos Média + Tooltips | 2 = Menu Réglages
    overlay_level = 0
    overlay_deadline = 0.0
    INFO_DURATION = 10.0
    MENU_DURATION = 12.0
    menu_selected_row = 0
    MENU_ROW_COUNT = 5

    # Toast éphémère en haut à droite (lors d'une action directe au joystick hors menu)
    toast_text = u""
    toast_color = (56, 189, 248)
    toast_timer = 0.0
    TOAST_DURATION = 1.6

    # Détection double-clic boutons du dessus & double-coup joystick gauche/droite
    last_top_btn_time = 0.0
    DOUBLE_CLICK_BTN_THRESHOLD = 0.45

    last_horiz_tap_dir = 0
    last_horiz_tap_time = 0.0
    DOUBLE_TAP_JOY_THRESHOLD = 0.60

    joy_axis_x_neutral = True
    joy_axis_y_neutral = True
    joy_hat_x_neutral = True
    joy_hat_y_neutral = True
    last_horiz_action_time = 0.0
    last_vert_action_time = 0.0

    video_proc = None
    video_start_time = 0
    VIDEO_MAX_PLAY_SECONDS = 210
    devnull_f = open(os.devnull, 'wb')

    def show_toast(msg, color=(56, 189, 248)):
        toast_State[0] = msg
        toast_State[1] = color
        toast_State[2] = time.time() + TOAST_DURATION

    toast_State = [u"", (56, 189, 248), 0.0]

    def switch_to_internal_mode(new_int_mode, now_ts):
        return (
            new_int_mode,
            get_files_for_mode(new_int_mode)
        )

    def find_partner_photo(start_ptr, want_vertical=None, exclude_offsets=None):
        """Cherche une photo suivante compatible dans la liste mélangée."""
        if exclude_offsets is None:
            exclude_offsets = set([0])
        max_scan = min(len(indices) - 1, 16)
        for offset in range(1, max_scan + 1):
            if offset in exclude_offsets:
                continue
            cand_ptr = (start_ptr + offset) % len(indices)
            cand_path = all_files[indices[cand_ptr]]
            try:
                cand_img = pygame.image.load(cand_path)
                cw, ch = cand_img.get_size()
                is_vert = ch > cw * 1.02
                if want_vertical is None or is_vert == want_vertical:
                    return offset, cand_img.convert(), cand_path, get_sidecar_data(cand_path)
            except Exception:
                pass
        return None, None, None, None

    try:
        while running:
            now = time.time()
            show_info = (overlay_level != 0)

            # --- 1. LOGIQUE TIMERS & CYCLE ---
            if overlay_level != 0 and now > overlay_deadline:
                was_video = (internal_mode != MODE_PHOTOS)
                overlay_level = 0
                show_info = False
                if was_video and video_proc is None:
                    need_load = True

            if current_mode == MODE_CYCLE and overlay_level == 0 and now - last_cycle_time > CYCLE_INTERVAL:
                internal_mode = (internal_mode % 3) + 1
                all_files = get_files_for_mode(internal_mode)
                indices = list(range(len(all_files)))
                random.shuffle(indices)
                current_idx_ptr = 0
                current_step = 1
                need_load = True
                last_cycle_time = now
                prev_screen_snapshot = None
                has_rendered_photo = False
                if video_proc:
                    stop_video(video_proc)
                    video_proc = None

            # --- 2. ENTRÉES BOUTONS (/dev/input/event*) ---
            for f in input_files:
                try:
                    data = f.read(event_size)
                    while data:
                        _, _, ev_type, ev_code, ev_value = struct.unpack(event_format, data)
                        if ev_type == EV_KEY and ev_value == 1:
                            # Boutons de devant (Façade) ou bouton inconnu => Quitter immédiatement l'économiseur
                            if ev_code in front_buttons or ev_code not in top_buttons:
                                running = False
                                break

                            # Boutons du dessus (Panel Arcade J1/J2) :
                            # - Double-clic rapide (< 0.45s) => Ouvre le Menu des Réglages (niveau 2)
                            # - Simple clic => Si écran propre (0), ouvre Infos + Tooltips (1) ; sinon referme tout (0)
                            is_double_click = (now - last_top_btn_time) < DOUBLE_CLICK_BTN_THRESHOLD
                            last_top_btn_time = now

                            if is_double_click:
                                last_top_btn_time = 0.0
                                overlay_level = 2
                                menu_selected_row = 0
                                overlay_deadline = now + MENU_DURATION
                                if video_proc:
                                    stop_video(video_proc)
                                    video_proc = None
                            else:
                                if overlay_level == 0:
                                    overlay_level = 1
                                    overlay_deadline = now + INFO_DURATION
                                    if video_proc:
                                        stop_video(video_proc)
                                        video_proc = None
                                else:
                                    was_video = (internal_mode != MODE_PHOTOS)
                                    overlay_level = 0
                                    if was_video and video_proc is None:
                                        need_load = True
                        data = f.read(event_size)
                except Exception:
                    pass

            if not running:
                break

            # --- 3. ÉVÉNEMENTS SDL & MANETTES (JOYSTICKS) ---
            horiz_actions = []  # liste de tuples (steer, is_fresh_tap)
            vert_actions = []   # liste de vdir (-1 = Haut ▲, +1 = Bas ▼)

            for event in pygame.event.get():
                if event.type in (pygame.QUIT, pygame.KEYDOWN):
                    running = False
                    break

                if event.type == pygame.JOYAXISMOTION:
                    if event.axis == 0:
                        if abs(event.value) < 0.35:
                            joy_axis_x_neutral = True
                        elif abs(event.value) > 0.6:
                            if joy_axis_x_neutral or (now - last_horiz_action_time > 0.42):
                                steer = 1 if event.value > 0 else -1
                                horiz_actions.append((steer, joy_axis_x_neutral))
                                joy_axis_x_neutral = False
                                last_horiz_action_time = now
                    elif event.axis == 1:
                        if abs(event.value) < 0.35:
                            joy_axis_y_neutral = True
                        elif abs(event.value) > 0.6:
                            if joy_axis_y_neutral or (now - last_vert_action_time > 0.35):
                                vdir = -1 if event.value < 0 else 1
                                vert_actions.append(vdir)
                                joy_axis_y_neutral = False
                                last_vert_action_time = now

                elif event.type == pygame.JOYHATMOTION:
                    hx, hy = event.value
                    if hx == 0:
                        joy_hat_x_neutral = True
                    elif joy_hat_x_neutral:
                        horiz_actions.append((1 if hx > 0 else -1, True))
                        joy_hat_x_neutral = False
                        last_horiz_action_time = now

                    if hy == 0:
                        joy_hat_y_neutral = True
                    elif joy_hat_y_neutral:
                        vert_actions.append(-1 if hy > 0 else 1)
                        joy_hat_y_neutral = False
                        last_vert_action_time = now

            if not running:
                break

            # Traitement des actions verticales (Haut ▲ / Bas ▼)
            for vdir in vert_actions:
                if overlay_level == 2:
                    # Navigation dans le Menu Réglages
                    overlay_deadline = now + MENU_DURATION
                    menu_selected_row = (menu_selected_row + vdir + MENU_ROW_COUNT) % MENU_ROW_COUNT
                else:
                    # Hors menu (écran propre 0 ou Infos 1) : Raccourci direct Style (sur photo) ou Son (sur vidéo)
                    if overlay_level == 1:
                        overlay_deadline = now + INFO_DURATION
                    if internal_mode == MODE_PHOTOS:
                        photo_style = shift_photo_style(photo_style, vdir)
                        settings["photo_style"] = photo_style
                        save_settings(settings)
                        st_lbl, _, st_col = STYLE_TITLES.get(photo_style, (u"Style", u"", (99, 179, 237)))
                        show_toast(st_lbl, st_col)
                        need_load = True
                        force_reload_same = True
                    else:
                        is_muted = not is_muted
                        settings["is_muted"] = is_muted
                        save_settings(settings)
                        show_toast(
                            u"Son vidéo : Coupé (Muet)" if is_muted else u"Son vidéo : Actif",
                            (248, 113, 113) if is_muted else (52, 211, 153)
                        )
                        if video_proc:
                            stop_video(video_proc)
                            video_proc = None
                            need_load = True

            # Traitement des actions horizontales (Gauche ◀ / Droite ▶)
            for steer, is_fresh_tap in horiz_actions:
                if overlay_level == 2:
                    # Modification de l'option sélectionnée dans le Menu Réglages
                    overlay_deadline = now + MENU_DURATION
                    if menu_selected_row == 0:
                        # Mode d'affichage (1..4)
                        current_mode = ((current_mode - 1 + steer) % 4) + 1
                        internal_mode = current_mode if current_mode != MODE_CYCLE else MODE_PHOTOS
                        all_files = get_files_for_mode(internal_mode)
                        indices = list(range(len(all_files)))
                        random.shuffle(indices)
                        current_idx_ptr = 0
                        current_step = 1
                        current_img_raw = None
                        modern_scene = None
                        prev_screen_snapshot = None
                        has_rendered_photo = False
                        alpha = 0
                        settings["current_mode"] = current_mode
                        save_settings(settings)
                        last_cycle_time = now
                        need_load = True
                        if video_proc:
                            stop_video(video_proc)
                            video_proc = None
                    elif menu_selected_row == 1:
                        # Style des photos
                        photo_style = shift_photo_style(photo_style, steer)
                        settings["photo_style"] = photo_style
                        save_settings(settings)
                        if internal_mode == MODE_PHOTOS:
                            need_load = True
                            force_reload_same = True
                    elif menu_selected_row == 2:
                        # Son des vidéos
                        is_muted = not is_muted
                        settings["is_muted"] = is_muted
                        save_settings(settings)
                    elif menu_selected_row == 3:
                        # Cadence des photos
                        display_time = shift_display_time(display_time, steer)
                        settings["display_time"] = display_time
                        save_settings(settings)
                    elif menu_selected_row == 4:
                        # Fermer le menu
                        was_video = (internal_mode != MODE_PHOTOS)
                        overlay_level = 0
                        if was_video and video_proc is None:
                            need_load = True
                else:
                    # Hors menu (écran propre 0 ou Infos 1)
                    if overlay_level == 1:
                        overlay_deadline = now + INFO_DURATION

                    # Détection du double-coup rapide (◀◀ ou ▶▶) en mode Cycle Auto pour passer à la phase suivante/précédente
                    if current_mode == MODE_CYCLE and is_fresh_tap and last_horiz_tap_dir == steer and (now - last_horiz_tap_time) < DOUBLE_TAP_JOY_THRESHOLD:
                        last_horiz_tap_dir = 0
                        last_horiz_tap_time = 0.0
                        internal_mode = ((internal_mode - 1 + steer) % 3) + 1
                        all_files = get_files_for_mode(internal_mode)
                        indices = list(range(len(all_files)))
                        random.shuffle(indices)
                        current_idx_ptr = 0
                        current_step = 1
                        current_img_raw = None
                        modern_scene = None
                        prev_screen_snapshot = None
                        has_rendered_photo = False
                        alpha = 0
                        last_cycle_time = now
                        need_load = True
                        if video_proc:
                            stop_video(video_proc)
                            video_proc = None
                        show_toast(u"Cycle Auto ▶ %s" % MODE_NAMES.get(internal_mode, u""), (251, 191, 36))
                        continue

                    if is_fresh_tap:
                        last_horiz_tap_dir = steer
                        last_horiz_tap_time = now

                    if indices:
                        step = current_step if steer > 0 else 1
                        current_idx_ptr = (current_idx_ptr + steer * step) % len(indices)
                        need_load = True
                        if video_proc:
                            stop_video(video_proc)
                            video_proc = None

            show_info = (overlay_level != 0)

            # --- 4. LOGIQUE CHARGEMENT ---
            if video_proc:
                if video_proc.poll() is not None:
                    video_proc = None
                    if indices:
                        current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                    need_load = True
                elif now - video_start_time > VIDEO_MAX_PLAY_SECONDS:
                    stop_video(video_proc)
                    video_proc = None
                    if indices:
                        current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                    need_load = True

            if need_load:
                if not indices:
                    screen.fill((0, 0, 0))
                    msg = u"Aucun fichier trouvé"
                    txt = font_main.render(msg, True, (255, 100, 100))
                    screen.blit(txt, ((sw - txt.get_width()) // 2, (sh - txt.get_height()) // 2))
                    pygame.display.flip()
                    time.sleep(2)
                    need_load = False
                    continue

                file_path = all_files[indices[current_idx_ptr]]

                if internal_mode == MODE_PHOTOS:
                    try:
                        # Choix du style de rendu pour cette photo
                        if photo_style == STYLE_AUTO_ART:
                            candidates = [s for s in ARTISTIC_POOL if s != last_auto_style]
                            active_render_style = random.choice(candidates) if candidates else STYLE_MODERN
                            last_auto_style = active_render_style
                        else:
                            active_render_style = photo_style

                        if active_render_style != STYLE_CLASSIC and has_rendered_photo and not show_info:
                            prev_screen_snapshot = screen.copy().convert()
                        else:
                            prev_screen_snapshot = None

                        img1_loaded = pygame.image.load(file_path)
                        img1 = img1_loaded.convert()
                        img1_w, img1_h = img1.get_size()
                        is_vertical1 = img1_h > img1_w * 1.02
                        meta1 = get_sidecar_data(file_path)
                        current_step = 1
                        border_px = max(3, int(min(sw, sh) * 0.004))

                        # =========================================================================
                        # STYLE 1 : MOSAÏQUE BENTO (3 PHOTOS SIMULTANÉES)
                        # =========================================================================
                        if active_render_style == STYLE_BENTO and len(indices) >= 3:
                            off2, img2, path2, meta2 = find_partner_photo(current_idx_ptr, want_vertical=False, exclude_offsets=set([0]))
                            if img2 is None:
                                off2, img2, path2, meta2 = find_partner_photo(current_idx_ptr, want_vertical=None, exclude_offsets=set([0]))
                            off3, img3, path3, meta3 = find_partner_photo(current_idx_ptr, want_vertical=False, exclude_offsets=set([0, off2]))
                            if img3 is None:
                                off3, img3, path3, meta3 = find_partner_photo(current_idx_ptr, want_vertical=None, exclude_offsets=set([0, off2]))

                            if img2 is not None and img3 is not None:
                                current_step = 3
                                p1 = (current_idx_ptr + 1) % len(indices)
                                p2 = (current_idx_ptr + 2) % len(indices)
                                c2 = (current_idx_ptr + off2) % len(indices)
                                c3 = (current_idx_ptr + off3) % len(indices)
                                if c2 != p1:
                                    indices[p1], indices[c2] = indices[c2], indices[p1]
                                    if c3 == p1:
                                        c3 = c2
                                if c3 != p2:
                                    indices[p2], indices[c3] = indices[c3], indices[p2]

                                scene_bg = make_blurred_background(img1, sw, sh, img2, vignette_surf=vignette_surf)

                                mx = int(sw * 0.018)
                                my = int(sh * 0.022)
                                gap = int(sw * 0.015)
                                bw = sw - 2 * mx
                                bh = sh - 2 * my

                                if is_vertical1 or random.random() < 0.6:
                                    # Colonne gauche grand portrait + 2 photos empilées à droite
                                    w_left = int(bw * 0.47)
                                    w_right = bw - w_left - gap
                                    h_top = (bh - gap) // 2
                                    h_bot = bh - h_top - gap

                                    rects = [
                                        (mx, my, w_left, bh),
                                        (mx + w_left + gap, my, w_right, h_top),
                                        (mx + w_left + gap, my + h_top + gap, w_right, h_bot)
                                    ]
                                else:
                                    # Grande photo panoramique en haut + 2 photos côte à côte en bas
                                    h_top = int(bh * 0.55)
                                    h_bot = bh - h_top - gap
                                    w_bl = (bw - gap) // 2
                                    w_br = bw - w_bl - gap

                                    rects = [
                                        (mx, my, bw, h_top),
                                        (mx, my + h_top + gap, w_bl, h_bot),
                                        (mx + w_bl + gap, my + h_top + gap, w_br, h_bot)
                                    ]

                                imgs_bento = [img1, img2, img3]
                                metas_bento = [meta1, meta2, meta3]
                                cards_bento = []
                                badges_bento = []

                                for (rx, ry, rw, rh), b_img, b_meta in zip(rects, imgs_bento, metas_bento):
                                    bake_card_frame_on_bg(scene_bg, rx, ry, rw, rh, border_px=3)
                                    cropped_tile = crop_to_aspect(b_img, rw, rh)
                                    cards_bento.append(prepare_modern_card(cropped_tile, rx, ry, rw, rh, allow_zoom=False, overscan=1.09))
                                    b_badge = build_caption_badge(b_meta.get("label", u""), font_tiny, font_tiny, rw - 14)
                                    badges_bento.append((b_badge, rx + rw // 2, ry + rh - 10))

                                modern_scene = {
                                    "render_type": "cards",
                                    "bg": scene_bg,
                                    "cards": cards_bento,
                                    "badges": badges_bento,
                                    "metas": metas_bento
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "bento",
                                    "filename": "%s + %s + %s" % (os.path.basename(file_path), os.path.basename(path2), os.path.basename(path3)),
                                    "label": meta1.get("label", u"") + (u"  |  " + meta2.get("label", u"") if meta2.get("label") else u"") + (u"  |  " + meta3.get("label", u"") if meta3.get("label") else u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "secondary": {
                                        "filename": os.path.basename(path2),
                                        "label": meta2.get("label", u""),
                                        "info": meta2.get("info", u""),
                                        "source_path": meta2.get("source_path", u"")
                                    },
                                    "tertiary": {
                                        "filename": os.path.basename(path3),
                                        "label": meta3.get("label", u""),
                                        "info": meta3.get("info", u""),
                                        "source_path": meta3.get("source_path", u"")
                                    },
                                    "timestamp": time.time()
                                })
                            else:
                                active_render_style = STYLE_MODERN

                        # =========================================================================
                        # STYLE 2 : POLAROID VINTAGE (DUO INCLINÉ OU SOLO GRAND FORMAT)
                        # =========================================================================
                        if active_render_style == STYLE_POLAROID:
                            do_duo_pol = (is_vertical1 or random.random() < 0.55) and len(indices) > 1
                            off2, img2, path2, meta2 = (None, None, None, None)
                            if do_duo_pol:
                                off2, img2, path2, meta2 = find_partner_photo(current_idx_ptr, want_vertical=is_vertical1)
                                if img2 is None:
                                    off2, img2, path2, meta2 = find_partner_photo(current_idx_ptr, want_vertical=None)

                            scene_bg = make_blurred_background(img1, sw, sh, img2, tint=(105, 92, 82), vignette_surf=vignette_surf)

                            # Si un Polaroid précédent existe, on le laisse posé en fond tamisé sur la table
                            if prev_polaroid_ghost is not None:
                                scene_bg.blit(prev_polaroid_ghost, (int(sw * 0.04), int(sh * 0.05)))

                            if img2 is not None:
                                current_step = 2
                                next_ptr = (current_idx_ptr + 1) % len(indices)
                                cand_ptr = (current_idx_ptr + off2) % len(indices)
                                indices[next_ptr], indices[cand_ptr] = indices[cand_ptr], indices[next_ptr]

                                pol_w = int(sw * 0.46)
                                pol_h = int(sh * 0.88)
                                ang1 = random.uniform(-4.2, -1.8)
                                ang2 = random.uniform(1.8, 4.2)

                                pol1 = make_polaroid_surface(img1, meta1, pol_w, pol_h, ang1, font_small, font_regular)
                                pol2 = make_polaroid_surface(img2, meta2, pol_w, pol_h, ang2, font_small, font_regular)

                                p1_x = int(sw * 0.26) - pol1.get_width() // 2
                                p1_y = (sh - pol1.get_height()) // 2
                                p2_x = int(sw * 0.74) - pol2.get_width() // 2
                                p2_y = (sh - pol2.get_height()) // 2

                                modern_scene = {
                                    "render_type": "polaroid",
                                    "bg": scene_bg,
                                    "polaroids": [
                                        (pol1, p1_x, p1_y, 8, -6),
                                        (pol2, p2_x, p2_y, -8, 6)
                                    ],
                                    "metas": [meta1, meta2]
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "duo",
                                    "filename": "%s + %s" % (os.path.basename(file_path), os.path.basename(path2)),
                                    "label": meta1.get("label", u"") + (u"  |  " + meta2.get("label", u"") if meta2.get("label") else u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "secondary": {
                                        "filename": os.path.basename(path2),
                                        "label": meta2.get("label", u""),
                                        "info": meta2.get("info", u""),
                                        "source_path": meta2.get("source_path", u"")
                                    },
                                    "timestamp": time.time()
                                })
                            else:
                                if is_vertical1:
                                    pol_w = int(sw * 0.64)
                                    pol_h = int(sh * 0.93)
                                else:
                                    pol_w = int(sw * 0.88)
                                    pol_h = int(sh * 0.92)
                                ang1 = random.choice([-2.8, -1.8, 1.8, 2.8])
                                pol1 = make_polaroid_surface(img1, meta1, pol_w, pol_h, ang1, font_main, font_small)
                                p1_x = (sw - pol1.get_width()) // 2
                                p1_y = (sh - pol1.get_height()) // 2

                                # Garder une version assombrie pour la table au prochain tirage
                                ghost = safe_smoothscale(pol1, (int(pol1.get_width() * 0.55), int(pol1.get_height() * 0.55))).convert()
                                dark_g = pygame.Surface(ghost.get_size()).convert()
                                dark_g.fill((95, 90, 85))
                                ghost.blit(dark_g, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
                                prev_polaroid_ghost = ghost

                                modern_scene = {
                                    "render_type": "polaroid",
                                    "bg": scene_bg,
                                    "polaroids": [(pol1, p1_x, p1_y, 10, -8)],
                                    "metas": [meta1]
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "solo",
                                    "filename": os.path.basename(file_path),
                                    "label": meta1.get("label", u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "timestamp": time.time()
                                })

                        # =========================================================================
                        # STYLE 3 : MAGAZINE PLEIN ÉCRAN (100% SANS BORDURES & TYPOGRAPHIE XXL)
                        # =========================================================================
                        elif active_render_style == STYLE_MAGAZINE:
                            if is_vertical1 and len(indices) > 1:
                                off2, img2, path2, meta2 = find_partner_photo(current_idx_ptr, want_vertical=True)
                            else:
                                off2, img2, path2, meta2 = (None, None, None, None)

                            scene_bg = pygame.Surface((sw, sh)).convert()
                            scene_bg.fill((12, 14, 20))

                            if img2 is not None:
                                # Double page Magazine 100% plein écran (Split-Screen 50/50)
                                current_step = 2
                                next_ptr = (current_idx_ptr + 1) % len(indices)
                                cand_ptr = (current_idx_ptr + off2) % len(indices)
                                indices[next_ptr], indices[cand_ptr] = indices[cand_ptr], indices[next_ptr]

                                half_w = (sw - 4) // 2
                                c1 = crop_to_aspect(img1, half_w, sh)
                                c2 = crop_to_aspect(img2, sw - half_w - 4, sh)
                                card1 = prepare_modern_card(c1, 0, 0, half_w, sh, allow_zoom=False, overscan=1.08)
                                card2 = prepare_modern_card(c2, half_w + 4, 0, sw - half_w - 4, sh, allow_zoom=False, overscan=1.08)

                                modern_scene = {
                                    "render_type": "magazine",
                                    "is_split": True,
                                    "bg": scene_bg,
                                    "cards": [card1, card2],
                                    "metas": [meta1, meta2]
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "duo",
                                    "filename": "%s + %s" % (os.path.basename(file_path), os.path.basename(path2)),
                                    "label": meta1.get("label", u"") + (u"  |  " + meta2.get("label", u"") if meta2.get("label") else u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "secondary": {
                                        "filename": os.path.basename(path2),
                                        "label": meta2.get("label", u""),
                                        "info": meta2.get("info", u""),
                                        "source_path": meta2.get("source_path", u"")
                                    },
                                    "timestamp": time.time()
                                })
                            else:
                                # Plein écran intégral 100% (Cover)
                                c1 = crop_to_aspect(img1, sw, sh)
                                card1 = prepare_modern_card(c1, 0, 0, sw, sh, allow_zoom=True, overscan=1.10)

                                modern_scene = {
                                    "render_type": "magazine",
                                    "is_split": False,
                                    "bg": scene_bg,
                                    "cards": [card1],
                                    "metas": [meta1]
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "solo",
                                    "filename": os.path.basename(file_path),
                                    "label": meta1.get("label", u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "timestamp": time.time()
                                })

                        # =========================================================================
                        # STYLE 4 & 5 : AMBILIGHT & DUO (MODERN) / NÉON BARTOP (ARCADE)
                        # =========================================================================
                        elif active_render_style in (STYLE_MODERN, STYLE_ARCADE):
                            is_arcade = (active_render_style == STYLE_ARCADE)
                            duo_img2 = None
                            duo_path2 = None
                            meta2 = None

                            if is_vertical1 and len(indices) > 1 and not force_reload_same and random.random() < DUO_PORTRAIT_PROBABILITY:
                                off2, duo_img2, duo_path2, meta2 = find_partner_photo(current_idx_ptr, want_vertical=True)
                                if duo_img2 is not None:
                                    next_ptr = (current_idx_ptr + 1) % len(indices)
                                    cand_ptr = (current_idx_ptr + off2) % len(indices)
                                    indices[next_ptr], indices[cand_ptr] = indices[cand_ptr], indices[next_ptr]
                                    current_step = 2

                            bg_tint = (82, 68, 135) if is_arcade else (125, 128, 138)

                            if duo_img2 is not None:
                                scene_bg = make_blurred_background(img1, sw, sh, duo_img2, tint=bg_tint, vignette_surf=vignette_surf)
                                if is_arcade:
                                    scene_bg.blit(scanline_surf, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

                                margin_x = int(sw * 0.018)
                                gap_x = int(sw * 0.018)
                                slot_w = (sw - 2 * margin_x - gap_x) // 2
                                slot_h = int(sh * 0.94)

                                img1_use, img2_use = harmonize_duo_portraits(img1, duo_img2, slot_w, slot_h)
                                u1_w, u1_h = img1_use.get_size()
                                u2_w, u2_h = img2_use.get_size()

                                r1 = min(float(slot_w) / u1_w, float(slot_h) / u1_h)
                                fw1, fh1 = max(1, int(u1_w * r1)), max(1, int(u1_h * r1))

                                r2 = min(float(slot_w) / u2_w, float(slot_h) / u2_h)
                                fw2, fh2 = max(1, int(u2_w * r2)), max(1, int(u2_h * r2))

                                total_w = fw1 + gap_x + fw2
                                fx1 = (sw - total_w) // 2
                                fx2 = fx1 + fw1 + gap_x
                                fy1 = (sh - fh1) // 2
                                fy2 = (sh - fh2) // 2

                                if is_arcade:
                                    bake_neon_frame_on_bg(scene_bg, fx1, fy1, fw1, fh1, neon_color=(0, 240, 255))
                                    bake_neon_frame_on_bg(scene_bg, fx2, fy2, fw2, fh2, neon_color=(255, 50, 180))
                                    badge1 = build_caption_badge(meta1.get("label", u""), font_small, font_regular, fw1 - 16, border_color=(0, 240, 255), dot_color=(0, 240, 255), date_color=(255, 110, 210))
                                    badge2 = build_caption_badge(meta2.get("label", u""), font_small, font_regular, fw2 - 16, border_color=(255, 50, 180), dot_color=(255, 50, 180), date_color=(0, 240, 255))
                                else:
                                    bake_card_frame_on_bg(scene_bg, fx1, fy1, fw1, fh1, border_px)
                                    bake_card_frame_on_bg(scene_bg, fx2, fy2, fw2, fh2, border_px)
                                    badge1 = build_caption_badge(meta1.get("label", u""), font_small, font_regular, fw1 - 16)
                                    badge2 = build_caption_badge(meta2.get("label", u""), font_small, font_regular, fw2 - 16)

                                card1 = prepare_modern_card(img1_use, fx1, fy1, fw1, fh1, allow_zoom=False)
                                card2 = prepare_modern_card(img2_use, fx2, fy2, fw2, fh2, allow_zoom=False)

                                modern_scene = {
                                    "render_type": "cards",
                                    "bg": scene_bg,
                                    "cards": [card1, card2],
                                    "badges": [
                                        (badge1, fx1 + fw1 // 2, fy1 + fh1 - int(sh * 0.015)),
                                        (badge2, fx2 + fw2 // 2, fy2 + fh2 - int(sh * 0.015))
                                    ],
                                    "metas": [meta1, meta2]
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "duo",
                                    "filename": "%s + %s" % (os.path.basename(file_path), os.path.basename(duo_path2)),
                                    "label": meta1.get("label", u"") + (u"  |  " + meta2.get("label", u"") if meta2.get("label") else u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "secondary": {
                                        "filename": os.path.basename(duo_path2),
                                        "label": meta2.get("label", u""),
                                        "info": meta2.get("info", u""),
                                        "source_path": meta2.get("source_path", u"")
                                    },
                                    "timestamp": time.time()
                                })
                            else:
                                scene_bg = make_blurred_background(img1, sw, sh, tint=bg_tint, vignette_surf=vignette_surf)
                                if is_arcade:
                                    scene_bg.blit(scanline_surf, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

                                max_w = int(sw * 0.96)
                                max_h = int(sh * 0.95)
                                ratio = min(float(max_w) / img1_w, float(max_h) / img1_h)
                                fw = max(1, int(img1_w * ratio))
                                fh = max(1, int(img1_h * ratio))
                                fx = (sw - fw) // 2
                                fy = (sh - fh) // 2

                                if is_arcade:
                                    neon_col = random.choice([(0, 240, 255), (255, 50, 180)])
                                    bake_neon_frame_on_bg(scene_bg, fx, fy, fw, fh, neon_color=neon_col)
                                    badge1 = build_caption_badge(meta1.get("label", u""), font_small, font_regular, int(sw * 0.90), border_color=neon_col, dot_color=neon_col, date_color=(0, 240, 255))
                                else:
                                    bake_card_frame_on_bg(scene_bg, fx, fy, fw, fh, border_px)
                                    badge1 = build_caption_badge(meta1.get("label", u""), font_small, font_regular, int(sw * 0.90))

                                card1 = prepare_modern_card(img1, fx, fy, fw, fh, allow_zoom=True)

                                modern_scene = {
                                    "render_type": "cards",
                                    "bg": scene_bg,
                                    "cards": [card1],
                                    "badges": [(badge1, sw // 2, fy + fh - int(sh * 0.016))],
                                    "metas": [meta1]
                                }

                                write_current_state({
                                    "type": "photo",
                                    "style": active_render_style,
                                    "layout": "solo",
                                    "filename": os.path.basename(file_path),
                                    "label": meta1.get("label", u""),
                                    "info": meta1.get("info", u""),
                                    "source_path": meta1.get("source_path", u""),
                                    "timestamp": time.time()
                                })

                        # =========================================================================
                        # STYLE 6 : CLASSIQUE D'ORIGINE
                        # =========================================================================
                        else:
                            modern_scene = None
                            if is_vertical1:
                                scale_w = sw
                                scale_h = int(img1_h * (float(sw) / img1_w))
                                current_img_raw = pygame.transform.scale(img1, (scale_w, scale_h))
                                anim_type = "scroll_v"
                                scroll_dir = random.choice(["down", "up"])
                            else:
                                ratio = min(float(sw) / img1_w, float(sh) / img1_h)
                                current_img_raw = pygame.transform.scale(img1, (int(img1_w * ratio), int(img1_h * ratio)))
                                anim_type = random.choice(["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"])

                            meta_data = meta1
                            write_current_state({
                                "type": "photo",
                                "style": STYLE_CLASSIC,
                                "layout": "classic",
                                "filename": os.path.basename(file_path),
                                "label": meta_data.get("label", u""),
                                "info": meta_data.get("info", u""),
                                "source_path": meta_data.get("source_path", u""),
                                "timestamp": time.time()
                            })
                            zoom_factor = 1.15 if anim_type == "zoom_out" else 1.0
                            alpha = 0
                            need_load = False
                            force_reload_same = False
                            last_switch = now

                        if active_render_style != STYLE_CLASSIC:
                            meta_data = meta1
                            alpha = 0 if prev_screen_snapshot is not None else 255
                            need_load = False
                            force_reload_same = False
                            last_switch = now

                    except Exception:
                        current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                else:
                    screen.fill((0, 0, 0))
                    margin_h = 60
                    if internal_mode == MODE_VIDEOS_GAMES:
                        vm = parse_game_metadata(file_path)
                        video_meta = {
                            "game": vm["game"],
                            "console": vm["console"],
                            "source_path": file_path
                        }
                        write_current_state({
                            "type": "video_game",
                            "filename": os.path.basename(file_path),
                            "label": vm["game"],
                            "info": vm["console"],
                            "source_path": file_path,
                            "timestamp": time.time()
                        })
                        t1 = font_small.render(vm["game"], True, (255, 255, 255))
                        t2 = font_small.render(vm["console"], True, (0, 255, 255))
                        sh1 = font_small.render(vm["game"], True, (0, 0, 0))
                        sh2 = font_small.render(vm["console"], True, (0, 0, 0))
                        screen.blit(sh1, (sw - t1.get_width() - 18, sh - 43))
                        screen.blit(t1, (sw - t1.get_width() - 20, sh - 45))
                        screen.blit(sh2, (22, sh - 43))
                        screen.blit(t2, (20, sh - 45))
                    else:
                        vm = get_sidecar_data(file_path)
                        label = vm.get("label", u"Vidéo Perso") or u"Vidéo Perso"
                        video_meta = {
                            "label": label,
                            "info": vm.get("info", u""),
                            "source_path": vm.get("source_path", u"") or file_path
                        }
                        write_current_state({
                            "type": "video_perso",
                            "filename": os.path.basename(file_path),
                            "label": label,
                            "info": vm.get("info", u""),
                            "source_path": vm.get("source_path", u""),
                            "timestamp": time.time()
                        })
                        t1 = font_small.render(label, True, (255, 255, 255))
                        sh1 = font_small.render(label, True, (0, 0, 0))
                        screen.blit(sh1, (sw - t1.get_width() - 18, sh - 43))
                        screen.blit(t1, (sw - t1.get_width() - 20, sh - 45))
                        if vm.get("info"):
                            t2 = font_tiny.render(u"Durée : %s" % vm["info"], True, (200, 200, 200))
                            sh2 = font_tiny.render(u"Durée : %s" % vm["info"], True, (0, 0, 0))
                            screen.blit(sh2, (22, sh - 43))
                            screen.blit(t2, (20, sh - 45))

                    if overlay_level == 0:
                        pygame.display.flip()
                        cmd = ["omxplayer", "-o", "both", "--no-osd", "--aspect-mode", "letterbox", "--win", "0,0,%d,%d" % (sw, sh - margin_h)]
                        if is_muted:
                            cmd += ["--vol", "-6000"]
                        cmd.append(file_path)
                        try:
                            video_proc = subprocess.Popen(cmd, stdout=devnull_f, stderr=devnull_f, preexec_fn=os.setsid)
                            video_start_time = now
                            need_load = False
                        except Exception:
                            video_proc = None
                            current_idx_ptr = (current_idx_ptr + 1) % len(indices)
                            need_load = True
                    else:
                        need_load = False

            if not need_load and not show_info and internal_mode == MODE_PHOTOS and now - last_switch > display_time:
                current_idx_ptr = (current_idx_ptr + current_step) % len(indices)
                need_load = True

            # --- 5. AFFICHAGE ---
            if internal_mode == MODE_PHOTOS and not need_load:
                progress = min(1.0, (now - last_switch) / display_time)

                if active_render_style != STYLE_CLASSIC and modern_scene is not None:
                    rtype = modern_scene.get("render_type", "cards")
                    screen.blit(modern_scene["bg"], (0, 0))

                    if rtype == "cards":
                        for card in modern_scene["cards"]:
                            render_modern_card(screen, card, progress, enable_animation and not show_info)
                        if not show_info:
                            for badge, cx, by in modern_scene["badges"]:
                                draw_caption_badge(screen, badge, cx, by)

                    elif rtype == "polaroid":
                        p = max(0.0, min(1.0, progress))
                        t = p * p * (3.0 - 2.0 * p) if (enable_animation and not show_info) else 0.5
                        for pol_surf, px, py, dx, dy in modern_scene["polaroids"]:
                            cur_x = int(px + (t - 0.5) * dx)
                            cur_y = int(py + (t - 0.5) * dy)
                            screen.blit(pol_surf, (cur_x, cur_y))

                    elif rtype == "magazine":
                        for card in modern_scene["cards"]:
                            render_modern_card(screen, card, progress, enable_animation and not show_info)
                        if modern_scene.get("is_split"):
                            pygame.draw.rect(screen, (240, 242, 248), (sw // 2 - 2, 0, 4, sh))
                        if not show_info:
                            screen.blit(bottom_grad_surf, (0, sh - bottom_grad_h), special_flags=pygame.BLEND_RGB_MULT)
                            if modern_scene.get("is_split") and len(modern_scene["metas"]) >= 2:
                                draw_magazine_editorial(screen, modern_scene["metas"][0], 32, sh - 28, sw // 2 - 50, font_main, font_regular, accent_color=(250, 204, 21))
                                draw_magazine_editorial(screen, modern_scene["metas"][1], sw // 2 + 28, sh - 28, sw // 2 - 50, font_main, font_regular, accent_color=(56, 189, 248))
                            else:
                                draw_magazine_editorial(screen, modern_scene["metas"][0], 42, sh - 34, sw - 84, font_editorial, font_small, accent_color=(250, 204, 21))

                    # Fondu enchaîné (Crossfade) fluide avec l'image précédente
                    if prev_screen_snapshot is not None:
                        alpha = min(255, alpha + CROSSFADE_SPEED)
                        if alpha < 255:
                            prev_screen_snapshot.set_alpha(255 - alpha)
                            screen.blit(prev_screen_snapshot, (0, 0))
                        else:
                            prev_screen_snapshot = None

                    has_rendered_photo = True

                elif current_img_raw is not None:
                    # --- RENDU CLASSIQUE D'ORIGINE ---
                    screen.fill((0, 0, 0))

                    if enable_animation and not show_info:
                        if anim_type == "scroll_v":
                            scale_h = current_img_raw.get_height()
                            max_offset = sh - scale_h
                            if scroll_dir == "down":
                                y_offset = int(progress * max_offset)
                            else:
                                y_offset = int((1.0 - progress) * max_offset)
                            img_to_draw = current_img_raw
                            x_offset = 0
                        elif anim_type == "zoom_in":
                            zoom_factor = 1.0 + progress * 0.12
                            z_w = int(current_img_raw.get_width() * zoom_factor)
                            z_h = int(current_img_raw.get_height() * zoom_factor)
                            img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                            x_offset = (sw - z_w) // 2
                            y_offset = (sh - z_h) // 2
                        elif anim_type == "zoom_out":
                            zoom_factor = 1.12 - progress * 0.12
                            z_w = int(current_img_raw.get_width() * zoom_factor)
                            z_h = int(current_img_raw.get_height() * zoom_factor)
                            img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                            x_offset = (sw - z_w) // 2
                            y_offset = (sh - z_h) // 2
                        elif anim_type == "pan_left":
                            zoom_factor = 1.15
                            z_w = int(current_img_raw.get_width() * zoom_factor)
                            z_h = int(current_img_raw.get_height() * zoom_factor)
                            img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                            max_x_offset = sw - z_w
                            max_y_offset = sh - z_h
                            x_offset = int((1.0 - progress) * max_x_offset) if max_x_offset < 0 else max_x_offset // 2
                            y_offset = max_y_offset // 2
                        elif anim_type == "pan_right":
                            zoom_factor = 1.15
                            z_w = int(current_img_raw.get_width() * zoom_factor)
                            z_h = int(current_img_raw.get_height() * zoom_factor)
                            img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                            max_x_offset = sw - z_w
                            max_y_offset = sh - z_h
                            x_offset = int(progress * max_x_offset) if max_x_offset < 0 else max_x_offset // 2
                            y_offset = max_y_offset // 2
                        elif anim_type == "pan_up":
                            zoom_factor = 1.15
                            z_w = int(current_img_raw.get_width() * zoom_factor)
                            z_h = int(current_img_raw.get_height() * zoom_factor)
                            img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                            max_x_offset = sw - z_w
                            max_y_offset = sh - z_h
                            x_offset = max_x_offset // 2
                            y_offset = int((1.0 - progress) * max_y_offset) if max_y_offset < 0 else max_y_offset // 2
                        elif anim_type == "pan_down":
                            zoom_factor = 1.15
                            z_w = int(current_img_raw.get_width() * zoom_factor)
                            z_h = int(current_img_raw.get_height() * zoom_factor)
                            img_to_draw = pygame.transform.scale(current_img_raw, (z_w, z_h))
                            max_x_offset = sw - z_w
                            max_y_offset = sh - z_h
                            x_offset = max_x_offset // 2
                            y_offset = int(progress * max_y_offset) if max_y_offset < 0 else max_y_offset // 2
                    else:
                        img_to_draw = current_img_raw
                        x_offset = (sw - current_img_raw.get_width()) // 2
                        y_offset = (sh - current_img_raw.get_height()) // 2

                    if alpha < 255:
                        alpha += FADE_SPEED
                    img_to_draw.set_alpha(min(alpha, 255))
                    screen.blit(img_to_draw, (x_offset, y_offset))

                    if not show_info and meta_data.get("label"):
                        label = meta_data["label"]
                        txt = font_classic_small.render(label, True, (255, 255, 255))
                        shd = font_classic_small.render(label, True, (0, 0, 0))
                        tx, ty = sw - txt.get_width() - 30, sh - txt.get_height() - 30
                        screen.blit(shd, (tx + 2, ty + 2))
                        screen.blit(txt, (tx, ty))

                    has_rendered_photo = True

            elif internal_mode != MODE_PHOTOS and overlay_level != 0:
                draw_video_backdrop(screen, sw, sh, internal_mode, video_meta, is_muted, font_main, font_small, font_regular)
            elif internal_mode != MODE_PHOTOS and overlay_level == 0 and not need_load:
                # Redessine la barre inférieure de 60px (sous omxplayer) pour afficher/effacer le toast de son ou de cycle
                pygame.draw.rect(screen, (0, 0, 0), (0, sh - 60, sw, 60))
                if internal_mode == MODE_VIDEOS_GAMES:
                    g_name = video_meta.get("game", u"")
                    c_name = video_meta.get("console", u"")
                    t1 = font_small.render(g_name, True, (255, 255, 255))
                    t2 = font_small.render(c_name, True, (0, 255, 255))
                    screen.blit(t2, (20, sh - 45))
                    screen.blit(t1, (sw - t1.get_width() - 20, sh - 45))
                else:
                    lbl = video_meta.get("label", u"Vidéo Perso")
                    inf = video_meta.get("info", u"")
                    t1 = font_small.render(lbl, True, (255, 255, 255))
                    screen.blit(t1, (sw - t1.get_width() - 20, sh - 45))
                    if inf:
                        t2 = font_tiny.render(u"Durée : %s" % inf, True, (200, 200, 200))
                        screen.blit(t2, (20, sh - 42))
                if now < toast_State[2] and toast_State[0]:
                    t_surf = font_small.render(toast_State[0], True, toast_State[1])
                    screen.blit(t_surf, ((sw - t_surf.get_width()) // 2, sh - 45))

            # --- 6. SUPERPOSITION INFOS/TOOLTIPS (NIVEAU 1), MENU (NIVEAU 2) OU TOAST DISCRET (NIVEAU 0) ---
            if overlay_level == 1:
                metas_to_show = modern_scene["metas"] if (internal_mode == MODE_PHOTOS and active_render_style != STYLE_CLASSIC and modern_scene) else [meta_data]
                idx_num = (indices[current_idx_ptr] + 1) if indices else 1
                total_cnt = len(all_files) if all_files else 1
                draw_info_overlay(
                    screen, sw, sh, current_mode, internal_mode, photo_style, active_render_style, is_muted,
                    metas_to_show, video_meta, idx_num, total_cnt, overlay_deadline - now,
                    font_main, font_small, font_regular, font_tiny
                )
            elif overlay_level == 2:
                draw_settings_menu(
                    screen, sw, sh, menu_selected_row, current_mode, internal_mode, photo_style, is_muted, display_time,
                    overlay_deadline - now, font_main, font_small, font_regular, font_tiny
                )
            elif now < toast_State[2] and internal_mode == MODE_PHOTOS:
                draw_corner_toast(screen, sw, sh, toast_State[0], font_small, accent_color=toast_State[1])

            pygame.display.flip()
            time.sleep(0.03)
    finally:
        if video_proc:
            stop_video(video_proc)
        try:
            devnull_f.close()
        except Exception:
            pass
        for f in input_files:
            f.close()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-animation", action="store_true")
    parser.add_argument("--style", choices=STYLE_ORDER, default=None)
    args = parser.parse_args()
    if args.style:
        s = load_settings()
        s["photo_style"] = args.style
        save_settings(s)
    run_slideshow(enable_animation=not args.no_animation)
