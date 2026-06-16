#!/usr/bin/env python3
"""
Grados-día de calefacción (HDD) y refrigeración (CDD) para las capitales de
provincia de España, calculados con el reanálisis ERA5 de Open-Meteo (sin API
key) y guardados en docs/grados-dia.json.

  HDD base 18 °C   ->  suma anual de max(0, 18 - T_media)
  CDD bases 21/24  ->  suma anual de max(0, T_media - base)

Uso:  python scripts/obtener_grados_dia.py
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

START_YEAR = 1960
HDD_BASE = 18
CDD_BASES = [21, 24]
MIN_DIAS = 350  # descarta años con huecos grandes (ERA5 no debería tenerlos)
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# El JSON se escribe en docs/ (raíz de GitHub Pages), junto al HTML del gráfico.
OUT = Path(__file__).resolve().parent.parent / "docs" / "grados-dia.json"

# (nombre que se muestra en el selector, latitud, longitud) — capital de provincia
PROVINCIAS = [
    ("A Coruña", 43.37, -8.40), ("Álava", 42.85, -2.67), ("Albacete", 38.99, -1.86),
    ("Alicante", 38.35, -0.48), ("Almería", 36.84, -2.46), ("Asturias", 43.36, -5.85),
    ("Ávila", 40.66, -4.70), ("Badajoz", 38.88, -6.97), ("Barcelona", 41.39, 2.17),
    ("Bizkaia", 43.26, -2.93), ("Burgos", 42.34, -3.70), ("Cáceres", 39.47, -6.37),
    ("Cádiz", 36.53, -6.29), ("Cantabria", 43.46, -3.81), ("Castellón", 39.99, -0.04),
    ("Ciudad Real", 38.99, -3.93), ("Córdoba", 37.89, -4.78), ("Cuenca", 40.07, -2.13),
    ("Gipuzkoa", 43.32, -1.98), ("Girona", 41.98, 2.82), ("Granada", 37.18, -3.60),
    ("Guadalajara", 40.63, -3.16), ("Huelva", 37.26, -6.95), ("Huesca", 42.13, -0.41),
    ("Illes Balears", 39.57, 2.65), ("Jaén", 37.77, -3.79), ("La Rioja", 42.47, -2.45),
    ("Las Palmas", 28.12, -15.43), ("León", 42.60, -5.57), ("Lleida", 41.62, 0.62),
    ("Lugo", 43.01, -7.56), ("Madrid", 40.42, -3.70), ("Málaga", 36.72, -4.42),
    ("Murcia", 37.99, -1.13), ("Navarra", 42.81, -1.65), ("Ourense", 42.34, -7.86),
    ("Palencia", 42.01, -4.53), ("Pontevedra", 42.43, -8.64), ("Salamanca", 40.97, -5.66),
    ("S. C. de Tenerife", 28.47, -16.25), ("Segovia", 40.95, -4.12), ("Sevilla", 37.39, -5.99),
    ("Soria", 41.76, -2.46), ("Tarragona", 41.12, 1.25), ("Teruel", 40.34, -1.11),
    ("Toledo", 39.86, -4.02), ("Valencia", 39.47, -0.38), ("Valladolid", 41.65, -4.72),
    ("Zamora", 41.50, -5.74), ("Zaragoza", 41.65, -0.89), ("Ceuta", 35.89, -5.31),
    ("Melilla", 35.29, -2.94),
]


def fetch_diario(lat, lon, end):
    """Descarga la temperatura media diaria 1960..end con reintentos."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{START_YEAR}-01-01",
        "end_date": end,
        "daily": "temperature_2m_mean",
        "timezone": "Europe/Madrid",
    }
    for intento in range(4):
        try:
            r = requests.get(ARCHIVE, params=params, timeout=90)
            r.raise_for_status()
            return r.json()["daily"]
        except Exception as e:  # noqa: BLE001
            print(f"   reintento {intento + 1}/4: {e}")
            time.sleep(5 * (intento + 1))
    raise RuntimeError(f"No se pudo descargar {lat},{lon}")


def grados_dia(daily):
    """Devuelve (years, hdd, {base: cdd}) a partir de la serie diaria."""
    por_anio = {}
    for t, temp in zip(daily["time"], daily["temperature_2m_mean"]):
        if temp is None:
            continue
        y = int(t[:4])
        reg = por_anio.setdefault(
            y, {"hdd": 0.0, "cdd": {b: 0.0 for b in CDD_BASES}, "dias": 0}
        )
        reg["hdd"] += max(0.0, HDD_BASE - temp)
        for b in CDD_BASES:
            reg["cdd"][b] += max(0.0, temp - b)
        reg["dias"] += 1

    years, hdd = [], []
    cdd = {b: [] for b in CDD_BASES}
    for y in sorted(por_anio):
        if por_anio[y]["dias"] < MIN_DIAS:
            continue
        years.append(y)
        hdd.append(round(por_anio[y]["hdd"]))
        for b in CDD_BASES:
            cdd[b].append(round(por_anio[y]["cdd"][b]))
    return years, hdd, cdd


def main():
    end = f"{date.today().year - 1}-12-31"  # último año completo
    salida = {
        "generado": date.today().isoformat(),
        "base_hdd": HDD_BASE,
        "bases_cdd": CDD_BASES,
        "fin": end,
        "provincias": {},
    }

    for i, (nombre, lat, lon) in enumerate(PROVINCIAS, 1):
        print(f"[{i}/{len(PROVINCIAS)}] {nombre} …")
        daily = fetch_diario(lat, lon, end)
        years, hdd, cdd = grados_dia(daily)
        salida["provincias"][nombre] = {
            "lat": lat,
            "lon": lon,
            "years": years,
            "hdd": hdd,
            **{f"cdd{b}": cdd[b] for b in CDD_BASES},
        }
        time.sleep(1.2)  # cortesía con la API

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"\nGuardado {OUT} · {len(salida['provincias'])} provincias · hasta {end}")


if __name__ == "__main__":
    sys.exit(main())
