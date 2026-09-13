#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Caudal de los grandes ríos amazónicos — calentamientoglobal.es

Fuente: Open-Meteo Flood API (modelo GloFAS v4 del Copernicus Emergency
Management Service). Resolución 0,05° (~5 km), reanálisis desde 1984.

OJO, esto es lo importante del script: GloFAS es una REJILLA. La celda
contigua al cauce del Amazonas devuelve 0,09 m³/s en vez de 85.000. Las
coordenadas de abajo NO son las de la ciudad: son las del centro de la celda
del cauce principal, calibradas una a una el 13-sep-2026 buscando el máximo
de caudal en una ventana de ±0,12° alrededor de cada estación de referencia.
Si alguien las "corrige" poniendo las de la ciudad, el indicador se rompe en
silencio y marca cero.

Salida: docs/amazonia/caudales.json
Climatología (se recalcula si falta o si tiene más de 30 días):
        docs/amazonia/caudales_climatologia.json

Uso:
    python obtener_amazonia_caudales.py
    python obtener_amazonia_caudales.py --forzar-climatologia
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent.parent
SALIDA_DIR = RAIZ / "docs" / "amazonia"
SALIDA = SALIDA_DIR / "caudales.json"
CLIMATOLOGIA = SALIDA_DIR / "caudales_climatologia.json"

API_ACTUAL = "https://flood-api.open-meteo.com/v1/flood"
API_ARCHIVO = "https://flood-api.open-meteo.com/v1/flood"

DIAS_PASADOS = 60          # serie reciente que se publica
DIAS_PREVISION = 7
ANIO_INICIO_CLIMA = 1984   # inicio del reanálisis GloFAS
VENTANA_DIAS = 7           # ±7 días alrededor del día del año, para la comparación
CADUCIDAD_CLIMA_DIAS = 30
TIEMPO_ESPERA = 60

# Coordenadas CALIBRADAS sobre el cauce (ver nota de arriba).
# 'caudal_calibracion' es el valor que devolvió la celda el día de la
# calibración: sirve de control de cordura, no se publica.
ESTACIONES = [
    {
        "id": "obidos",
        "nombre": "Óbidos",
        "rio": "Amazonas",
        "pais": "Brasil",
        "lat": -1.975, "lon": -55.475,
        "lat_ciudad": -1.918, "lon_ciudad": -55.518,
        "caudal_calibracion": 85112.77,
        "nota": "La estación de referencia mundial del Amazonas: recoge el 80 % de la cuenca.",
    },
    {
        "id": "manaus_negro",
        "nombre": "Manaos",
        "rio": "Río Negro",
        "pais": "Brasil",
        "lat": -3.125, "lon": -60.175,
        "lat_ciudad": -3.13, "lon_ciudad": -60.02,
        "caudal_calibracion": 15884.48,
        "nota": "Aguas arriba del encuentro con el Solimões, para no medir el río equivocado.",
    },
    {
        "id": "manacapuru_solimoes",
        "nombre": "Manacapuru",
        "rio": "Solimões",
        "pais": "Brasil",
        "lat": -3.375, "lon": -60.725,
        "lat_ciudad": -3.30, "lon_ciudad": -60.62,
        "caudal_calibracion": 50465.14,
        "nota": "El Amazonas antes de recibir al Negro.",
    },
    {
        "id": "porto_velho_madeira",
        "nombre": "Porto Velho",
        "rio": "Madeira",
        "pais": "Brasil",
        "lat": -8.775, "lon": -63.975,
        "lat_ciudad": -8.76, "lon_ciudad": -63.90,
        "caudal_calibracion": 6250.73,
        "nota": "El mayor afluente del Amazonas y la vía de la soja.",
    },
    {
        "id": "itaituba_tapajos",
        "nombre": "Itaituba",
        "rio": "Tapajós",
        "pais": "Brasil",
        "lat": -4.275, "lon": -56.025,
        "lat_ciudad": -4.28, "lon_ciudad": -55.98,
        "caudal_calibracion": 2690.54,
        "nota": "Cuenca de aguas claras, muy sensible a la sequía.",
    },
    {
        "id": "altamira_xingu",
        "nombre": "Altamira",
        "rio": "Xingú",
        "pais": "Brasil",
        "lat": -3.275, "lon": -52.225,
        "lat_ciudad": -3.20, "lon_ciudad": -52.21,
        "caudal_calibracion": 532.33,
        "nota": "Aguas abajo queda Belo Monte; el estiaje aquí es extremo.",
    },
    {
        "id": "iquitos_amazonas",
        "nombre": "Iquitos",
        "rio": "Amazonas",
        "pais": "Perú",
        "lat": -3.675, "lon": -73.275,
        "lat_ciudad": -3.75, "lon_ciudad": -73.25,
        "caudal_calibracion": 17946.34,
        "nota": "El Amazonas peruano, 3.000 km aguas arriba de Óbidos.",
    },
    {
        "id": "rurrenabaque_beni",
        "nombre": "Rurrenabaque",
        "rio": "Beni",
        "pais": "Bolivia",
        "lat": -14.375, "lon": -67.575,
        "lat_ciudad": -14.44, "lon_ciudad": -67.53,
        "caudal_calibracion": 1594.88,
        "nota": "Amazonía boliviana, salida de los Andes.",
    },
    {
        "id": "leguizamo_putumayo",
        "nombre": "Puerto Leguízamo",
        "rio": "Putumayo",
        "pais": "Colombia",
        "lat": -0.075, "lon": -74.675,
        "lat_ciudad": -0.19, "lon_ciudad": -74.78,
        "caudal_calibracion": 1123.61,
        "nota": "Frontera Colombia-Perú, Amazonía noroccidental.",
    },
]

