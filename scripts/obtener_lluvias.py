import requests
import json
import os
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# Open-Meteo: gratuito, sin API key, sin retraso.
# Documentación: https://open-meteo.com/en/docs
# ─────────────────────────────────────────────────────────────────────────────
PROVINCIAS = [
    {"id": "almeria",        "nombre": "Almería",        "ccaa": "Andalucía",           "lat": 37.23, "lon": -1.86,  "media_anual_mm": 220},
    {"id": "cadiz",          "nombre": "Cádiz",          "ccaa": "Andalucía",           "lat": 36.52, "lon": -6.30,  "media_anual_mm": 640},
    {"id": "cordoba",        "nombre": "Córdoba",        "ccaa": "Andalucía",           "lat": 37.88, "lon": -4.78,  "media_anual_mm": 580},
    {"id": "granada",        "nombre": "Granada",        "ccaa": "Andalucía",           "lat": 37.18, "lon": -3.60,  "media_anual_mm": 450},
    {"id": "huelva",         "nombre": "Huelva",         "ccaa": "Andalucía",           "lat": 37.25, "lon": -6.95,  "media_anual_mm": 560},
    {"id": "jaen",           "nombre": "Jaén",           "ccaa": "Andalucía",           "lat": 37.77, "lon": -3.79,  "media_anual_mm": 500},
    {"id": "malaga",         "nombre": "Málaga",         "ccaa": "Andalucía",           "lat": 36.72, "lon": -4.42,  "media_anual_mm": 530},
    {"id": "sevilla",        "nombre": "Sevilla",        "ccaa": "Andalucía",           "lat": 37.39, "lon": -5.99,  "media_anual_mm": 540},
    {"id": "huesca",         "nombre": "Huesca",         "ccaa": "Aragón",              "lat": 42.14, "lon": -0.41,  "media_anual_mm": 530},
    {"id": "teruel",         "nombre": "Teruel",         "ccaa": "Aragón",              "lat": 40.34, "lon": -1.11,  "media_anual_mm": 420},
    {"id": "zaragoza",       "nombre": "Zaragoza",       "ccaa": "Aragón",              "lat": 41.65, "lon": -0.89,  "media_anual_mm": 315},
    {"id": "asturias",       "nombre": "Asturias",       "ccaa": "Asturias",            "lat": 43.36, "lon": -5.85,  "media_anual_mm": 1050},
    {"id": "baleares",       "nombre": "Illes Balears",  "ccaa": "Illes Balears",       "lat": 39.57, "lon":  2.65,  "media_anual_mm": 450},
    {"id": "canarias_las_p", "nombre": "Las Palmas",     "ccaa": "Canarias",            "lat": 28.10, "lon": -15.41, "media_anual_mm": 200},
    {"id": "canarias_sc_tf", "nombre": "S.C. Tenerife",  "ccaa": "Canarias",            "lat": 28.46, "lon": -16.25, "media_anual_mm": 300},
    {"id": "cantabria",      "nombre": "Cantabria",      "ccaa": "Cantabria",           "lat": 43.18, "lon": -3.99,  "media_anual_mm": 1200},
    {"id": "albacete",       "nombre": "Albacete",       "ccaa": "Castilla-La Mancha",  "lat": 39.00, "lon": -1.86,  "media_anual_mm": 380},
    {"id": "ciudad_real",    "nombre": "Ciudad Real",    "ccaa": "Castilla-La Mancha",  "lat": 38.99, "lon": -3.93,  "media_anual_mm": 390},
    {"id": "cuenca",         "nombre": "Cuenca",         "ccaa": "Castilla-La Mancha",  "lat": 40.07, "lon": -2.14,  "media_anual_mm": 480},
    {"id": "guadalajara",    "nombre": "Guadalajara",    "ccaa": "Castilla-La Mancha",  "lat": 40.63, "lon": -3.17,  "media_anual_mm": 450},
    {"id": "toledo",         "nombre": "Toledo",         "ccaa": "Castilla-La Mancha",  "lat": 39.86, "lon": -4.02,  "media_anual_mm": 380},
    {"id": "avila",          "nombre": "Ávila",          "ccaa": "Castilla y León",     "lat": 40.66, "lon": -4.69,  "media_anual_mm": 420},
    {"id": "burgos",         "nombre": "Burgos",         "ccaa": "Castilla y León",     "lat": 42.34, "lon": -3.70,  "media_anual_mm": 590},
    {"id": "leon",           "nombre": "León",           "ccaa": "Castilla y León",     "lat": 42.60, "lon": -5.57,  "media_anual_mm": 580},
    {"id": "palencia",       "nombre": "Palencia",       "ccaa": "Castilla y León",     "lat": 42.01, "lon": -4.53,  "media_anual_mm": 510},
    {"id": "salamanca",      "nombre": "Salamanca",      "ccaa": "Castilla y León",     "lat": 40.96, "lon": -5.66,  "media_anual_mm": 450},
    {"id": "segovia",        "nombre": "Segovia",        "ccaa": "Castilla y León",     "lat": 40.95, "lon": -4.12,  "media_anual_mm": 480},
    {"id": "soria",          "nombre": "Soria",          "ccaa": "Castilla y León",     "lat": 41.77, "lon": -2.46,  "media_anual_mm": 550},
    {"id": "valladolid",     "nombre": "Valladolid",     "ccaa": "Castilla y León",     "lat": 41.65, "lon": -4.72,  "media_anual_mm": 460},
    {"id": "zamora",         "nombre": "Zamora",         "ccaa": "Castilla y León",     "lat": 41.50, "lon": -5.74,  "media_anual_mm": 430},
    {"id": "barcelona",      "nombre": "Barcelona",      "ccaa": "Cataluña",            "lat": 41.38, "lon":  2.17,  "media_anual_mm": 580},
    {"id": "girona",         "nombre": "Girona",         "ccaa": "Cataluña",            "lat": 41.98, "lon":  2.82,  "media_anual_mm": 700},
    {"id": "lleida",         "nombre": "Lleida",         "ccaa": "Cataluña",            "lat": 41.62, "lon":  0.63,  "media_anual_mm": 380},
    {"id": "tarragona",      "nombre": "Tarragona",      "ccaa": "Cataluña",            "lat": 41.11, "lon":  1.25,  "media_anual_mm": 480},
    {"id": "badajoz",        "nombre": "Badajoz",        "ccaa": "Extremadura",         "lat": 38.88, "lon": -6.97,  "media_anual_mm": 490},
    {"id": "caceres",        "nombre": "Cáceres",        "ccaa": "Extremadura",         "lat": 39.47, "lon": -6.37,  "media_anual_mm": 580},
    {"id": "acoruna",        "nombre": "A Coruña",       "ccaa": "Galicia",             "lat": 43.36, "lon": -8.40,  "media_anual_mm": 1050},
    {"id": "lugo",           "nombre": "Lugo",           "ccaa": "Galicia",             "lat": 43.01, "lon": -7.55,  "media_anual_mm": 1100},
    {"id": "ourense",        "nombre": "Ourense",        "ccaa": "Galicia",             "lat": 42.34, "lon": -7.87,  "media_anual_mm": 850},
    {"id": "pontevedra",     "nombre": "Pontevedra",     "ccaa": "Galicia",             "lat": 42.43, "lon": -8.65,  "media_anual_mm": 1600},
    {"id": "rioja",          "nombre": "La Rioja",       "ccaa": "La Rioja",            "lat": 42.27, "lon": -2.37,  "media_anual_mm": 500},
    {"id": "madrid",         "nombre": "Madrid",         "ccaa": "Comunidad de Madrid", "lat": 40.42, "lon": -3.70,  "media_anual_mm": 440},
    {"id": "murcia",         "nombre": "Murcia",         "ccaa": "Región de Murcia",    "lat": 37.99, "lon": -1.13,  "media_anual_mm": 300},
    {"id": "navarra",        "nombre": "Navarra",        "ccaa": "Navarra",             "lat": 42.82, "lon": -1.65,  "media_anual_mm": 750},
    {"id": "alava",          "nombre": "Álava",          "ccaa": "País Vasco",          "lat": 42.85, "lon": -2.67,  "media_anual_mm": 780},
    {"id": "guipuzcoa",      "nombre": "Gipuzkoa",       "ccaa": "País Vasco",          "lat": 43.19, "lon": -2.04,  "media_anual_mm": 1500},
    {"id": "vizcaya",        "nombre": "Bizkaia",        "ccaa": "País Vasco",          "lat": 43.26, "lon": -2.93,  "media_anual_mm": 1200},
    {"id": "alicante",       "nombre": "Alicante",       "ccaa": "C. Valenciana",       "lat": 38.35, "lon": -0.48,  "media_anual_mm": 330},
    {"id": "castellon",      "nombre": "Castellón",      "ccaa": "C. Valenciana",       "lat": 40.00, "lon": -0.05,  "media_anual_mm": 480},
    {"id": "valencia",       "nombre": "Valencia",       "ccaa": "C. Valenciana",       "lat": 39.47, "lon": -0.37,  "media_anual_mm": 450},
    {"id": "ceuta",          "nombre": "Ceuta",          "ccaa": "Ceuta",               "lat": 35.89, "lon": -5.32,  "media_anual_mm": 700},
    {"id": "melilla",        "nombre": "Melilla",        "ccaa": "Melilla",             "lat": 35.29, "lon": -2.94,  "media_anual_mm": 370},
]

