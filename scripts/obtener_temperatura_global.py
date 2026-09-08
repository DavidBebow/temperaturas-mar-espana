#!/usr/bin/env python3
"""
Temperatura global diaria · calentamientoglobal.es

Descarga la serie diaria de temperatura media global del aire en superficie
(ERA5, Copernicus Climate Change Service / ECMWF, publicada en Climate Pulse)
y genera docs/temperatura_global.json con el dato del último día disponible,
la media móvil de 365 días, la media del año en curso y su posición en el
ranking histórico.

El fichero de origen empieza con 18 líneas de cabecera que comienzan por «#»
(descripción, fuente, licencia). Hay que saltarlas antes de leer el CSV: si no,
csv.DictReader toma la primera línea de comentario como cabecera y no reconoce
ni una sola fila.

Columnas reales, en la primera línea que no empieza por «#»:
    date, 2t, clim_91-20, ano_91-20, status
    - 2t          temperatura media global absoluta del día, en °C
    - clim_91-20  climatología del mismo día del año en el periodo 1991-2020
    - ano_91-20   anomalía respecto a esa climatología
    - status      FINAL o PRELIMINARY

Si la descarga falla, reutiliza el JSON anterior y marca fuente_ok = false,
igual que hace obtener_reloj_climatico.py.

Uso:  python3 scripts/obtener_temperatura_global.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

URL_CSV = "https://sites.ecmwf.int/data/climatepulse/data/series/era5_daily_series_2t_global.csv"
SALIDA = Path(__file__).resolve().parent.parent / "docs" / "temperatura_global.json"

# Desfase entre el periodo de referencia moderno (1991-2020) y el preindustrial
# (1850-1900) para la temperatura global del aire en superficie, según C3S.
# Es la misma constante que Copernicus aplica en sus boletines mensuales.
# Si C3S la revisa, se cambia aquí y la página entera queda corregida.
OFFSET_PREINDUSTRIAL = 0.88

UMBRAL_PARIS = 1.5

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_es(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def coma(valor: float, dec: int) -> str:
    return f"{valor:.{dec}f}".replace(".", ",")


def descargar() -> list[dict]:
    req = urllib.request.Request(
        URL_CSV,
        headers={"User-Agent": "calentamientoglobal.es/1.0 (+https://calentamientoglobal.es)"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        crudo = r.read().decode("utf-8", errors="replace")

    # Saltar la cabecera de comentarios («#») antes de leer el CSV.
    utiles = [l for l in crudo.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not utiles:
        raise RuntimeError("el fichero descargado no tiene ninguna línea de datos")

    lector = csv.DictReader(io.StringIO("\n".join(utiles)))
    faltan = {"date", "2t", "ano_91-20"} - set(lector.fieldnames or [])
    if faltan:
        raise RuntimeError(
            f"la cabecera del CSV ha cambiado: faltan {sorted(faltan)}; "
            f"se leyó {lector.fieldnames}"
        )

    filas = []
    for f in lector:
        try:
            filas.append({
                "fecha": datetime.strptime(f["date"].strip(), "%Y-%m-%d").date(),
                "t": float(f["2t"]),
                "ano": float(f["ano_91-20"]),
                "estado": (f.get("status") or "").strip().upper() or "FINAL",
            })
        except (ValueError, KeyError, TypeError):
            continue  # cabeceras repetidas, filas incompletas o el último día a medias

    if len(filas) < 400:
        raise RuntimeError(f"la serie descargada solo trae {len(filas)} filas; se aborta")

    filas.sort(key=lambda x: x["fecha"])
    return filas


def construir(filas: list[dict]) -> dict:
    ultimo = filas[-1]
    ventana = filas[-365:]

    media_365 = sum(f["ano"] for f in ventana) / len(ventana)
    dias_sobre_15 = sum(1 for f in ventana if f["ano"] + OFFSET_PREINDUSTRIAL >= UMBRAL_PARIS)

    # Año en curso hasta la fecha, y el mismo tramo de calendario en años anteriores,
    # para que la comparación sea de manzanas con manzanas.
    anyo = ultimo["fecha"].year
    corte = ultimo["fecha"].timetuple().tm_yday

    def media_hasta_corte(a: int) -> float | None:
        vals = [f["ano"] for f in filas
                if f["fecha"].year == a and f["fecha"].timetuple().tm_yday <= corte]
        return sum(vals) / len(vals) if len(vals) >= corte * 0.9 else None

    medias = {a: m for a in range(1940, anyo + 1) if (m := media_hasta_corte(a)) is not None}
    media_anyo = medias.get(anyo)
    puesto = None
    if media_anyo is not None:
        puesto = sorted(medias.values(), reverse=True).index(media_anyo) + 1

    record = max(filas, key=lambda f: f["ano"])

    anom_pre = ultimo["ano"] + OFFSET_PREINDUSTRIAL
    frase = (
        f"El {fecha_es(ultimo['fecha'])} la temperatura media del planeta fue de "
        f"{coma(ultimo['t'], 2)} °C, {coma(anom_pre, 2)} °C por encima de la era "
        f"preindustrial (ERA5, Copernicus)."
    )

    return {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente_ok": True,
        "fuente": "ERA5 · Copernicus Climate Change Service (C3S/ECMWF) vía Climate Pulse",
        "offset_preindustrial": OFFSET_PREINDUSTRIAL,
        "fecha_dato": ultimo["fecha"].isoformat(),
        "estado": ultimo["estado"],
        "t_absoluta": round(ultimo["t"], 2),
        "anomalia_9120": round(ultimo["ano"], 2),
        "anomalia_preindustrial": round(anom_pre, 2),
        "media_365_9120": round(media_365, 2),
        "media_365_preindustrial": round(media_365 + OFFSET_PREINDUSTRIAL, 2),
        "anyo_en_curso": {
            "anyo": anyo,
            "dias": corte,
            "media_9120": round(media_anyo, 2) if media_anyo is not None else None,
            "media_preindustrial": round(media_anyo + OFFSET_PREINDUSTRIAL, 2) if media_anyo is not None else None,
            "puesto": puesto,
        },
        "dias_sobre_15_ultimo_anyo": dias_sobre_15,
        "record_diario": {
            "fecha": record["fecha"].isoformat(),
            "t_absoluta": round(record["t"], 2),
            "anomalia_preindustrial": round(record["ano"] + OFFSET_PREINDUSTRIAL, 2),
        },
        "frase_citable": frase,
    }


def main() -> int:
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    try:
        datos = construir(descargar())
    except Exception as e:  # red caída, formato cambiado, serie truncada
        print(f"[temperatura_global] fallo al actualizar: {e}", file=sys.stderr)
        if SALIDA.exists():
            previo = json.loads(SALIDA.read_text(encoding="utf-8"))
            previo["fuente_ok"] = False
            previo["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            SALIDA.write_text(json.dumps(previo, ensure_ascii=False, indent=2), encoding="utf-8")
            print("[temperatura_global] se conserva la lectura anterior", file=sys.stderr)
            return 0
        return 1

    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(datos["frase_citable"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