FUENTE = {
    "nombre": "Open-Meteo Flood API · modelo GloFAS v4 (Copernicus EMS / ECMWF)",
    "url": "https://open-meteo.com/en/docs/flood-api",
    "licencia": "Datos Copernicus (CC BY 4.0) servidos por Open-Meteo; uso no comercial gratuito",
    "atribucion_obligatoria": "Copernicus Emergency Management Service · GloFAS v4, vía Open-Meteo",
}

ADVERTENCIA = (
    "Caudal MODELIZADO, no medido: GloFAS simula el caudal sobre una rejilla de "
    "5 km a partir de lluvia y suelo, y puede desviarse de los aforos oficiales. "
    "Sirve para comparar cada río consigo mismo a lo largo del tiempo, no para "
    "dar el caudal exacto de un día."
)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[caudales-amazonia] {msg}", flush=True)


def pedir(url: str, params: dict, intentos: int = 4) -> dict | list:
    espera = 5
    ultimo = None
    for n in range(1, intentos + 1):
        try:
            r = requests.get(url, params=params, timeout=TIEMPO_ESPERA)
            if r.status_code == 429:
                raise RuntimeError("429 límite de peticiones")
            r.raise_for_status()
            datos = r.json()
            if isinstance(datos, dict) and datos.get("error"):
                raise RuntimeError(datos.get("reason", "error de la API"))
            return datos
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            log(f"  intento {n}/{intentos} fallido: {exc}")
            if n < intentos:
                time.sleep(espera)
                espera *= 2
    raise RuntimeError(f"sin respuesta tras {intentos} intentos: {ultimo}")


def clave_dia(f: date) -> str:
    return f"{f.month:02d}-{f.day:02d}"


def claves_ventana(f: date, ventana: int = VENTANA_DIAS) -> list[str]:
    return [clave_dia(f + timedelta(days=d)) for d in range(-ventana, ventana + 1)]


def percentil_de(valor: float, muestra: list[float]) -> float:
    if not muestra:
        return float("nan")
    menores = sum(1 for v in muestra if v < valor)
    iguales = sum(1 for v in muestra if v == valor)
    return round(100.0 * (menores + 0.5 * iguales) / len(muestra), 1)


def etiqueta_estado(p: float) -> tuple[str, str]:
    if p != p:  # NaN
        return "sin_referencia", "Sin serie histórica suficiente"
    if p < 5:
        return "extremadamente_bajo", "Extremadamente bajo para la fecha"
    if p < 20:
        return "bajo", "Por debajo de lo normal"
    if p <= 80:
        return "normal", "Dentro de lo normal"
    if p <= 95:
        return "alto", "Por encima de lo normal"
    return "extremadamente_alto", "Extremadamente alto para la fecha"


# --------------------------------------------------------------------------
# Climatología (1984 → hace dos años), una petición por estación
# --------------------------------------------------------------------------

