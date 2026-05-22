import requests
import json
import os
from datetime import datetime, timedelta

AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "")
AEMET_BASE    = "https://opendata.aemet.es/opendata/api"

# AEMET tarda ~5 días en consolidar datos climatológicos diarios
DIAS_RETRASO = 5

PROVINCIAS = [
    {"id": "almeria",        "nombre": "Almería",          "ccaa": "Andalucía",           "aemet": "ALMERIA",        "lat": 37.23, "lon": -1.86,  "media_anual_mm": 220},
    {"id": "cadiz",          "nombre": "Cádiz",            "ccaa": "Andalucía",           "aemet": "CADIZ",          "lat": 36.52, "lon": -6.30,  "media_anual_mm": 640},
    {"id": "cordoba",        "nombre": "Córdoba",          "ccaa": "Andalucía",           "aemet": "CORDOBA",        "lat": 37.88, "lon": -4.78,  "media_anual_mm": 580},
    {"id": "granada",        "nombre": "Granada",          "ccaa": "Andalucía",           "aemet": "GRANADA",        "lat": 37.18, "lon": -3.60,  "media_anual_mm": 450},
    {"id": "huelva",         "nombre": "Huelva",           "ccaa": "Andalucía",           "aemet": "HUELVA",         "lat": 37.25, "lon": -6.95,  "media_anual_mm": 560},
    {"id": "jaen",           "nombre": "Jaén",             "ccaa": "Andalucía",           "aemet": "JAEN",           "lat": 37.77, "lon": -3.79,  "media_anual_mm": 500},
    {"id": "malaga",         "nombre": "Málaga",           "ccaa": "Andalucía",           "aemet": "MALAGA",         "lat": 36.72, "lon": -4.42,  "media_anual_mm": 530},
    {"id": "sevilla",        "nombre": "Sevilla",          "ccaa": "Andalucía",           "aemet": "SEVILLA",        "lat": 37.39, "lon": -5.99,  "media_anual_mm": 540},
    {"id": "huesca",         "nombre": "Huesca",           "ccaa": "Aragón",              "aemet": "HUESCA",         "lat": 42.14, "lon": -0.41,  "media_anual_mm": 530},
    {"id": "teruel",         "nombre": "Teruel",           "ccaa": "Aragón",              "aemet": "TERUEL",         "lat": 40.34, "lon": -1.11,  "media_anual_mm": 420},
    {"id": "zaragoza",       "nombre": "Zaragoza",         "ccaa": "Aragón",              "aemet": "ZARAGOZA",       "lat": 41.65, "lon": -0.89,  "media_anual_mm": 315},
    {"id": "asturias",       "nombre": "Asturias",         "ccaa": "Asturias",            "aemet": "ASTURIAS",       "lat": 43.36, "lon": -5.85,  "media_anual_mm": 1050},
    {"id": "baleares",       "nombre": "Illes Balears",    "ccaa": "Illes Balears",       "aemet": "ILLES BALEARS",  "lat": 39.57, "lon":  2.65,  "media_anual_mm": 450},
    {"id": "canarias_las_p", "nombre": "Las Palmas",       "ccaa": "Canarias",            "aemet": "LAS PALMAS",     "lat": 28.10, "lon": -15.41, "media_anual_mm": 200},
    {"id": "canarias_sc_tf", "nombre": "S.C. Tenerife",    "ccaa": "Canarias",            "aemet": "STA. CRUZ DE TENERIFE", "lat": 28.46, "lon": -16.25, "media_anual_mm": 300},
    {"id": "cantabria",      "nombre": "Cantabria",        "ccaa": "Cantabria",           "aemet": "CANTABRIA",      "lat": 43.18, "lon": -3.99,  "media_anual_mm": 1200},
    {"id": "albacete",       "nombre": "Albacete",         "ccaa": "Castilla-La Mancha",  "aemet": "ALBACETE",       "lat": 39.00, "lon": -1.86,  "media_anual_mm": 380},
    {"id": "ciudad_real",    "nombre": "Ciudad Real",      "ccaa": "Castilla-La Mancha",  "aemet": "CIUDAD REAL",    "lat": 38.99, "lon": -3.93,  "media_anual_mm": 390},
    {"id": "cuenca",         "nombre": "Cuenca",           "ccaa": "Castilla-La Mancha",  "aemet": "CUENCA",         "lat": 40.07, "lon": -2.14,  "media_anual_mm": 480},
    {"id": "guadalajara",    "nombre": "Guadalajara",      "ccaa": "Castilla-La Mancha",  "aemet": "GUADALAJARA",    "lat": 40.63, "lon": -3.17,  "media_anual_mm": 450},
    {"id": "toledo",         "nombre": "Toledo",           "ccaa": "Castilla-La Mancha",  "aemet": "TOLEDO",         "lat": 39.86, "lon": -4.02,  "media_anual_mm": 380},
    {"id": "avila",          "nombre": "Ávila",            "ccaa": "Castilla y León",     "aemet": "AVILA",          "lat": 40.66, "lon": -4.69,  "media_anual_mm": 420},
    {"id": "burgos",         "nombre": "Burgos",           "ccaa": "Castilla y León",     "aemet": "BURGOS",         "lat": 42.34, "lon": -3.70,  "media_anual_mm": 590},
    {"id": "leon",           "nombre": "León",             "ccaa": "Castilla y León",     "aemet": "LEON",           "lat": 42.60, "lon": -5.57,  "media_anual_mm": 580},
    {"id": "palencia",       "nombre": "Palencia",         "ccaa": "Castilla y León",     "aemet": "PALENCIA",       "lat": 42.01, "lon": -4.53,  "media_anual_mm": 510},
    {"id": "salamanca",      "nombre": "Salamanca",        "ccaa": "Castilla y León",     "aemet": "SALAMANCA",      "lat": 40.96, "lon": -5.66,  "media_anual_mm": 450},
    {"id": "segovia",        "nombre": "Segovia",          "ccaa": "Castilla y León",     "aemet": "SEGOVIA",        "lat": 40.95, "lon": -4.12,  "media_anual_mm": 480},
    {"id": "soria",          "nombre": "Soria",            "ccaa": "Castilla y León",     "aemet": "SORIA",          "lat": 41.77, "lon": -2.46,  "media_anual_mm": 550},
    {"id": "valladolid",     "nombre": "Valladolid",       "ccaa": "Castilla y León",     "aemet": "VALLADOLID",     "lat": 41.65, "lon": -4.72,  "media_anual_mm": 460},
    {"id": "zamora",         "nombre": "Zamora",           "ccaa": "Castilla y León",     "aemet": "ZAMORA",         "lat": 41.50, "lon": -5.74,  "media_anual_mm": 430},
    {"id": "barcelona",      "nombre": "Barcelona",        "ccaa": "Cataluña",            "aemet": "BARCELONA",      "lat": 41.38, "lon":  2.17,  "media_anual_mm": 580},
    {"id": "girona",         "nombre": "Girona",           "ccaa": "Cataluña",            "aemet": "GIRONA",         "lat": 41.98, "lon":  2.82,  "media_anual_mm": 700},
    {"id": "lleida",         "nombre": "Lleida",           "ccaa": "Cataluña",            "aemet": "LLEIDA",         "lat": 41.62, "lon":  0.63,  "media_anual_mm": 380},
    {"id": "tarragona",      "nombre": "Tarragona",        "ccaa": "Cataluña",            "aemet": "TARRAGONA",      "lat": 41.11, "lon":  1.25,  "media_anual_mm": 480},
    {"id": "badajoz",        "nombre": "Badajoz",          "ccaa": "Extremadura",         "aemet": "BADAJOZ",        "lat": 38.88, "lon": -6.97,  "media_anual_mm": 490},
    {"id": "caceres",        "nombre": "Cáceres",          "ccaa": "Extremadura",         "aemet": "CACERES",        "lat": 39.47, "lon": -6.37,  "media_anual_mm": 580},
    {"id": "acoruna",        "nombre": "A Coruña",         "ccaa": "Galicia",             "aemet": "A CORUÑA",       "lat": 43.36, "lon": -8.40,  "media_anual_mm": 1050},
    {"id": "lugo",           "nombre": "Lugo",             "ccaa": "Galicia",             "aemet": "LUGO",           "lat": 43.01, "lon": -7.55,  "media_anual_mm": 1100},
    {"id": "ourense",        "nombre": "Ourense",          "ccaa": "Galicia",             "aemet": "OURENSE",        "lat": 42.34, "lon": -7.87,  "media_anual_mm": 850},
    {"id": "pontevedra",     "nombre": "Pontevedra",       "ccaa": "Galicia",             "aemet": "PONTEVEDRA",     "lat": 42.43, "lon": -8.65,  "media_anual_mm": 1600},
    {"id": "rioja",          "nombre": "La Rioja",         "ccaa": "La Rioja",            "aemet": "LA RIOJA",       "lat": 42.27, "lon": -2.37,  "media_anual_mm": 500},
    {"id": "madrid",         "nombre": "Madrid",           "ccaa": "Comunidad de Madrid", "aemet": "MADRID",         "lat": 40.42, "lon": -3.70,  "media_anual_mm": 440},
    {"id": "murcia",         "nombre": "Murcia",           "ccaa": "Región de Murcia",    "aemet": "MURCIA",         "lat": 37.99, "lon": -1.13,  "media_anual_mm": 300},
    {"id": "navarra",        "nombre": "Navarra",          "ccaa": "Navarra",             "aemet": "NAVARRA",        "lat": 42.82, "lon": -1.65,  "media_anual_mm": 750},
    {"id": "alava",          "nombre": "Álava",            "ccaa": "País Vasco",          "aemet": "ALAVA",          "lat": 42.85, "lon": -2.67,  "media_anual_mm": 780},
    {"id": "guipuzcoa",      "nombre": "Gipuzkoa",         "ccaa": "País Vasco",          "aemet": "GUIPUZCOA",      "lat": 43.19, "lon": -2.04,  "media_anual_mm": 1500},
    {"id": "vizcaya",        "nombre": "Bizkaia",          "ccaa": "País Vasco",          "aemet": "VIZCAYA",        "lat": 43.26, "lon": -2.93,  "media_anual_mm": 1200},
    {"id": "alicante",       "nombre": "Alicante",         "ccaa": "C. Valenciana",       "aemet": "ALICANTE",       "lat": 38.35, "lon": -0.48,  "media_anual_mm": 330},
    {"id": "castellon",      "nombre": "Castellón",        "ccaa": "C. Valenciana",       "aemet": "CASTELLON",      "lat": 40.00, "lon": -0.05,  "media_anual_mm": 480},
    {"id": "valencia",       "nombre": "Valencia",         "ccaa": "C. Valenciana",       "aemet": "VALENCIA",       "lat": 39.47, "lon": -0.37,  "media_anual_mm": 450},
    {"id": "ceuta",          "nombre": "Ceuta",            "ccaa": "Ceuta",               "aemet": "CEUTA",          "lat": 35.89, "lon": -5.32,  "media_anual_mm": 700},
    {"id": "melilla",        "nombre": "Melilla",          "ccaa": "Melilla",             "aemet": "MELILLA",        "lat": 35.29, "lon": -2.94,  "media_anual_mm": 370},
]

