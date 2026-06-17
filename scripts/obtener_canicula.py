"""
obtener_canicula.py
-------------------------------------------------------------------------------
Calcula el Índice de Calor Canicular (ICC) por provincia para España y lo
escribe en docs/canicula.json, listo para servir por GitHub Pages.

FUENTE DE DATOS: Open-Meteo (sin API key).
  - Forecast API : Tmáx y Tmín de los últimos días + hoy (1 llamada para todas
                   las provincias, multipunto).
  - Archive API  : se usa UNA sola vez por provincia para calcular el percentil 90
                   climático de Tmáx en verano (referencia local). Luego se cachea
                   en el JSON (campo ref_p90) y no se vuelve a descargar.

PATRÓN INCREMENTAL (igual que noches tropicales):
  - El JSON guarda un 'historico' diario por provincia, así los días consecutivos
    de calor se calculan sin volver a descargar series largas.

ÍNDICE ICC (0-100), transparente y documentado:
  - Intensidad   (0-50): cuánto supera la Tmáx de hoy el P90 climático local.
  - Persistencia (0-30): días consecutivos con Tmáx >= P90 local.
  - Noche cálida (0-20): a partir de la Tmín de hoy (relación con noches tropicales).
  ICC = intensidad + persistencia + noche.

NOTA METODOLÓGICA: el ICC es un índice propio de intensidad de calor estival,
NO una declaración oficial de ola de calor ni de canícula de AEMET.
-------------------------------------------------------------------------------
"""

import requests
import json
import os
import time
from datetime import datetime, date

# --- CONFIGURACIÓN ------------------------------------------------------------
OUTPUT_PATH   = "docs/canicula.json"
TIMEZONE      = "Europe/Madrid"
PAST_DAYS     = 7          # días hacia atrás para calcular persistencia
HIST_MAX_DIAS = 120        # tope de historico por provincia (evita bloat)
REF_YEARS     = ("2010-01-01", "2020-12-31")  # ventana para el P90 climático
PAUSA_API     = 1.2        # segundos entre llamadas a Open-Meteo (cortesía)

# --- PROVINCIAS (capital como punto representativo) ---------------------------
PROVINCIAS = [
    {"id": "alava",            "nombre": "Álava",                  "lat": 42.85, "lon": -2.67},
    {"id": "albacete",         "nombre": "Albacete",               "lat": 38.99, "lon": -1.86},
    {"id": "alicante",         "nombre": "Alicante",               "lat": 38.35, "lon": -0.48},
    {"id": "almeria",          "nombre": "Almería",                "lat": 36.84, "lon": -2.46},
    {"id": "asturias",         "nombre": "Asturias",               "lat": 43.36, "lon": -5.85},
    {"id": "avila",            "nombre": "Ávila",                  "lat": 40.66, "lon": -4.70},
    {"id": "badajoz",          "nombre": "Badajoz",                "lat": 38.88, "lon": -6.97},
    {"id": "barcelona",        "nombre": "Barcelona",              "lat": 41.39, "lon":  2.17},
    {"id": "burgos",           "nombre": "Burgos",                 "lat": 42.34, "lon": -3.70},
    {"id": "caceres",          "nombre": "Cáceres",                "lat": 39.48, "lon": -6.37},
    {"id": "cadiz",            "nombre": "Cádiz",                  "lat": 36.53, "lon": -6.29},
    {"id": "cantabria",        "nombre": "Cantabria",              "lat": 43.46, "lon": -3.81},
    {"id": "castellon",        "nombre": "Castellón",              "lat": 39.99, "lon": -0.04},
    {"id": "ciudad_real",      "nombre": "Ciudad Real",            "lat": 38.99, "lon": -3.93},
    {"id": "cordoba",          "nombre": "Córdoba",                "lat": 37.89, "lon": -4.78},
    {"id": "a_coruna",         "nombre": "A Coruña",               "lat": 43.36, "lon": -8.41},
    {"id": "cuenca",           "nombre": "Cuenca",                 "lat": 40.07, "lon": -2.13},
    {"id": "girona",           "nombre": "Girona",                 "lat": 41.98, "lon":  2.82},
    {"id": "granada",          "nombre": "Granada",                "lat": 37.18, "lon": -3.60},
    {"id": "guadalajara",      "nombre": "Guadalajara",            "lat": 40.63, "lon": -3.16},
    {"id": "gipuzkoa",         "nombre": "Gipuzkoa",               "lat": 43.32, "lon": -1.98},
    {"id": "huelva",           "nombre": "Huelva",                 "lat": 37.26, "lon": -6.95},
    {"id": "huesca",           "nombre": "Huesca",                 "lat": 42.13, "lon": -0.41},
    {"id": "jaen",             "nombre": "Jaén",                   "lat": 37.77, "lon": -3.79},
    {"id": "leon",             "nombre": "León",                   "lat": 42.60, "lon": -5.57},
    {"id": "lleida",           "nombre": "Lleida",                 "lat": 41.62, "lon":  0.62},
    {"id": "lugo",             "nombre": "Lugo",                   "lat": 43.01, "lon": -7.56},
    {"id": "madrid",           "nombre": "Madrid",                 "lat": 40.42, "lon": -3.70},
    {"id": "malaga",           "nombre": "Málaga",                 "lat": 36.72, "lon": -4.42},
    {"id": "murcia",           "nombre": "Murcia",                 "lat": 37.99, "lon": -1.13},
    {"id": "navarra",          "nombre": "Navarra",                "lat": 42.81, "lon": -1.65},
    {"id": "ourense",          "nombre": "Ourense",                "lat": 42.34, "lon": -7.86},
    {"id": "palencia",         "nombre": "Palencia",               "lat": 42.01, "lon": -4.53},
    {"id": "las_palmas",       "nombre": "Las Palmas",             "lat": 28.12, "lon": -15.43},
    {"id": "pontevedra",       "nombre": "Pontevedra",             "lat": 42.43, "lon": -8.64},
    {"id": "la_rioja",         "nombre": "La Rioja",               "lat": 42.47, "lon": -2.45},
    {"id": "salamanca",        "nombre": "Salamanca",              "lat": 40.96, "lon": -5.66},
    {"id": "sc_tenerife",      "nombre": "Santa Cruz de Tenerife", "lat": 28.47, "lon": -16.25},
    {"id": "segovia",          "nombre": "Segovia",                "lat": 40.95, "lon": -4.12},
    {"id": "sevilla",          "nombre": "Sevilla",                "lat": 37.39, "lon": -5.99},
    {"id": "soria",            "nombre": "Soria",                  "lat": 41.76, "lon": -2.46},
    {"id": "tarragona",        "nombre": "Tarragona",              "lat": 41.12, "lon":  1.25},
    {"id": "teruel",           "nombre": "Teruel",                 "lat": 40.34, "lon": -1.11},
    {"id": "toledo",           "nombre": "Toledo",                 "lat": 39.86, "lon": -4.02},
    {"id": "valencia",         "nombre": "Valencia",               "lat": 39.47, "lon": -0.38},
    {"id": "valladolid",       "nombre": "Valladolid",             "lat": 41.65, "lon": -4.72},
    {"id": "bizkaia",          "nombre": "Bizkaia",                "lat": 43.26, "lon": -2.93},
    {"id": "zamora",           "nombre": "Zamora",                 "lat": 41.50, "lon": -5.74},
    {"id": "zaragoza",         "nombre": "Zaragoza",               "lat": 41.65, "lon": -0.89},
    {"id": "baleares",         "nombre": "Islas Baleares",         "lat": 39.57, "lon":  2.65},
    {"id": "ceuta",            "nombre": "Ceuta",                  "lat": 35.89, "lon": -5.31},
    {"id": "melilla",          "nombre": "Melilla",                "lat": 35.29, "lon": -2.94},
]


