import requests
import json
import os
from datetime import datetime, timedelta

# ============================================================
# OBJETIVOS PARIS 2030 POR PAÍS (reducción % respecto año base)
# Fuente: UNFCCC NDC Registry
# Formato: {"iso": reduccion_porcentaje, "anio_base": año, "tipo": "absoluto"/"intensidad"}
# ============================================================
OBJETIVOS_PARIS = {
    "CHN": {"objetivo_gt": 10.5,  "anio_meta": 2030, "descripcion": "Pico antes de 2030"},
    "USA": {"objetivo_gt": 2.8,   "anio_meta": 2030, "descripcion": "-50% respecto 2005"},
    "IND": {"objetivo_gt": 3.2,   "anio_meta": 2030, "descripcion": "-45% intensidad PIB"},
    "RUS": {"objetivo_gt": 1.8,   "anio_meta": 2030, "descripcion": "-30% respecto 1990"},
    "JPN": {"objetivo_gt": 0.77,  "anio_meta": 2030, "descripcion": "-46% respecto 2013"},
    "DEU": {"objetivo_gt": 0.27,  "anio_meta": 2030, "descripcion": "-65% respecto 1990"},
    "KOR": {"objetivo_gt": 0.33,  "anio_meta": 2030, "descripcion": "-40% respecto 2018"},
    "CAN": {"objetivo_gt": 0.35,  "anio_meta": 2030, "descripcion": "-45% respecto 2005"},
    "GBR": {"objetivo_gt": 0.18,  "anio_meta": 2030, "descripcion": "-78% respecto 1990"},
    "SAU": {"objetivo_gt": 0.52,  "anio_meta": 2030, "descripcion": "-278 MtCO2 respecto BAU"},
    "IRN": {"objetivo_gt": 0.36,  "anio_meta": 2030, "descripcion": "-12% respecto BAU"},
    "AUS": {"objetivo_gt": 0.34,  "anio_meta": 2030, "descripcion": "-43% respecto 2005"},
    "BRA": {"objetivo_gt": 1.0,   "anio_meta": 2030, "descripcion": "-53% respecto 2005"},
    "IDN": {"objetivo_gt": 1.4,   "anio_meta": 2030, "descripcion": "-32% respecto BAU"},
    "TUR": {"objetivo_gt": 0.56,  "anio_meta": 2030, "descripcion": "-21% respecto BAU"},
    "MEX": {"objetivo_gt": 0.51,  "anio_meta": 2030, "descripcion": "-35% respecto BAU"},
    "ZAF": {"objetivo_gt": 0.44,  "anio_meta": 2030, "descripcion": "350-420 MtCO2 en 2025-2030"},
    "POL": {"objetivo_gt": 0.18,  "anio_meta": 2030, "descripcion": "-55% respecto 1990 (EU)"},
    "THA": {"objetivo_gt": 0.22,  "anio_meta": 2030, "descripcion": "-30% respecto BAU"},
    "ARG": {"objetivo_gt": 0.35,  "anio_meta": 2030, "descripcion": "349 MtCO2 en 2030"},
    "ESP": {"objetivo_gt": 0.13,  "anio_meta": 2030, "descripcion": "-55% respecto 1990 (EU)"},
    "FRA": {"objetivo_gt": 0.10,  "anio_meta": 2030, "descripcion": "-55% respecto 1990 (EU)"},
    "ITA": {"objetivo_gt": 0.11,  "anio_meta": 2030, "descripcion": "-55% respecto 1990 (EU)"},
    "UKR": {"objetivo_gt": 0.30,  "anio_meta": 2030, "descripcion": "-65% respecto 1990"},
    "KAZ": {"objetivo_gt": 0.24,  "anio_meta": 2030, "descripcion": "-15% respecto 1990"},
    "VNM": {"objetivo_gt": 0.26,  "anio_meta": 2030, "descripcion": "-27% respecto BAU"},
    "EGY": {"objetivo_gt": 0.22,  "anio_meta": 2030, "descripcion": "-33% respecto BAU"},
    "PAK": {"objetivo_gt": 0.18,  "anio_meta": 2030, "descripcion": "-50% respecto BAU"},
    "MYS": {"objetivo_gt": 0.13,  "anio_meta": 2030, "descripcion": "-45% intensidad PIB"},
    "NGA": {"objetivo_gt": 0.19,  "anio_meta": 2030, "descripcion": "-47% respecto BAU"},
}

