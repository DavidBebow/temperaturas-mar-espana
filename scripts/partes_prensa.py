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

Auditoría del 17-10-2026 (segunda pasada). Regla: una cifra de un lugar se publica solo si la ha
medido un organismo oficial en ese lugar. Quedan en revisión (no salen en la web sin aprobación):
  · lluvia municipal y año hidrológico del reanálisis ERA5, y la proyección 2050 de un solo modelo;
  · caudal simulado (GloFAS), calidad del aire modelizada (CAMS), focos FIRMS por comunidad;
  · la temperatura de la boya frente a «lo normal» (la normal sale de un cálculo sin auditar);
  · el recuento de avisos desde julio (el archivo propio tiene días sin descargar);
  · un embalse por debajo del 1 % (suele ser un vaciado por obras, no sequía).
Corregido: la lluvia de estaciones ya no mezcla la media de las estaciones con el porcentaje de
otro cálculo; solo cuentan estaciones de la propia provincia (inventario de AEMET); «sin lluvia
apreciable» pasa a «sin recoger 1 mm» (para AEMET, apreciable es ≥ 0,1 mm); la racha que llega al
tope de la ventana se da como «al menos»; la predicción descarta el municipio cuya normal sale de
una estación que no se parece a sus vecinos (Castellbisbal comparado con Montserrat, a 1.000 m);
la mortalidad por calor da el periodo real del dato provincial.
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
from hallazgos_prensa import PROVINCIAS, MESES, f1, fecha_larga, fecha_dia, num, estaciones_lluvia, _nombre_corto  # noqa: E402

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
    """«el sábado 17»: absoluto, para que el titular no caduque (un «mañana» leído al día siguiente miente)."""
    d = date.fromisoformat(iso)
    return f"el {DIAS_SEMANA[d.weekday()]} {d.day}"


def lista_nombres(nombres: list[str], maximo: int = 3) -> str:
    """«Cáceres, Plasencia y Coria» · «Cáceres, Plasencia, Coria y otras 3 localidades»"""
    nombres = list(dict.fromkeys(nombres))
    if len(nombres) <= maximo:
        return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]
    resto = len(nombres) - maximo
    return ", ".join(nombres[:maximo]) + f" y otras {resto} localidad{'es' if resto > 1 else ''}"


def nombre_embalse(f: dict) -> str:
    """«de Alarcón», «de la Fuensanta», «de Los Rábanos», «del Vado»: la preposición que trae la ficha."""
    nombre = f["nombre"]
    if nombre.startswith("El "):
        return "del " + nombre[3:]
    if nombre.lower().startswith(("la ", "los ", "las ")):
        return "de " + nombre
    return f"{f.get('de') or 'de'} {nombre}"


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def pct_txt(v) -> str:
    return f"{f1(v)} %"


def miles(v) -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(v)


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


def plural(n, uno: str, varios: str) -> str:
    """«1 naranja», «3 naranjas»."""
    return f"{n} {uno if n == 1 else varios}"


def cuenta_avisos(avs) -> str:
    """«2 avisos rojos y 4 naranjas», «4 avisos naranjas» (sin «0 avisos rojos»)."""
    r = sum(1 for a in avs if a.get("nivel") == "rojo")
    n = sum(1 for a in avs if a.get("nivel") == "naranja")
    if r and n:
        return f"{plural(r, 'aviso rojo', 'avisos rojos')} y {plural(n, 'naranja', 'naranjas')}"
    return plural(r, "aviso rojo", "avisos rojos") if r else plural(n, "aviso naranja", "avisos naranjas")


