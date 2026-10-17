#!/usr/bin/env python3
"""
Partes de prensa provinciales · Observatorio climático (calentamientoglobal.es).

Cada día, para cada una de las 52 provincias, escribe un parte con cinco ángulos
fijos, cada uno alimentado por una «sonda» que lee un dataset del observatorio y
busca lo más citable de ese día. Nunca sale vacío: si no hay récord, hay ranking,
comparación con lo normal, con el año pasado o con el inicio de la serie.

  ayer        lo observado: lluvia por estación/municipio (AEMET), noches tropicales
              (AEMET), firma climática, canícula, mar en la boya, aire, y los
              hallazgos del detector (hallazgos.json) de esa provincia
  semana      lo que viene: predicción AEMET por municipio frente a su normal 1991-2020
  agua        embalse a embalse (fichas, serie desde 1988), aforos oficiales, GloFAS,
              nivel del mar
  municipios  otoño por municipio (ERA5), año hidrológico por municipio (1981),
              proyección 2050
  impacto     avisos acumulados (AEMET), mortalidad por calor (ISCIII), coste de
              desastres (Consorcio), incendios (FIRMS), días de más de 32 °C

Lee (todo en docs/):   provincias/<slug>.json, prediccion/NN.json, lluvias_municipios.json,
  temperaturas_nocturnas.json, embalses/fichas/*.json, embalses/*.json, caudal/{hoy,red,aforos}.json,
  otonio_municipios.json, municipios_mapa.json, municipios.json, avisos_historico.json,
  calor_mortalidad.json, dias32.json, viento.json, prensa/hallazgos.json
Escribe:  prensa/partes/NN.json (el parte de hoy), prensa/partes/archivo/AAAA-MM-DD.json (las 52, compacto),
  prensa/partes/index.json (titular del día de cada provincia + coincidencias nacionales)

Nada se envía solo: el parte propone, David decide.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
PARTES = DOCS / "prensa" / "partes"
HOY = date.today()
AYER = HOY - timedelta(days=1)
AHORA = datetime.now(timezone.utc).replace(microsecond=0)

sys.path.insert(0, str(RAIZ / "scripts"))
from hallazgos_prensa import PROVINCIAS, MESES, f1, fecha_larga, fecha_dia, num  # noqa: E402

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# slug de la ficha (/cambio-climatico-en-…/) → fichero de docs/provincias/
SLUG_PROV_JSON = {"a-coruna": "a_coruna", "santa-cruz-de-tenerife": "sc_tenerife", "ciudad-real": "ciudad_real",
                  "la-rioja": "la_rioja", "las-palmas": "las_palmas"}

PESO = {"record": 100, "extremo": 80, "prevision": 70, "comparacion": 55, "cifra": 35}


def leer(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def leer_o(p: Path, d=None):
    try:
        return leer(p)
    except Exception:
        return d


def dist_km(a, b, c, d):
    r = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def dia_semana(iso: str) -> str:
    d = date.fromisoformat(iso)
    if d == HOY:
        return "hoy"
    if d == HOY + timedelta(days=1):
        return "mañana"
    return "el " + DIAS_SEMANA[d.weekday()]


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def pct_txt(v) -> str:
    return f"{f1(v)} %"


# Población por provincia (INE, padrón a 1-1-2024, en miles, redondeada). Solo para dimensionar alertas.
POBLACION_MILES = {
    "01": 338, "02": 388, "03": 1990, "04": 755, "05": 161, "06": 666, "07": 1231, "08": 5826, "09": 360, "10": 388,
    "11": 1261, "12": 603, "13": 490, "14": 775, "15": 1129, "16": 199, "17": 814, "18": 937, "19": 282, "20": 733,
    "21": 539, "22": 230, "23": 620, "24": 450, "25": 453, "26": 326, "27": 324, "28": 7002, "29": 1790, "30": 1576,
    "31": 679, "32": 304, "33": 1010, "34": 158, "35": 1145, "36": 951, "37": 328, "38": 1072, "39": 592, "40": 156,
    "41": 1965, "42": 90, "43": 870, "44": 135, "45": 740, "46": 2690, "47": 523, "48": 1160, "49": 166, "50": 996,
    "51": 83, "52": 86,
}


def signo_txt(v):
    return ("+" if (v or 0) >= 0 else "−") + f1(abs(v or 0))


def indice_desplazamiento(fc: dict):
    """(nivel 1-5, ratio, titular, dato) o None. Basado en firma_climatica.json."""
    if not fc or fc.get("tmax") is None or fc.get("lado") != "calor":
        return None
    cap = fc.get("nombre", "")
    if fc.get("sin_precedente"):
        return (5, 99.0, f"Los {f1(fc['tmax'])} °C previstos hoy en {cap} no tienen precedente para estas fechas en 1951-1980: el máximo entonces fue {f1(fc['max_antes'])} °C",
                f"nivel 5 (sin precedente) · máxima prevista {f1(fc['tmax'])} °C · máximo de 1951-1980 para estas fechas {f1(fc['max_antes'])} °C")
    ra, rh = num(fc.get("retorno_antes")), num(fc.get("retorno_ahora"))
    if not ra or not rh or ra < 1 or rh <= 0:
        return None
    ratio = ra / rh
    if ratio < 2:
        return None
    nivel = min(5, int(ratio))
    veces = "más del doble de" if nivel == 2 else f"al menos {nivel} veces más"
    return (nivel, round(ratio, 1),
            f"El calor previsto hoy en {cap} ({f1(fc['tmax'])} °C) es {veces} frecuente que en 1951-1980 (nivel {nivel} de 5)",
            f"un día así ocurría cada {f1(ra)} años en 1951-1980 y ahora cada {f1(rh)} · ×{f1(ratio)} · nivel {nivel} de 5")


class Parte:
    def __init__(self, cod: str, nombre: str, slug: str):
        self.cod, self.nombre, self.slug = cod, nombre, slug
        self.items: list[dict] = []
        self.cifras: list[dict] = []
        self.errores: list[str] = []

    def add(self, angulo: str, clase: str, titular: str, dato: str, fuente: str, metodo: str,
            contexto=None, limites=None, citabilidad="alta", fecha_dato=None, provisional=False,
            pagina=None, fuerza_extra=0.0, csv=None, grafico=None):
        fecha_dato = fecha_dato or AYER.isoformat()
        edad = (HOY - date.fromisoformat(fecha_dato[:10])).days
        frescura = max(0.4, 1 - 0.06 * max(0, edad - 1))
        fuerza = PESO[clase] * frescura * (1.0 if citabilidad == "alta" else 0.85 if citabilidad == "media" else 0.5) + fuerza_extra
        h = {"id": slugify(f"{self.cod}-{angulo}-{titular[:70]}-{fecha_dato}"), "angulo": angulo, "clase": clase,
             "titular": titular, "dato": dato, "contexto": contexto or [], "fuente": fuente, "metodo": metodo,
             "limites": limites or [], "citabilidad": citabilidad, "fecha_dato": fecha_dato, "edad_dias": edad,
             "provisional": provisional, "pagina": pagina, "fuerza": round(fuerza, 1), "csv": csv, "grafico": grafico,
             "requiere_revision": any("COMPROBAR" in l for l in (limites or []))}
        self.items.append(h)
        return h

    def cifra(self, etiqueta: str, valor: str, nota: str = "", fuente: str = ""):
        self.cifras.append({"etiqueta": etiqueta, "valor": valor, "nota": nota, "fuente": fuente})


# ----------------------------------------------------------------------------
# datos compartidos (se cargan una vez)
# ----------------------------------------------------------------------------
class Datos:
    def __init__(self):
        self.capitales = {c["provincia"]: c for c in leer_o(DOCS / "viento.json", {"capitales": []})["capitales"]}
        self.lluvias = leer_o(DOCS / "lluvias_municipios.json", {})
        self.nocturnas = leer_o(DOCS / "temperaturas_nocturnas.json", {})
        self.otonio = leer_o(DOCS / "otonio_municipios.json", {})
        self.mun_mapa = leer_o(DOCS / "municipios_mapa.json", {})
        self.mun2050 = leer_o(DOCS / "municipios.json", {"items": []})
        self.avisos_h = leer_o(DOCS / "avisos_historico.json", {"dias": {}})
        self.calor = leer_o(DOCS / "calor_mortalidad.json", {})
        self.dias32 = leer_o(DOCS / "dias32.json", {"provincias": []})
        self.embalses_nac = leer_o(DOCS / "embalses.json", {})
        self.hallazgos = leer_o(DOCS / "prensa" / "hallazgos.json", {"enviables": [], "locales": []})
        self.red = leer_o(DOCS / "caudal" / "red.json", {"puntos": []})
        self.hoy_caudal = leer_o(DOCS / "caudal" / "hoy.json", {})
        self.aforos = leer_o(DOCS / "caudal" / "aforos.json", {"estaciones": []})
        self.fichas = []
        for fp in glob.glob(str(DOCS / "embalses" / "fichas" / "*.json")):
            f = leer_o(Path(fp))
            if f and f.get("provincia"):
                self.fichas.append(f)
        # percentiles GloFAS de hoy por punto
        self.pct_hoy = {}
        try:
            import base64
            b = base64.b64decode(self.hoy_caudal["pct"])
            n_dias, hoy_i = int(self.hoy_caudal["n"]), int(self.hoy_caudal["hoy"])
            for p in self.red["puntos"]:
                i = int(p["id"]) * n_dias + hoy_i
                if i < len(b) and b[i] != 255:
                    self.pct_hoy[int(p["id"])] = b[i]
        except Exception:
            pass

    def provincia_mas_cercana(self, lat, lon, max_km=70):
        mejor, dm = None, 1e9
        for prov, c in self.capitales.items():
            d = dist_km(lat, lon, c["lat"], c["lon"])
            if d < dm:
                mejor, dm = prov, d
        return mejor if dm <= max_km else None


# ----------------------------------------------------------------------------
# sondas
# ----------------------------------------------------------------------------
def sonda_ayer(P: Parte, D: Datos, pj: dict):
    cod = P.cod
    # --- lluvia por municipio (AEMET observación) ---------------------------------
    L = D.lluvias
    if L.get("municipios"):
        fecha = L.get("fecha", AYER.isoformat())
        mios = {k: v for k, v in L["municipios"].items() if k.startswith(cod)}
        pv = (L.get("provincias") or {}).get(cod, {})
        if mios:
            top = max(mios.values(), key=lambda m: num(m.get("dia"), 0) or 0)
            mm = num(top.get("dia"), 0) or 0
            fuente = L.get("fuente", "AEMET OpenData · observación convencional")
            metodo = "Suma de la precipitación horaria de la estación AEMET más próxima a cada municipio, de 0 a 24 h hora local."
            if mm >= 10:
                P.add("ayer", "extremo" if mm >= 30 else "comparacion",
                      f"{top['n']} recogió ayer {f1(mm)} mm, lo más llovido de la provincia de {P.nombre}",
                      f"{f1(mm)} mm en la estación {top.get('est')} · {pv.get('mojadas', '?')} de {pv.get('est', '?')} estaciones de la provincia con lluvia · semana: {f1(num(pv.get('sem'), 0))} mm",
                      fuente, metodo, fecha_dato=fecha,
                      contexto=[f"Estaciones de la provincia con lluvia ayer: {pv.get('mojadas', 0)} de {pv.get('est', 0)}."],
                      limites=["Dato de la estación AEMET más cercana al municipio, no un pluviómetro en cada pueblo."],
                      pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
            else:
                seco = [m for m in mios.values() if (num(m.get("racha"), 0) or 0) >= 10]
                racha_max = max(mios.values(), key=lambda m: num(m.get("racha"), 0) or 0)
                r = int(num(racha_max.get("racha"), 0) or 0)
                lp = pj.get("indicadores", {}).get("lluvias", {})
                if r >= 10:
                    P.add("ayer", "comparacion",
                          f"{racha_max['n']} lleva {r} días sin lluvia apreciable; la provincia de {P.nombre} suma {f1(num(pv.get('sem'), 0))} mm esta semana",
                          f"{r} días seguidos con menos de 1 mm en {racha_max['n']} · {len(seco)} municipios con 10 o más días secos · semana {f1(num(pv.get('sem'), 0))} mm"
                          + (f" ({f1(lp['anomalia_semana_pct'])} % frente a lo normal)" if lp.get("anomalia_semana_pct") is not None else ""),
                          fuente, metodo, fecha_dato=fecha, citabilidad="alta",
                          contexto=[f"Acumulado de 2026 en la provincia: {f1(lp['mm_anual'])} mm, {f1(lp['anomalia_anual_pct'])} % frente a lo normal hasta la fecha ({f1(lp['media_hasta_hoy_mm'])} mm)."] if lp.get("mm_anual") is not None else [],
                          pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
                elif lp.get("anomalia_semana_pct") is not None:
                    P.add("ayer", "cifra",
                          f"Sin lluvia ayer en {P.nombre}: la semana deja {f1(num(pv.get('sem'), 0))} mm, un {abs(int(lp['anomalia_semana_pct']))} % {'menos' if lp['anomalia_semana_pct'] < 0 else 'más'} de lo normal",
                          f"{pv.get('mojadas', 0)} de {pv.get('est', 0)} estaciones con lluvia · semana {f1(num(pv.get('sem'), 0))} mm · 2026: {f1(lp.get('mm_anual', 0))} mm ({f1(lp.get('anomalia_anual_pct', 0))} % frente a lo normal)",
                          fuente, metodo, fecha_dato=fecha, pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
            P.cifra("Lluvia ayer (máximo provincial)", f"{f1(mm)} mm", top["n"], "AEMET")
        if pv.get("sem") is not None:
            P.cifra("Lluvia de la semana", f"{f1(num(pv['sem'], 0))} mm", f"media de {pv.get('est', '?')} estaciones", "AEMET")

    # --- noches tropicales (AEMET) --------------------------------------------------
    nt = pj.get("indicadores", {}).get("noches_tropicales") or []
    for c in nt[:3]:
        if c.get("nt_anyo"):
            P.cifra(f"Noches tropicales en 2026 · {c['nombre']}", str(c["nt_anyo"]), f"{c.get('nt_mes', 0)} en {MESES[HOY.month - 1]}", "AEMET")
    if nt and nt[0].get("t_min_anoche") is not None and nt[0]["t_min_anoche"] >= 20:
        c = nt[0]
        P.add("ayer", "extremo", f"Noche tropical en {c['nombre']} a mediados de {MESES[HOY.month - 1]}: mínima de {f1(c['t_min_anoche'])} °C",
              f"mínima {f1(c['t_min_anoche'])} °C · {c.get('nt_anyo')} noches tropicales en 2026, {c.get('nt_mes')} en {MESES[HOY.month - 1]}",
              "AEMET OpenData", "Mínima diaria de la estación AEMET de la ciudad; noche tropical = mínima ≥ 20 °C.",
              pagina="https://calentamientoglobal.es/noches-tropicales/")

    # --- índice de desplazamiento climático (nuestro «Climate Shift Index») ---------
    # ¿Cuántas veces más frecuente es la máxima prevista hoy que en 1951-1980? Solo cuando
    # el día era raro entonces (retorno ≥ 1 año): con retornos más cortos el cociente es ruido.
    fc = pj.get("indicadores", {}).get("firma_climatica") or {}
    idc = indice_desplazamiento(fc)
    if idc:
        nivel, ratio, tit, dato = idc
        P.cifra("Índice de desplazamiento climático (hoy)", f"×{f1(ratio)}" if not fc.get("sin_precedente") else "sin precedente", f"nivel {nivel} de 5 · {f1(fc['tmax'])} °C previstos", "cálculo propio")
        P.add("ayer", "extremo" if nivel >= 3 else "comparacion", tit, dato,
              "ERA5 (Copernicus) · cálculo propio", "Índice de desplazamiento climático: frecuencia con la que una máxima como la prevista hoy ocurría en estas fechas (±15 días) en 1951-1980 frente a 1996-2025, en la celda ERA5 de la capital. Nivel 1-5 = al menos 1-5 veces más frecuente ahora.",
              citabilidad="media", fecha_dato=HOY.isoformat(),
              contexto=[f"Máxima prevista hoy: {f1(fc['tmax'])} °C · percentil {f1(fc.get('percentil', 0))} del clima 1951-1980 · desplazamiento de la distribución: {signo_txt(fc.get('delta'))} °C."],
              limites=["Reanálisis en la celda de la capital, no la estación de AEMET.", "Método observacional (comparación de periodos), no un modelo con y sin emisiones: es la mitad «observada» del índice de Climate Central."],
              pagina="https://calentamientoglobal.es/firma-climatica/")
        P.items[-1]["indice_desplazamiento"] = nivel

    # --- mar en la boya ------------------------------------------------------------
    for b in (pj.get("indicadores", {}).get("boyas") or [])[:1]:
        if b.get("temp") is not None:
            an = b.get("anomalia_reciente")
            P.cifra(f"Mar en {b['nombre']}", f"{f1(b['temp'])} °C", f"{'+' if an and an > 0 else ''}{f1(an)} °C frente a lo normal" if an is not None else "", "Puertos del Estado")
            if an is not None and abs(an) >= 1.5:
                P.add("ayer", "comparacion",
                      f"El mar en {b['nombre']} está a {f1(b['temp'])} °C, {f1(abs(an))} °C {'por encima' if an > 0 else 'por debajo'} de lo normal para estas fechas",
                      f"{f1(b['temp'])} °C el {fecha_dia(b['fecha'])} · máximo del año {f1(b['max_anio']['valor'])} °C ({fecha_dia(b['max_anio']['fecha'])})"
                      + (f" · tendencia +{f1(b['tendencia_decada'])} °C por década" if b.get("tendencia_decada") else ""),
                      "Puertos del Estado (REDEXT/REDCOS) vía Copernicus Marine", "Temperatura del agua medida por la boya; normal calculada sobre su propia serie.",
                      fecha_dato=b.get("fecha"), pagina="https://calentamientoglobal.es/temperaturas-del-mar-espana-actualizado/")

    # --- canícula / aire ---------------------------------------------------------
    ca = pj.get("indicadores", {}).get("canicula") or {}
    if ca.get("dias_consecutivos", 0) >= 3:
        P.add("ayer", "extremo", f"{P.nombre} encadena {ca['dias_consecutivos']} días por encima del percentil 90 de calor para la fecha",
              f"{ca['dias_consecutivos']} días seguidos · máxima {f1(ca.get('tmax_hoy', 0))} °C · umbral p90 {f1(ca.get('ref_p90', 0))} °C",
              "Open-Meteo · índice propio", "Índice de canícula: días consecutivos con máxima sobre el percentil 90 de 1991-2020 para la fecha.",
              citabilidad="media", pagina="https://calentamientoglobal.es/canicula/")
    for a in (pj.get("indicadores", {}).get("calidad_aire") or [])[:1]:
        if a.get("supera_oms") or a.get("sahariano"):
            P.add("ayer", "comparacion", f"{a['nombre']} respira hoy aire «{a['etiqueta']}»: {a['contaminante_dominante']} por encima del límite de la OMS" if a.get("supera_oms") else f"Polvo sahariano sobre {a['nombre']}: calidad del aire «{a['etiqueta']}»",
                  f"índice europeo {a.get('aqi_europeo')} · PM2.5 {a.get('pm25')} µg/m³",
                  "CAMS (Copernicus) vía Open-Meteo", "Calidad del aire modelizada en la capital; límites OMS 2021.", citabilidad="media",
                  pagina="https://calentamientoglobal.es/calidad-del-aire/")

    # --- hallazgos del detector de esta provincia --------------------------------
    for h in D.hallazgos.get("enviables", []) + D.hallazgos.get("locales", []):
        if h.get("provincia_slug") == P.slug and h.get("citabilidad") in ("alta", "media"):
            it = P.add("ayer", "record" if h["tipo"] in ("record_fecha", "record_absoluto") else "extremo", h["titular"], h["dato"],
                       h["fuente"], h["metodo"], contexto=h.get("contexto"), limites=h.get("limites"), citabilidad=h["citabilidad"],
                       fecha_dato=h["fecha_dato"], provisional=bool(h.get("provisional")), pagina=h.get("pagina"),
                       csv=h.get("csv"), grafico=h.get("grafico"))
            it["id_hallazgo"] = h["id"]


def sonda_semana(P: Parte, D: Datos):
    pr = leer_o(DOCS / "prediccion" / f"{P.cod}.json")
    if not pr or not pr.get("municipios"):
        return
    fuente = pr.get("fuente", "AEMET OpenData · predicción por municipio")
    anom = []   # (anomalía, municipio, fecha, tx, nx)
    frio = []
    lluvia = {}  # fecha → [municipios con pp ≥ 80]
    n_mun = 0
    for code, m in pr["municipios"].items():
        dias = (m.get("d") or {}).get("dias") or []
        n_mun += 1
        for d in dias[1:7]:
            if d.get("tx") is not None and d.get("nx") is not None:
                a = d["tx"] - d["nx"]
                anom.append((a, m["n"], d["f"], d["tx"], d["nx"]))
                if a <= -5:
                    frio.append((a, m["n"], d["f"], d["tx"], d["nx"]))
            if (d.get("pp") or 0) >= 80:
                lluvia.setdefault(d["f"], []).append(m["n"])
    if not anom:
        return
    metodo = (f"Predicción oficial de AEMET para cada municipio, comparada con la máxima normal 1991-2020 de la estación AEMET de referencia "
              f"({pr.get('normales', '')}).")
    limites = ["Es una predicción: AEMET la actualiza dos veces al día y puede cambiar. Citar siempre como «AEMET prevé».",
               "La normal es la de la estación AEMET más cercana, no la del municipio exacto."]
    calor = sorted([x for x in anom if x[0] >= 5], key=lambda x: -x[0])
    if calor:
        a, mun, f, tx, nx = calor[0]
        n_m = len({x[1] for x in calor})
        P.add("semana", "prevision", f"AEMET prevé {int(round(tx))} °C en {mun} {dia_semana(f)}, {f1(a)} °C por encima de lo normal para un {fecha_dia(f)}",
              f"máxima prevista {tx} °C · normal 1991-2020 {f1(nx)} °C · {n_m} de {n_mun} municipios con algún día ≥ 5 °C sobre lo normal esta semana",
              fuente, metodo, limites=limites, fecha_dato=HOY.isoformat(), citabilidad="alta",
              contexto=[f"Municipios con más de 5 °C de exceso: " + ", ".join(sorted({x[1] for x in calor})[:10]) + ("…" if n_m > 10 else "") + "."],
              pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")
    if frio:
        a, mun, f, tx, nx = min(frio)
        P.add("semana", "prevision", f"AEMET prevé {int(round(tx))} °C en {mun} {dia_semana(f)}, {f1(abs(a))} °C por debajo de lo normal para un {fecha_dia(f)}",
              f"máxima prevista {tx} °C · normal 1991-2020 {f1(nx)} °C · {len({x[1] for x in frio})} municipios con algún día ≥ 5 °C bajo lo normal",
              fuente, metodo, limites=limites, fecha_dato=HOY.isoformat(), pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")
    if lluvia:
        f = max(lluvia, key=lambda k: len(lluvia[k]))
        n = len(lluvia[f])
        if n >= max(3, n_mun // 4):
            P.add("semana", "prevision", f"AEMET da lluvia casi segura (≥ 80 %) {dia_semana(f)} en {n} de {n_mun} municipios de {P.nombre}",
                  f"{n} municipios con probabilidad ≥ 80 % el {fecha_dia(f)} · días con lluvia probable: " + ", ".join(dia_semana(k) for k in sorted(lluvia)),
                  fuente, "Probabilidad de precipitación diaria de la predicción municipal de AEMET.", limites=limites[:1], fecha_dato=HOY.isoformat(),
                  pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")
    # media de la semana frente a lo normal
    med = sum(x[0] for x in anom) / len(anom)
    P.cifra("Semana que viene (AEMET)", f"{'+' if med >= 0 else ''}{f1(med)} °C", "máximas frente a lo normal, media de los municipios", "AEMET")
    if abs(med) >= 3 and not calor and not frio:
        P.add("semana", "comparacion", f"Semana {'cálida' if med > 0 else 'fría'} en {P.nombre}: AEMET prevé máximas {f1(abs(med))} °C {'por encima' if med > 0 else 'por debajo'} de lo normal de media",
              f"media de {n_mun} municipios y 6 días · desviación media {'+' if med > 0 else ''}{f1(med)} °C", fuente, metodo, limites=limites, fecha_dato=HOY.isoformat(),
              pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")


def sonda_agua(P: Parte, D: Datos, pj: dict):
    # --- embalse a embalse ----------------------------------------------------------
    mios = [f for f in D.fichas if f.get("provincia") == P.nombre or f.get("provincia_slug") in (P.slug, P.slug.replace("-", "_"))]
    fuente = "Boletín Hidrológico Semanal del MITECO (BD-Embalses)"
    metodo = "Porcentaje de llenado de cada embalse en el boletín semanal, comparado con la misma semana de cada año de su serie (desde 1988) y con su media de diez años."
    for f in sorted(mios, key=lambda f: -(num(f.get("capacidad_hm3"), 0) or 0)):
        rk = f.get("ranking_semana") or {}
        pos, de = rk.get("posicion"), rk.get("de")
        pct, cap = num(f.get("pct")), num(f.get("capacidad_hm3"), 0) or 0
        if pct is None or not pos or not de or de < 15 or cap < 5:
            continue
        bol = f.get("boletin_fecha", AYER.isoformat())
        h1a = (f.get("hace_1a") or {}).get("pct")
        sa = f.get("semana_anterior") or {}
        ctx = [f"Hace un año: {pct_txt(h1a)}." if h1a is not None else "",
               f"Media de diez años para esta semana: {pct_txt(f['pct_media_10a'])}." if f.get("pct_media_10a") is not None else "",
               f"Variación semanal: {'+' if (sa.get('dif_pts') or 0) >= 0 else ''}{f1(sa.get('dif_pts', 0))} puntos." if sa else ""]
        ctx = [c for c in ctx if c]
        base = dict(fuente=fuente, metodo=metodo, fecha_dato=bol, citabilidad="alta", contexto=ctx,
                    pagina=f.get("url_web"), limites=["Dato oficial del MITECO; el ángulo (su puesto en la serie) es cálculo propio."])
        nombre = f"{f.get('de', 'de')} {f['nombre']}" if not f["nombre"].lower().startswith(("el ", "la ", "los ", "las ")) else f["nombre"]
        if pos == 1:
            P.add("agua", "record", f"El embalse {nombre} está al {pct_txt(pct)}, su nivel más alto para esta semana desde {rk.get('desde', 1988)}",
                  f"{pct_txt(pct)} ({f1(f.get('volumen_hm3', 0))} de {f1(cap)} hm³) · anterior máximo para la semana {pct_txt(rk['anio_mas_alto']['pct'])} ({rk['anio_mas_alto']['anio']})", **base)
        elif pos == de:
            P.add("agua", "record", f"El embalse {nombre} está al {pct_txt(pct)}, su nivel más bajo para esta semana desde {rk.get('desde', 1988)}",
                  f"{pct_txt(pct)} ({f1(f.get('volumen_hm3', 0))} de {f1(cap)} hm³) · " + (f"empata con el mínimo de {rk['anio_mas_bajo']['anio']}" if abs(pct - num(rk['anio_mas_bajo']['pct'], -1)) < 0.05 else f"anterior mínimo para la semana {pct_txt(rk['anio_mas_bajo']['pct'])} ({rk['anio_mas_bajo']['anio']})"), **base)
        elif pos <= 3:
            P.add("agua", "extremo", f"El embalse {nombre}, al {pct_txt(pct)}: el {pos}.º nivel más alto para esta semana en {de} años",
                  f"{pct_txt(pct)} · máximo para la semana {pct_txt(rk['anio_mas_alto']['pct'])} ({rk['anio_mas_alto']['anio']}) · puesto {pos} de {de}", **base)
        elif pos >= de - 2:
            P.add("agua", "extremo", f"El embalse {nombre}, al {pct_txt(pct)}: el {de - pos + 1}.º nivel más bajo para esta semana en {de} años",
                  f"{pct_txt(pct)} · mínimo para la semana {pct_txt(rk['anio_mas_bajo']['pct'])} ({rk['anio_mas_bajo']['anio']}) · puesto {pos} de {de}", **base)
        elif h1a is not None and abs(pct - h1a) >= 25:
            P.add("agua", "comparacion", f"El embalse {nombre} tiene {f1(abs(pct - h1a))} puntos {'más' if pct > h1a else 'menos'} de agua que hace un año: {pct_txt(pct)} frente a {pct_txt(h1a)}",
                  f"{pct_txt(pct)} · hace un año {pct_txt(h1a)} · puesto {pos} de {de} para la semana", **base)
    # provincia entera
    emb = None
    for fp in glob.glob(str(DOCS / "embalses" / "*.json")):
        e = leer_o(Path(fp))
        if e and e.get("provincia") == P.nombre and "pct" in e:
            emb = e
            break
    if emb:
        p10, p1a = num(emb.get("pct_media_10a")), num(emb.get("pct_hace_1a"))
        P.cifra("Embalses de la provincia", pct_txt(emb["pct"]), (f"media 10 años {pct_txt(p10)}" if p10 is not None else ""), "MITECO")
        if p10 is not None and abs(num(emb["pct"]) - p10) >= 15 and not any(i["angulo"] == "agua" and i["clase"] in ("record", "extremo") for i in P.items):
            P.add("agua", "comparacion", f"Los embalses de {P.nombre} están al {pct_txt(emb['pct'])}, {f1(abs(num(emb['pct']) - p10))} puntos {'por encima' if num(emb['pct']) > p10 else 'por debajo'} de su media de diez años",
                  f"{pct_txt(emb['pct'])} · hace un año {pct_txt(p1a) if p1a is not None else '—'} · media 10 años {pct_txt(p10)} · {emb.get('total_embalses')} embalses",
                  fuente, "Suma de los embalses de la provincia en el boletín semanal; media de diez años para la misma semana.", fecha_dato=emb.get("boletin_fecha", AYER.isoformat()),
                  pagina=f"https://calentamientoglobal.es/embalses-{P.slug}/")
    # --- aforos oficiales cerca -------------------------------------------------------
    cap = D.capitales.get(P.nombre)
    if cap:
        cerca = [a for a in D.aforos.get("estaciones", []) if a.get("lat") and dist_km(a["lat"], a["lon"], cap["lat"], cap["lon"]) <= 60]
        for a in sorted(cerca, key=lambda a: -abs(num(a.get("v24"), 0) or 0))[:1]:
            v = num(a.get("v24"))
            if v is not None and abs(v) >= 40 and (num(a.get("q"), 0) or 0) >= 1:
                P.add("agua", "extremo", f"El {a['rio']} en {a['nombre'].split(' en ')[-1]} {'sube' if v > 0 else 'baja'} un {int(abs(v))} % en 24 horas: {f1(a['q'])} m³/s",
                      f"{f1(a['q'])} m³/s a las {a['t'][11:16]} UTC · variación 24 h {'+' if v > 0 else ''}{f1(v)} %", a.get("fuente_n", "aforo oficial"),
                      "Caudal medido en la estación de aforo del organismo de cuenca, último dato publicado.", fecha_dato=HOY.isoformat(),
                      limites=["Dato en tiempo real, sujeto a validación del organismo."], pagina="https://calentamientoglobal.es/caudal-rios-espana-mapa/")
        # --- GloFAS ---
        puntos = [p for p in D.red.get("puntos", []) if dist_km(p["lat"], p["lon"], cap["lat"], cap["lon"]) <= 80 and int(p["id"]) in D.pct_hoy]
        if puntos:
            ext = min(puntos, key=lambda p: D.pct_hoy[int(p["id"])])
            pc = D.pct_hoy[int(ext["id"])]
            hum = max(puntos, key=lambda p: D.pct_hoy[int(p["id"])])
            ph = D.pct_hoy[int(hum["id"])]
            emitida = D.hoy_caudal.get("emitida", AYER.isoformat())
            if pc <= 10:
                P.add("agua", "comparacion", f"El {ext['rio']} en {ext['lugar']} lleva un caudal en el percentil {pc} de su serie: muy por debajo de lo habitual para la fecha",
                      f"percentil {pc} (1997-2025) · tramo GloFAS «{ext['nombre']}»", "GloFAS v4 (Copernicus CEMS)", "Caudal simulado comparado con los percentiles de su época del año (1997-2025).",
                      citabilidad="media", fecha_dato=emitida, limites=["Caudal simulado, no aforado: en ríos regulados puede diferir del dato real."], pagina="https://calentamientoglobal.es/caudal-rios-espana-mapa/")
            elif ph >= 90:
                P.add("agua", "comparacion", f"El {hum['rio']} en {hum['lugar']} lleva un caudal en el percentil {ph}: más agua de la habitual para la fecha",
                      f"percentil {ph} (1997-2025) · tramo GloFAS «{hum['nombre']}»", "GloFAS v4 (Copernicus CEMS)", "Caudal simulado comparado con los percentiles de su época del año (1997-2025).",
                      citabilidad="media", fecha_dato=emitida, limites=["Caudal simulado, no aforado."], pagina="https://calentamientoglobal.es/caudal-rios-espana-mapa/")
    # --- nivel del mar ----------------------------------------------------------------
    for n in (pj.get("indicadores", {}).get("nivel_mar") or [])[:1]:
        if n.get("desviacion_cm") is not None and abs(n["desviacion_cm"]) >= 10:
            P.add("agua", "comparacion", f"El nivel del mar en {n['nombre']} lleva {n.get('dias_consecutivos', 0)} días {'por encima' if n['desviacion_cm'] > 0 else 'por debajo'} de la media: {'+' if n['desviacion_cm'] > 0 else ''}{f1(n['desviacion_cm'])} cm",
                  f"{'+' if n['desviacion_cm'] > 0 else ''}{f1(n['desviacion_cm'])} cm sobre la media 1993-2012 · {n.get('dias_consecutivos', 0)} días consecutivos",
                  "Copernicus Marine (altimetría)", "Anomalía del nivel del mar en el punto de costa más próximo, frente a la media 1993-2012.", citabilidad="media",
                  limites=["Altimetría de satélite, no mareógrafo: incluye marea meteorológica y variación estacional."], pagina="https://calentamientoglobal.es/nivel-del-mar-espana-ahora/")


def sonda_municipios(P: Parte, D: Datos, pj: dict):
    cod = P.cod
    # --- otoño por municipio (ERA5) ----------------------------------------------
    O = D.otonio
    mios = {k: v for k, v in (O.get("municipios") or {}).items() if k.startswith(cod)}
    if mios:
        hasta = O.get("hasta", AYER.isoformat())
        vals = [(v["pct"], v) for v in mios.values() if v.get("pct") is not None]
        if vals:
            vals.sort(key=lambda x: x[0])
            secos = [v for p, v in vals if p < 50]
            humedos = [v for p, v in vals if p >= 150]
            med = sum(p for p, _ in vals) / len(vals)
            s, h = vals[0][1], vals[-1][1]
            fuente = O.get("fuente", "ERA5 (Copernicus) vía Open-Meteo")
            metodo = f"Lluvia acumulada del otoño (desde el 1 de septiembre hasta el {fecha_dia(hasta)}) en la celda ERA5 de cada municipio, frente a la normal 1991-2020 del mismo periodo."
            lim = [O.get("aviso", "Reanálisis en una celda de unos 25 km, no el pluviómetro.")]
            if len(secos) >= max(2, len(vals) // 3):
                P.add("municipios", "comparacion", f"{len(secos)} de {len(vals)} municipios de {P.nombre} llevan menos de la mitad de la lluvia normal de otoño; {s['n']}, solo el {s['pct']} %",
                      f"{s['n']} {f1(s['mm'])} mm de {f1(s['normal'])} normales ({s['pct']} %) · media provincial {int(med)} % · el más lluvioso: {h['n']} ({h['pct']} %)",
                      fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta,
                      contexto=[f"El otoño pasado hasta la misma fecha, {s['n']} llevaba {f1(s.get('anterior', 0))} mm."] if s.get("anterior") is not None else [],
                      pagina=f"https://calentamientoglobal.es/lluvia-otono-{P.slug}/")
            elif len(humedos) >= max(2, len(vals) // 3):
                P.add("municipios", "comparacion", f"{len(humedos)} de {len(vals)} municipios de {P.nombre} ya han recogido más de 1,5 veces la lluvia normal de otoño; {h['n']}, el {h['pct']} %",
                      f"{h['n']} {f1(h['mm'])} mm de {f1(h['normal'])} normales ({h['pct']} %) · media provincial {int(med)} % · el más seco: {s['n']} ({s['pct']} %)",
                      fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta, pagina=f"https://calentamientoglobal.es/lluvia-otono-{P.slug}/")
            else:
                P.add("municipios", "cifra", f"Otoño al {int(med)} % de lo normal en {P.nombre}: de {s['n']} ({s['pct']} %) a {h['n']} ({h['pct']} %)",
                      f"{len(vals)} municipios · media {int(med)} % · {len(secos)} por debajo del 50 % · {len(humedos)} por encima del 150 %",
                      fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta, pagina=f"https://calentamientoglobal.es/lluvia-otono-{P.slug}/")
            P.cifra("Otoño (lluvia frente a lo normal)", f"{int(med)} %", f"media de {len(vals)} municipios", "ERA5")
    # --- año por municipio desde 1981 ----------------------------------------------
    M = D.mun_mapa
    if M.get("municipios"):
        campos = M["campos"]
        iI, iN, iMM, iMed, iP, iDe = (campos.index(x) for x in ("ine", "nombre", "mm", "mediana", "puesto", "de"))
        mios = [m for m in M["municipios"] if str(m[iI]).startswith(cod)]
        if mios:
            hasta = M.get("hasta", AYER.isoformat())
            de = mios[0][iDe]
            secos = sorted([m for m in mios if m[iP] >= de - 2], key=lambda m: -m[iP])
            humedos = sorted([m for m in mios if m[iP] <= 3], key=lambda m: m[iP])
            fuente = "ERA5 (Copernicus) vía Open-Meteo · cálculo propio"
            metodo = f"Lluvia acumulada de 2026 hasta el {fecha_dia(hasta)} en la celda ERA5 de cada municipio, ordenada frente al mismo periodo de cada año desde {M.get('desde_anio', 1981)}."
            lim = ["Reanálisis en una celda de unos 25 km, no el pluviómetro. Dato hasta el cierre del último mes consolidado."]
            if secos:
                m = secos[0]
                r = de - m[iP] + 1
                P.add("municipios", "record" if r == 1 else "extremo",
                      f"{m[iN]} vive el {'año más seco' if r == 1 else str(r) + '.º año más seco'} desde {M.get('desde_anio', 1981)}: {f1(m[iMM])} mm frente a {f1(m[iMed])} de mediana"
                      + (f"; otros {len(secos) - 1} municipios de {P.nombre} están entre los tres más secos" if len(secos) > 1 else ""),
                      f"{f1(m[iMM])} mm hasta el {fecha_dia(hasta)} · mediana {f1(m[iMed])} mm · puesto {m[iP]} de {de} por lluvia", fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta,
                      contexto=[f"También entre los tres más secos: " + ", ".join(x[iN] for x in secos[1:8]) + "."] if len(secos) > 1 else [],
                      pagina=f"https://calentamientoglobal.es/cambio-climatico-en-{P.slug}/")
            if humedos:
                m = humedos[0]
                P.add("municipios", "record" if m[iP] == 1 else "extremo",
                      f"{m[iN]} vive el {'año más lluvioso' if m[iP] == 1 else str(m[iP]) + '.º año más lluvioso'} desde {M.get('desde_anio', 1981)}: {f1(m[iMM])} mm frente a {f1(m[iMed])} de mediana"
                      + (f"; otros {len(humedos) - 1} municipios de {P.nombre} están entre los tres más lluviosos" if len(humedos) > 1 else ""),
                      f"{f1(m[iMM])} mm hasta el {fecha_dia(hasta)} · mediana {f1(m[iMed])} mm · puesto {m[iP]} de {de}", fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta,
                      contexto=[f"También entre los tres más lluviosos: " + ", ".join(x[iN] for x in humedos[1:8]) + "."] if len(humedos) > 1 else [],
                      pagina=f"https://calentamientoglobal.es/cambio-climatico-en-{P.slug}/")
    # --- 2050 ---------------------------------------------------------------------
    items = [m for m in D.mun2050.get("items", []) if str(m.get("code", "")).startswith(cod) and m.get("c5") is not None]
    if items:
        meta = D.mun2050.get("meta", {})
        top = max(items, key=lambda m: (m["c5"] - m["ch"]))
        capital = next((m for m in items if m["prov"] == P.nombre and m["n"] == pj.get("capital")), None)
        P.add("municipios", "cifra", f"{top['n']} pasará de {top['ch']} a {top['c5']} días de calor extremo al año en 2050, el mayor salto de la provincia de {P.nombre}",
              f"días con máxima ≥ 35 °C: {top['ch']} (2005-2020) → {top['c5']} (2035-2050) · noches tropicales: {top.get('nh')} → {top.get('n5')} · clima análogo en 2050: {top.get('an')}"
              + (f" · capital: {capital['ch']} → {capital['c5']} días" if capital else ""),
              f"{meta.get('fuente', 'CMIP6 HighResMIP')} · modelo {meta.get('modelo', '')}", "Proyección climática CMIP6 de alta resolución, periodo 2035-2050 frente a 2005-2020, en el punto de cada municipio.",
              citabilidad="media", fecha_dato=HOY.isoformat(), limites=["Un solo modelo climático: la cifra exacta variará entre modelos; la dirección y el orden de magnitud son robustos."],
              pagina=f"https://calentamientoglobal.es/clima-2050/{P.slug}/")


def sonda_impacto(P: Parte, D: Datos, pj: dict):
    # --- avisos acumulados -----------------------------------------------------------
    A = D.avisos_h
    if A.get("dias"):
        tot = {"rojo": 0, "naranja": 0, "amarillo": 0}
        dias_con = 0
        for f, d in A["dias"].items():
            pp = (d.get("por_provincia") or {}).get(P.nombre) or (d.get("por_provincia") or {}).get(pj.get("provincia", ""))
            if pp:
                dias_con += 1
                for k in tot:
                    tot[k] += int(pp.get(k, 0) or 0)
        suma = sum(tot.values())
        P.cifra(f"Avisos AEMET desde el {fecha_dia(A['desde'])}", str(suma), f"{tot['rojo']} rojos · {tot['naranja']} naranjas · {tot['amarillo']} amarillos", "AEMET/MeteoAlarm")
        hoy_av = pj.get("indicadores", {}).get("avisos") or {}
        if hoy_av.get("naranjas") or hoy_av.get("rojos"):
            nivel = "rojo" if hoy_av.get("rojos") else "naranja"
            graves = [it for it in hoy_av.get("items", []) if it.get("nivel") == nivel]
            tipos = sorted({(it.get("tipo") or "").lower() for it in graves if it.get("tipo")})
            zonas = sorted({it.get("zona") for it in graves if it.get("zona")})
            por = (" por " + " y ".join(tipos)) if tipos else ""
            activo = any(it.get("activo_ya") for it in graves)
            inicio = min((it.get("inicio") or "" for it in graves), default="")
            if activo or not inicio:
                cuando = "está en aviso"
            else:
                cuando = f"tendrá aviso"
            desde = ""
            if not activo and inicio:
                desde = f" desde el {fecha_dia(inicio[:10])} a las {inicio[11:16]}"
            P.add("impacto", "record" if nivel == "rojo" else "extremo", f"{P.nombre} {cuando} {nivel} de AEMET{por}{desde}" + (f" ({', '.join(zonas[:3])})" if zonas else ""),
                  f"{hoy_av.get('rojos', 0)} rojos · {hoy_av.get('naranjas', 0)} naranjas · {hoy_av.get('amarillos', 0)} amarillos vigentes o anunciados · desde el {fecha_dia(A['desde'])}: {suma} avisos-zona",
                  "AEMET vía MeteoAlarm", "Avisos vigentes o ya anunciados por AEMET en las zonas de la provincia; acumulado por fecha de inicio.", fecha_dato=HOY.isoformat(),
                  limites=["Nunca contradecir ni matizar un aviso de AEMET con otro dato.", "Comprobar la hora de inicio y fin en aemet.es antes de publicar."], pagina="https://calentamientoglobal.es/avisos-meteorologicos/")
        elif suma >= 10:
            P.add("impacto", "cifra", f"{P.nombre} acumula {suma} avisos de AEMET desde el {fecha_dia(A['desde'])}, {tot['naranja'] + tot['rojo']} de ellos naranjas o rojos",
                  f"{tot['rojo']} rojos · {tot['naranja']} naranjas · {tot['amarillo']} amarillos · {dias_con} días con algún aviso", "AEMET vía MeteoAlarm",
                  "Recuento de avisos-zona por fecha de inicio en las zonas de la provincia.", fecha_dato=AYER.isoformat(), limites=["Serie propia desde julio de 2026: no permite comparar con años anteriores todavía."],
                  pagina="https://calentamientoglobal.es/avisos-meteorologicos/")
    # --- mortalidad por calor ---------------------------------------------------------
    C = D.calor
    pc = (C.get("provincias") or {}).get(P.slug) or (C.get("provincias") or {}).get(P.slug.replace("-", "_"))
    if pc and pc.get("verano") is not None:
        va = C.get("verano_actual") or {}
        P.cifra("Muertes atribuibles al calor (verano 2026)", str(pc["verano"]), f"desde el 1 de junio · España: {va.get('atribuibles_calor', '')}", "ISCIII (MoMo)")
        if pc["verano"] >= 20:
            P.add("impacto", "cifra", f"{pc['verano']} muertes atribuibles al calor en {P.nombre} desde el 1 de junio, según el sistema MoMo",
                  f"{pc['verano']} atribuibles · España: {va.get('atribuibles_calor')} · dato hasta el {fecha_dia(va.get('a_fecha', AYER.isoformat()))}",
                  C.get("fuente", "ISCIII · MoMo"), "Estimación estadística del ISCIII del exceso de defunciones por temperatura (no muertes por golpe de calor).",
                  fecha_dato=va.get("a_fecha", AYER.isoformat()), limites=["Se revisa a medida que entran datos: citar solo meses cerrados como definitivos."],
                  pagina="https://calentamientoglobal.es/muertes-por-calor-espana/")
    # --- coste de desastres --------------------------------------------------------
    cd = pj.get("indicadores", {}).get("coste_desastres") or {}
    if cd.get("coste_millones_eur"):
        P.cifra("Coste de desastres (Consorcio)", f"{cd['coste_millones_eur']} M€", "riesgos extraordinarios, acumulado", "Consorcio de Compensación de Seguros")
    # --- incendios -----------------------------------------------------------------
    inc = pj.get("indicadores", {}).get("incendios_ccaa") or {}
    if inc.get("tiene_fuego") and (inc.get("focos_activos") or 0) >= 5:
        P.add("impacto", "extremo", f"{inc['focos_activos']} focos de calor activos en {inc['nombre']} en las últimas 48 horas (satélite)",
              f"{inc['focos_activos']} focos · {inc.get('dias_consecutivos', 0)} días seguidos con fuego · {inc.get('dias_anio_actual', 0)} días con fuego en 2026",
              "NASA FIRMS (VIIRS)", "Detecciones de puntos calientes por satélite en la comunidad autónoma, ventana de 48 horas.", citabilidad="media", fecha_dato=HOY.isoformat(),
              limites=["Un foco satelital no equivale a un incendio declarado: contrastar con el servicio autonómico."], pagina="https://calentamientoglobal.es/incendios-forestales-espana/")
    # --- días de más de 32 °C ---------------------------------------------------------
    for p in D.dias32.get("provincias", []):
        if p.get("prov") == P.nombre and p.get("actual") is not None and p.get("media_9120"):
            r = num(p["actual"]) / num(p["media_9120"])
            P.cifra("Días de más de 32 °C en 2026", str(p["actual"]), f"normal 1991-2020: {f1(p['media_9120'])}", "ERA5")
            if r >= 1.5 and num(p["actual"]) >= 20:
                P.add("impacto", "comparacion", f"{P.nombre} suma {p['actual']} días de más de 32 °C en 2026, {f1(r)} veces su normal",
                      f"{p['actual']} días · normal 1991-2020: {f1(p['media_9120'])} · media 1961-1990: {f1(p.get('media_6190', 0))}", D.dias32.get("fuente", "ERA5 vía Open-Meteo"),
                      "Días con máxima ≥ 32 °C en el punto de referencia de la provincia, contados por año natural.", citabilidad="media", fecha_dato=D.dias32.get("actualizado", AYER.isoformat())[:10],
                      limites=["Un punto por provincia (reanálisis), no la red de AEMET."], pagina="https://calentamientoglobal.es/dias-de-mas-de-32-grados/")


# ----------------------------------------------------------------------------
# parte por provincia
# ----------------------------------------------------------------------------
def parte_provincia(cod: str, D: Datos) -> dict:
    nombre, slug = PROVINCIAS[cod]
    P = Parte(cod, nombre, slug)
    pj = leer_o(DOCS / "provincias" / f"{SLUG_PROV_JSON.get(slug, slug.replace('-', '_'))}.json", {}) or {}
    for sonda in (lambda: sonda_ayer(P, D, pj), lambda: sonda_semana(P, D), lambda: sonda_agua(P, D, pj),
                  lambda: sonda_municipios(P, D, pj), lambda: sonda_impacto(P, D, pj)):
        try:
            sonda()
        except Exception as e:
            P.errores.append(f"{sonda.__code__.co_name}: {type(e).__name__}: {e}")
    # dedupe por titular y orden por fuerza dentro de cada ángulo
    vistos, items = set(), []
    for h in sorted(P.items, key=lambda h: -h["fuerza"]):
        if h["titular"] in vistos:
            continue
        vistos.add(h["titular"])
        items.append(h)
    angulos = {a: [h for h in items if h["angulo"] == a] for a in ("ayer", "semana", "agua", "municipios", "impacto")}
    titular = max(items, key=lambda h: h["fuerza"]) if items else None
    return {"generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": HOY.isoformat(), "cod": cod, "provincia": nombre, "slug": slug,
            "capital": pj.get("capital"), "ccaa": pj.get("ccaa"), "titular_del_dia": titular, "angulos": angulos, "cifras": P.cifras,
            "n_items": len(items), "errores": P.errores,
            "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0 · los datos de origen conservan la licencia de su organismo"}


def coincidencias(partes: list[dict]) -> list[dict]:
    """Lo que se repite en muchas provincias es noticia nacional."""
    out = []
    # alerta de desplazamiento climático: ≥ 8 provincias con nivel ≥ 3 (o cualquiera sin precedente)
    niveles, cods = {}, {}
    for p in partes:
        for h in p["angulos"].get("ayer", []):
            if h.get("indice_desplazamiento"):
                niveles[p["provincia"]] = max(niveles.get(p["provincia"], 0), h["indice_desplazamiento"])
                cods[p["provincia"]] = p["cod"]
    altas = {k: v for k, v in niveles.items() if v >= 3}
    if len(altas) >= 8 or sum(1 for v in altas.values() if v >= 5) >= 4:
        pob = sum(POBLACION_MILES.get(cods[k], 0) for k in altas) / 1000
        top = sorted(altas.items(), key=lambda kv: -kv[1])[:10]
        out.append({"tipo": "alerta_desplazamiento", "n": len(altas), "poblacion_millones": round(pob, 1),
                    "titular": f"Alerta de desplazamiento climático: el calor previsto hoy es al menos 3 veces más frecuente que en 1951-1980 en {len(altas)} provincias"
                               + (f", donde viven {pob:.1f} millones de personas".replace(".", ",") if pob else ""),
                    "provincias": list(altas), "dato": "; ".join(f"{k} (nivel {v})" for k, v in top),
                    "metodo": "Índice de desplazamiento climático por capital: frecuencia de la máxima prevista hoy en 1951-1980 frente a 1996-2025 (ERA5). Nivel 3 = al menos tres veces más frecuente ahora; nivel 5 = cinco veces o sin precedente."})
    def cuenta(pred, titulo, dato_fn):
        provs = [p for p in partes if any(pred(h) for h in sum(p["angulos"].values(), []))]
        if len(provs) >= 8:
            out.append({"titular": titulo.format(n=len(provs)), "provincias": [p["provincia"] for p in provs], "n": len(provs), "dato": dato_fn(provs)})
    cuenta(lambda h: h["angulo"] == "municipios" and "menos de la mitad de la lluvia normal de otoño" in h["titular"],
           "{n} provincias tienen a un tercio o más de sus municipios con menos de la mitad de la lluvia normal de otoño", lambda ps: "; ".join(p["provincia"] for p in ps))
    cuenta(lambda h: h["angulo"] == "semana" and "por encima de lo normal" in h["titular"] and h["clase"] == "prevision",
           "AEMET prevé esta semana máximas 5 °C o más por encima de lo normal en municipios de {n} provincias", lambda ps: "; ".join(p["provincia"] for p in ps))
    cuenta(lambda h: h["angulo"] == "agua" and h["clase"] == "record" and "más bajo" in h["titular"],
           "Embalses en su nivel más bajo para esta semana desde 1988 en {n} provincias", lambda ps: "; ".join(p["provincia"] for p in ps))
    cuenta(lambda h: h["angulo"] == "agua" and h["clase"] == "record" and "más alto" in h["titular"],
           "Embalses en su nivel más alto para esta semana desde 1988 en {n} provincias", lambda ps: "; ".join(p["provincia"] for p in ps))
    cuenta(lambda h: h["angulo"] == "municipios" and "más seco desde" in h["titular"],
           "Municipios con el año más seco (o entre los tres más secos) desde 1981 en {n} provincias", lambda ps: "; ".join(p["provincia"] for p in ps))
    cuenta(lambda h: h["angulo"] == "ayer" and "sin lluvia apreciable" in h["titular"],
           "Rachas de 10 o más días sin lluvia en municipios de {n} provincias", lambda ps: "; ".join(p["provincia"] for p in ps))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", help="código de provincia (p. ej. 30) para probar")
    ap.add_argument("--salida", default=str(PARTES))
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    D = Datos()
    cods = [args.solo] if args.solo else sorted(PROVINCIAS)
    partes = []
    for cod in cods:
        p = parte_provincia(cod, D)
        partes.append(p)
        with open(salida / f"{cod}.json", "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
    if not args.solo:
        # archivo del día: un solo fichero con lo esencial de las 52 provincias (hemeroteca sin URLs)
        (salida / "archivo").mkdir(exist_ok=True)
        compacto = {"fecha": HOY.isoformat(), "generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "provincias": {}}
        for p in partes:
            compacto["provincias"][p["cod"]] = [{k: h.get(k) for k in ("angulo", "clase", "titular", "dato", "fecha_dato", "fuente", "citabilidad", "provisional")}
                                                for a in p["angulos"].values() for h in a]
        with open(salida / "archivo" / f"{HOY.isoformat()}.json", "w", encoding="utf-8") as f:
            json.dump(compacto, f, ensure_ascii=False)
        idx = {"generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": HOY.isoformat(),
               "provincias": [{"cod": p["cod"], "provincia": p["provincia"], "slug": p["slug"], "n_items": p["n_items"],
                               "titular": (p["titular_del_dia"] or {}).get("titular"), "angulo": (p["titular_del_dia"] or {}).get("angulo"),
                               "fuerza": (p["titular_del_dia"] or {}).get("fuerza")} for p in partes],
               "coincidencias": coincidencias(partes)}
        with open(salida / "index.json", "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=1)
    for p in partes:
        t = p["titular_del_dia"]
        print(f"{p['cod']} {p['provincia']:24s} {p['n_items']:2d} items · {t['angulo'] if t else '-':10s} {t['titular'][:95] if t else 'SIN NADA'}")
        for e in p["errores"]:
            print("   !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