# ============================================================
# DATOS ESTÁTICOS: emisiones 2023 por país (GtCO2)
# Fuente: Global Carbon Project 2024
# Para países no cubiertos por Carbon Monitor
# ============================================================
EMISIONES_2023 = {
    "CHN": 11.47, "USA": 4.92, "IND": 2.84, "RUS": 1.77, "JPN": 1.02,
    "DEU": 0.66,  "IRN": 0.74, "KOR": 0.61, "SAU": 0.72, "CAN": 0.55,
    "BRA": 0.44,  "ZAF": 0.45, "AUS": 0.38, "IDN": 0.73, "TUR": 0.44,
    "MEX": 0.38,  "GBR": 0.32, "ITA": 0.29, "FRA": 0.28, "POL": 0.30,
    "ESP": 0.22,  "ARG": 0.19, "THA": 0.25, "EGY": 0.24, "PAK": 0.22,
    "UKR": 0.18,  "KAZ": 0.22, "VNM": 0.32, "MYS": 0.25, "NGA": 0.12,
    "COL": 0.09,  "CHL": 0.08, "PER": 0.06, "VEN": 0.07, "DZA": 0.15,
    "MAR": 0.07,  "GHA": 0.03, "ETH": 0.02, "TZA": 0.02, "AGO": 0.06,
    "TUN": 0.04,  "SDN": 0.03, "MOZ": 0.01, "KEN": 0.02, "CMR": 0.01,
    "NOR": 0.04,  "SWE": 0.04, "FIN": 0.03, "DNK": 0.03, "NLD": 0.14,
    "BEL": 0.09,  "AUT": 0.06, "CHE": 0.04, "CZE": 0.09, "ROU": 0.07,
    "HUN": 0.04,  "GRC": 0.05, "PRT": 0.05, "SVK": 0.03, "BGR": 0.04,
    "SRB": 0.05,  "HRV": 0.02, "BLR": 0.06, "AZE": 0.05, "UZB": 0.12,
    "TKM": 0.08,  "SGP": 0.21, "HKG": 0.06, "TWN": 0.27, "PHL": 0.15,
    "MMR": 0.04,  "BGD": 0.10, "LKA": 0.02, "NPL": 0.01, "KHM": 0.02,
    "LAO": 0.02,  "MNG": 0.05, "PRK": 0.07, "ISR": 0.07, "IRQ": 0.19,
    "SYR": 0.03,  "JOR": 0.03, "LBN": 0.02, "OMN": 0.07, "ARE": 0.22,
    "KWT": 0.09,  "QAT": 0.10, "BHR": 0.03, "YEM": 0.02, "AFG": 0.01,
    "NZL": 0.03,  "PNG": 0.02, "ECU": 0.04, "BOL": 0.03, "PRY": 0.01,
    "URY": 0.02,  "GTM": 0.02, "CUB": 0.03, "DOM": 0.03, "SLV": 0.01,
}