# ─────────────────────────────────────────────────────────────────────────────
# OPEN-METEO: una sola llamada por provincia devuelve todo el histórico del año
# ─────────────────────────────────────────────────────────────────────────────

def get_daily_prec(url, lat, lon, start, end, timeout=60):
    """Llamada a Open-Meteo y devuelve lista de mm diarios con reintentos."""
    params = {
        "latitude":   lat, "longitude":  lon,
        "daily":      "precipitation_sum",
        "timezone":   "Europe/Madrid",
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date":   end.strftime("%Y-%m-%d"),
    }
    for intento in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            data = r.json()
            if "daily" not in data:
                return []
            prec = data["daily"]["precipitation_sum"]
            return [x if x is not None else 0.0 for x in prec]
        except Exception:
            if intento < 2:
                import time; time.sleep(5)
    return []

def obtener_datos_provincia(prov, ini_anual, fin):
    """
    Dos llamadas Open-Meteo:
    - /v1/forecast  → últimos 7 días (datos más recientes, sin lag)
    - /v1/archive   → acumulado anual (datos históricos consolidados)
    """
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"

    lat, lon = prov["lat"], prov["lon"]

    # Últimos 7 días desde forecast (sin lag, datos de hace 1-2 días)
    prec_rec = get_daily_prec(FORECAST_URL, lat, lon, fin - timedelta(days=6), fin)
    mm_ayer   = round(prec_rec[-1], 1) if prec_rec else 0.0
    mm_semana = round(sum(prec_rec), 1)

    # Acumulado anual desde archive
    prec_anual = get_daily_prec(ARCHIVE_URL, lat, lon, ini_anual, fin)
    mm_anual   = round(sum(prec_anual), 1)

    return mm_ayer, mm_semana, mm_anual

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS (igual que antes)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_anomalia(real_mm, media_mm):
    if not media_mm:
        return None
    return round(((real_mm - media_mm) / media_mm) * 100, 1)

