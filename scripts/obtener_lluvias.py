import requests
import json
import os
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# La API key de AEMET OpenData se obtiene gratis en:
# https://opendata.aemet.es/centrodedescargas/altaUsuarios
# Ponla como secreto de GitHub: AEMET_API_KEY
# ─────────────────────────────────────────────────────────────────────────────
AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "")
AEMET_BASE    = "https://opendata.aemet.es/opendata/api"

# ─────────────────────────────────────────────────────────────────────────────
# DICCIONARIO MAESTRO DE PROVINCIAS
# id_ine: código INE de la provincia (usado por AEMET para filtrar)
# lat/lon: centroide aproximado para el marcador del mapa
# media_anual_mm: precipitación media histórica anual (fuente: AEMET Atlas Climático)
# ─────────────────────────────────────────────────────────────────────────────
PROVINCIAS = [
    {"id": "almeria",        "nombre": "Almería",         "ccaa": "Andalucía",              "id_ine": "04", "lat": 37.23, "lon": -1.86,  "media_anual_mm": 220},
    {"id": "cadiz",          "nombre": "Cádiz",           "ccaa": "Andalucía",              "id_ine": "11", "lat": 36.52, "lon": -6.30,  "media_anual_mm": 640},
    {"id": "cordoba",        "nombre": "Córdoba",         "ccaa": "Andalucía",              "id_ine": "14", "lat": 37.88, "lon": -4.78,  "media_anual_mm": 580},
    {"id": "granada",        "nombre": "Granada",         "ccaa": "Andalucía",              "id_ine": "18", "lat": 37.18, "lon": -3.60,  "media_anual_mm": 450},
    {"id": "huelva",         "nombre": "Huelva",          "ccaa": "Andalucía",              "id_ine": "21", "lat": 37.25, "lon": -6.95,  "media_anual_mm": 560},
    {"id": "jaen",           "nombre": "Jaén",            "ccaa": "Andalucía",              "id_ine": "23", "lat": 37.77, "lon": -3.79,  "media_anual_mm": 500},
    {"id": "malaga",         "nombre": "Málaga",          "ccaa": "Andalucía",              "id_ine": "29", "lat": 36.72, "lon": -4.42,  "media_anual_mm": 530},
    {"id": "sevilla",        "nombre": "Sevilla",         "ccaa": "Andalucía",              "id_ine": "41", "lat": 37.39, "lon": -5.99,  "media_anual_mm": 540},
    {"id": "huesca",         "nombre": "Huesca",          "ccaa": "Aragón",                 "id_ine": "22", "lat": 42.14, "lon": -0.41,  "media_anual_mm": 530},
    {"id": "teruel",         "nombre": "Teruel",          "ccaa": "Aragón",                 "id_ine": "44", "lat": 40.34, "lon": -1.11,  "media_anual_mm": 420},
    {"id": "zaragoza",       "nombre": "Zaragoza",        "ccaa": "Aragón",                 "id_ine": "50", "lat": 41.65, "lon": -0.89,  "media_anual_mm": 315},
    {"id": "asturias",       "nombre": "Asturias",        "ccaa": "Asturias",               "id_ine": "33", "lat": 43.36, "lon": -5.85,  "media_anual_mm": 1050},
    {"id": "baleares",       "nombre": "Illes Balears",   "ccaa": "Illes Balears",          "id_ine": "07", "lat": 39.57, "lon":  2.65,  "media_anual_mm": 450},
    {"id": "canarias_las_p", "nombre": "Las Palmas",      "ccaa": "Canarias",               "id_ine": "35", "lat": 28.10, "lon": -15.41, "media_anual_mm": 200},
    {"id": "canarias_sc_tf", "nombre": "Santa Cruz de Tenerife", "ccaa": "Canarias",        "id_ine": "38", "lat": 28.46, "lon": -16.25, "media_anual_mm": 300},
    {"id": "cantabria",      "nombre": "Cantabria",       "ccaa": "Cantabria",              "id_ine": "39", "lat": 43.18, "lon": -3.99,  "media_anual_mm": 1200},
    {"id": "albacete",       "nombre": "Albacete",        "ccaa": "Castilla-La Mancha",     "id_ine": "02", "lat": 39.00, "lon": -1.86,  "media_anual_mm": 380},
    {"id": "ciudad_real",    "nombre": "Ciudad Real",     "ccaa": "Castilla-La Mancha",     "id_ine": "13", "lat": 38.99, "lon": -3.93,  "media_anual_mm": 390},
    {"id": "cuenca",         "nombre": "Cuenca",          "ccaa": "Castilla-La Mancha",     "id_ine": "16", "lat": 40.07, "lon": -2.14,  "media_anual_mm": 480},
    {"id": "guadalajara",    "nombre": "Guadalajara",     "ccaa": "Castilla-La Mancha",     "id_ine": "19", "lat": 40.63, "lon": -3.17,  "media_anual_mm": 450},
    {"id": "toledo",         "nombre": "Toledo",          "ccaa": "Castilla-La Mancha",     "id_ine": "45", "lat": 39.86, "lon": -4.02,  "media_anual_mm": 380},
    {"id": "avila",          "nombre": "Ávila",           "ccaa": "Castilla y León",        "id_ine": "05", "lat": 40.66, "lon": -4.69,  "media_anual_mm": 420},
    {"id": "burgos",         "nombre": "Burgos",          "ccaa": "Castilla y León",        "id_ine": "09", "lat": 42.34, "lon": -3.70,  "media_anual_mm": 590},
    {"id": "leon",           "nombre": "León",            "ccaa": "Castilla y León",        "id_ine": "24", "lat": 42.60, "lon": -5.57,  "media_anual_mm": 580},
    {"id": "palencia",       "nombre": "Palencia",        "ccaa": "Castilla y León",        "id_ine": "34", "lat": 42.01, "lon": -4.53,  "media_anual_mm": 510},
    {"id": "salamanca",      "nombre": "Salamanca",       "ccaa": "Castilla y León",        "id_ine": "37", "lat": 40.96, "lon": -5.66,  "media_anual_mm": 450},
    {"id": "segovia",        "nombre": "Segovia",         "ccaa": "Castilla y León",        "id_ine": "40", "lat": 40.95, "lon": -4.12,  "media_anual_mm": 480},
    {"id": "soria",          "nombre": "Soria",           "ccaa": "Castilla y León",        "id_ine": "42", "lat": 41.77, "lon": -2.46,  "media_anual_mm": 550},
    {"id": "valladolid",     "nombre": "Valladolid",      "ccaa": "Castilla y León",        "id_ine": "47", "lat": 41.65, "lon": -4.72,  "media_anual_mm": 460},
    {"id": "zamora",         "nombre": "Zamora",          "ccaa": "Castilla y León",        "id_ine": "49", "lat": 41.50, "lon": -5.74,  "media_anual_mm": 430},
    {"id": "barcelona",      "nombre": "Barcelona",       "ccaa": "Cataluña",               "id_ine": "08", "lat": 41.38, "lon":  2.17,  "media_anual_mm": 580},
    {"id": "girona",         "nombre": "Girona",          "ccaa": "Cataluña",               "id_ine": "17", "lat": 41.98, "lon":  2.82,  "media_anual_mm": 700},
    {"id": "lleida",         "nombre": "Lleida",          "ccaa": "Cataluña",               "id_ine": "25", "lat": 41.62, "lon":  0.63,  "media_anual_mm": 380},
    {"id": "tarragona",      "nombre": "Tarragona",       "ccaa": "Cataluña",               "id_ine": "43", "lat": 41.11, "lon":  1.25,  "media_anual_mm": 480},
    {"id": "badajoz",        "nombre": "Badajoz",         "ccaa": "Extremadura",            "id_ine": "06", "lat": 38.88, "lon": -6.97,  "media_anual_mm": 490},
    {"id": "caceres",        "nombre": "Cáceres",         "ccaa": "Extremadura",            "id_ine": "10", "lat": 39.47, "lon": -6.37,  "media_anual_mm": 580},
    {"id": "acoruna",        "nombre": "A Coruña",        "ccaa": "Galicia",                "id_ine": "15", "lat": 43.36, "lon": -8.40,  "media_anual_mm": 1050},
    {"id": "lugo",           "nombre": "Lugo",            "ccaa": "Galicia",                "id_ine": "27", "lat": 43.01, "lon": -7.55,  "media_anual_mm": 1100},
    {"id": "ourense",        "nombre": "Ourense",         "ccaa": "Galicia",                "id_ine": "32", "lat": 42.34, "lon": -7.87,  "media_anual_mm": 850},
    {"id": "pontevedra",     "nombre": "Pontevedra",      "ccaa": "Galicia",                "id_ine": "36", "lat": 42.43, "lon": -8.65,  "media_anual_mm": 1600},
    {"id": "rioja",          "nombre": "La Rioja",        "ccaa": "La Rioja",               "id_ine": "26", "lat": 42.27, "lon": -2.37,  "media_anual_mm": 500},
    {"id": "madrid",         "nombre": "Madrid",          "ccaa": "Comunidad de Madrid",    "id_ine": "28", "lat": 40.42, "lon": -3.70,  "media_anual_mm": 440},
    {"id": "murcia",         "nombre": "Murcia",          "ccaa": "Región de Murcia",       "id_ine": "30", "lat": 37.99, "lon": -1.13,  "media_anual_mm": 300},
    {"id": "navarra",        "nombre": "Navarra",         "ccaa": "Navarra",                "id_ine": "31", "lat": 42.82, "lon": -1.65,  "media_anual_mm": 750},
    {"id": "alava",          "nombre": "Álava",           "ccaa": "País Vasco",             "id_ine": "01", "lat": 42.85, "lon": -2.67,  "media_anual_mm": 780},
    {"id": "guipuzcoa",      "nombre": "Gipuzkoa",        "ccaa": "País Vasco",             "id_ine": "20", "lat": 43.19, "lon": -2.04,  "media_anual_mm": 1500},
    {"id": "vizcaya",        "nombre": "Bizkaia",         "ccaa": "País Vasco",             "id_ine": "48", "lat": 43.26, "lon": -2.93,  "media_anual_mm": 1200},
    {"id": "alicante",       "nombre": "Alicante",        "ccaa": "C. Valenciana",          "id_ine": "03", "lat": 38.35, "lon": -0.48,  "media_anual_mm": 330},
    {"id": "castellon",      "nombre": "Castellón",       "ccaa": "C. Valenciana",          "id_ine": "12", "lat": 40.00, "lon": -0.05,  "media_anual_mm": 480},
    {"id": "valencia",       "nombre": "Valencia",        "ccaa": "C. Valenciana",          "id_ine": "46", "lat": 39.47, "lon": -0.37,  "media_anual_mm": 450},
    {"id": "ceuta",          "nombre": "Ceuta",           "ccaa": "Ceuta",                  "id_ine": "51", "lat": 35.89, "lon": -5.32,  "media_anual_mm": 700},
    {"id": "melilla",        "nombre": "Melilla",         "ccaa": "Melilla",                "id_ine": "52", "lat": 35.29, "lon": -2.94,  "media_anual_mm": 370},
]

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE AEMET
# ─────────────────────────────────────────────────────────────────────────────