# Población 2023 (millones) para cálculo per cápita
POBLACION_2023 = {
    "CHN": 1412, "USA": 335,  "IND": 1429, "RUS": 144,  "JPN": 124,
    "DEU": 84,   "IRN": 89,   "KOR": 52,   "SAU": 37,   "CAN": 40,
    "BRA": 215,  "ZAF": 60,   "AUS": 26,   "IDN": 277,  "TUR": 85,
    "MEX": 128,  "GBR": 68,   "ITA": 59,   "FRA": 68,   "POL": 38,
    "ESP": 47,   "ARG": 46,   "THA": 72,   "EGY": 106,  "PAK": 231,
    "UKR": 44,   "KAZ": 19,   "VNM": 98,   "MYS": 33,   "NGA": 223,
    "COL": 52,   "CHL": 19,   "PER": 33,   "VEN": 29,   "DZA": 45,
    "MAR": 38,   "GHA": 33,   "ETH": 126,  "TZA": 64,   "AGO": 35,
    "TUN": 12,   "SDN": 48,   "MOZ": 33,   "KEN": 55,   "CMR": 28,
    "NOR": 5.5,  "SWE": 10.5, "FIN": 5.5,  "DNK": 5.9,  "NLD": 17.9,
    "BEL": 11.6, "AUT": 9.1,  "CHE": 8.7,  "CZE": 10.9, "ROU": 19.0,
    "HUN": 9.7,  "GRC": 10.4, "PRT": 10.2, "SVK": 5.5,  "BGR": 6.5,
    "SRB": 6.8,  "HRV": 3.9,  "BLR": 9.4,  "AZE": 10.2, "UZB": 36.0,
    "TKM": 6.1,  "SGP": 5.9,  "HKG": 7.5,  "TWN": 23.6, "PHL": 115,
    "MMR": 54,   "BGD": 170,  "LKA": 22,   "NPL": 30,   "KHM": 17,
    "LAO": 7.4,  "MNG": 3.4,  "PRK": 26,   "ISR": 9.7,  "IRQ": 42,
    "SYR": 22,   "JOR": 10.2, "LBN": 5.5,  "OMN": 4.6,  "ARE": 9.9,
    "KWT": 4.3,  "QAT": 2.8,  "BHR": 1.5,  "YEM": 35,   "AFG": 41,
    "NZL": 5.1,  "PNG": 10.3, "ECU": 18,   "BOL": 12,   "PRY": 7.4,
    "URY": 3.5,  "GTM": 18,   "CUB": 11,   "DOM": 11,   "SLV": 6.3,
}

# Nombres de países en español
NOMBRES_PAISES = {
    "CHN": "China", "USA": "Estados Unidos", "IND": "India",
    "RUS": "Rusia", "JPN": "Japón", "DEU": "Alemania",
    "IRN": "Irán", "KOR": "Corea del Sur", "SAU": "Arabia Saudí",
    "CAN": "Canadá", "BRA": "Brasil", "ZAF": "Sudáfrica",
    "AUS": "Australia", "IDN": "Indonesia", "TUR": "Türkiye",
    "MEX": "México", "GBR": "Reino Unido", "ITA": "Italia",
    "FRA": "Francia", "POL": "Polonia", "ESP": "España",
    "ARG": "Argentina", "THA": "Tailandia", "EGY": "Egipto",
    "PAK": "Pakistán", "UKR": "Ucrania", "KAZ": "Kazajistán",
    "VNM": "Vietnam", "MYS": "Malasia", "NGA": "Nigeria",
    "COL": "Colombia", "CHL": "Chile", "PER": "Perú",
    "VEN": "Venezuela", "DZA": "Argelia", "MAR": "Marruecos",
    "GHA": "Ghana", "ETH": "Etiopía", "TZA": "Tanzania",
    "AGO": "Angola", "TUN": "Túnez", "SDN": "Sudán",
    "MOZ": "Mozambique", "KEN": "Kenia", "CMR": "Camerún",
    "NOR": "Noruega", "SWE": "Suecia", "FIN": "Finlandia",
    "DNK": "Dinamarca", "NLD": "Países Bajos", "BEL": "Bélgica",
    "AUT": "Austria", "CHE": "Suiza", "CZE": "República Checa",
    "ROU": "Rumanía", "HUN": "Hungría", "GRC": "Grecia",
    "PRT": "Portugal", "SVK": "Eslovaquia", "BGR": "Bulgaria",
    "SRB": "Serbia", "HRV": "Croacia", "BLR": "Bielorrusia",
    "AZE": "Azerbaiyán", "UZB": "Uzbekistán", "TKM": "Turkmenistán",
    "SGP": "Singapur", "HKG": "Hong Kong", "TWN": "Taiwán",
    "PHL": "Filipinas", "MMR": "Myanmar", "BGD": "Bangladesh",
    "LKA": "Sri Lanka", "NPL": "Nepal", "KHM": "Camboya",
    "LAO": "Laos", "MNG": "Mongolia", "PRK": "Corea del Norte",
    "ISR": "Israel", "IRQ": "Irak", "SYR": "Siria",
    "JOR": "Jordania", "LBN": "Líbano", "OMN": "Omán",
    "ARE": "Emiratos Árabes", "KWT": "Kuwait", "QAT": "Qatar",
    "BHR": "Baréin", "YEM": "Yemen", "AFG": "Afganistán",
    "NZL": "Nueva Zelanda", "PNG": "Papúa Nueva Guinea",
    "ECU": "Ecuador", "BOL": "Bolivia", "PRY": "Paraguay",
    "URY": "Uruguay", "GTM": "Guatemala", "CUB": "Cuba",
    "DOM": "Rep. Dominicana", "SLV": "El Salvador",
}