def _norm_nombre(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


# Inventario de estaciones de AEMET (indicativo → nombre, provincia, altitud), sacado de los diarios
# climatológicos de AEMET OpenData. Sirve para no atribuir a una provincia una estación de la vecina
# (Alcalá de Henares, en Madrid, es la estación de referencia de Azuqueca, en Guadalajara).
INVENTARIO = leer_o(DOCS / "prensa" / "aemet_inventario.json", {}) or {}
_PROV_INV = {"arabaalava": "alava", "illesbalears": "baleares", "baleares": "baleares", "stacruzdetenerife": "santa-cruz-de-tenerife",
             "santacruzdetenerife": "santa-cruz-de-tenerife", "acoruna": "a-coruna", "ciudadreal": "ciudad-real", "larioja": "la-rioja",
             "laspalmas": "las-palmas"}
_EST_PROV: dict[str, set] = {}
for _cod, (_nom, _prov, _alt) in INVENTARIO.items():
    _p = _norm_nombre(_prov)
    _EST_PROV.setdefault(_norm_nombre(_nom), set()).add(_PROV_INV.get(_p, _p))


def estacion_en_provincia(est: str, slug: str, municipios_ref: list[str]) -> bool:
    """True solo si consta que la estación está en la provincia: por el inventario de AEMET o porque
    su nombre empieza por el de un municipio de la provincia que la usa de referencia."""
    provs = _EST_PROV.get(_norm_nombre(est))
    if provs:
        return slug.replace("-", "") in {p.replace("-", "") for p in provs}
    ne = _norm_nombre(est)
    return any(len(_norm_nombre(m)) >= 4 and ne.startswith(_norm_nombre(m)) for m in municipios_ref)


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
        self.est_lluvia = None  # estaciones_lluvia(self.lluvias), se calcula al primer uso
        self.nocturnas = leer_o(DOCS / "temperaturas_nocturnas.json", {})
        self.otonio = leer_o(DOCS / "otonio_municipios.json", {})
        self.mun_mapa = leer_o(DOCS / "municipios_mapa.json", {})
        self.mun2050 = leer_o(DOCS / "municipios.json", {"items": []})
        self.avisos_h = leer_o(DOCS / "avisos_historico.json", {"dias": {}})
        self.avisos = leer_o(DOCS / "avisos.json", {})
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
    # --- lluvia por estación (AEMET observación) -----------------------------------
    # Solo estaciones que constan en la provincia y solo valores medidos por cada una (estaciones_lluvia): el
    # 18-10-2026 «Pego lleva 26,9 mm» era el dato de Oliva, que el fichero por municipios usa de relevo.
    # Sin superlativo en el titular: el fichero no tiene toda la red de AEMET, solo las estaciones de referencia
    # de los municipios del mapa. El «más alta de las N» va en el dato, con su alcance.
    L = D.lluvias
    if L.get("municipios"):
        fecha = L.get("fecha", AYER.isoformat())
        if D.est_lluvia is None:
            D.est_lluvia = estaciones_lluvia(L)
        estaciones = {e: r for e, r in D.est_lluvia.items() if r.get("prov") == cod}
        fuente = L.get("fuente", "AEMET OpenData · observación convencional")
        metodo = "Precipitación de 0 a 24 h (hora local) de las estaciones de AEMET de la provincia, sumada a partir del dato horario de AEMET OpenData. Solo estaciones con las 24 horas."
        alcance = ("El observatorio sigue las estaciones de AEMET que sirven de referencia a los municipios de su mapa de lluvia, "
                   "no toda la red: en otra estación de AEMET pudo llover más.")
        tope = max((int(num(m.get("racha"), 0) or 0) for m in L["municipios"].values()), default=0)
        con_dia = {e: r for e, r in estaciones.items() if r.get("dia") is not None}

        def oficial(e):
            corto = _nombre_corto(e)
            return corto, ("" if corto == e else f" · nombre en AEMET: «{e}»")

        def lider(filas, campo, conjunto):
            """«la cifra más alta de las 12 estaciones …» o, si solo hay una, «única estación …»."""
            if len(filas) == 1:
                return f"única estación de AEMET de la provincia {conjunto}"
            mm = filas[0][1][campo]
            emp = [_nombre_corto(e) for e, r in filas[1:] if r[campo] == mm]
            return ("la cifra más alta" + (f" (empatada con {', '.join(emp)})" if emp else "")
                    + f" de las {len(filas)} estaciones de AEMET de la provincia {conjunto}")

        if con_dia:
            n_est = len(con_dia)
            con_lluvia = sum(1 for r in con_dia.values() if r["dia"] >= 1)
            filas = sorted(con_dia.items(), key=lambda kv: (-kv[1]["dia"], kv[0]))
            e_top, top = filas[0]
            mm = top["dia"]
            corto, of = oficial(e_top)
            # estaciones a las que les falta alguna hora del día: su cifra es un mínimo y no entra en la comparación
            parc = sorted(((e, r) for e, r in estaciones.items() if r.get("dia_min") is not None and (r.get("dia_h") or 0) >= 20),
                          key=lambda kv: (-kv[1]["dia_min"], kv[0]))
            nota_parc = (["Con horas sin dato en AEMET (la cifra es un mínimo): " + " · ".join(
                f"{_nombre_corto(e)}: al menos {f1(r['dia_min'])} mm ({r['dia_h']} de 24 horas)" for e, r in parc[:3] if r["dia_min"] >= 1) + "."]
                if parc and parc[0][1]["dia_min"] >= 1 else [])
            if parc and parc[0][1]["dia_min"] > mm and parc[0][1]["dia_min"] >= 10:
                # «Hellín recogió al menos 46,3 mm»: con una hora sin dato ya supera a todas las de día completo
                e_p, r_p = parc[0]
                corto_p, of_p = oficial(e_p)
                falta = 24 - int(r_p["dia_h"])
                P.add("ayer", "extremo" if r_p["dia_min"] >= 30 else "comparacion",
                      f"La estación de AEMET de {corto_p} recogió al menos {f1(r_p['dia_min'])} mm el {fecha_dia(fecha)}",
                      f"{f1(r_p['dia_min'])} mm en las {r_p['dia_h']} horas del {fecha_dia(fecha)} con dato en AEMET ({plural(falta, 'hora', 'horas')} sin dato: la cifra real puede ser mayor)"
                      + f" · más que cualquiera de {('la estación' if n_est == 1 else f'las {n_est} estaciones')} de AEMET de la provincia con las 24 horas que sigue el observatorio (la que más, {corto}: {f1(mm)} mm){of_p}",
                      fuente, metodo.replace(" Solo estaciones con las 24 horas.", ""), fecha_dato=fecha,
                      limites=[f"A la estación le {'falta una hora' if falta == 1 else f'faltan {falta} horas'} de ese día en AEMET OpenData: citar como «al menos».",
                               "Lluvia de una estación de AEMET: en el resto del término municipal pudo llover más o menos.", alcance],
                      pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
            elif mm >= 10:
                P.add("ayer", "extremo" if mm >= 30 else "comparacion",
                      f"La estación de AEMET de {corto} recogió {f1(mm)} mm el {fecha_dia(fecha)}",
                      f"{f1(mm)} mm de 0 a 24 h (hora local) del {fecha_dia(fecha)}, {lider(filas, 'dia', 'con las 24 horas que sigue el observatorio')}"
                      + (f" · {plural(con_lluvia, 'recogió', 'recogieron')} 1 mm o más" if n_est > 1 else "") + of,
                      fuente, metodo, fecha_dato=fecha,
                      contexto=(["Las que más: " + " · ".join(f"{_nombre_corto(e)}: {f1(r['dia'])} mm" for e, r in filas[:5]) + "."] if n_est > 1 else []) + nota_parc,
                      limites=["Lluvia de una estación de AEMET: en el resto del término municipal pudo llover más o menos.", alcance],
                      pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
            else:
                # una racha seca solo se publica si la estación tiene dato de hoy y aún no llega a 1 mm (si hoy no
                # hay dato de la estación, puede estar lloviendo: el 18-10 Ontinyent «10 días sin lluvia» con aviso rojo)
                secas = sorted(((int(r["racha"]), e) for e, r in con_dia.items()
                                if r.get("racha") is not None and r.get("hoy") is not None and r["hoy"] < 1), key=lambda x: (-x[0], x[1]))
                if secas and secas[0][0] >= 10:
                    r_, e_seca = secas[0]
                    corto_s, of_s = oficial(e_seca)
                    # la ventana del cálculo tiene tope: si la racha llega a él, la real puede ser más larga
                    al_menos = "al menos " if tope and r_ >= tope else ""
                    hoy_s = D.est_lluvia[e_seca]
                    P.add("ayer", "comparacion",
                          f"La estación de AEMET de {corto_s} lleva {al_menos}{r_} días seguidos sin recoger 1 mm de lluvia (hasta el {fecha_dia(fecha)})",
                          f"{al_menos}{r_} días seguidos con menos de 1 mm en la estación de AEMET de {corto_s}{of_s}, hasta el {fecha_dia(fecha)} incluido"
                          + (f" · el {fecha_dia(L.get('hoy_fecha'))} lleva {f1(hoy_s['hoy'])} mm hasta las {int(hoy_s['hoy_h'])}:00" if hoy_s.get("hoy") is not None and hoy_s.get("hoy_h") and L.get("hoy_fecha") else ""),
                          fuente, "Días consecutivos, hasta el último día completo, en que la estación de AEMET recogió menos de 1 mm.", fecha_dato=fecha, citabilidad="alta",
                          limites=([f"La ventana de cálculo es de {tope} días: la racha real puede ser más larga."] if al_menos else []),
                          pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
            if mm > 0:
                P.cifra(f"Lluvia el {fecha_dia(fecha)}", f"{f1(mm)} mm", f"{corto}, la que más de las que sigue el observatorio", "AEMET")
            else:
                P.cifra(f"Lluvia el {fecha_dia(fecha)}", "0 mm", ("en la estación de AEMET de la provincia que sigue el observatorio" if n_est == 1 else f"en las {n_est} estaciones de AEMET de la provincia que sigue el observatorio"), "AEMET")
            sem = [r["sem"] for r in con_dia.values() if r.get("sem") is not None and r.get("sem_dias") == 7]
            if sem:
                P.cifra("Lluvia de los últimos siete días", f"{f1(sum(sem) / len(sem))} mm",
                        (f"estación de AEMET de {corto}" if len(sem) == 1 else f"media de {len(sem)} estaciones de AEMET"), "AEMET")
        # --- hoy, hasta la última hora cerrada de la red (18-10-2026: lo más fresco que hay) ---
        hoy_f, corte = L.get("hoy_fecha"), L.get("corte_red")
        if hoy_f and corte:
            completas = {e: r for e, r in estaciones.items() if r.get("hoy") is not None and r.get("hoy_h") == corte}
            if completas:
                filas_h = sorted(completas.items(), key=lambda kv: (-kv[1]["hoy"], kv[0]))
                e_h, r_h = filas_h[0]
                mm_h = r_h["hoy"]
                corto_h, of_h = oficial(e_h)
                if mm_h >= 10:
                    con_h = sum(1 for r in completas.values() if r["hoy"] >= 1)
                    n_h = len(completas)
                    P.add("ayer", "extremo" if mm_h >= 30 else "comparacion",
                          f"La estación de AEMET de {corto_h} lleva {f1(mm_h)} mm el {fecha_dia(hoy_f)} hasta las {int(corte)}:00",
                          f"{f1(mm_h)} mm de 0:00 a {int(corte)}:00 (hora local) del {fecha_dia(hoy_f)}, {lider(filas_h, 'hoy', 'que sigue el observatorio con todas esas horas')}"
                          + (f" · {plural(con_h, 'lleva', 'llevan')} 1 mm o más" if n_h > 1 else "") + of_h,
                          fuente, "Suma de la precipitación horaria de AEMET OpenData desde las 0:00 hasta la última hora cerrada en toda la red. Solo estaciones con todas esas horas.",
                          fecha_dato=hoy_f, pagina="https://calentamientoglobal.es/lluvia-hoy-espana/",
                          contexto=(["Las que más: " + " · ".join(f"{_nombre_corto(e)}: {f1(r['hoy'])} mm" for e, r in filas_h[:5]) + "."] if n_h > 1 else []),
                          limites=[f"Día en curso: la cifra sube a medida que entran horas. Citar siempre con la hora («hasta las {int(corte)}:00»).", alcance])
                    # lo de hoy, primero entre las cifras
                    P.cifras.insert(0, {"etiqueta": f"Lluvia el {fecha_dia(hoy_f)} hasta las {int(corte)}:00", "valor": f"{f1(mm_h)} mm",
                                        "nota": f"{corto_h}, la que más de las que sigue el observatorio", "fuente": "AEMET"})

    # --- noches tropicales (AEMET) --------------------------------------------------
    # Auditoría 17-10-2026: el recuento anual («81 noches tropicales en 2026») sale de un archivo diario con huecos
    # (Valencia sin datos desde abril daba 0; Cartagena, sin datos desde julio, 30). No se publica el recuento:
    # solo la noche concreta que ha medido la estación.
    nt = pj.get("indicadores", {}).get("noches_tropicales") or []
    if nt and nt[0].get("t_min_anoche") is not None and nt[0]["t_min_anoche"] >= 20:
        c = nt[0]
        fna = c.get("fecha_anoche") or D.nocturnas.get("fecha_anoche") or AYER.isoformat()
        P.add("ayer", "extremo", f"Noche tropical en {c['nombre']} el {fecha_dia(fna)}: la estación de AEMET no bajó de {f1(c['t_min_anoche'])} °C",
              f"mínima {f1(c['t_min_anoche'])} °C en la estación de AEMET de {c['nombre']} la noche del {fecha_dia(fna)}",
              "AEMET OpenData", "Mínima diaria de la estación AEMET de la ciudad; noche tropical = mínima ≥ 20 °C.", fecha_dato=fna,
              pagina="https://calentamientoglobal.es/noches-tropicales/")

    # --- índice de desplazamiento climático (nuestro «Climate Shift Index») ---------
    # ¿Cuántas veces más frecuente es la máxima prevista hoy que en 1951-1980? Solo cuando
    # el día era raro entonces (retorno ≥ 1 año): con retornos más cortos el cociente es ruido.
    # El índice de desplazamiento climático se retiró de la sala de prensa el 17-10-2026: compara la
    # previsión de Open-Meteo (modelos de alta resolución en el punto) con un clima de reanálisis de
    # ~25 km; en capitales costeras eso infla el nivel. Vuelve cuando previsión y clima salgan del mismo modelo.

    # --- mar en la boya ------------------------------------------------------------
    for b in (pj.get("indicadores", {}).get("boyas") or [])[:1]:
        if b.get("temp") is not None:
            an = b.get("anomalia_reciente")
            P.cifra(f"Mar en la boya de {b['nombre']}", f"{f1(b['temp'])} °C", f"dato del {fecha_dia(b['fecha'])}" if b.get("fecha") else "", "Puertos del Estado")
            if an is not None and abs(an) >= 1.5:
                P.add("ayer", "comparacion",
                      f"La boya de {b['nombre']} midió el mar a {f1(b['temp'])} °C el {fecha_dia(b['fecha'])}, {f1(abs(an))} °C {'por encima' if an > 0 else 'por debajo'} de lo normal para estas fechas",
                      f"{f1(b['temp'])} °C el {fecha_dia(b['fecha'])} · máximo del año {f1(b['max_anio']['valor'])} °C ({fecha_dia(b['max_anio']['fecha'])})"
                      + (f" · tendencia +{f1(b['tendencia_decada'])} °C por década" if b.get("tendencia_decada") else ""),
                      "Puertos del Estado (REDEXT/REDCOS) vía Copernicus Marine", "Temperatura del agua medida por la boya; normal calculada sobre su propia serie.",
                      fecha_dato=b.get("fecha"), pagina="https://calentamientoglobal.es/temperaturas-del-mar-espana-actualizado/",
                      limites=["COMPROBAR: la «normal» y la anomalía «reciente» salen de un cálculo propio sin auditar (no consta qué días promedia ni contra qué periodo); "
                               "la tendencia, de una serie de unos 20 años con huecos. No se publica sin revisar."])

    # --- canícula / aire ---------------------------------------------------------
    ca = pj.get("indicadores", {}).get("canicula") or {}
    if ca.get("dias_consecutivos", 0) >= 3:
        P.add("ayer", "extremo", f"{P.nombre} encadena {ca['dias_consecutivos']} días por encima del percentil 90 de calor para la fecha",
              f"{ca['dias_consecutivos']} días seguidos · máxima {f1(ca.get('tmax_hoy', 0))} °C · umbral p90 {f1(ca.get('ref_p90', 0))} °C",
              "Open-Meteo · índice propio", "Índice de canícula: días consecutivos con máxima sobre el percentil 90 de 1991-2020 para la fecha.",
              citabilidad="media", pagina="https://calentamientoglobal.es/canicula/",
              limites=["COMPROBAR: índice propio sobre modelo, sin contraste con las estaciones de AEMET; no se publica."])
    for a in (pj.get("indicadores", {}).get("calidad_aire") or [])[:1]:
        if a.get("supera_oms") or a.get("sahariano"):
            P.add("ayer", "comparacion", f"El modelo CAMS de Copernicus da aire «{a['etiqueta']}» en {a['nombre']} el {fecha_dia(HOY.isoformat())}: {a['contaminante_dominante']} por encima del límite de la OMS" if a.get("supera_oms") else f"El modelo CAMS de Copernicus prevé polvo sahariano sobre {a['nombre']} el {fecha_dia(HOY.isoformat())}: calidad del aire «{a['etiqueta']}»",
                  f"índice europeo {a.get('aqi_europeo')} · PM2.5 {a.get('pm25')} µg/m³",
                  "CAMS (Copernicus) vía Open-Meteo", "Calidad del aire modelizada en la capital; límites OMS 2021.", citabilidad="media",
                  limites=["COMPROBAR: es un modelo (celda de unos 10 km), no una estación de la red de calidad del aire; la etiqueta no "
                           "cuadraba con el índice (índice europeo 63 rotulado «Buena»). No se publica."],
                  pagina="https://calentamientoglobal.es/calidad-del-aire/")

    # --- hallazgos del detector de esta provincia --------------------------------
    for h in D.hallazgos.get("enviables", []) + D.hallazgos.get("locales", []):
        if h.get("provincia_slug") == P.slug and h.get("citabilidad") in ("alta", "media"):
            it = P.add("ayer", "record" if h["tipo"] in ("record_fecha", "record_absoluto") else "extremo", h["titular"], h["dato"],
                       h["fuente"], h["metodo"], contexto=h.get("contexto"), limites=h.get("limites"), citabilidad=h["citabilidad"],
                       fecha_dato=h["fecha_dato"], provisional=bool(h.get("provisional")), pagina=h.get("pagina"),
                       csv=h.get("csv"), grafico=h.get("grafico"))
            it["id_hallazgo"] = h["id"]


def sonda_semana(P: Parte, D: Datos, capital: str = ""):
    pr = leer_o(DOCS / "prediccion" / f"{P.cod}.json")
    if not pr or not pr.get("municipios"):
        return
    fuente = pr.get("fuente", "AEMET OpenData · predicción por municipio")
    bruto = []  # (anomalía, municipio, fecha, tx, nx, km, estación)
    lluvia = {}  # fecha → [municipios con pp ≥ 80]
    n_mun = 0
    # Auditoría 17-10-2026 (verificación independiente): (1) solo cuenta la predicción elaborada hoy: en la pasada
    # de la mañana 259 municipios seguían con la del día anterior, y AEMET ya había cambiado San Juan del Puerto
    # (30 → 29 °C), Alfaro (13 → 15 °C) o León (lluvia del 80 % → 40 %); (2) nunca sobre el día en curso, solo días
    # futuros; (3) la normal tiene que tener al menos 25 años del periodo 1991-2020.
    hoy_iso = HOY.isoformat()
    for code, m in pr["municipios"].items():
        dd = m.get("d") or {}
        if not str(dd.get("elab", "")).startswith(hoy_iso):
            continue
        dias = dd.get("dias") or []
        n_mun += 1
        norm = m.get("norm") or {}
        km = num(norm.get("km"), 99)
        anios = num(norm.get("anios"), 0) or 0
        for d in dias:
            if d["f"] <= hoy_iso:
                continue
            # la normal es de una estación de AEMET: solo vale si está cerca del municipio y tiene serie
            if d.get("tx") is not None and d.get("nx") is not None and km <= 25 and anios >= 25:
                bruto.append((d["tx"] - d["nx"], m["n"], d["f"], d["tx"], d["nx"], km, norm.get("nom") or ""))
            if (d.get("pp") or 0) >= 80:
                lluvia.setdefault(d["f"], []).append(m["n"])
    if not n_mun:
        return
    # Auditoría 17-10-2026: la estación «más cercana» puede estar a otra altitud (Castellbisbal se comparaba con
    # Montserrat, a 1.000 m, y salía +9,4 °C). La predicción de AEMET es suave en el espacio: si la desviación de
    # un municipio se separa más de 3 °C de la mediana de la provincia ese día, el fallo es de la normal, no del
    # tiempo, y el municipio no cuenta. Con menos de cinco municipios ese día solo vale una estación a ≤ 10 km.
    por_fecha: dict[str, list] = {}
    for x in bruto:
        por_fecha.setdefault(x[2], []).append(x[0])
    def _mediana(v):
        v = sorted(v)
        n = len(v)
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    anom = []
    est_de = {}
    for x in bruto:
        vals = por_fecha[x[2]]
        if (len(vals) >= 5 and abs(x[0] - _mediana(vals)) <= 3) or (len(vals) < 5 and x[5] <= 10):
            anom.append(x[:5])
            est_de[x[1]] = x[6]
    frio = [x for x in anom if x[0] <= -5]
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
        P.add("semana", "prevision", f"AEMET prevé {int(round(tx))} °C en {mun} {dia_semana(f)}, {f1(a)} °C más de lo normal para la fecha",
              f"máxima prevista {tx} °C · normal 1991-2020 de la estación de AEMET de {est_de.get(mun, 'referencia')}: {f1(nx)} °C · {n_m} de las {n_mun} localidades de la provincia que sigue el observatorio {'supera' if n_m == 1 else 'superan'} lo normal en 5 °C algún día de los próximos seis · predicción de AEMET del {fecha_dia(hoy_iso)}",
              fuente, metodo, limites=limites, fecha_dato=HOY.isoformat(), citabilidad="alta",
              contexto=[f"Municipios con más de 5 °C de exceso: " + ", ".join(sorted({x[1] for x in calor})[:10]) + ("…" if n_m > 10 else "") + "."],
              pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")
    if frio:
        a, mun, f, tx, nx = min(frio)
        P.add("semana", "prevision", f"AEMET prevé solo {int(round(tx))} °C de máxima en {mun} {dia_semana(f)}, {f1(abs(a))} °C menos de lo normal para la fecha",
              f"máxima prevista {tx} °C · normal 1991-2020 de la estación de AEMET de {est_de.get(mun, 'referencia')}: {f1(nx)} °C · {len({x[1] for x in frio})} de las {n_mun} localidades que sigue el observatorio {'queda' if len({x[1] for x in frio}) == 1 else 'quedan'} 5 °C o más por debajo algún día · predicción de AEMET del {fecha_dia(hoy_iso)}",
              fuente, metodo, limites=limites, fecha_dato=HOY.isoformat(), pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")
    if lluvia:
        f = max(lluvia, key=lambda k: len(lluvia[k]))
        n = len(lluvia[f])
        if n >= max(3, n_mun // 4):
            orden = sorted(lluvia[f], key=lambda n: (n != capital, 0))
            P.add("semana", "prevision", f"AEMET da una probabilidad de lluvia del 80 % o más {dia_semana(f)} en {lista_nombres(orden)}",
                  f"{n} de las {n_mun} localidades de {P.nombre} que sigue el observatorio con probabilidad ≥ 80 % el {fecha_dia(f)}"
                  + (" · otros días con la misma probabilidad en al menos " + str(max(3, n_mun // 4)) + " localidades: " + ", ".join(dia_semana(k) for k in sorted(lluvia) if k != f and len(lluvia[k]) >= max(3, n_mun // 4))
                     if any(k != f and len(lluvia[k]) >= max(3, n_mun // 4) for k in lluvia) else "")
                  + f" · predicción de AEMET del {fecha_dia(hoy_iso)}",
                  fuente, "Probabilidad de precipitación diaria de la predicción municipal de AEMET.", limites=limites[:1], fecha_dato=HOY.isoformat(),
                  pagina=f"https://calentamientoglobal.es/el-tiempo/{P.slug}/")
    # media de la semana frente a lo normal
    med = sum(x[0] for x in anom) / len(anom)
    P.cifra("Semana que viene (AEMET)", f"{'+' if med >= 0 else ''}{f1(med)} °C", "máximas frente a lo normal, media de los municipios", "AEMET")
    if abs(med) >= 3 and not calor and not frio:
        P.add("semana", "comparacion", f"Semana {'cálida' if med > 0 else 'fría'} en {P.nombre}: AEMET prevé máximas {f1(abs(med))} °C {'por encima' if med > 0 else 'por debajo'} de lo normal de media",
              f"media de {n_mun} localidades y 6 días · desviación media {'+' if med > 0 else ''}{f1(med)} °C", fuente, metodo, limites=limites, fecha_dato=HOY.isoformat(),
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
        vol = num(f.get("volumen_hm3"))
        # Auditoría 17-10-2026: (1) los «Sistema …» del boletín agrupan varias presas: no son un embalse;
        # (2) el boletín da hm³ enteros, así que por debajo de 20 hm³ un solo hm³ mueve 5 puntos o más y el
        # puesto no es fiable; (3) un empate con el récord no es récord.
        if (pct is None or vol is None or not pos or not de or de < 15 or cap < 20
                or str(f.get("nombre", "")).lower().startswith("sistema")):
            continue
        bol = f.get("boletin_fecha", AYER.isoformat())
        h1a = (f.get("hace_1a") or {}).get("pct")
        sa = f.get("semana_anterior") or {}
        ctx = [f"Hace un año: {pct_txt(h1a)}." if h1a is not None else "",
               f"Media de diez años para la misma semana: {pct_txt(f['pct_media_10a'])}." if f.get("pct_media_10a") is not None else "",
               f"Variación semanal: {'+' if (sa.get('dif_pts') or 0) >= 0 else ''}{f1(sa.get('dif_pts', 0))} puntos." if sa else ""]
        ctx = [c for c in ctx if c]
        lim = ["Dato oficial del MITECO; el ángulo (su puesto en la serie) es cálculo propio."]
        if pct < 1 or vol < 1:
            # Alfonso XIII (Murcia) al 0 %: un embalse vacío suele ser un desembalse por obras o un dato sin
            # reportar, no la sequía. Se publica solo si la confederación lo confirma.
            lim.append("COMPROBAR: embalse por debajo del 1 % (0 hm³). Confirmar con la confederación que no es un vaciado por obras ni un dato sin reportar.")
        base = dict(fuente=fuente, metodo=metodo, fecha_dato=bol, citabilidad="alta", contexto=ctx,
                    pagina=f.get("url_web"), limites=lim)
        nombre = nombre_embalse(f)
        desde = rk.get("desde", 1988)
        # Auditoría 17-10-2026 (verificación independiente): el puesto se calcula por VOLUMEN (hm³) sobre la serie
        # de la misma semana de cada año, con empates. Por porcentaje engañaba cuando la capacidad cambió
        # (Vadomojón pasó de 163 a 146 hm³: era 1.º por % y 6.º por volumen) y contaba los empates como superados
        # (Rules «3.º» empatado con 2019).
        anio_act = int(bol[:4])
        otros = [x for x in (f.get("anual_semana") or []) if x.get("anio") != anio_act and num(x.get("vol_hm3")) is not None]
        if len(otros) + 1 != de:
            continue
        vols = [num(x["vol_hm3"]) for x in otros]
        n_mas = sum(1 for v in vols if v > vol)
        n_menos = sum(1 for v in vols if v < vol)
        empate = any(v == vol for v in vols)
        top = max(otros, key=lambda x: num(x["vol_hm3"]))
        bot = min(otros, key=lambda x: num(x["vol_hm3"]))
        serie_txt = f"en la misma semana del año en los {de} años de su serie, que empieza en {desde}"
        bol_txt = f"boletín del MITECO del {fecha_dia(bol)}"
        if n_mas == 0 and not empate:
            P.add("agua", "record", f"El embalse {nombre} está al {pct_txt(pct)}: nunca había tenido tanta agua {serie_txt}",
                  f"{pct_txt(pct)} ({miles(vol)} de {miles(cap)} hm³) · anterior máximo para esa semana: {miles(top['vol_hm3'])} hm³ ({top['anio']}) · {bol_txt}", **base)
        elif n_menos == 0 and not empate:
            P.add("agua", "record", f"El embalse {nombre} está al {pct_txt(pct)}: nunca había tenido tan poca agua {serie_txt}",
                  f"{pct_txt(pct)} ({miles(vol)} de {miles(cap)} hm³) · anterior mínimo para esa semana: {miles(bot['vol_hm3'])} hm³ ({bot['anio']}) · {bol_txt}", **base)
        elif cap >= 100 and 1 <= n_mas <= 2 and not empate:
            P.add("agua", "extremo", f"El embalse {nombre}, al {pct_txt(pct)}: su {n_mas + 1}.º mayor volumen de agua {serie_txt}",
                  f"{pct_txt(pct)} ({miles(vol)} de {miles(cap)} hm³) · máximo para esa semana: {miles(top['vol_hm3'])} hm³ ({top['anio']}) · {bol_txt}", **base)
        elif cap >= 100 and 1 <= n_menos <= 2 and not empate:
            P.add("agua", "extremo", f"El embalse {nombre}, al {pct_txt(pct)}: su {n_menos + 1}.º menor volumen de agua {serie_txt}",
                  f"{pct_txt(pct)} ({miles(vol)} de {miles(cap)} hm³) · mínimo para esa semana: {miles(bot['vol_hm3'])} hm³ ({bot['anio']}) · {bol_txt}", **base)
        elif h1a is not None and abs(pct - h1a) >= 25:
            # la comparación en puntos solo vale si la capacidad no cambió en el año
            h1 = f.get("hace_1a") or {}
            v1 = num(h1.get("vol_hm3"))
            if not v1 or not h1a or abs(v1 / h1a * 100 - cap) > max(2.0, 0.02 * cap):
                continue
            P.add("agua", "comparacion", f"El embalse {nombre} tiene {f1(abs(pct - h1a))} puntos {'más' if pct > h1a else 'menos'} de agua que hace un año: {pct_txt(pct)} frente a {pct_txt(h1a)}",
                  f"{pct_txt(pct)} ({miles(vol)} de {miles(cap)} hm³) · hace un año {pct_txt(h1a)} ({miles(v1)} hm³) · {bol_txt}", **base)
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
            # Auditoría 17-10-2026: «sube un 54 %» con 4,2 m³/s es ruido de un caudal mínimo. Solo con caudal ≥ 20 m³/s,
            # y con la fecha y la hora local del dato en el titular.
            if v is not None and abs(v) >= 40 and (num(a.get("q"), 0) or 0) >= 20 and a.get("t"):
                try:
                    from zoneinfo import ZoneInfo
                    tl = datetime.fromisoformat(a["t"].replace("Z", "+00:00"))
                    if tl.tzinfo is None:
                        tl = tl.replace(tzinfo=timezone.utc)
                    tl = tl.astimezone(ZoneInfo("Atlantic/Canary" if P.cod in ("35", "38") else "Europe/Madrid"))
                except Exception:
                    continue
                lugar = a['nombre'].split(' en ')[-1]
                P.add("agua", "extremo", f"El {a['rio']} en {lugar} {'subió' if v > 0 else 'bajó'} un {int(abs(v))} % en las 24 horas previas a las {tl:%H:%M} del {fecha_dia(tl.date().isoformat())}: {f1(a['q'])} m³/s",
                      f"{f1(a['q'])} m³/s a las {tl:%H:%M} (hora local) del {fecha_dia(tl.date().isoformat())} · variación en 24 horas {'+' if v > 0 else ''}{f1(v)} %", a.get("fuente_n", "aforo oficial"),
                      "Caudal medido en la estación de aforo del organismo de cuenca, último dato publicado.", fecha_dato=tl.date().isoformat(),
                      limites=["Dato en tiempo real, sujeto a validación del organismo de cuenca."], pagina="https://calentamientoglobal.es/caudal-rios-espana-mapa/")
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
                      citabilidad="media", fecha_dato=emitida, limites=["Caudal simulado, no aforado: en ríos regulados puede diferir del dato real.",
                                                                         "COMPROBAR: es un modelo (GloFAS), no un aforo; no se publica sin contrastarlo con el SAIH de la cuenca."], pagina="https://calentamientoglobal.es/caudal-rios-espana-mapa/")
            elif ph >= 90:
                P.add("agua", "comparacion", f"El {hum['rio']} en {hum['lugar']} lleva un caudal en el percentil {ph}: más agua de la habitual para la fecha",
                      f"percentil {ph} (1997-2025) · tramo GloFAS «{hum['nombre']}»", "GloFAS v4 (Copernicus CEMS)", "Caudal simulado comparado con los percentiles de su época del año (1997-2025).",
                      citabilidad="media", fecha_dato=emitida, limites=["Caudal simulado, no aforado.",
                                                                         "COMPROBAR: es un modelo (GloFAS), no un aforo; no se publica sin contrastarlo con el SAIH de la cuenca."], pagina="https://calentamientoglobal.es/caudal-rios-espana-mapa/")
    # --- nivel del mar ----------------------------------------------------------------
    for n in (pj.get("indicadores", {}).get("nivel_mar") or [])[:1]:
        if n.get("desviacion_cm") is not None and abs(n["desviacion_cm"]) >= 10:
            P.add("agua", "comparacion", f"El nivel del mar frente a {n['nombre']} lleva {n.get('dias_consecutivos', 0)} días {'por encima' if n['desviacion_cm'] > 0 else 'por debajo'} de la media 1993-2012: {'+' if n['desviacion_cm'] > 0 else ''}{f1(n['desviacion_cm'])} cm",
                  f"{'+' if n['desviacion_cm'] > 0 else ''}{f1(n['desviacion_cm'])} cm sobre la media 1993-2012 · {n.get('dias_consecutivos', 0)} días consecutivos",
                  "Copernicus Marine (altimetría)", "Anomalía del nivel del mar en el punto de costa más próximo, frente a la media 1993-2012.", citabilidad="media",
                  limites=["Altimetría de satélite, no mareógrafo: incluye marea meteorológica y variación estacional.",
                           "COMPROBAR: la referencia es la media anual 1993-2012, no lo normal para la estación del año; en otoño el mar está más alto por ciclo estacional. No se publica hasta usar una normal estacional."],
                  pagina="https://calentamientoglobal.es/nivel-del-mar-espana-ahora/")


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
                P.add("municipios", "comparacion", f"{len(secos)} de {len(vals)} municipios de {P.nombre} llevan menos de la mitad de la lluvia normal de otoño, según el reanálisis ERA5; {s['n']}, solo el {s['pct']} %",
                      f"{s['n']} {f1(s['mm'])} mm de {f1(s['normal'])} normales ({s['pct']} %) · media provincial {int(med)} % · el más lluvioso: {h['n']} ({h['pct']} %)",
                      fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta,
                      contexto=[f"El otoño pasado hasta la misma fecha, {s['n']} llevaba {f1(s.get('anterior', 0))} mm."] if s.get("anterior") is not None else [],
                      pagina=f"https://calentamientoglobal.es/lluvia-otono-{P.slug}/")
            elif len(humedos) >= max(2, len(vals) // 3):
                P.add("municipios", "comparacion", f"{len(humedos)} de {len(vals)} municipios de {P.nombre} ya han recogido más de 1,5 veces la lluvia normal de otoño, según el reanálisis ERA5; {h['n']}, el {h['pct']} %",
                      f"{h['n']} {f1(h['mm'])} mm de {f1(h['normal'])} normales ({h['pct']} %) · media provincial {int(med)} % · el más seco: {s['n']} ({s['pct']} %)",
                      fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta, pagina=f"https://calentamientoglobal.es/lluvia-otono-{P.slug}/")
            else:
                P.add("municipios", "cifra", f"Otoño al {int(med)} % de la lluvia normal en {P.nombre}, según el reanálisis ERA5: de {s['n']} ({s['pct']} %) a {h['n']} ({h['pct']} %)",
                      f"{len(vals)} municipios · media {int(med)} % · {len(secos)} por debajo del 50 % · {len(humedos)} por encima del 150 %",
                      fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta, pagina=f"https://calentamientoglobal.es/lluvia-otono-{P.slug}/")
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
                      f"{m[iN]} lleva {'el año más seco' if r == 1 else 'su ' + str(r) + '.º año más seco'} (hasta el {fecha_dia(hasta)}) de la serie del reanálisis ERA5, que empieza en {M.get('desde_anio', 1981)}: {f1(m[iMM])} mm frente a {f1(m[iMed])} de mediana"
                      + (f"; otros {len(secos) - 1} municipios de {P.nombre} están entre los tres más secos" if len(secos) > 1 else ""),
                      f"{f1(m[iMM])} mm hasta el {fecha_dia(hasta)} · mediana {f1(m[iMed])} mm · puesto {m[iP]} de {de} por lluvia", fuente, metodo, limites=lim, citabilidad="media", fecha_dato=hasta,
                      contexto=[f"También entre los tres más secos: " + ", ".join(x[iN] for x in secos[1:8]) + "."] if len(secos) > 1 else [],
                      pagina=f"https://calentamientoglobal.es/cambio-climatico-en-{P.slug}/")
            if humedos:
                m = humedos[0]
                P.add("municipios", "record" if m[iP] == 1 else "extremo",
                      f"{m[iN]} lleva {'el año más lluvioso' if m[iP] == 1 else 'su ' + str(m[iP]) + '.º año más lluvioso'} (hasta el {fecha_dia(hasta)}) de la serie del reanálisis ERA5, que empieza en {M.get('desde_anio', 1981)}: {f1(m[iMM])} mm frente a {f1(m[iMed])} de mediana"
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
        P.add("municipios", "cifra", f"Un modelo climático de alta resolución proyecta para {top['n']} de {top['ch']} a {top['c5']} días de más de 35 °C al año hacia 2035-2050, el mayor salto de la provincia de {P.nombre}",
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
        # días que el archivo propio no llegó a descargar (sin ellos el acumulado se queda corto)
        huecos = []
        try:
            x, fin = date.fromisoformat(A["desde"]), AYER
            while x <= fin:
                if x.isoformat() not in A["dias"]:
                    huecos.append(x)
                x += timedelta(days=1)
        except Exception:
            huecos = [None]
        hoy_av = pj.get("indicadores", {}).get("avisos") or {}
        # Aviso vigente (18-10-2026): AEMET cambia los avisos cada pocas horas (el 17-10 Almería pasó de naranja a rojo
        # a las 14:44), así que el titular lleva la hora de la consulta: «A las 8:30 del 18 de octubre, AEMET tenía…».
        # Así es cierto aunque AEMET lo cambie después. El parte se rehace cada hora.
        AV = D.avisos or {}
        graves_todos = [a for a in AV.get("avisos", []) if a.get("cod") == P.cod and a.get("nivel") in ("rojo", "naranja")]
        if graves_todos and AV.get("generado"):
            try:
                g = datetime.fromisoformat(AV["generado"])
                cuando_txt = f"A las {g.hour}:{g.minute:02d} del {fecha_dia(g.date().isoformat())}"
            except Exception:
                g, cuando_txt = datetime.now(timezone.utc), ""  # sin hora de consulta no se publica
            nivel = "rojo" if any(a["nivel"] == "rojo" for a in graves_todos) else "naranja"
            graves = [a for a in graves_todos if a["nivel"] == nivel]
            tipos = sorted({(a.get("tipo") or "").lower() for a in graves if a.get("tipo")})
            zonas = sorted({a.get("zona") for a in graves if a.get("zona")})
            zonas_txt = (", ".join(zonas[:-1]) + " y " + zonas[-1]) if 1 < len(zonas) <= 3 else (zonas[0] if len(zonas) == 1 else ", ".join(zonas[:3]) + f" y {len(zonas) - 3} zona{'s' if len(zonas) - 3 > 1 else ''} más")

            def _hh(iso):
                return f"{int(iso[11:13])}:{iso[14:16]} del {fecha_dia(iso[:10])}"

            def tramos(avs):
                """Ventanas de aviso de una zona, uniendo las que empalman (23:59 → 0:00 del día siguiente)."""
                xs = sorted((datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"]), a["inicio"], a["fin"])
                            for a in avs if a.get("inicio") and a.get("fin"))
                out = []
                for i, f, i_s, f_s in xs:
                    if out and (i - out[-1][1]).total_seconds() <= 60:
                        if f > out[-1][1]:
                            out[-1][1], out[-1][3] = f, f_s
                    else:
                        out.append([i, f, i_s, f_s])
                return out

            por_zona = {z: tramos([a for a in graves if a.get("zona") == z]) for z in zonas}
            firmas = {tuple((t[2], t[3]) for t in tr) for tr in por_zona.values()}
            intervalo = ""
            if len(firmas) == 1:
                tr = next(iter(por_zona.values()))
                if len(tr) == 1:
                    i_dt, f_dt, i_s, f_s = tr[0]
                    intervalo = (f", vigente hasta las {_hh(f_s)}" if i_dt <= g else f", de las {_hh(i_s)} a las {_hh(f_s)}")
            detalle = " · ".join(f"{z}: " + "; ".join(("hasta las " + _hh(t[3])) if t[0] <= g else (f"de las {_hh(t[2])} a las {_hh(t[3])}") for t in tr)
                                 for z, tr in por_zona.items() if tr)
            fines = [t[1] for tr in por_zona.values() for t in tr]
            if cuando_txt:
                it = P.add("impacto", "record" if nivel == "rojo" else "extremo",
                           f"{cuando_txt}, AEMET tenía aviso {nivel} por {' y '.join(tipos)} en {zonas_txt} ({P.nombre}){intervalo}",
                           cuenta_avisos(graves_todos) + " por zona, fenómeno y tramo horario a esa hora"
                           + (f" · {nivel}: {detalle}" if detalle else ""),
                           AV.get("fuente", "AEMET vía MeteoAlarm"), "Avisos de AEMET (vía MeteoAlarm) vigentes o anunciados en las zonas de la provincia a la hora de la consulta.",
                           fecha_dato=g.date().isoformat(),
                           limites=["Nunca contradecir ni matizar un aviso de AEMET con otro dato.",
                                    "AEMET actualiza los avisos varias veces al día: el titular dice la hora de la consulta; comprobar el estado actual en aemet.es."],
                           pagina="https://calentamientoglobal.es/avisos-meteorologicos/")
                # la web deja de enseñarlo cuando acaba el último tramo (aunque la pasada siguiente no haya llegado)
                if fines:
                    it["caduca"] = max(fines).isoformat()
        if suma >= 10 and not (hoy_av.get("naranjas") or hoy_av.get("rojos")):
            P.add("impacto", "cifra", f"{P.nombre} suma {suma} avisos de AEMET por zona desde el {fecha_dia(A['desde'])}, {tot['naranja'] + tot['rojo']} de ellos naranjas o rojos",
                  f"{plural(tot['rojo'], 'rojo', 'rojos')} · {plural(tot['naranja'], 'naranja', 'naranjas')} · {plural(tot['amarillo'], 'amarillo', 'amarillos')} · {dias_con} días con algún aviso", "AEMET vía MeteoAlarm",
                  "Recuento de avisos-zona por fecha de inicio en las zonas de la provincia.", fecha_dato=AYER.isoformat(),
                  limites=["Serie propia desde julio de 2026: no permite comparar con años anteriores todavía."]
                          + ([f"COMPROBAR: al archivo le faltan {len(huecos)} días sin descargar; el acumulado se queda corto. No se publica."] if huecos else []),
                  pagina="https://calentamientoglobal.es/avisos-meteorologicos/")
    # --- mortalidad por calor ---------------------------------------------------------
    C = D.calor
    pc = (C.get("provincias") or {}).get(P.slug) or (C.get("provincias") or {}).get(P.slug.replace("-", "_"))
    # 20-10-2026: el balance del verano (acaba el 30 de septiembre) deja de ser noticia a los 10 días; en octubre la sala
    # de cada provincia seguía abriendo con «59 muertes atribuibles al calor… entre el 1 de junio y el 30 de septiembre».
    fresco = bool(pc and pc.get("hasta")) and (HOY - date.fromisoformat(str(pc["hasta"])[:10])).days <= 10
    if pc and fresco and pc.get("verano") is not None and pc.get("desde") and pc.get("hasta"):
        # Auditoría 17-10-2026: el dato provincial acaba el 30 de septiembre y el nacional sigue hasta octubre; antes se
        # daban juntos «hasta el 16 de octubre». Ahora el periodo es el del dato provincial y España, el mismo periodo.
        desde_p, hasta_p = pc["desde"], pc["hasta"]
        # Desde el 18-10-2026 el generador guarda el valor diario sin redondear («exacto»): se suma ese y se redondea al final.
        nac_x = sum(float(d.get("exacto", d.get("atribuibles")) or 0) for d in (C.get("dias") or []) if desde_p <= d.get("fecha", "") <= hasta_p)
        nac = int(nac_x + 0.5)
        periodo = f"entre el {fecha_dia(desde_p)} y el {fecha_dia(hasta_p)}"
        # Auditoría 17-10-2026: contrastado con el fichero de datos de MoMo (momo.isciii.es/public/momo/data). El
        # generador redondea cada día antes de sumar, y el total se desvía: Ciudad Real 18 frente a 25,6 de MoMo,
        # Castellón 124 frente a 128,7, España 5.689 frente a 5.684. No se publica hasta que el generador sume los
        # valores sin redondear.
        # Corregido el 18-10-2026 (calor_mortalidad_generar.py suma sin redondear). El aviso solo sigue si el JSON aún
        # no lleva la marca de la suma nueva (la primera pasada del generador corregido rehace todo el histórico).
        redondeo = None if C.get("metodo_suma") == "diaria_sin_redondear" else "COMPROBAR: el generador de calor_mortalidad.json suma valores diarios ya redondeados y el total se aparta del de MoMo (hasta 8 defunciones por provincia). No se publica hasta corregirlo."
        if pc["verano"] >= 20:
            P.add("impacto", "cifra", f"{pc['verano']} muertes atribuibles al calor en {P.nombre} {periodo}, según el sistema MoMo del Instituto de Salud Carlos III",
                  f"{pc['verano']} defunciones atribuibles al exceso de temperatura {periodo}" + (f" · España, en el mismo periodo: {miles(nac)}" if nac else ""),
                  C.get("fuente", "ISCIII · MoMo"), "Estimación estadística del ISCIII del exceso de defunciones atribuible a la temperatura (no son muertes por golpe de calor).",
                  fecha_dato=hasta_p, limites=["Estimación que el ISCIII revisa a medida que entran defunciones: citar como «según la estimación del sistema MoMo»."] + ([redondeo] if redondeo else []),
                  pagina="https://calentamientoglobal.es/muertes-por-calor-espana/")
    # --- incendios -----------------------------------------------------------------
    inc = pj.get("indicadores", {}).get("incendios_ccaa") or {}
    if inc.get("tiene_fuego") and (inc.get("focos_activos") or 0) >= 5:
        P.add("impacto", "cifra", f"Los satélites de la NASA detectaron {inc['focos_activos']} focos de calor en {inc['nombre']} (toda la comunidad) en las 48 horas previas al {fecha_dia(HOY.isoformat())}",
              f"{inc['focos_activos']} focos · {inc.get('dias_consecutivos', 0)} días seguidos con fuego · {inc.get('dias_anio_actual', 0)} días con fuego en 2026",
              "NASA FIRMS (VIIRS)", "Detecciones de puntos calientes por satélite en la comunidad autónoma, ventana de 48 horas.", citabilidad="media", fecha_dato=HOY.isoformat(),
              limites=["Un foco satelital no equivale a un incendio declarado: contrastar con el servicio autonómico.",
                       "COMPROBAR: los focos incluyen quemas agrícolas y fuentes industriales fijas, y los «días con fuego» salen de un archivo propio sin auditar. No se publica."],
              pagina="https://calentamientoglobal.es/incendios-forestales-espana/")
    # Los días de más de 32 °C del punto de reanálisis (dias32.json) se retiraron el 17-10-2026: no coinciden
    # ni con el archivo de capitales ni con las estaciones de AEMET (Castellón: 20 frente a 72 de AEMET).


# ----------------------------------------------------------------------------
# parte por provincia
# ----------------------------------------------------------------------------
def parte_provincia(cod: str, D: Datos) -> dict:
    nombre, slug = PROVINCIAS[cod]
    P = Parte(cod, nombre, slug)
    pj = leer_o(DOCS / "provincias" / f"{SLUG_PROV_JSON.get(slug, slug.replace('-', '_'))}.json", {}) or {}
    for sonda in (lambda: sonda_ayer(P, D, pj), lambda: sonda_semana(P, D, pj.get("capital") or ""), lambda: sonda_agua(P, D, pj),
                  lambda: sonda_municipios(P, D, pj), lambda: sonda_impacto(P, D, pj)):
        try:
            sonda()
        except Exception as e:
            P.errores.append(f"{sonda.__code__.co_name}: {type(e).__name__}: {e}")
    # Auditoría 17-10-2026: la lluvia por municipio sale de la celda del reanálisis ERA5 (unos 25 km) y la proyección
    # 2050 de un solo modelo; ninguna es una medición en el municipio. Quedan en revisión: no salen sin aprobación.
    for h in P.items:
        if h["angulo"] == "municipios" and not h["requiere_revision"]:
            h["limites"] = list(h["limites"]) + ["COMPROBAR: cifra de un municipio calculada con reanálisis o modelo, no medida por AEMET en él. No se publica sin revisión."]
            h["requiere_revision"] = True
    # dedupe por titular y orden por fuerza dentro de cada ángulo
    vistos, items = set(), []
    for h in sorted(P.items, key=lambda h: -h["fuerza"]):
        if h["titular"] in vistos:
            continue
        vistos.add(h["titular"])
        items.append(h)
    angulos = {a: [h for h in items if h["angulo"] == a] for a in ("ayer", "semana", "agua", "municipios", "impacto")}
    # el titular del día sale solo de lo que se publica (nada pendiente de revisión)
    publicables = [h for h in items if not h.get("requiere_revision")]
    titular = max(publicables, key=lambda h: h["fuerza"]) if publicables else None
    return {"generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": HOY.isoformat(), "cod": cod, "provincia": nombre, "slug": slug,
            "capital": pj.get("capital"), "ccaa": pj.get("ccaa"), "titular_del_dia": titular, "angulos": angulos, "cifras": P.cifras,
            "n_items": len(items), "errores": P.errores,
            "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0 · los datos de origen conservan la licencia de su organismo"}


def coincidencias(partes: list[dict]) -> list[dict]:
    """Lo que se repite en muchas provincias es noticia nacional."""
    out = []
    def territorios(ps):
        # Ceuta y Melilla son ciudades autónomas, no provincias
        ciu = [p["provincia"] for p in ps if p["cod"] in ("51", "52")]
        n_prov = len(ps) - len(ciu)
        txt = f"{n_prov} provincia{'s' if n_prov != 1 else ''}"
        if ciu:
            txt += " y en " + " y ".join(ciu)
        return txt
    def cuenta(pred, titulo, dato_fn):
        # solo cuenta lo que la sala de prensa publica (nada en revisión)
        provs = [p for p in partes if any(pred(h) and not h.get("requiere_revision") for h in sum(p["angulos"].values(), []))]
        if len(provs) >= 8:
            out.append({"titular": titulo.format(t=territorios(provs)), "provincias": [p["provincia"] for p in provs], "n": len(provs), "dato": dato_fn(provs)})
    lista = lambda ps: "; ".join(p["provincia"] for p in ps)
    cuenta(lambda h: h["angulo"] == "semana" and "más de lo normal" in h["titular"] and h["clase"] == "prevision",
           f"AEMET prevé máximas al menos 5 °C por encima de lo normal en localidades de {{t}} en los próximos seis días (predicción del {fecha_dia(HOY.isoformat())})", lista)
    cuenta(lambda h: h["angulo"] == "agua" and h["clase"] == "record" and "tan poca agua" in h["titular"],
           "En {t} hay algún embalse con el menor volumen de toda su serie para la misma semana del año", lista)
    cuenta(lambda h: h["angulo"] == "agua" and h["clase"] == "record" and "tanta agua" in h["titular"],
           "En {t} hay algún embalse con el mayor volumen de toda su serie para la misma semana del año", lista)
    # la estación tiene que constar en la provincia (inventario de AEMET), así que el recuento es un mínimo
    cuenta(lambda h: h["angulo"] == "ayer" and "sin recoger 1 mm de lluvia" in h["titular"],
           f"En al menos {{t}} hay alguna estación de AEMET que lleva 10 días o más seguidos sin recoger 1 mm de lluvia (hasta el {fecha_dia(AYER.isoformat())})", lista)
    return out


def destacados(p: dict, n: int = 5) -> list[dict]:
    """Lo más fuerte del parte, un ítem por ángulo primero, sin nada pendiente de revisión."""
    pub = sorted((h for a in p["angulos"].values() for h in a if not h.get("requiere_revision")), key=lambda h: -h["fuerza"])
    elegidos, angulos = [], set()
    for h in pub:
        if h["angulo"] not in angulos:
            elegidos.append(h)
            angulos.add(h["angulo"])
    for h in pub:
        if len(elegidos) >= n:
            break
        if h not in elegidos:
            elegidos.append(h)
    elegidos = sorted(elegidos[:n], key=lambda h: -h["fuerza"])
    return [{k: h.get(k) for k in ("id", "angulo", "clase", "titular", "dato", "contexto", "fuente", "metodo", "limites", "fecha_dato",
                                   "provisional", "pagina", "citabilidad", "fuerza", "caduca")} for h in elegidos]


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
                               "n_publicables": sum(1 for a in p["angulos"].values() for h in a if not h.get("requiere_revision")),
                               "capital": p.get("capital"),
                               "titular": (p["titular_del_dia"] or {}).get("titular"), "angulo": (p["titular_del_dia"] or {}).get("angulo"),
                               "fuerza": (p["titular_del_dia"] or {}).get("fuerza"),
                               # lo que la portada enseña al elegir la provincia: lo más fuerte de cada ángulo, sin nada en revisión
                               "destacados": destacados(p)} for p in partes],
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