# --- UTILIDADES ---------------------------------------------------------------
def percentil(valores, p):
    """Percentil p (0-100) por interpolación lineal. Sin numpy."""
    datos = sorted(v for v in valores if v is not None)
    if not datos:
        return None
    if len(datos) == 1:
        return datos[0]
    k = (len(datos) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(datos) - 1)
    return datos[f] + (datos[c] - datos[f]) * (k - f)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def nivel_color(icc):
    if icc is None:        return "#888888", "Sin datos"
    if icc < 20:           return "#0066CC", "Calor suave"
    if icc < 40:           return "#44AA66", "Calor de verano"
    if icc < 60:           return "#FFCC44", "Canícula"
    if icc < 80:           return "#FF8822", "Canícula intensa"
    return "#CC2200", "Canícula extrema"


# --- DESCARGA DE DATOS --------------------------------------------------------
def cargar_json_previo():
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                prev = json.load(f)
            return {p["id"]: p for p in prev.get("provincias", [])}
        except Exception as e:
            print(f"⚠️ No se pudo leer el JSON previo: {e}")
    return {}


def descargar_forecast():
    """Una sola llamada multipunto para Tmáx/Tmín recientes de todas las provincias."""
    lats = ",".join(str(p["lat"]) for p in PROVINCIAS)
    lons = ",".join(str(p["lon"]) for p in PROVINCIAS)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lons}"
        "&daily=temperature_2m_max,temperature_2m_min"
        f"&timezone={TIMEZONE}&past_days={PAST_DAYS}&forecast_days=1"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    # Con multipunto, Open-Meteo devuelve una lista de objetos.
    return data if isinstance(data, list) else [data]


def descargar_ref_p90(prov):
    """P90 de Tmáx en verano (jul-ago) para una provincia. Solo si no está cacheado."""
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={prov['lat']}&longitude={prov['lon']}"
        f"&start_date={REF_YEARS[0]}&end_date={REF_YEARS[1]}"
        "&daily=temperature_2m_max"
        f"&timezone={TIMEZONE}"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    d = r.json().get("daily", {})
    fechas = d.get("time", [])
    tmaxs = d.get("temperature_2m_max", [])
    verano = [t for f, t in zip(fechas, tmaxs)
              if t is not None and f[5:7] in ("07", "08")]
    return round(percentil(verano, 90), 1) if verano else None