def obtener_datos_carbon_monitor():
    """
    Obtiene datos recientes de Carbon Monitor API.
    Cubre ~30 grandes emisores con datos diarios.
    Devuelve dict {iso3: gt_co2_diario}
    """
    hoy = datetime.now()
    fecha_reciente = (hoy - timedelta(days=10)).strftime("%Y-%m-%d")
    fecha_anterior = (hoy - timedelta(days=375)).strftime("%Y-%m-%d")

    resultados_actual   = {}
    resultados_anterior = {}

    # Mapeo Carbon Monitor -> ISO3
    CM_PAISES = {
        "China": "CHN", "US": "USA", "India": "IND",
        "Russia": "RUS", "Japan": "JPN", "Germany": "DEU",
        "South Korea": "KOR", "Canada": "CAN", "Brazil": "BRA",
        "South Africa": "ZAF", "Australia": "AUS", "UK": "GBR",
        "France": "FRA", "Italy": "ITA", "Spain": "ESP",
        "Poland": "POL", "Turkey": "TUR", "Mexico": "MEX",
        "EU27 & UK": None,  # agregado, lo ignoramos
        "WORLD": None,
        "ROW": None,
    }

    try:
        # Datos recientes
        url = f"https://api.carbonmonitor.org/data?dateFrom={fecha_reciente}&dateTo={fecha_reciente}&countries=all&sectors=Total"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()

        for entry in data.get("carbonMonitorData", []):
            pais_cm  = entry.get("country", "")
            iso3     = CM_PAISES.get(pais_cm)
            valor_mt = entry.get("value", 0) or 0  # en MtCO2/día
            if iso3 and valor_mt:
                resultados_actual[iso3] = round(valor_mt * 365 / 1000, 3)  # convertir a GtCO2/año

        print(f"  Carbon Monitor actual: {len(resultados_actual)} países")

    except Exception as e:
        print(f"  Error Carbon Monitor actual: {e}")

    try:
        # Datos año anterior (misma fecha)
        url_ant = f"https://api.carbonmonitor.org/data?dateFrom={fecha_anterior}&dateTo={fecha_anterior}&countries=all&sectors=Total"
        r2 = requests.get(url_ant, timeout=20)
        r2.raise_for_status()
        data2 = r2.json()

        for entry in data2.get("carbonMonitorData", []):
            pais_cm  = entry.get("country", "")
            iso3     = CM_PAISES.get(pais_cm)
            valor_mt = entry.get("value", 0) or 0
            if iso3 and valor_mt:
                resultados_anterior[iso3] = round(valor_mt * 365 / 1000, 3)

        print(f"  Carbon Monitor año anterior: {len(resultados_anterior)} países")

    except Exception as e:
        print(f"  Error Carbon Monitor año anterior: {e}")

    return resultados_actual, resultados_anterior

def clasificar_desviacion(emision_actual, objetivo_paris):
    """
    Calcula la desviación respecto al objetivo de París 2030.
    Positivo = emite MÁS de lo comprometido. Negativo = emite menos.
    """
    if objetivo_paris is None or emision_actual is None:
        return None, None, "#888888"
    desviacion = round(emision_actual - objetivo_paris, 3)
    pct = round((desviacion / objetivo_paris) * 100, 1) if objetivo_paris > 0 else None

    if desviacion <= -0.05:
        color = "#0066CC"    # muy por debajo del objetivo (bien)
    elif desviacion < 0:
        color = "#44AA66"    # por debajo del objetivo (bien)
    elif desviacion < objetivo_paris * 0.1:
        color = "#FFCC44"    # ligeramente por encima
    elif desviacion < objetivo_paris * 0.3:
        color = "#FF8822"    # claramente por encima
    else:
        color = "#CC2200"    # muy por encima del objetivo

    return desviacion, pct, color