def climatologia_caducada(ruta: Path) -> bool:
    if not ruta.exists():
        return True
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        generada = datetime.fromisoformat(datos["generada"].replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return True
    return (datetime.now(timezone.utc) - generada).days > CADUCIDAD_CLIMA_DIAS


def construir_climatologia() -> dict:
    """Descarga la serie larga de cada estación y resume por día del año."""
    fin = date.today() - timedelta(days=365)  # el reanálisis va con retraso
    inicio = date(ANIO_INICIO_CLIMA, 1, 1)
    salida = {
        "generada": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "periodo": {"inicio": inicio.isoformat(), "fin": fin.isoformat()},
        "metodo": (
            "Para cada estación y cada día del año se agrupan todos los valores "
            f"del reanálisis GloFAS en una ventana de ±{VENTANA_DIAS} días alrededor "
            "de esa fecha, en todos los años disponibles."
        ),
        "estaciones": {},
    }

    for est in ESTACIONES:
        log(f"climatología · {est['nombre']} ({est['rio']})")
        datos = pedir(
            API_ARCHIVO,
            {
                "latitude": est["lat"],
                "longitude": est["lon"],
                "daily": "river_discharge",
                "start_date": inicio.isoformat(),
                "end_date": fin.isoformat(),
            },
        )
        if isinstance(datos, list):
            datos = datos[0]
        tiempos = datos["daily"]["time"]
        valores = datos["daily"]["river_discharge"]

        por_dia: dict[str, list[float]] = {}
        for t, v in zip(tiempos, valores):
            if v is None:
                continue
            f = date.fromisoformat(t)
            por_dia.setdefault(clave_dia(f), []).append(float(v))

        resumen = {}
        for k, vals in por_dia.items():
            vals_ord = sorted(vals)
            resumen[k] = {
                "n": len(vals_ord),
                "media": round(statistics.fmean(vals_ord), 2),
                "mediana": round(statistics.median(vals_ord), 2),
                "min": round(vals_ord[0], 2),
                "max": round(vals_ord[-1], 2),
            }
        salida["estaciones"][est["id"]] = {
            "lat": est["lat"],
            "lon": est["lon"],
            "por_dia": resumen,
            "valores_por_dia": {k: [round(v, 2) for v in sorted(vs)] for k, vs in por_dia.items()},
        }
        time.sleep(3)

    return salida


def cargar_climatologia(forzar: bool = False) -> dict | None:
    if forzar or climatologia_caducada(CLIMATOLOGIA):
        log("recalculando la climatología (falta o está caducada)…")
        try:
            datos = construir_climatologia()
        except Exception as exc:  # noqa: BLE001
            log(f"AVISO: no se pudo construir la climatología: {exc}")
            if CLIMATOLOGIA.exists():
                log("  se sigue con la climatología antigua")
                return json.loads(CLIMATOLOGIA.read_text(encoding="utf-8"))
            return None
        SALIDA_DIR.mkdir(parents=True, exist_ok=True)
        CLIMATOLOGIA.write_text(
            json.dumps(datos, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        log(f"climatología escrita en {CLIMATOLOGIA}")
        return datos
    return json.loads(CLIMATOLOGIA.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Datos del día
# --------------------------------------------------------------------------

def datos_actuales() -> list[dict]:
    """Una sola petición con las nueve coordenadas."""
    datos = pedir(
        API_ACTUAL,
        {
            "latitude": ",".join(str(e["lat"]) for e in ESTACIONES),
            "longitude": ",".join(str(e["lon"]) for e in ESTACIONES),
            "daily": "river_discharge",
            "past_days": DIAS_PASADOS,
            "forecast_days": DIAS_PREVISION,
        },
    )
    return datos if isinstance(datos, list) else [datos]


def construir() -> dict:
    hoy = date.today()
    clima = cargar_climatologia()
    respuestas = datos_actuales()
    if len(respuestas) != len(ESTACIONES):
        raise RuntimeError(
            f"la API devolvió {len(respuestas)} puntos y se esperaban {len(ESTACIONES)}"
        )

    estaciones = []
    fallos = []

    for est, resp in zip(ESTACIONES, respuestas):
        try:
            tiempos = resp["daily"]["time"]
            valores = resp["daily"]["river_discharge"]
            serie = [
                {"fecha": t, "caudal": (round(v, 1) if v is not None else None)}
                for t, v in zip(tiempos, valores)
            ]

            observados = [(t, v) for t, v in zip(tiempos, valores)
                          if v is not None and date.fromisoformat(t) <= hoy]
            if not observados:
                raise RuntimeError("sin valores para hoy ni días previos")
            fecha_dato, caudal_hoy = observados[-1]
            caudal_hoy = float(caudal_hoy)

            # control de cordura contra la calibración: un salto de tres órdenes
            # de magnitud significa que la celda ya no es la del cauce
            ref = est.get("caudal_calibracion")
            sospechoso = bool(ref and (caudal_hoy < ref / 100 or caudal_hoy > ref * 100))

            percentil = float("nan")
            media_fecha = None
            minimo_hist = None
            maximo_hist = None
            anios_serie = 0
            if clima and est["id"] in clima.get("estaciones", {}):
                bloque = clima["estaciones"][est["id"]]
                muestra: list[float] = []
                for k in claves_ventana(date.fromisoformat(fecha_dato)):
                    muestra.extend(bloque.get("valores_por_dia", {}).get(k, []))
                if muestra:
                    percentil = percentil_de(caudal_hoy, muestra)
                    media_fecha = round(statistics.fmean(muestra), 1)
                    minimo_hist = round(min(muestra), 1)
                    maximo_hist = round(max(muestra), 1)
                    anios_serie = round(len(muestra) / (2 * VENTANA_DIAS + 1))

            estado, estado_texto = etiqueta_estado(percentil)

            hace7 = [v for t, v in observados if
                     date.fromisoformat(t) <= hoy - timedelta(days=7)]
            variacion_7d = None
            if hace7:
                base = float(hace7[-1])
                if base > 0:
                    variacion_7d = round(100.0 * (caudal_hoy - base) / base, 1)

            estaciones.append({
                "id": est["id"],
                "nombre": est["nombre"],
                "rio": est["rio"],
                "pais": est["pais"],
                "nota": est["nota"],
                "lat": est["lat_ciudad"],
                "lon": est["lon_ciudad"],
                "celda": {"lat": est["lat"], "lon": est["lon"]},
                "fecha_dato": fecha_dato,
                "caudal": round(caudal_hoy, 1),
                "unidad": "m³/s",
                "media_para_la_fecha": media_fecha,
                "porcentaje_de_la_media": (
                    round(100.0 * caudal_hoy / media_fecha, 1) if media_fecha else None
                ),
                "percentil": None if percentil != percentil else percentil,
                "estado": estado,
                "estado_texto": estado_texto,
                "minimo_historico_fecha": minimo_hist,
                "maximo_historico_fecha": maximo_hist,
                "anios_comparados": anios_serie,
                "variacion_7d_pct": variacion_7d,
                "celda_sospechosa": sospechoso,
                "serie": serie,
            })
            if sospechoso:
                fallos.append({
                    "estacion": est["id"],
                    "motivo": (
                        f"caudal {caudal_hoy} m³/s frente a {ref} en la calibración: "
                        "revisar si la celda sigue sobre el cauce"
                    ),
                })
        except Exception as exc:  # noqa: BLE001
            log(f"ERROR en {est['id']}: {exc}")
            fallos.append({"estacion": est["id"], "motivo": str(exc)})

    if len(estaciones) < len(ESTACIONES) / 2:
        raise RuntimeError(
            f"solo {len(estaciones)} de {len(ESTACIONES)} estaciones válidas: "
            "no se escribe el fichero para no publicar un dato cojo"
        )

    destacada = next((e for e in estaciones if e["id"] == "obidos"), estaciones[0])

    return {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fecha_dato": destacada["fecha_dato"],
        "fuente": FUENTE,
        "advertencia": ADVERTENCIA,
        "metodo": (
            "Coordenadas fijadas sobre la celda del cauce principal (máximo de caudal "
            "en una ventana de ±0,12° alrededor de la estación de referencia). El "
            "percentil compara el valor del día con todos los valores del reanálisis "
            f"GloFAS desde {ANIO_INICIO_CLIMA} en una ventana de ±{VENTANA_DIAS} días "
            "alrededor de la misma fecha."
        ),
        "climatologia": (
            {"periodo": clima["periodo"], "generada": clima["generada"]} if clima else None
        ),
        "destacado": {
            "estacion": destacada["nombre"],
            "rio": destacada["rio"],
            "caudal": destacada["caudal"],
            "percentil": destacada["percentil"],
            "estado_texto": destacada["estado_texto"],
        },
        "estaciones": estaciones,
        "fallos": fallos,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar-climatologia", action="store_true",
                    help="recalcula la serie 1984→ aunque no esté caducada")
    args = ap.parse_args()

    if args.forzar_climatologia:
        cargar_climatologia(forzar=True)

    datos = construir()
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(
        json.dumps(datos, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    log(f"escrito {SALIDA} · {len(datos['estaciones'])} estaciones · "
        f"{len(datos['fallos'])} avisos")
    for e in datos["estaciones"]:
        log(f"  {e['rio']:<10} {e['nombre']:<16} {e['caudal']:>10,.0f} m³/s  "
            f"p{e['percentil']}  {e['estado_texto']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"FALLO: {exc}")
        sys.exit(1)