def aemet_get(endpoint):
    """Llamada a la API de AEMET: primero obtenemos la URL de datos, luego los datos."""
    headers = {"api_key": AEMET_API_KEY, "Accept": "application/json"}
    try:
        r1 = requests.get(f"{AEMET_BASE}{endpoint}", headers=headers, timeout=20)
        meta = r1.json()
        if meta.get("estado") != 200:
            return None
        r2 = requests.get(meta["datos"], timeout=30)
        return r2.json()
    except Exception as e:
        print(f"  ✗ Error AEMET [{endpoint}]: {e}")
        return None

def fecha_aemet(d: datetime) -> str:
    """Formatea una fecha al estilo AEMET: YYYY-MM-DDTHH:MM:SSUTC"""
    return d.strftime("%Y-%m-%dT00:00:00UTC")

def obtener_precipitacion_periodo(fecha_ini: datetime, fecha_fin: datetime) -> dict:
    """
    Descarga observaciones climatológicas de todas las estaciones para un período.
    Devuelve un dict {id_provincia_ine: mm_totales}.
    """
    fi = fecha_aemet(fecha_ini)
    ff = fecha_aemet(fecha_fin)
    endpoint = f"/valores/climatologicos/diarios/datos/fechaini/{fi}/fechafin/{ff}/todasestaciones"
    datos = aemet_get(endpoint)
    if not datos:
        return {}

    # Agrupamos por provincia (primeros 2 dígitos del indicativo de estación = código INE)
    acumulado = {}  # {id_ine: [lista de mm]}
    for obs in datos:
        indicativo = obs.get("indicativo", "")
        id_ine = indicativo[:2] if len(indicativo) >= 2 else ""
        try:
            # La precipitación viene como string con coma decimal; "Ip" = inapreciable
            prec_str = obs.get("prec", "0").replace(",", ".").strip()
            if prec_str in ("", "Ip", "Varias"):
                prec_mm = 0.0
            else:
                prec_mm = float(prec_str)
            if id_ine not in acumulado:
                acumulado[id_ine] = []
            acumulado[id_ine].append(prec_mm)
        except ValueError:
            pass

    # Media de las estaciones de cada provincia (más representativo que la suma)
    resultado = {}
    for id_ine, valores in acumulado.items():
        if valores:
            resultado[id_ine] = round(sum(valores) / len(valores), 1)
    return resultado