# --- CÁLCULO DEL ÍNDICE -------------------------------------------------------
def calcular_icc(tmax_hoy, tmin_hoy, ref_p90, dias_consecutivos):
    if tmax_hoy is None or ref_p90 is None:
        return None
    # Intensidad 0-50: anomalía de Tmáx respecto al P90 local (-4°C -> 0 ; +6°C -> 50)
    anom = tmax_hoy - ref_p90
    intensidad = clamp((anom + 4) / 10.0, 0, 1) * 50
    # Persistencia 0-30: 5+ días consecutivos -> máximo
    persistencia = clamp(dias_consecutivos / 5.0, 0, 1) * 30
    # Noche cálida 0-20: Tmín 18°C -> 0 ; 25°C -> 20
    noche = 0
    if tmin_hoy is not None:
        noche = clamp((tmin_hoy - 18) / 7.0, 0, 1) * 20
    return round(intensidad + persistencia + noche)


def dias_calor_consecutivos(serie_tmax, fechas, ref_p90):
    """Días consecutivos (terminando en el más reciente) con Tmáx >= P90 local."""
    if ref_p90 is None:
        return 0
    n = 0
    for t in reversed(serie_tmax):
        if t is not None and t >= ref_p90:
            n += 1
        else:
            break
    return n


# --- PROCESO PRINCIPAL --------------------------------------------------------
def main():
    print("☀️ Calculando el Índice de Calor Canicular (ICC)...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    previo = cargar_json_previo()
    forecast = descargar_forecast()
    hoy_iso = date.today().isoformat()

    resultado = []
    iccs = []

    for i, prov in enumerate(PROVINCIAS):
        bloque = forecast[i] if i < len(forecast) else {}
        daily = bloque.get("daily", {})
        fechas = daily.get("time", [])
        tmaxs = daily.get("temperature_2m_max", [])
        tmins = daily.get("temperature_2m_min", [])

        tmax_hoy = tmaxs[-1] if tmaxs else None
        tmin_hoy = tmins[-1] if tmins else None

        # Referencia climática: cacheada o se descarga una vez
        prev = previo.get(prov["id"], {})
        ref_p90 = prev.get("ref_p90")
        if ref_p90 is None:
            try:
                print(f"  · Descargando referencia climática de {prov['nombre']}...")
                ref_p90 = descargar_ref_p90(prov)
                time.sleep(PAUSA_API)
            except Exception as e:
                print(f"  ⚠️ Sin referencia para {prov['nombre']}: {e}")
                ref_p90 = None

        # Historico incremental
        historico = prev.get("historico", {})
        if tmax_hoy is not None:
            historico[hoy_iso] = {"tmax": round(tmax_hoy, 1),
                                  "tmin": round(tmin_hoy, 1) if tmin_hoy is not None else None}
        # Recorta el historico
        if len(historico) > HIST_MAX_DIAS:
            for k in sorted(historico.keys())[:-HIST_MAX_DIAS]:
                del historico[k]

        dias = dias_calor_consecutivos(tmaxs, fechas, ref_p90)
        icc = calcular_icc(tmax_hoy, tmin_hoy, ref_p90, dias)
        color, nivel = nivel_color(icc)
        if icc is not None:
            iccs.append(icc)

        resultado.append({
            "id": prov["id"],
            "nombre": prov["nombre"],
            "lat": prov["lat"],
            "lon": prov["lon"],
            "ref_p90": ref_p90,
            "tmax_hoy": round(tmax_hoy, 1) if tmax_hoy is not None else None,
            "tmin_hoy": round(tmin_hoy, 1) if tmin_hoy is not None else None,
            "dias_consecutivos": dias,
            "noche_tropical": bool(tmin_hoy is not None and tmin_hoy >= 20),
            "icc": icc,
            "nivel": nivel,
            "color": color,
            "historico": historico,
        })

    icc_media = round(sum(iccs) / len(iccs)) if iccs else None
    color_med, nivel_med = nivel_color(icc_media)
    ahora = datetime.now()

    salida = {
        "ultima_actualizacion": ahora.isoformat(),
        "fecha_legible": ahora.strftime("%d/%m/%Y a las %H:%M"),
        "fuente": "Open-Meteo (Forecast & Archive API)",
        "metodologia": ("Índice propio de intensidad de calor estival (0-100): "
                        "intensidad (anomalía de Tmáx sobre el P90 climático local) + "
                        "persistencia (días consecutivos de calor) + noche cálida (Tmín). "
                        "No es una declaración oficial de AEMET."),
        "temporada": ahora.year,
        "total_provincias": len(resultado),
        "icc_media": icc_media,
        "nivel_media": nivel_med,
        "color_media": color_med,
        "provincias": resultado,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"✓ {len(resultado)} provincias procesadas. ICC medio nacional: {icc_media} ({nivel_med})")


if __name__ == "__main__":
    main()
