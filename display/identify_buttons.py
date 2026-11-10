#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Script d'identification des boutons du meuble Arcade Bartop.
Permet de tester et cartographier les boutons du panel supérieur et de la façade.
Compatible Python 2.7 et Python 3.x.
"""
from __future__ import print_function
import os
import sys
import glob
import time
import struct
import fcntl
import json

SETTINGS_FILE = "/recalbox/share/userscripts/slideshow/slideshow_settings.json"

EV_KEY = 1
event_format = 'llHHi'
event_size = struct.calcsize(event_format)

def get_input_devices():
    return glob.glob('/dev/input/event*')

def load_settings():
    defaults = {
        "front_buttons": [296, 297, 312, 313, 314, 315]
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
        except Exception:
            pass
    return defaults

def save_settings(s):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(s, f)
        print("\n[OK] Configuration sauvegardee dans %s" % SETTINGS_FILE)
    except Exception as e:
        print("\n[ERREUR] Impossible de sauvegarder : %s" % str(e))

def run_identifier_gui():
    """Mode graphique plein écran directement sur l'écran du Bartop."""
    try:
        import pygame
    except ImportError:
        print("Pygame non disponible. Passage en mode console.")
        run_identifier_cli()
        return

    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_NOMOUSE"] = "1"
    pygame.init()

    info = pygame.display.Info()
    sw = info.current_w or 1280
    sh = info.current_h or 1024
    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)

    font_title = pygame.font.Font(None, int(sh * 0.055))
    font_sub = pygame.font.Font(None, int(sh * 0.035))
    font_code = pygame.font.Font(None, int(sh * 0.080))
    font_small = pygame.font.Font(None, int(sh * 0.028))

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

    settings = load_settings()
    front_set = set(settings.get("front_buttons", [296, 297, 312, 313, 314, 315]))

    last_code = None
    last_type = u""
    press_count = 0
    history = []

    running = True
    clock = pygame.time.Clock()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

        for f in input_files:
            try:
                data = f.read(event_size)
                while data:
                    _, _, ev_type, ev_code, ev_val = struct.unpack(event_format, data)
                    if ev_type == EV_KEY and ev_val == 1:
                        last_code = ev_code
                        press_count += 1
                        is_front = (ev_code in front_set)
                        last_type = u"FAÇADE (Sortie)" if is_front else u"PANEL SUPÉRIEUR (Jeu)"
                        history.append((ev_code, last_type, time.strftime("%H:%M:%S")))
                        if len(history) > 8:
                            history.pop(0)
                    data = f.read(event_size)
            except Exception:
                pass

        # Rendu graphique
        screen.fill((15, 20, 32))

        # En-tête
        t1 = font_title.render("IDENTIFICATEUR DE TOUCHES BARTOP", True, (56, 189, 248))
        screen.blit(t1, ((sw - t1.get_width()) // 2, int(sh * 0.06)))

        t2 = font_sub.render("Appuyez sur n'importe quel bouton du meuble", True, (200, 210, 225))
        screen.blit(t2, ((sw - t2.get_width()) // 2, int(sh * 0.13)))

        # Cadre central code détecté
        card_w = int(sw * 0.84)
        card_h = int(sh * 0.35)
        card_x = (sw - card_w) // 2
        card_y = int(sh * 0.22)
        pygame.draw.rect(screen, (24, 32, 50), (card_x, card_y, card_w, card_h), 0)
        pygame.draw.rect(screen, (99, 102, 241), (card_x, card_y, card_w, card_h), 3)

        if last_code is not None:
            c_surf = font_code.render("CODE LINUX : %d" % last_code, True, (251, 191, 36))
            screen.blit(c_surf, ((sw - c_surf.get_width()) // 2, card_y + int(card_h * 0.22)))

            col = (239, 68, 68) if u"FAÇADE" in last_type else (52, 211, 153)
            ty_surf = font_sub.render("Classification : %s" % last_type, True, col)
            screen.blit(ty_surf, ((sw - ty_surf.get_width()) // 2, card_y + int(card_h * 0.62)))
        else:
            wait_surf = font_sub.render("En attente d'un appui sur un bouton...", True, (148, 163, 184))
            screen.blit(wait_surf, ((sw - wait_surf.get_width()) // 2, card_y + int(card_h * 0.42)))

        # Historique des derniers appuis
        hist_y = int(sh * 0.63)
        h_title = font_sub.render("Derniers boutons détectés :", True, (165, 180, 252))
        screen.blit(h_title, (card_x + 20, hist_y))

        for idx, (code, c_type, c_time) in enumerate(reversed(history)):
            hy = hist_y + 40 + idx * int(sh * 0.038)
            col = (248, 113, 113) if u"FAÇADE" in c_type else (110, 231, 183)
            row_txt = font_small.render("[%s]  Code: %d   ->   %s" % (c_time, code, c_type), True, col)
            screen.blit(row_txt, (card_x + 30, hy))

        # Pied d'écran
        foot = font_small.render("Appuyez sur la touche 'Q' ou 'Echap' du clavier pour quitter", True, (100, 116, 139))
        screen.blit(foot, ((sw - foot.get_width()) // 2, sh - 40))

        pygame.display.flip()
        clock.tick(30)

    for f in input_files:
        try:
            f.close()
        except Exception:
            pass
    pygame.quit()


def run_identifier_cli():
    """Mode console terminal interactif (accessible via SSH)."""
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

    settings = load_settings()
    front_set = set(settings.get("front_buttons", [296, 297, 312, 313, 314, 315]))

    print("=" * 65)
    print("      IDENTIFICATEUR DE TOUCHES BARTOP RETROPIE / RECALBOX")
    print("=" * 65)
    print("Appuyez sur les boutons de votre meuble.")
    print("Ce script affiche en direct le code Linux evdev de chaque bouton.")
    print("(Faites CTRL+C pour quitter)\n")
    print("Boutons de facade actuels qui provoquent la sortie : %s\n" % list(front_set))
    print("-" * 65)

    try:
        while True:
            for f in input_files:
                try:
                    data = f.read(event_size)
                    while data:
                        _, _, ev_type, ev_code, ev_val = struct.unpack(event_format, data)
                        if ev_type == EV_KEY and ev_val == 1:
                            is_front = (ev_code in front_set)
                            nature = "FAÇADE [QUITTE]" if is_front else "PANEL DESSUS [INFOS/MENU]"
                            print("[%s] BOUTON PRESSÉ -> Code: %-4d | %s" % (
                                time.strftime("%H:%M:%S"), ev_code, nature
                            ))
                        data = f.read(event_size)
                except Exception:
                    pass
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n\nTest termine par l'utilisateur.")
    finally:
        for f in input_files:
            try:
                f.close()
            except Exception:
                pass

if __name__ == "__main__":
    if "--cli" in sys.argv or not os.environ.get("DISPLAY") and not os.path.exists("/dev/fb0"):
        run_identifier_cli()
    else:
        try:
            run_identifier_gui()
        except Exception as e:
            print("[INFO] Fallback vers mode console : %s" % str(e))
            run_identifier_cli()