def obtener_precipitacion_anual(anio: int) -> dict:
    """Suma mensual del año para obtener el acumulado anual."""
    hoy = datetime.now()
    fin = datetime(anio, hoy.month, hoy.day) if anio == hoy.year else datetime(anio, 12, 31)
    return obtener_precipitacion_periodo(datetime(anio, 1, 1), fin)

# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK: datos sintéticos realistas cuando la API no está disponible
# (útil en desarrollo o si la clave AEMET caduca)
# ─────────────────────────────────────────────────────────────────────────────
import random

def datos_fallback_ayer(prov):
    """Lluvia de ayer: entre 0 y ~25 mm, más probable el norte húmedo."""
    norte = prov["ccaa"] in ("Galicia", "Asturias", "Cantabria", "País Vasco", "Navarra")
    base = random.uniform(0, 20) if norte else random.uniform(0, 6)
    return round(base, 1)

def datos_fallback_semana(prov):
    return round(datos_fallback_ayer(prov) * random.uniform(2.5, 5.0), 1)

def datos_fallback_anual(prov):
    fraccion = datetime.now().timetuple().tm_yday / 365
    variacion = random.uniform(0.7, 1.3)
    return round(prov["media_anual_mm"] * fraccion * variacion, 0)

# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def calcular_anomalia(real_mm, media_mm):
    """
    Anomalía porcentual respecto a la media histórica proporcional al día del año.
    Positivo = más lluvia de lo normal. Negativo = déficit.
    """
    if media_mm <= 0:
        return None
    return round(((real_mm - media_mm) / media_mm) * 100, 1)