def aemet_get(endpoint):
    headers = {"api_key": AEMET_API_KEY, "Accept": "application/json"}
    try:
        r1 = requests.get(f"{AEMET_BASE}{endpoint}", headers=headers, timeout=20)
        meta = r1.json()
        if meta.get("estado") != 200:
            print(f"  ✗ AEMET {meta.get('estado')}: {meta.get('descripcion')}")
            return None
        r2 = requests.get(meta["datos"], timeout=30)
        return r2.json()
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None

def fecha_aemet(d):
    return d.strftime("%Y-%m-%dT00:00:00UTC")

def mm_de_registro(obs):
    """Extrae mm de precipitación de un registro AEMET."""
    prec_str = str(obs.get("prec", "")).replace(",", ".").strip()
    if prec_str in ("", "Ip", "Varias", "None", "nan"):
        return 0.0
    try:
        return float(prec_str)
    except ValueError:
        return 0.0

def obtener_precipitacion_periodo(fecha_ini, fecha_fin):
    """
    Descarga datos diarios y los agrega por provincia usando el campo 'provincia'
    de AEMET (mayúsculas). Devuelve {nombre_aemet_mayusc: mm_acumulados}.
    """
    datos = aemet_get(
        f"/valores/climatologicos/diarios/datos"
        f"/fechaini/{fecha_aemet(fecha_ini)}"
        f"/fechafin/{fecha_aemet(fecha_fin)}"
        f"/todasestaciones"
    )
    if not datos:
        return {}

    # {provincia: {indicativo: mm_acumulados}}
    por_estacion = {}
    for obs in datos:
        prov = obs.get("provincia", "").strip().upper()
        if not prov:
            continue
        indicativo = obs.get("indicativo", "")
        mm = mm_de_registro(obs)
        if prov not in por_estacion:
            por_estacion[prov] = {}
        por_estacion[prov][indicativo] = por_estacion[prov].get(indicativo, 0.0) + mm

    # Media entre estaciones de la provincia
    resultado = {}
    for prov, estaciones in por_estacion.items():
        valores = list(estaciones.values())
        resultado[prov] = round(sum(valores) / len(valores), 1)

    return resultado

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

