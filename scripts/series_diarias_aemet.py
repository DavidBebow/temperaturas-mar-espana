#!/usr/bin/env python3
"""Series diarias largas de AEMET, estación a estación · calentamientoglobal.es

Para qué: medir lo que una media mensual no deja ver — cuánto dura el verano (del primer al último día de calor),
las noches tropicales, los días de lluvia torrencial o la primera helada desde 1920-1950, con el dato diario de la
propia estación de AEMET y no con un reanálisis.

Qué baja: valores climatológicos diarios (API de AEMET OpenData, /valores/climatologicos/diarios/...) de las
estaciones con tabla de extremos desde 1960 o antes (docs/records/baseline.json) y de las estaciones de ciudad que ya
usa el observatorio (scripts/obtener_temperaturas_nocturnas.py). AEMET admite como mucho 6 meses por petición: se
pide por semestres, del más reciente al más antiguo.

Dónde lo deja: archivo/aemet_diario/<indicativo>.csv.gz (fecha, tmax, tmin, tmed, prec; prec = None cuando AEMET da
«Acum», lluvia de varios días sumada; «Ip», inapreciable, cuenta como 0,0) y archivo/aemet_diario/estado.json (qué
semestres hay, cuáles fallaron, cuándo se refrescó).

Es reanudable: cada pasada sigue donde lo dejó la anterior y se para sola antes de `SERIES_TOPE_MIN` minutos.
Cuando una estación está completa, solo se refrescan sus dos últimos semestres (una vez por semana).
Sin dependencias: solo la biblioteca estándar.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "archivo" / "aemet_diario"
ESTADO = DIR / "estado.json"
BASE = "https://opendata.aemet.es/opendata/api"
KEY = os.environ.get("AEMET_API_KEY", "")
TOPE_MIN = float(os.environ.get("SERIES_TOPE_MIN", "300"))
PAUSA = float(os.environ.get("SERIES_PAUSA", "1.3"))      # entre peticiones: el API comparte cupo con otros flujos
ANIO_MIN = 1920
DESDE_MAX = 1960                                          # estaciones con tabla de extremos desde este año o antes
REFRESCO_DIAS = 7
T0 = time.time()


def log(m):
    print(time.strftime("%H:%M:%S ") + m, flush=True)


def leer_json(p, defecto):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defecto


def estaciones():
    """Lista ordenada: primero las de ciudad (capitales), después las de serie larga del inventario de extremos."""
    ciudad = re.findall(r'"idema":\s*"([^"]+)"', (RAIZ / "scripts" / "obtener_temperaturas_nocturnas.py").read_text(encoding="utf-8"))
    base = (leer_json(RAIZ / "docs" / "records" / "baseline.json", {}) or {}).get("estaciones") or {}
    largas = sorted((v.get("desde") or 9999, k) for k, v in base.items() if (v.get("desde") or 9999) <= DESDE_MAX)
    orden, vistos = [], set()
    for ide in ciudad + [k for _, k in largas]:
        if ide not in vistos:
            vistos.add(ide)
            desde = (base.get(ide) or {}).get("desde") or 1950
            orden.append((ide, max(ANIO_MIN, int(desde)), (base.get(ide) or {}).get("nombre")))
    return orden


def peticion(url, intentos=4):
    """GET con la clave en la URL (como pide AEMET). Devuelve (json o None, mensaje)."""
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "calentamientoglobal.es/series"})
            with urllib.request.urlopen(req, timeout=90) as r:
                cuerpo = r.read()
            try:
                return json.loads(cuerpo.decode("latin-1") if cuerpo[:1] not in (b"{", b"[") else cuerpo.decode("utf-8", "replace")), "ok"
            except Exception:  # noqa: BLE001
                return json.loads(cuerpo.decode("latin-1")), "ok"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log(f"  429: espero {60 * (i + 1)} s")
                time.sleep(60 * (i + 1))
                continue
            if e.code == 404:
                try:
                    return json.loads(e.read().decode("utf-8", "replace")), "404"
                except Exception:  # noqa: BLE001
                    return None, "404"
            msg = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
        time.sleep(5 * (i + 1))
    return None, msg


def semestre(ide, anio, mitad):
    ini, fin = (f"{anio}-01-01", f"{anio}-06-30") if mitad == 1 else (f"{anio}-07-01", f"{anio}-12-31")
    url = (f"{BASE}/valores/climatologicos/diarios/datos/fechaini/{ini}T00:00:00UTC/fechafin/{fin}T23:59:59UTC/estacion/"
           f"{urllib.parse.quote(ide)}?api_key={KEY}")
    meta, msg = peticion(url)
    time.sleep(PAUSA)
    if meta is None:
        return None, msg
    est = meta.get("estado")
    if est == 404 or msg == "404":
        return [], "sin datos"
    if est == 429:
        time.sleep(60)
        return None, "429"
    if est != 200 or not meta.get("datos"):
        return None, f"estado {est}: {str(meta.get('descripcion'))[:80]}"
    datos, msg = peticion(meta["datos"])
    time.sleep(PAUSA)
    if datos is None:
        return None, msg
    return datos if isinstance(datos, list) else [], "ok"


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if s == "Ip":
        return 0.0
    if s in ("", "Acum", "Varias"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def leer_csv(ide):
    f = DIR / f"{ide}.csv.gz"
    if not f.exists():
        return {}
    out = {}
    for r in csv.DictReader(io.TextIOWrapper(gzip.open(f), encoding="utf-8")):
        out[r["fecha"]] = r
    return out


def escribir_csv(ide, filas):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DIR / f"{ide}.csv.gz.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as g:
        w = csv.writer(g)
        w.writerow(["fecha", "tmax", "tmin", "tmed", "prec"])
        for k in sorted(filas):
            r = filas[k]
            w.writerow([k, r.get("tmax", ""), r.get("tmin", ""), r.get("tmed", ""), r.get("prec", "")])
    tmp.replace(DIR / f"{ide}.csv.gz")


def fila(d):
    def t(x):
        v = num(x)
        return "" if v is None else f"{v:.1f}"
    return {"tmax": t(d.get("tmax")), "tmin": t(d.get("tmin")), "tmed": t(d.get("tmed")), "prec": t(d.get("prec"))}


def main():
    if not KEY:
        log("Falta AEMET_API_KEY")
        return 1
    estado = leer_json(ESTADO, {}) or {}
    estado.setdefault("estaciones", {})
    hoy = date.today()
    lista = estaciones()
    log(f"{len(lista)} estaciones en la lista")
    peticiones = 0
    for n, (ide, desde, nombre) in enumerate(lista, 1):
        if (time.time() - T0) / 60 > TOPE_MIN:
            log("Tope de tiempo: sigo en la próxima pasada")
            break
        e = estado["estaciones"].setdefault(ide, {"nombre": nombre, "desde_pedido": desde, "hechos": [], "fallidos": [], "completa": False})
        hechos = set(e["hechos"])
        semestres = [(a, m) for a in range(hoy.year, desde - 1, -1) for m in (2, 1) if date(a, 1 if m == 1 else 7, 1) <= hoy]
        if e.get("completa"):
            ult = e.get("refrescado")
            if ult and (hoy - date.fromisoformat(ult)).days < REFRESCO_DIAS:
                continue
            pendientes = semestres[:2]
        else:
            pendientes = [s for s in semestres if f"{s[0]}-{s[1]}" not in hechos] + semestres[:1]
        filas = leer_csv(ide)
        vacios_seguidos = 0
        nuevos = 0
        for a, m in pendientes:
            if (time.time() - T0) / 60 > TOPE_MIN:
                break
            datos, msg = semestre(ide, a, m)
            peticiones += 1
            clave = f"{a}-{m}"
            if datos is None:
                if clave not in e["fallidos"]:
                    e["fallidos"].append(clave)
                log(f"  {ide} {clave}: fallo ({msg})")
                continue
            if clave in e["fallidos"]:
                e["fallidos"].remove(clave)
            hechos.add(clave)
            if datos:
                vacios_seguidos = 0
                for d in datos:
                    if d.get("fecha"):
                        filas[d["fecha"]] = fila(d)
                        nuevos += 1
            else:
                vacios_seguidos += 1
                # 10 años seguidos sin dato hacia atrás: ahí empieza la serie
                if vacios_seguidos >= 20 and not e.get("completa"):
                    for a2, m2 in semestres:
                        if (a2, m2) < (a, m):
                            hechos.add(f"{a2}-{m2}")
                    break
        e["hechos"] = sorted(hechos)
        if all(f"{a}-{m}" in hechos for a, m in semestres) and not e["fallidos"]:
            e["completa"] = True
            e["refrescado"] = hoy.isoformat()
        if filas:
            escribir_csv(ide, filas)
            fechas = sorted(filas)
            e.update(primer_dia=fechas[0], ultimo_dia=fechas[-1], dias=len(fechas))
        estado["generado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"[{n:3}/{len(lista)}] {ide:7} {str(nombre)[:30]:30} +{nuevos:6} días · {e.get('primer_dia', '-')} → {e.get('ultimo_dia', '-')}"
            f" · {'completa' if e.get('completa') else 'en curso'} · fallidos {len(e['fallidos'])}")
    hechas = sum(1 for e in estado["estaciones"].values() if e.get("completa"))
    log(f"Fin: {peticiones} semestres pedidos · {hechas}/{len(lista)} estaciones completas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