def etiqueta_anomalia(a):
    if a is None:  return "Sin datos"
    if a < -40:    return "Muy seco"
    if a < -15:    return "Seco"
    if a < 15:     return "Normal"
    if a < 40:     return "Lluvioso"
    return "Muy lluvioso"

def color_lluvia(mm):
    if mm is None: return "#2a3a4a"
    if mm == 0:    return "#1a2530"
    if mm < 2:     return "#1e4060"
    if mm < 5:     return "#1e6090"
    if mm < 10:    return "#1e90c0"
    if mm < 20:    return "#22b8e8"
    if mm < 40:    return "#44d4ff"
    return "#88eeff"

def color_anomalia(a):
    if a is None:  return "#2a3a4a"
    if a < -40:    return "#8B1A1A"
    if a < -15:    return "#CC3300"
    if a < 15:     return "#CCAA44"
    if a < 40:     return "#2288CC"
    return "#0044AA"

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def procesar_lluvias():
    hoy        = datetime.now()
    fin        = hoy - timedelta(days=2)  # archive lag ~2 días
    ini_anual  = datetime(hoy.year, 1, 1)
    dia_del_anio = fin.timetuple().tm_yday

    print(f"Open-Meteo · {len(PROVINCIAS)} provincias · datos hasta {fin.strftime('%d/%m/%Y')}")

    provincias_resultado = []

    for i, prov in enumerate(PROVINCIAS, 1):
        print(f"  [{i:02d}/{len(PROVINCIAS)}] {prov['nombre']}...", end=" ", flush=True)
        mm_dia, mm_semana, mm_anual = obtener_datos_provincia(prov, ini_anual, fin)
        print(f"ayer={mm_dia}mm  7d={mm_semana}mm  anual={mm_anual}mm")

        media_diaria    = round(prov["media_anual_mm"] / 365, 2)
        media_semana    = round(media_diaria * 7, 1)
        media_hasta_hoy = round(prov["media_anual_mm"] * (dia_del_anio / 365), 1)

        anom_dia    = calcular_anomalia(mm_dia,    media_diaria)
        anom_semana = calcular_anomalia(mm_semana, media_semana)
        anom_anual  = calcular_anomalia(mm_anual,  media_hasta_hoy)

        provincias_resultado.append({
            "id": prov["id"], "nombre": prov["nombre"], "ccaa": prov["ccaa"],
            "lat": prov["lat"], "lon": prov["lon"],
            "mm_ayer":   mm_dia,
            "mm_semana": mm_semana,
            "mm_anual":  mm_anual,
            "media_diaria_mm":    media_diaria,
            "media_semana_mm":    media_semana,
            "media_anual_mm":     prov["media_anual_mm"],
            "media_hasta_hoy_mm": media_hasta_hoy,
            "anomalia_ayer_pct":   anom_dia,
            "anomalia_semana_pct": anom_semana,
            "anomalia_anual_pct":  anom_anual,
            "etiqueta_ayer":   etiqueta_anomalia(anom_dia),
            "etiqueta_semana": etiqueta_anomalia(anom_semana),
            "etiqueta_anual":  etiqueta_anomalia(anom_anual),
            "color_ayer":        color_lluvia(mm_dia),
            "color_semana":      color_lluvia(mm_semana),
            "color_anual":       color_lluvia(mm_anual),
            "color_anom_ayer":   color_anomalia(anom_dia),
            "color_anom_semana": color_anomalia(anom_semana),
            "color_anom_anual":  color_anomalia(anom_anual),
        })

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": hoy.isoformat(),
        "fecha_legible":  hoy.strftime("%d/%m/%Y a las %H:%M"),
        "fecha_datos":    fin.strftime("%d/%m/%Y"),
        "fuente":         "Open-Meteo",
        "provincias":     provincias_resultado,
    }

    with open("docs/lluvias_nacional.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ docs/lluvias_nacional.json generado · {len(provincias_resultado)} provincias")

if __name__ == "__main__":
    procesar_lluvias()
