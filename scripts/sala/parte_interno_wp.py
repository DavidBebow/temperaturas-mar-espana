#!/usr/bin/env python3
"""
Envía el parte interno del almacén a WordPress por la vía autenticada que ya usan el resto de scripts (REST de WordPress con
WP_USER + contraseña de aplicación, meta de la página 22057 «Parte interno del almacén»; mismo patrón que niebla.py, heladas.py, nieve.py).

  Workflow (detector):  python scripts/sala/parte_interno_wp.py --clave detector
  Air (lo suyo):        python scripts/sala/parte_interno_wp.py --clave air --archivo /ruta/interno_air.json

Guarda el JSON en el meta `cg_parte_interno` (detector) o `cg_parte_interno_air` (Air) de la página. El meta lo registra el plugin
cg-sala-prensa 7.2.0 (register_post_meta, solo editable por quien pueda editar páginas); el shortcode [cg_parte_interno] lo pinta
en el servidor solo para administradores. Nada de esto se publica en docs/ ni en Pages.

Variables: WP_USER, WP_APP_PASSWORD (en el workflow, el secreto WP_APP_AGOSTO). Nunca tumba la pasada: devuelve 0 aunque falle y lo dice.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
WP_API = os.environ.get("WP_API", "https://calentamientoglobal.es/wp-json/wp/v2")
WP_PAGINA = int(os.environ.get("WP_PARTE_PAGINA", "22057"))
META = {"detector": "cg_parte_interno", "air": "cg_parte_interno_air"}
UA = "calentamientoglobal.es/parte-interno"


def enviar(clave: str, archivo: Path) -> str:
    usuario, pwd = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
    if not usuario or not pwd:
        return "parte interno: sin WP_USER / WP_APP_PASSWORD, no se envía"
    if not archivo.exists():
        return f"parte interno: no existe {archivo}, no se envía"
    texto = archivo.read_text(encoding="utf-8")
    try:
        json.loads(texto)
    except ValueError as e:
        return f"parte interno: {archivo.name} no es JSON válido ({e}), no se envía"
    cuerpo = json.dumps({"meta": {META[clave]: texto}}).encode()
    aut = "Basic " + base64.b64encode(f"{usuario}:{pwd}".encode()).decode()
    ultimo = None
    for i in range(3):
        req = urllib.request.Request(f"{WP_API}/pages/{WP_PAGINA}", data=cuerpo, method="POST", headers={
            "Authorization": aut, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8") or "null") or {}
            guardado = (res.get("meta") or {}).get(META[clave])
            if not guardado:
                return f"parte interno ({clave}): AVISO, WordPress no ha guardado el meta {META[clave]} (¿plugin 7.2.0 sin instalar?)"
            h = hashlib.sha256(texto.encode()).hexdigest()[:12]
            return f"parte interno ({clave}): enviado a la página {WP_PAGINA} ({len(texto)} caracteres, sha {h})"
        except Exception as e:           # noqa: BLE001
            ultimo = e
            if i < 2:
                time.sleep(8 * (i + 1))
    return f"parte interno ({clave}): ERROR {type(ultimo).__name__}: {ultimo}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clave", choices=sorted(META), default="detector")
    ap.add_argument("--archivo", default="")
    a = ap.parse_args()
    f = Path(a.archivo) if a.archivo else RAIZ / "salida_privada" / "parte_interno.json"
    try:
        print(enviar(a.clave, f))
    except Exception as e:               # noqa: BLE001
        print(f"parte interno: ERROR {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
