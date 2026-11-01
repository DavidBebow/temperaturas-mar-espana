#!/usr/bin/env python3
"""Captura PNG diaria de cada herramienta del observatorio (capa «Reutilizar», bloque F).

Lee docs/reutilizar/herramientas.json, abre cada widget con ?captura=1 en Chromium
(Playwright), guarda el PNG optimizado en capturas_out/ y escribe
docs/capturas/indice.json. Subir los PNG a la release «capturas» lo hace el workflow.

Uso:  python3 scripts/capturas.py [--solo ID[,ID]] [--base URL] [--out DIR]
  --base  origen desde el que se sirven los widgets (por defecto, el del catálogo, es decir Pages;
          en local: http://localhost:8000/ con `python3 -m http.server -d docs`).
Nunca aborta la pasada: lo que falla queda anotado en capturas_out/fallos.json.
"""
import argparse
import io
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
REPO = "davidbebow/temperaturas-mar-espana"
URL_RELEASE = "https://github.com/%s/releases/download/capturas/" % REPO
TOPE_ALTO = 2400
MAX_BYTES = 400 * 1024


def plegar(s):
    """Nombre seguro para release y URL: sin tildes, ASCII, minúsculas."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-")


def variantes(h):
    """Lista de (slug|None, ruta relativa del widget, parámetros) de una herramienta."""
    w = h["widget"]
    if "{slug}" in w:  # copias por fichero: embalses/<slug>.html
        carpeta = DOCS / Path(w).parent
        vistos, out = set(), []
        excluir = {"provincia", "ficha", "index"}
        for f in sorted(carpeta.glob("*.html")):
            slug = unicodedata.normalize("NFC", f.stem)
            if slug in excluir or slug in vistos:
                continue
            vistos.add(slug)
            out.append((slug, f.name and (Path(w).parent / f.name).as_posix(), {}))
        return out
    if h.get("parametro"):  # plantilla con parámetro: provincia.html?p=<slug>
        idx = json.loads((DOCS / "provincias" / "index.json").read_text(encoding="utf-8"))
        lista = idx["provincias"]
        slugs = sorted(x["slug"] for x in lista) if isinstance(lista, list) else sorted(lista)
        return [(s, w, {h["parametro"]: s}) for s in slugs]
    return [(None, w, {})]


def optimizar(png_bytes):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    if buf.tell() > MAX_BYTES:
        q = im.quantize(256)
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True)
    return buf.getvalue(), im.size


def _local(route):
    import mimetypes
    from urllib.parse import unquote, urlparse
    rel = unquote(urlparse(route.request.url).path.split("/temperaturas-mar-espana/", 1)[1])
    f = DOCS / rel
    if f.is_file():
        route.fulfill(status=200, body=f.read_bytes(),
                      content_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream")
    else:
        route.fulfill(status=404, body=b"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--out", default=str(RAIZ / "capturas_out"))
    a = ap.parse_args()

    cat = json.loads((DOCS / "reutilizar" / "herramientas.json").read_text(encoding="utf-8"))
    base = a.base or cat["base"]
    if not base.endswith("/"):
        base += "/"
    solo = {x.strip() for x in a.solo.split(",") if x.strip()}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    trabajos = []
    for h in cat["herramientas"]:
        if not h.get("captura"):
            continue  # p. ej. las 374 fichas de embalse: fuera por volumen
        if solo and h["id"] not in solo:
            continue
        for slug, rel, params in variantes(h):
            trabajos.append((h, slug, rel, params))
    print("capturas previstas:", len(trabajos), flush=True)

    # Índice previo: se conserva lo que no se vuelva a capturar (--solo) para no perder entradas.
    ip = DOCS / "capturas" / "indice.json"
    previo = {}
    if ip.exists():
        try:
            previo = json.loads(ip.read_text(encoding="utf-8")).get("capturas", {})
        except Exception:
            previo = {}
    capturas, fallos = dict(previo) if solo else {}, []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for n, (h, slug, rel, params) in enumerate(trabajos, 1):
            cfg = h["captura"]
            clave = plegar(h["id"] + ("-" + slug if slug else ""))
            qs = "&".join("%s=%s" % (k, quote(v)) for k, v in params.items())
            url = base + quote(rel, safe="/") + "?" + (qs + "&" if qs else "") + "captura=1&t=" + str(int(time.time()))
            t0 = time.time()
            ctx = None
            try:
                ctx = nav.new_context(viewport={"width": cfg["ancho"], "height": cfg["alto"]},
                                      device_scale_factor=1, locale="es-ES", timezone_id="Europe/Madrid")
                if "localhost" in base:  # prueba local: los recursos absolutos de Pages se sirven desde docs/
                    ctx.route("https://davidbebow.github.io/temperaturas-mar-espana/**", _local)
                pg = ctx.new_page()
                pg.goto(url, wait_until="networkidle", timeout=60000)
                try:
                    pg.wait_for_function("window.__cgCapturaLista === true", timeout=15000)
                except Exception:
                    raise RuntimeError("la banda de captura no llegó a pintarse (__cgCapturaLista)")
                pg.wait_for_timeout(cfg.get("espera_ms", 3000))
                completa = bool(cfg.get("completa"))
                if completa:
                    alto_doc = pg.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)")
                    completa = alto_doc <= TOPE_ALTO
                png = pg.screenshot(full_page=completa, type="png")
                datos, (w, hh) = optimizar(png)
                (out / (clave + ".png")).write_bytes(datos)
                capturas[clave] = {"url": URL_RELEASE + clave + ".png", "fecha": hoy,
                                   "bytes": len(datos), "ancho": w, "alto": hh}
                print("[%d/%d] OK   %s %d KB %dx%d %.1fs" % (n, len(trabajos), clave, len(datos) // 1024, w, hh, time.time() - t0), flush=True)
            except Exception as e:  # nunca aborta la pasada
                fallos.append({"clave": clave, "url": url, "motivo": str(e)[:300]})
                print("[%d/%d] FALLO %s: %s" % (n, len(trabajos), clave, str(e)[:160]), flush=True)
            finally:
                if ctx:
                    ctx.close()
        nav.close()

    (out / "fallos.json").write_text(json.dumps(fallos, ensure_ascii=False, indent=1), encoding="utf-8")
    ip.parent.mkdir(parents=True, exist_ok=True)
    ip.write_text(json.dumps({"generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "capturas": dict(sorted(capturas.items()))}, ensure_ascii=False, indent=1) + "\n",
                  encoding="utf-8")
    print("hechas: %d · fallidas: %d" % (len(trabajos) - len(fallos), len(fallos)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