def etiqueta_anomalia(anomalia):
    if anomalia is None:   return "Sin datos"
    if anomalia < -40:     return "Muy seco"
    if anomalia < -15:     return "Seco"
    if anomalia < 15:      return "Normal"
    if anomalia < 40:      return "Lluvioso"
    return "Muy lluvioso"

def color_lluvia(mm_ayer):
    """Color según litros caídos ayer (para capa por defecto)."""
    if mm_ayer is None:  return "#2a3a4a"
    if mm_ayer == 0:     return "#1a2530"
    if mm_ayer < 2:      return "#1e4060"
    if mm_ayer < 5:      return "#1e6090"
    if mm_ayer < 10:     return "#1e90c0"
    if mm_ayer < 20:     return "#22b8e8"
    if mm_ayer < 40:     return "#44d4ff"
    return "#88eeff"

def color_anomalia(anomalia):
    """Escala divergente: rojo=seco, azul=lluvioso."""
    if anomalia is None:    return "#2a3a4a"
    if anomalia < -40:      return "#8B1A1A"
    if anomalia < -15:      return "#CC3300"
    if anomalia < 15:       return "#CCAA44"
    if anomalia < 40:       return "#2288CC"
    return "#0044AA"

def procesar_lluvias():
    hoy = datetime.now()
    ayer = hoy - timedelta(days=1)
    inicio_semana = hoy - timedelta(days=7)
    anio_actual = hoy.year

    usar_api = bool(AEMET_API_KEY)
    print(f"{'✓ API AEMET activa' if usar_api else '⚠ Sin API key — usando datos de demostración'}")

    if usar_api:
        print("  Descargando precipitaciones de ayer...")
        prec_ayer_raw = obtener_precipitacion_periodo(ayer, ayer)
        print("  Descargando precipitaciones de los últimos 7 días...")
        prec_semana_raw = obtener_precipitacion_periodo(inicio_semana, ayer)
        print("  Descargando acumulado anual...")
        prec_anual_raw = obtener_precipitacion_anual(anio_actual)
    else:
        prec_ayer_raw = prec_semana_raw = prec_anual_raw = {}

    provincias_resultado = []

    for prov in PROVINCIAS:
        id_ine = prov["id_ine"]

        # Precipitaciones
        if usar_api and prec_ayer_raw:
            mm_ayer   = prec_ayer_raw.get(id_ine, 0.0)
            mm_semana = prec_semana_raw.get(id_ine, 0.0)
            mm_anual  = prec_anual_raw.get(id_ine, 0.0)
        else:
            mm_ayer   = datos_fallback_ayer(prov)
            mm_semana = datos_fallback_semana(prov)
            mm_anual  = datos_fallback_anual(prov)

        # Media histórica proporcional al día del año
        dia_del_anio = hoy.timetuple().tm_yday
        media_hasta_hoy = round(prov["media_anual_mm"] * (dia_del_anio / 365), 1)

        # Anomalías
        # Para ayer usamos la media diaria histórica
        media_diaria = round(prov["media_anual_mm"] / 365, 2)
        media_semana = round(media_diaria * 7, 1)

        anom_ayer   = calcular_anomalia(mm_ayer,   media_diaria)
        anom_semana = calcular_anomalia(mm_semana, media_semana)
        anom_anual  = calcular_anomalia(mm_anual,  media_hasta_hoy)

        provincias_resultado.append({
            "id":      prov["id"],
            "nombre":  prov["nombre"],
            "ccaa":    prov["ccaa"],
            "lat":     prov["lat"],
            "lon":     prov["lon"],
            # Precipitaciones
            "mm_ayer":   mm_ayer,
            "mm_semana": mm_semana,
            "mm_anual":  mm_anual,
            # Medias históricas de referencia
            "media_diaria_mm":    media_diaria,
            "media_semana_mm":    media_semana,
            "media_anual_mm":     prov["media_anual_mm"],
            "media_hasta_hoy_mm": media_hasta_hoy,
            # Anomalías
            "anomalia_ayer_pct":   anom_ayer,
            "anomalia_semana_pct": anom_semana,
            "anomalia_anual_pct":  anom_anual,
            # Etiquetas
            "etiqueta_ayer":   etiqueta_anomalia(anom_ayer),
            "etiqueta_semana": etiqueta_anomalia(anom_semana),
            "etiqueta_anual":  etiqueta_anomalia(anom_anual),
            # Colores precalculados
            "color_ayer":        color_lluvia(mm_ayer),
            "color_semana":      color_lluvia(mm_semana),
            "color_anual":       color_lluvia(mm_anual),
            "color_anom_ayer":   color_anomalia(anom_ayer),
            "color_anom_semana": color_anomalia(anom_semana),
            "color_anom_anual":  color_anomalia(anom_anual),
        })

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": hoy.isoformat(),
        "fecha_legible":  hoy.strftime("%d/%m/%Y a las %H:%M"),
        "fuente":         "AEMET OpenData" if usar_api else "Datos de demostración",
        "fecha_ayer":     ayer.strftime("%d/%m/%Y"),
        "fecha_semana":   inicio_semana.strftime("%d/%m/%Y") + " – " + ayer.strftime("%d/%m/%Y"),
        "anio":           str(anio_actual),
        "demo_mode":      not usar_api,
        "provincias":     provincias_resultado,
    }

    with open("docs/lluvias_nacional.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ docs/lluvias_nacional.json generado con {len(provincias_resultado)} provincias.")
    print(f"  Fecha: {output['fecha_legible']}")

if __name__ == "__main__":
    procesar_lluvias()
