#!/usr/bin/env python3
"""Días de niebla al año en las capitales (AEMET, valores climatológicos mensuales).

Baja de AEMET OpenData (mensualesanuales) los campos de niebla y visibilidad de la estación de cada capital
(las mismas de scripts/balance_mensual.py) y calcula, por capital, los días de niebla de cada año, la media de
1971-1990, la de 2006-2025 y el reparto por meses. Proceso manual (workflow niebla-clima.yml), reanudable:

  archivo/niebla/clima_crudo.json   lo bajado, mes a mes (se reutiliza: solo pide los trienios que faltan)
  docs/niebla/clima.json            el resumen que usa la página /niebla/

  n_fog    días de niebla del mes (observación)
  nv_1000  días con visibilidad inferior a 1 km      nv_0100: inferior a 100 m      nv_0050: inferior a 50 m

Uso:  python scripts/niebla_clima.py            baja lo que falte y resume
      python scripts/niebla_clima.py --resumen  solo recalcula el resumen con lo ya bajado
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import niebla as N  # noqa: E402  (_aemet_get, log, RAIZ)
from balance_mensual import ESTACIONES  # noqa: E402  cod provincia -> (indicativo, ciudad, estación, tipo)

CRUDO = N.RAIZ / "archivo" / "niebla" / "clima_crudo.json"
SALIDA = N.RAIZ / "docs" / "niebla" / "clima.json"
URL = ("https://opendata.aemet.es/opendata/api/valores/climatologicos/mensualesanuales/datos/"
       "anioini/{a}/aniofin/{b}/estacion/{ide}")
CAMPOS = ("n_fog", "nv_1000", "nv_0100", "nv_0050")
INICIO = 1971
ANTES, AHORA_P = (1971, 1990), (2006, 2025)
NORMAL = (1991, 2020)
MIN_ANIOS = 15                  # años completos que exige cada periodo de 20
PAUSA = 0.7                     # segundos entre llamadas
_VISTO: list = []
LIMITE_S = int(os.environ.get("CLIMA_LIMITE_S", "6600"))   # se para solo y se reanuda en la siguiente ejecución


def _num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def pedir(ide: str, a: int, b: int, clave: str):
    """Lista de meses del trienio, [] si AEMET no tiene datos, None si falla (se reintenta otro día)."""
    for i in range(6):
        try:
            r = N._aemet_get(URL.format(a=a, b=b, ide=ide), clave)
            if isinstance(r, dict) and int(r.get("estado") or 0) == 404:
                return []
            if not isinstance(r, dict) or not r.get("datos"):
                raise RuntimeError(f"respuesta sin datos: {str(r)[:100]}")
            time.sleep(PAUSA)
            d = N._aemet_get(r["datos"])
            return d if isinstance(d, list) else []
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            N.log(f"    {ide} {a}-{b}: HTTP {e.code} (intento {i + 1})")
            time.sleep(65 if e.code == 429 else 3 + 2 * i)
        except Exception as e:           # noqa: BLE001
            N.log(f"    {ide} {a}-{b}: {type(e).__name__}: {str(e)[:160]} (intento {i + 1})")
            time.sleep(3 + 2 * i)
    return None


def bajar() -> dict:
    clave = (os.environ.get("AEMET_API_KEY") or "").strip()
    if not clave:
        raise SystemExit("falta el secreto AEMET_API_KEY")
    crudo = N.leer_json(CRUDO) or {"estaciones": {}}
    t0, ultimo = time.time(), datetime.now(timezone.utc).year
    for cod, (ide, ciudad, _est, _tipo) in sorted(ESTACIONES.items()):
        e = crudo["estaciones"].setdefault(ide, {"hechos": [], "meses": {}})
        nuevos = 0
        for a in range(INICIO, ultimo + 1, 3):
            b = min(a + 2, ultimo)
            clave_t = f"{a}-{b}"
            if clave_t in e["hechos"] and b < ultimo - 1:
                continue
            if time.time() - t0 > LIMITE_S:
                N.log("Límite de tiempo: se guarda y se reanuda en la siguiente ejecución")
                _guardar(crudo)
                return crudo
            filas = pedir(ide, a, b, clave)
            if not _VISTO and filas:
                _VISTO.append(1)
                N.log(f"  primera respuesta ({ide} {clave_t}): {len(filas)} filas; campos de niebla en la primera: "
                      f"{ {c: filas[0].get(c) for c in CAMPOS} }; fecha {filas[0].get('fecha')}")
            time.sleep(PAUSA)
            if filas is None:
                N.log(f"  {ciudad} {clave_t}: fallo, queda pendiente")
                continue
            for f in filas:
                fecha = str(f.get("fecha") or "")
                vals = {c: _num(f.get(c)) for c in CAMPOS if _num(f.get(c)) is not None}
                if fecha and vals:
                    e["meses"][fecha] = vals
            if clave_t not in e["hechos"]:
                e["hechos"].append(clave_t)
            nuevos += 1
        if nuevos:
            N.log(f"{ciudad} ({ide}): {nuevos} trienios nuevos, {len(e['meses'])} meses con dato")
            _guardar(crudo)
    crudo["completo"] = True
    _guardar(crudo)
    return crudo


def _guardar(crudo: dict) -> None:
    CRUDO.parent.mkdir(parents=True, exist_ok=True)
    crudo["descargado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    CRUDO.write_text(json.dumps(crudo, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def anual(meses: dict, campo: str) -> dict:
    """Total de cada año con los 12 meses; si falta alguno, el valor anual de AEMET (mes 13) si existe."""
    out, anios = {}, sorted({k.split("-")[0] for k in meses})
    for y in anios:
        ms = [meses.get(f"{y}-{m}", {}).get(campo) for m in range(1, 13)]
        if all(v is not None for v in ms):
            out[int(y)] = round(sum(ms), 1)
        elif meses.get(f"{y}-13", {}).get(campo) is not None and sum(v is not None for v in ms) >= 11:
            out[int(y)] = meses[f"{y}-13"][campo]
    return out


def _media(an: dict, per: tuple):
    v = [an[y] for y in range(per[0], per[1] + 1) if y in an]
    return (round(sum(v) / len(v), 1), len(v)) if v else (None, 0)


def resumir(crudo: dict) -> dict:
    caps = []
    for cod, (ide, ciudad, est, _tipo) in sorted(ESTACIONES.items()):
        meses = (crudo.get("estaciones", {}).get(ide) or {}).get("meses") or {}
        fila = {"cod": cod, "ciudad": ciudad, "estacion": est, "indicativo": ide}
        for campo in ("n_fog", "nv_1000"):
            an = anual(meses, campo)
            m1, n1 = _media(an, ANTES)
            m2, n2 = _media(an, AHORA_P)
            m3, n3 = _media(an, NORMAL)
            por_mes = []
            for m in range(1, 13):
                v = [meses[f"{y}-{m}"][campo] for y in range(NORMAL[0], NORMAL[1] + 1)
                     if meses.get(f"{y}-{m}", {}).get(campo) is not None]
                por_mes.append(round(sum(v) / len(v), 1) if len(v) >= MIN_ANIOS else None)
            fila[campo] = {"anual": {str(y): v for y, v in sorted(an.items())},
                           "antes": m1 if n1 >= MIN_ANIOS else None, "antes_n": n1,
                           "ahora": m2 if n2 >= MIN_ANIOS else None, "ahora_n": n2,
                           "normal": m3 if n3 >= MIN_ANIOS else None, "normal_n": n3,
                           "por_mes": por_mes,
                           "ultimo_anio": max(an) if an else None}
        caps.append(fila)
    return {"generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "fuente": "AEMET OpenData, valores climatológicos mensuales de cada estación",
            "periodos": {"antes": list(ANTES), "ahora": list(AHORA_P), "normal": list(NORMAL), "min_anios": MIN_ANIOS},
            "completo": bool(crudo.get("completo")), "capitales": caps}


def main() -> int:
    crudo = (N.leer_json(CRUDO) or {"estaciones": {}}) if "--resumen" in sys.argv else bajar()
    res = resumir(crudo)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    con = sum(1 for c in res["capitales"] if c["n_fog"]["normal"] is not None)
    ambos = sum(1 for c in res["capitales"] if c["n_fog"]["antes"] is not None and c["n_fog"]["ahora"] is not None)
    N.log(f"clima.json: {len(res['capitales'])} capitales, {con} con normal 1991-2020 de días de niebla, "
          f"{ambos} con los dos periodos; completo={res['completo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
