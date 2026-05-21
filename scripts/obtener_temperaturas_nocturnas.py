import requests
import json
import os
from datetime import datetime, timedelta, date

# ─────────────────────────────────────────────────────────────────────────────
# LISTADO MAESTRO: 50 ciudades representativas de España
# ─────────────────────────────────────────────────────────────────────────────
CIUDADES = [
    # Andalucía
    {"id": "sevilla",       "nombre": "Sevilla",       "ccaa": "Andalucía",          "lat": 37.389, "lon": -5.984},
    {"id": "malaga",        "nombre": "Málaga",        "ccaa": "Andalucía",          "lat": 36.720, "lon": -4.420},
    {"id": "granada",       "nombre": "Granada",       "ccaa": "Andalucía",          "lat": 37.177, "lon": -3.599},
    {"id": "cordoba",       "nombre": "Córdoba",       "ccaa": "Andalucía",          "lat": 37.884, "lon": -4.779},
    {"id": "almeria",       "nombre": "Almería",       "ccaa": "Andalucía",          "lat": 36.834, "lon": -2.464},
    {"id": "huelva",        "nombre": "Huelva",        "ccaa": "Andalucía",          "lat": 37.261, "lon": -6.944},
    {"id": "cadiz",         "nombre": "Cádiz",         "ccaa": "Andalucía",          "lat": 36.527, "lon": -6.290},
    {"id": "jaen",          "nombre": "Jaén",          "ccaa": "Andalucía",          "lat": 37.779, "lon": -3.790},
    {"id": "motril",        "nombre": "Motril",        "ccaa": "Andalucía",          "lat": 36.745, "lon": -3.517},
    # Comunidad Valenciana
    {"id": "valencia",      "nombre": "Valencia",      "ccaa": "C. Valenciana",      "lat": 39.470, "lon": -0.376},
    {"id": "alicante",      "nombre": "Alicante",      "ccaa": "C. Valenciana",      "lat": 38.345, "lon": -0.483},
    {"id": "castellon",     "nombre": "Castellón",     "ccaa": "C. Valenciana",      "lat": 39.986, "lon": -0.049},
    # Región de Murcia
    {"id": "murcia",        "nombre": "Murcia",        "ccaa": "Región de Murcia",   "lat": 37.992, "lon": -1.130},
    {"id": "cartagena",     "nombre": "Cartagena",     "ccaa": "Región de Murcia",   "lat": 37.605, "lon": -0.986},
    {"id": "lorca",         "nombre": "Lorca",         "ccaa": "Región de Murcia",   "lat": 37.671, "lon": -1.700},
    # Cataluña
    {"id": "barcelona",     "nombre": "Barcelona",     "ccaa": "Cataluña",           "lat": 41.389, "lon":  2.159},
    {"id": "tarragona",     "nombre": "Tarragona",     "ccaa": "Cataluña",           "lat": 41.119, "lon":  1.245},
    {"id": "lleida",        "nombre": "Lleida",        "ccaa": "Cataluña",           "lat": 41.618, "lon":  0.624},
    {"id": "girona",        "nombre": "Girona",        "ccaa": "Cataluña",           "lat": 41.983, "lon":  2.824},
    # Madrid
    {"id": "madrid",        "nombre": "Madrid",        "ccaa": "Madrid",             "lat": 40.416, "lon": -3.703},
    # Castilla-La Mancha
    {"id": "toledo",        "nombre": "Toledo",        "ccaa": "Castilla-La Mancha", "lat": 39.857, "lon": -4.024},
    {"id": "ciudad_real",   "nombre": "Ciudad Real",   "ccaa": "Castilla-La Mancha", "lat": 38.986, "lon": -3.929},
    {"id": "albacete",      "nombre": "Albacete",      "ccaa": "Castilla-La Mancha", "lat": 38.994, "lon": -1.858},
    # Castilla y León
    {"id": "valladolid",    "nombre": "Valladolid",    "ccaa": "Castilla y León",    "lat": 41.652, "lon": -4.724},
    {"id": "salamanca",     "nombre": "Salamanca",     "ccaa": "Castilla y León",    "lat": 40.965, "lon": -5.664},
    {"id": "burgos",        "nombre": "Burgos",        "ccaa": "Castilla y León",    "lat": 42.344, "lon": -3.707},
    {"id": "leon",          "nombre": "León",          "ccaa": "Castilla y León",    "lat": 42.599, "lon": -5.570},
    # Aragón
    {"id": "zaragoza",      "nombre": "Zaragoza",      "ccaa": "Aragón",             "lat": 41.649, "lon": -0.887},
    {"id": "huesca",        "nombre": "Huesca",        "ccaa": "Aragón",             "lat": 42.140, "lon": -0.409},
    {"id": "teruel",        "nombre": "Teruel",        "ccaa": "Aragón",             "lat": 40.345, "lon": -1.107},
    # País Vasco
    {"id": "bilbao",        "nombre": "Bilbao",        "ccaa": "País Vasco",         "lat": 43.263, "lon": -2.935},
    {"id": "san_sebastian", "nombre": "San Sebastián", "ccaa": "País Vasco",         "lat": 43.318, "lon": -1.981},
    {"id": "vitoria",       "nombre": "Vitoria",       "ccaa": "País Vasco",         "lat": 42.846, "lon": -2.673},
    # Galicia
    {"id": "vigo",          "nombre": "Vigo",          "ccaa": "Galicia",            "lat": 42.231, "lon": -8.712},
    {"id": "coruna",        "nombre": "A Coruña",      "ccaa": "Galicia",            "lat": 43.362, "lon": -8.412},
    {"id": "santiago",      "nombre": "Santiago",      "ccaa": "Galicia",            "lat": 42.880, "lon": -8.545},
    # Asturias / Cantabria
    {"id": "oviedo",        "nombre": "Oviedo",        "ccaa": "Asturias",           "lat": 43.362, "lon": -5.849},
    {"id": "santander",     "nombre": "Santander",     "ccaa": "Cantabria",          "lat": 43.462, "lon": -3.810},
    # Navarra / La Rioja
    {"id": "pamplona",      "nombre": "Pamplona",      "ccaa": "Navarra",            "lat": 42.817, "lon": -1.644},
    {"id": "logrono",       "nombre": "Logroño",       "ccaa": "La Rioja",           "lat": 42.466, "lon": -2.445},
    # Extremadura
    {"id": "badajoz",       "nombre": "Badajoz",       "ccaa": "Extremadura",        "lat": 38.879, "lon": -6.970},
    {"id": "caceres",       "nombre": "Cáceres",       "ccaa": "Extremadura",        "lat": 39.476, "lon": -6.372},
    # Baleares
    {"id": "palma",         "nombre": "Palma",         "ccaa": "Baleares",           "lat": 39.569, "lon":  2.650},
    {"id": "ibiza",         "nombre": "Ibiza",         "ccaa": "Baleares",           "lat": 38.909, "lon":  1.433},
    {"id": "mahon",         "nombre": "Mahón",         "ccaa": "Baleares",           "lat": 39.888, "lon":  4.266},
    # Canarias
    {"id": "las_palmas",    "nombre": "Las Palmas",    "ccaa": "Canarias",           "lat": 28.124, "lon": -15.430},
    {"id": "santa_cruz_tf", "nombre": "Sta. Cruz TF",  "ccaa": "Canarias",           "lat": 28.464, "lon": -16.252},
    # Ceuta / Melilla
    {"id": "ceuta",         "nombre": "Ceuta",         "ccaa": "Ceuta",              "lat": 35.889, "lon": -5.322},
    {"id": "melilla",       "nombre": "Melilla",       "ccaa": "Melilla",            "lat": 35.292, "lon": -2.938},
]

