#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera os icones de cadeado da bandeja (azul=congelado, laranja=
descongelado) via Pillow -- sem depender de arquivos de imagem em disco."""
from PIL import Image, ImageDraw

BLUE = (0x2F, 0x6F, 0xED, 255)
ORANGE = (0xF5, 0xA6, 0x23, 255)
_SIZE = 64


def _lock_icon(color):
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((14, 28, 50, 56), radius=6, fill=color)   # corpo
    d.arc((18, 6, 46, 42), start=180, end=360, fill=color, width=6)  # argola
    d.ellipse((28, 36, 36, 44), fill=(0, 0, 0, 160))              # fechadura
    return img


def frozen_icon():
    """Cadeado azul: arvore congelada."""
    return _lock_icon(BLUE)


def thawed_icon():
    """Cadeado laranja: arvore descongelada."""
    return _lock_icon(ORANGE)


def icon_for(frozen):
    return frozen_icon() if frozen else thawed_icon()
