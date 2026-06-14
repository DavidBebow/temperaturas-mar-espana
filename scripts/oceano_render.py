#!/usr/bin/env python3
"""
OCÉANO · Paso 3 de 3
Convierte la rejilla (_grid_oceano.npz) en la capa visual del mapa, reproyectada a
Web Mercator y con la tierra transparente, más una tarjeta social opcional.

Salidas (en docs/):
  oceano_hoy.png        -> capa coloreada por categoría
  tarjeta_oceano.png    -> tarjeta cuadrada para Instagram

Requiere: numpy, pillow
"""
import os, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GRID = os.path.join(ROOT, "_grid_oceano.npz")

COL = {0:(14,42,74,90), 1:(253,224,71,205), 2:(251,146,60,215),
       3:(239,68,68,225), 4:(127,29,29,235), 5:(90,12,12,240)}
LAT_MAX = 85.05112878

def to_mercator(img, lats):
    H = 512
    ymax = np.log(np.tan(np.pi/4 + np.radians(LAT_MAX)/2))
    yr = np.linspace(ymax, -ymax, H)
    latr = np.degrees(2*np.arctan(np.exp(yr)) - np.pi/2)
    idx = np.abs(lats[None, :] - latr[:, None]).argmin(axis=1)
    return img[idx]

def main():
    if not os.path.exists(GRID):
        print("OMITIDO: no hay rejilla nueva (la descarga se saltó). Se conserva el PNG anterior.")
        return
    z = np.load(GRID); cat, lats = z["cat"], z["lats"]
    if lats[0] < lats[-1]: cat = cat[::-1]; lats = lats[::-1]
    H, W = cat.shape
    img = np.zeros((H, W, 4), np.uint8); ocean = cat >= 0
    for c, rgba in COL.items():
        img[(np.round(cat) == c) & ocean] = rgba
    img[~ocean] = (0, 0, 0, 0)
    Image.fromarray(to_mercator(img, lats), "RGBA").save(os.path.join(DOCS, "oceano_hoy.png"))
    print("OK  docs/oceano_hoy.png")
    try:
        card(json.load(open(os.path.join(DOCS, "oceano.json"), encoding="utf8")))
    except Exception as e:                            # noqa
        print(f"  (tarjeta social omitida: {e})")

def card(d):
    W = H = 1080
    bg = Image.new("RGB", (W, H), (10, 16, 32))
    base = Image.open(os.path.join(DOCS, "oceano_hoy.png")).convert("RGBA")
    base = base.resize((W, int(W*base.height/base.width)))
    bg.paste(base, (0, (H-base.height)//2), base)
    dr = ImageDraw.Draw(bg)
    try:
        f1 = ImageFont.truetype("DejaVuSans-Bold.ttf", 92); f2 = ImageFont.truetype("DejaVuSans.ttf", 34)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    g = d["global"]
    dr.text((60, 70), "EL PLANETA HOY", font=f2, fill=(159,178,208))
    dr.text((60, 120), f"{g['pct_en_mhw']:.1f}%".replace(".", ","), font=f1, fill=(251,146,60))
    dr.text((60, 240), "del océano en ola de calor marina", font=f2, fill=(234,241,255))
    if g.get("racha_dias"):
        dr.text((60, H-120), f"▲ {g['racha_dias']} días seguidos sobre la media", font=f2, fill=(52,211,153))
    dr.text((60, H-60), "CalentamientoGlobal.es · Fuente: NOAA Coral Reef Watch", font=f2, fill=(159,178,208))
    bg.save(os.path.join(DOCS, "tarjeta_oceano.png"))
    print("OK  docs/tarjeta_oceano.png")

if __name__ == "__main__":
    main()