# ─────────────────────────────────────────────────────────────────────────────
# FECHAS
# ─────────────────────────────────────────────────────────────────────────────
hoy  = date.today()
ayer = hoy - timedelta(days=1)

# Pedimos desde el 1 de enero del año anterior hasta ayer en UNA sola llamada
fecha_inicio = date(hoy.year - 1, 1, 1)
fecha_fin    = ayer

def open_meteo(lat, lon):
    """Una sola llamada por ciudad con todo el rango necesario."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_min,temperature_2m_max"
        f"&start_date={fecha_inicio}&end_date={fecha_fin}"
        f"&timezone=Europe%2FMadrid"
    )
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            return r.json().get("daily", {})
    except Exception as e:
        print(f"    Error ({lat},{lon}): {e}")
    return {}

def media(lista):
    vals = [v for v in lista if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

def contar_nt(mins):
    return sum(1 for v in mins if v is not None and v >= 20.0)

def filtrar_por_mes_anyo(fechas, valores, mes, anyo):
    return [v for f, v in zip(fechas, valores) if f.startswith(f"{anyo}-{mes:02d}")]

def calcular_color(t):
    if t is None:   return "#888888", "Sin datos"
    if t >= 25:     return "#CC2200", "Muy cálida"
    if t >= 20:     return "#FF6600", "Tropical"
    if t >= 15:     return "#FFAA00", "Cálida"
    if t >= 10:     return "#44AA66", "Templada"
    if t >= 5:      return "#3399CC", "Fresca"
    return "#0055AA", "Fría"

def procesar():
    print(f"Consultando Open-Meteo ({fecha_inicio} → {fecha_fin}) — 1 llamada por ciudad...")
    os.makedirs("docs", exist_ok=True)
    resultado = []

    mes_act  = hoy.month
    anyo_act = hoy.year
    anyo_ant = hoy.year - 1

    for i, ciudad in enumerate(CIUDADES):
        print(f"  [{i+1}/{len(CIUDADES)}] {ciudad['nombre']}...")

        daily  = open_meteo(ciudad["lat"], ciudad["lon"])
        fechas = daily.get("time", [])
        mins   = daily.get("temperature_2m_min", [])
        maxs   = daily.get("temperature_2m_max", [])

        if not fechas:
            resultado.append({**ciudad, "t_min_anoche": None, "media_min_mes": None,
                "media_max_mes": None, "media_min_mes_ant": None, "media_max_mes_ant": None,
                "diff_min_vs_ant": None, "diff_max_vs_ant": None,
                "nt_mes": 0, "nt_anyo": 0, "color": "#888888", "etiqueta": "Sin datos"})
            continue

        # Mínima de anoche = último dato disponible
        t_min_anoche = round(mins[-1], 1) if mins and mins[-1] is not None else None

        # Mes actual (año en curso)
        mins_mes = filtrar_por_mes_anyo(fechas, mins, mes_act, anyo_act)
        maxs_mes = filtrar_por_mes_anyo(fechas, maxs, mes_act, anyo_act)

        # Mismo mes del año anterior
        mins_mes_ant = filtrar_por_mes_anyo(fechas, mins, mes_act, anyo_ant)
        maxs_mes_ant = filtrar_por_mes_anyo(fechas, maxs, mes_act, anyo_ant)

        # Año en curso completo (desde 1 enero hasta ayer)
        mins_anyo = filtrar_por_mes_anyo(fechas, mins, None, anyo_act) if False else \
                    [v for f, v in zip(fechas, mins) if f.startswith(str(anyo_act))]

        media_min_mes     = media(mins_mes)
        media_max_mes     = media(maxs_mes)
        media_min_mes_ant = media(mins_mes_ant)
        media_max_mes_ant = media(maxs_mes_ant)

        diff_min = round(media_min_mes - media_min_mes_ant, 1) \
                   if media_min_mes is not None and media_min_mes_ant is not None else None
        diff_max = round(media_max_mes - media_max_mes_ant, 1) \
                   if media_max_mes is not None and media_max_mes_ant is not None else None

        nt_mes  = contar_nt(mins_mes)
        nt_anyo = contar_nt(mins_anyo)

        color, etiqueta = calcular_color(t_min_anoche)

        resultado.append({
            "id":                ciudad["id"],
            "nombre":            ciudad["nombre"],
            "ccaa":              ciudad["ccaa"],
            "lat":               ciudad["lat"],
            "lon":               ciudad["lon"],
            "t_min_anoche":      t_min_anoche,
            "media_min_mes":     media_min_mes,
            "media_max_mes":     media_max_mes,
            "media_min_mes_ant": media_min_mes_ant,
            "media_max_mes_ant": media_max_mes_ant,
            "diff_min_vs_ant":   diff_min,
            "diff_max_vs_ant":   diff_max,
            "nt_mes":            nt_mes,
            "nt_anyo":           nt_anyo,
            "color":             color,
            "etiqueta":          etiqueta,
        })

    # Mes en español (sin locale)
    MESES = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    mes_nombre     = MESES[mes_act - 1]
    mes_nombre_ant = MESES[mes_act - 1]

    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "mes_actual":           mes_nombre.capitalize(),
        "anyo_actual":          anyo_act,
        "mes_anterior_ref":     f"{mes_nombre_ant} {anyo_ant}",
        "fuente":               "Open-Meteo Archive API (ERA5)",
        "total_ciudades":       len(resultado),
        "ciudades":             resultado,
    }

    with open("docs/temperaturas_nocturnas.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ docs/temperaturas_nocturnas.json generado con {len(resultado)} ciudades.")

if __name__ == "__main__":
    procesar()
