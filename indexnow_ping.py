#!/usr/bin/env python3
"""
indexnow_ping.py — Notifica a IndexNow (Bing, Yandex, DuckDuckGo, Ecosia...)
que una o varias URLs se han actualizado, para reindexación casi inmediata.

Pensado para engancharse al final de un workflow de GitHub Actions que
actualiza datos (mapas, observatorio, etc.). Bing es el índice que alimenta
ChatGPT y Copilot, así que mantener estas URLs frescas ahí es lo más rentable.

Uso:
    # URLs sueltas por argumento
    python indexnow_ping.py https://calentamientoglobal.es/pagina-1/ https://calentamientoglobal.es/pagina-2/

    # o desde un fichero (una URL por línea)
    python indexnow_ping.py --file urls.txt

Config por variables de entorno (recomendado en GitHub Actions Secrets):
    INDEXNOW_KEY           clave IndexNow (hex, 8-128 chars)   [obligatorio]
    INDEXNOW_HOST          dominio sin protocolo               [def: calentamientoglobal.es]
    INDEXNOW_KEY_LOCATION  URL pública del fichero de clave    [def: https://<HOST>/<KEY>.txt]

Códigos de salida: 0 = OK; 1 = error de configuración/red.
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.error

ENDPOINT = "https://api.indexnow.org/indexnow"  # hub compartido; reparte a Bing/Yandex/etc.


def load_urls(args) -> list[str]:
    urls: list[str] = []
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            urls += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    urls += args.urls
    # dedup preservando orden
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*", help="URLs a notificar")
    ap.add_argument("--file", help="fichero con una URL por línea")
    args = ap.parse_args()

    key = os.environ.get("INDEXNOW_KEY", "").strip()
    host = os.environ.get("INDEXNOW_HOST", "calentamientoglobal.es").strip()
    key_location = os.environ.get(
        "INDEXNOW_KEY_LOCATION", f"https://{host}/{key}.txt"
    ).strip()

    if not key:
        print("ERROR: falta INDEXNOW_KEY", file=sys.stderr)
        return 1

    urls = load_urls(args)
    if not urls:
        print("ERROR: no se han pasado URLs", file=sys.stderr)
        return 1

    # IndexNow acepta hasta 10.000 URLs por envío; troceamos por seguridad.
    CHUNK = 10000
    ok = True
    for i in range(0, len(urls), CHUNK):
        batch = urls[i : i + CHUNK]
        payload = {
            "host": host,
            "key": key,
            "keyLocation": key_location,
            "urlList": batch,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                code = resp.getcode()
                print(f"IndexNow OK ({code}) — {len(batch)} URLs enviadas")
                for u in batch:
                    print(f"  · {u}")
        except urllib.error.HTTPError as e:
            ok = False
            body = e.read().decode("utf-8", "ignore")
            meaning = {
                400: "Bad request (JSON mal formado)",
                403: "Clave inválida o no encontrada en keyLocation",
                422: "Alguna URL no pertenece al host, o keyLocation no coincide",
                429: "Demasiadas peticiones (throttling)",
            }.get(e.code, "error")
            print(f"IndexNow FALLO {e.code} — {meaning}\n{body}", file=sys.stderr)
        except urllib.error.URLError as e:
            ok = False
            print(f"IndexNow error de red: {e.reason}", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