def clasificar_per_capita(tco2_per_capita):
    """Clasifica las emisiones per cápita."""
    if tco2_per_capita is None:
        return "#888888", "Sin datos"
    elif tco2_per_capita < 2:
        return "#0066CC", "Muy bajas"
    elif tco2_per_capita < 5:
        return "#44AA66", "Bajas"
    elif tco2_per_capita < 8:
        return "#FFCC44", "Medias"
    elif tco2_per_capita < 12:
        return "#FF8822", "Altas"
    elif tco2_per_capita < 20:
        return "#CC2200", "Muy altas"
    else:
        return "#8800AA", "Extremadamente altas"

def generar_json():
    print(f"\n{'='*60}")
    print(f"Actualizando emisiones CO2 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    print("Obteniendo datos Carbon Monitor...")
    cm_actual, cm_anterior = obtener_datos_carbon_monitor()

    resultados = []

    for iso3, nombre in NOMBRES_PAISES.items():
        # Emisiones actuales: Carbon Monitor si disponible, sino datos 2023
        emision_actual = cm_actual.get(iso3) or EMISIONES_2023.get(iso3)
        fuente_actual  = "Carbon Monitor (tiempo real)" if iso3 in cm_actual else "Global Carbon Project 2023"

        # Emisiones año anterior: Carbon Monitor si disponible, sino datos 2023
        emision_anterior = cm_anterior.get(iso3) or EMISIONES_2023.get(iso3)

        # Diferencia anual
        diferencia_anual = None
        if emision_actual is not None and emision_anterior is not None:
            diferencia_anual = round(emision_actual - emision_anterior, 3)

        # Objetivo París
        paris = OBJETIVOS_PARIS.get(iso3)
        objetivo_gt = paris["objetivo_gt"] if paris else None
        descripcion_paris = paris["descripcion"] if paris else "Sin objetivo registrado"

        # Desviación respecto a París
        desviacion_gt, desviacion_pct, color = clasificar_desviacion(emision_actual, objetivo_gt)

        # Emisiones per cápita (tCO2/habitante/año)
        poblacion = POBLACION_2023.get(iso3)
        per_capita = None
        if emision_actual is not None and poblacion:
            per_capita = round((emision_actual * 1000) / poblacion, 2)  # Gt -> Mt -> tCO2
        color_pc, etiqueta_pc = clasificar_per_capita(per_capita)

        resultados.append({
            "iso3":             iso3,
            "nombre":           nombre,
            "emision_actual_gt":  emision_actual,
            "emision_anterior_gt": emision_anterior,
            "diferencia_anual_gt": diferencia_anual,
            "fuente_actual":    fuente_actual,
            "objetivo_paris_gt": objetivo_gt,
            "descripcion_paris": descripcion_paris,
            "desviacion_gt":    desviacion_gt,
            "desviacion_pct":   desviacion_pct,
            "color":            color,
            "per_capita_tco2":  per_capita,
            "color_per_capita": color_pc,
            "etiqueta_per_capita": etiqueta_pc,
            "poblacion_m":      poblacion,
        })

        if emision_actual:
            print(f"  {nombre}: {emision_actual} Gt | PC: {per_capita} t | París: {desviacion_gt} Gt")

    # Ordenar por emisión total descendente
    resultados.sort(key=lambda x: x["emision_actual_gt"] or 0, reverse=True)

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion":    datetime.now().isoformat(),
        "fecha_legible":           datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_paises":            len(resultados),
        "paises_con_datos":        sum(1 for r in resultados if r["emision_actual_gt"]),
        "paises_carbon_monitor":   len(cm_actual),
        "emisiones_globales_gt":   round(sum(r["emision_actual_gt"] for r in resultados if r["emision_actual_gt"]), 2),
        "fuentes":                 "Carbon Monitor (tiempo real) + Global Carbon Project 2024",
        "paises":                  resultados
    }

    with open("docs/emisiones_co2.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON guardado en docs/emisiones_co2.json")
    print(f"✓ {output['paises_con_datos']} países con datos")
    print(f"✓ {output['paises_carbon_monitor']} países con datos en tiempo real\n")

if __name__ == "__main__":
    generar_json()