def procesar_lluvias():
    hoy  = datetime.now()
    # AEMET consolida datos con ~5 días de retraso
    fin         = hoy - timedelta(days=DIAS_RETRASO)
    ini_semana  = fin - timedelta(days=6)   # 7 días hasta 'fin'
    ini_anual   = datetime(fin.year, 1, 1)

    usar_api = bool(AEMET_API_KEY)
    print(f"{'✓ API AEMET activa' if usar_api else '⚠ Sin API key — modo demo'}")
    if usar_api:
        print(f"  Período más reciente disponible: {fin.strftime('%d/%m/%Y')}")

    if usar_api:
        print("  → Descargando día más reciente...")
        prec_dia    = obtener_precipitacion_periodo(fin, fin)
        print(f"     {len(prec_dia)} provincias")

        print("  → Descargando últimos 7 días...")
        prec_semana = obtener_precipitacion_periodo(ini_semana, fin)
        print(f"     {len(prec_semana)} provincias")

        print("  → Descargando acumulado anual...")
        prec_anual  = obtener_precipitacion_periodo(ini_anual, fin)
        print(f"     {len(prec_anual)} provincias")
    else:
        prec_dia = prec_semana = prec_anual = {}

    dia_del_anio = fin.timetuple().tm_yday
    provincias_resultado = []

    for prov in PROVINCIAS:
        clave = prov["aemet"]  # nombre en mayúsculas tal como devuelve AEMET

        if usar_api and prec_dia:
            mm_dia    = prec_dia.get(clave, 0.0)
            mm_semana = prec_semana.get(clave, 0.0)
            mm_anual  = prec_anual.get(clave, 0.0)
        else:
            import random
            norte    = prov["ccaa"] in ("Galicia","Asturias","Cantabria","País Vasco","Navarra")
            mm_dia    = round(random.uniform(0, 18 if norte else 4), 1)
            mm_semana = round(mm_dia * random.uniform(2.5, 5.0), 1)
            mm_anual  = round(prov["media_anual_mm"] * (dia_del_anio/365) * random.uniform(0.7,1.3), 0)

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
        "fuente":         "AEMET OpenData" if usar_api else "Datos de demostración",
        "demo_mode":      not usar_api,
        "provincias":     provincias_resultado,
    }

    with open("docs/lluvias_nacional.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ docs/lluvias_nacional.json — {len(provincias_resultado)} provincias")
    print(f"  Datos del: {fin.strftime('%d/%m/%Y')}")

if __name__ == "__main__":
    procesar_lluvias()
