import csv
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

COMUNIDADES = [
    {"id": "andalucia", "nombre": "Andalucía", "lat": 37.45, "lon": -4.50, "bbox_w": -7.52, "bbox_s": 35.95, "bbox_e": -1.62, "bbox_n": 38.73},
    {"id": "aragon", "nombre": "Aragón", "lat": 41.60, "lon": -0.90, "bbox_w": -2.25, "bbox_s": 39.95, "bbox_e": 0.78, "bbox_n": 42.98},
    {"id": "asturias", "nombre": "Asturias", "lat": 43.30, "lon": -6.00, "bbox_w": -7.10, "bbox_s": 42.92, "bbox_e": -4.52, "bbox_n": 43.67},
    {"id": "baleares", "nombre": "Islas Baleares", "lat": 39.50, "lon": 2.80, "bbox_w": 1.15, "bbox_s": 38.64, "bbox_e": 4.34, "bbox_n": 40.09},
    {"id": "canarias", "nombre": "Canarias", "lat": 28.20, "lon": -15.50, "bbox_w": -18.18, "bbox_s": 27.63, "bbox_e": -13.34, "bbox_n": 29.47},
    {"id": "cantabria", "nombre": "Cantabria", "lat": 43.18, "lon": -4.00, "bbox_w": -4.88, "bbox_s": 42.77, "bbox_e": -3.32, "bbox_n": 43.51},
    {"id": "castilla_mancha", "nombre": "Castilla-La Mancha", "lat": 39.50, "lon": -2.50, "bbox_w": -5.23, "bbox_s": 37.92, "bbox_e": -0.93, "bbox_n": 41.33},
    {"id": "castilla_leon", "nombre": "Castilla y León", "lat": 41.60, "lon": -4.50, "bbox_w": -7.00, "bbox_s": 40.14, "bbox_e": -2.00, "bbox_n": 43.22},
    {"id": "cataluna", "nombre": "Cataluña", "lat": 41.70, "lon": 1.60, "bbox_w": 0.15, "bbox_s": 40.51, "bbox_e": 3.33, "bbox_n": 42.86},
    {"id": "c_valenciana", "nombre": "Comunidad Valenciana", "lat": 39.20, "lon": -0.75, "bbox_w": -1.52, "bbox_s": 37.84, "bbox_e": 0.53, "bbox_n": 40.79},
    {"id": "extremadura", "nombre": "Extremadura", "lat": 39.20, "lon": -6.20, "bbox_w": -7.55, "bbox_s": 37.93, "bbox_e": -4.63, "bbox_n": 40.49},
    {"id": "galicia", "nombre": "Galicia", "lat": 42.80, "lon": -8.00, "bbox_w": -9.32, "bbox_s": 41.80, "bbox_e": -6.74, "bbox_n": 43.78},
    {"id": "la_rioja", "nombre": "La Rioja", "lat": 42.30, "lon": -2.40, "bbox_w": -3.12, "bbox_s": 41.91, "bbox_e": -1.67, "bbox_n": 42.63},
    {"id": "madrid", "nombre": "Comunidad de Madrid", "lat": 40.40, "lon": -3.70, "bbox_w": -4.59, "bbox_s": 39.88, "bbox_e": -3.05, "bbox_n": 41.17},
    {"id": "murcia", "nombre": "Región de Murcia", "lat": 37.90, "lon": -1.50, "bbox_w": -2.35, "bbox_s": 37.37, "bbox_e": -0.64, "bbox_n": 38.73},
    {"id": "navarra", "nombre": "Navarra", "lat": 42.70, "lon": -1.70, "bbox_w": -2.48, "bbox_s": 41.91, "bbox_e": -0.48, "bbox_n": 43.32},
    {"id": "pais_vasco", "nombre": "País Vasco", "lat": 43.00, "lon": -2.50, "bbox_w": -3.50, "bbox_s": 42.57, "bbox_e": -1.72, "bbox_n": 43.46},
    {"id": "ceuta", "nombre": "Ceuta", "lat": 35.89, "lon": -5.31, "bbox_w": -5.40, "bbox_s": 35.84, "bbox_e": -5.27, "bbox_n": 35.93},
    {"id": "melilla", "nombre": "Melilla", "lat": 35.29, "lon": -2.94, "bbox_w": -2.98, "bbox_s": 35.26, "bbox_e": -2.90, "bbox_n": 35.35},
]

SENSORES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
AREA_ESPANA = "-18.5,27.5,4.5,44.0"
HORAS_ACTIVO = 48
TZ_ESPANA = ZoneInfo("Europe/Madrid")


def ahora_utc():
    return datetime.now(timezone.utc)


def ahora_espana():
    return datetime.now(TZ_ESPANA)


def asignar_comunidad(lat, lon):
    for c in COMUNIDADES:
        if c["bbox_w"] <= lon <= c["bbox_e"] and c["bbox_s"] <= lat <= c["bbox_n"]:
            return c["id"]
    return None


def parsear_deteccion_utc(fecha, hora):
    if not fecha:
        return None
    hora = str(hora or "").strip().zfill(4)
    try:
        return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def obtener_focos_sensor(api_key, sensor, dias=2):
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{sensor}/{AREA_ESPANA}/{dias}"
    focos = []

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        texto = r.text.strip()
        if not texto or "exceeded" in texto.lower() or "invalid map key" in texto.lower():
            print(f"  {sensor}: sin datos, límite API o clave inválida")
            return focos

        reader = csv.DictReader(io.StringIO(texto))
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                conf = str(row.get("confidence", "n")).strip().lower()
                frp = float(row.get("frp", 0) or 0)
                fecha = row.get("acq_date", "")
                hora = row.get("acq_time", "")
                deteccion_utc = parsear_deteccion_utc(fecha, hora)

                if conf not in ["n", "h", "nominal", "high"]:
                    continue

                comunidad = asignar_comunidad(lat, lon)
                if not comunidad:
                    continue

                focos.append({
                    "lat": lat,
                    "lon": lon,
                    "frp": round(frp, 1),
                    "fecha": fecha,
                    "acq_time": str(hora).zfill(4),
