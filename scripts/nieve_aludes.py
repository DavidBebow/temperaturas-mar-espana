#!/usr/bin/env python3
"""Peligro de aludes · lector de los boletines de AEMET para nieve.py.

Fuente: boletines en PDF de AEMET, en URL fijas bajo
https://www.aemet.es/documentos/es/eltiempo/prediccion/montana/boletin_peligro_aludes/ (índice:
https://www.aemet.es/es/eltiempo/prediccion/montana/boletin_peligro_aludes). Reutilización autorizada citando a AEMET.

Regla de seguridad, por encima de todo: el peligro de aludes no se deduce, no se estima y no se rellena. Se publica el
nivel que AEMET escribe (la palabra de la escala europea: Débil, Limitado, Notable, Fuerte, Muy fuerte), con su zona y su
fecha de validez, o no se publica nada. Cualquier boletín cuyo texto no case exactamente con el formato conocido se
descarta y se anota el motivo.

Formatos conocidos (comprobados con copias reales de web.archive.org, ver tests/aludes_muestras/):
  tabla      Pirineo (navarro y aragonés, catalán): «Pronóstico hasta las 24 horas del jueves, día 29 de enero» y una tabla
             de zonas con su nivel.
  estimación semanales (Guadarrama, Picos de Europa, Cordel y Peña Labra): «Pronóstico para el viernes, día 26» y
             «ESTIMACIÓN DEL NIVEL DE PELIGRO EN LA ESCALA EUROPEA» con un nivel (y, a veces, otro entre paréntesis).
  fin        nota de fin de campaña («se da por finalizada la campaña»): no trae nivel.
El número del nivel no viene en el texto de los PDF: solo la palabra, que es el nivel. El número sale de la escala
europea (1 Débil … 5 Muy fuerte). Si algún día el texto trae número y palabra y no coinciden, se descarta.

Sin dependencias salvo pypdf para leer el PDF (si no está, el boletín se anota como no leído y no se publica nada).
Nunca para nieve.py.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_PDF = "https://www.aemet.es/documentos/es/eltiempo/prediccion/montana/boletin_peligro_aludes/"
URL_INDICE = "https://www.aemet.es/es/eltiempo/prediccion/montana/boletin_peligro_aludes"
URL_OPENDATA = "https://opendata.aemet.es/opendata/api/prediccion/especifica/nivologica/"
URL_ICGC = "https://bpa.icgc.cat/"          # comprobada en Chrome el 13-11-2026; la del Conselh Generau d'Aran no se pudo confirmar
TZ = ZoneInfo("Europe/Madrid")
UA = "calentamientoglobal.es/nieve (+https://calentamientoglobal.es/nieve/)"
TIMEOUT_S = 60
REINTENTOS = 2
MAX_DIAS_SEMANAL = 8                   # un boletín semanal no se pinta pasados 8 días desde su emisión
MESES_TEMPORADA = (12, 1, 2, 3, 4, 5)
FUENTE = "AEMET (Agencia Estatal de Meteorología), boletines de peligro de aludes"
LICENCIA = "Reutilización autorizada por AEMET citándola como autora"

NIVELES = {"débil": 1, "limitado": 2, "notable": 3, "fuerte": 4, "muy fuerte": 5}
NIVEL_TEXTO = {1: "Débil", 2: "Limitado", 3: "Notable", 4: "Fuerte", 5: "Muy fuerte"}
PROBLEMAS = ["Nieve reciente", "Placas de viento", "Nieve venteada", "Capas débiles persistentes", "Nieve húmeda",
             "Deslizamientos basales", "Sin problema evidente", "Favorable"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ESCALA_PIE = ("Válido fuera de las pistas balizadas y abiertas. Con nieve, el peligro nunca es cero. "
              "Consulta el boletín completo antes de salir.")

# id, nombre, fichero, periodicidad, macizo, provincias (slug), area de OpenData (solo las dos del Pirineo)
BOLETINES = [
    {"id": "pirineo-nav-ara", "nombre": "Pirineo navarro y aragonés", "fichero": "BPA_Pirineo_Nav_Ara.pdf",
     "periodicidad": "diario", "macizo": "pirineo", "provincias": ["navarra", "huesca"], "area": 1,
     "nombres": ["Navarra", "Huesca"]},
    {"id": "pirineo-cat", "nombre": "Pirineo catalán", "fichero": "BPA_Pirineo_Cat.pdf",
     "periodicidad": "diario", "macizo": "pirineo", "provincias": ["lleida", "girona"], "area": 0,
     "nombres": ["Lleida", "Girona", "Barcelona"], "opcional": {"barcelona": "Barcelona"}},
    {"id": "guadarrama", "nombre": "Sierra de Guadarrama", "fichero": "BPA_PN_Guadarrama.pdf",
     "periodicidad": "semanal", "macizo": "central", "provincias": ["madrid", "segovia"], "area": None},
    {"id": "picos-europa", "nombre": "Picos de Europa", "fichero": "BPA_PN_Picos_Europa.pdf",
     "periodicidad": "semanal", "macizo": "cantabrica", "provincias": ["asturias", "cantabria", "leon"], "area": None},
    {"id": "cordel-penalabra", "nombre": "Sierras del Cordel y Peña Labra", "fichero": "BPA_sierra_Cordel_PLabra.pdf",
     "periodicidad": "semanal", "macizo": "cantabrica", "provincias": ["cantabria", "palencia"], "area": None},
]
POR_ID = {b["id"]: b for b in BOLETINES}
MACIZOS_CON_BOLETIN = sorted({b["macizo"] for b in BOLETINES})
PROVINCIAS_CON_BOLETIN = sorted({p for b in BOLETINES for p in b["provincias"]})


class Descarte(Exception):
    """El boletín no casa con el formato conocido: no se publica nada de él."""


def log(m: str) -> None:
    print(m, flush=True)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).replace(" ", " ").replace("​", "")


def _l(s: str) -> str:
    return re.sub(r"\s+", " ", _norm(s)).strip()


def url_pdf(b: dict) -> str:
    return BASE_PDF + b["fichero"]


# ------------------------------------------------------------------------------------------------------ descarga y texto
def _get(url: str, cabeceras: dict | None = None, timeout: float = TIMEOUT_S) -> bytes:
    ultimo = None
    for i in range(REINTENTOS + 1):
        try:
            rq = urllib.request.Request(url, headers={"User-Agent": UA, **(cabeceras or {})})
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return r.read()
        except Exception as e:          # noqa: BLE001
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{type(ultimo).__name__}: {ultimo}")


def textos_pdf(datos: bytes) -> tuple[str, str | None]:
    """Texto del PDF con pypdf: (modo normal, modo «layout» o None). Las páginas se unen con salto de línea."""
    import io
    from pypdf import PdfReader        # noqa: PLC0415
    rd = PdfReader(io.BytesIO(datos))
    normal = "\n".join((p.extract_text() or "") for p in rd.pages)
    try:
        lay = "\n".join((p.extract_text(extraction_mode="layout") or "") for p in rd.pages)
    except Exception:                   # noqa: BLE001
        lay = None
    return normal, lay


def lineas(texto: str) -> list[str]:
    """Líneas limpias: sin espacios sobrantes ni líneas vacías."""
    out = []
    for ln in _norm(texto).split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


# --------------------------------------------------------------------------------------------------------------- fechas
def _mes(nombre: str) -> int | None:
    n = _l(nombre).lower()
    return MESES.index(n) + 1 if n in MESES else None


def _dia_sem(nombre: str) -> int | None:
    n = _l(nombre).lower()
    return DIAS.index(n) if n in DIAS else None


RE_EMITIDO = re.compile(r"^(\w+), (\d{1,2}) de (\w+) de (\d{4})(?: \(corrección\))?$", re.I)
RE_ELABORADO = re.compile(r"^Elaborado el día (\d{1,2}) de (\w+) de (\d{4})$", re.I)
RE_HASTA = re.compile(r"^Pronóstico hasta las 24 horas del (\w+),? día (\d{1,2}) de (\w+)$", re.I)
RE_PARA = re.compile(r"^Pronóstico para el (\w+),? día (\d{1,2})$", re.I)
RE_FIN = re.compile(r"se (?:da|dio|dan) por finalizada la campaña", re.I)
RE_FECHA_ISO = re.compile(r"\d{4}-\d{2}-\d{2}$")


def _fecha(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError as e:
        raise Descarte(f"fecha imposible {y}-{m}-{d}") from e


def fecha_emision(ls: list[str]) -> tuple[date, bool]:
    """Fecha de emisión (con el día de la semana comprobado) y si el boletín es una corrección."""
    for ln in ls[:12]:
        m = RE_EMITIDO.match(ln)
        if m and _dia_sem(m.group(1)) is not None and _mes(m.group(3)):
            f = _fecha(int(m.group(4)), _mes(m.group(3)), int(m.group(2)))
            if f.weekday() != _dia_sem(m.group(1)):
                raise Descarte(f"el día de la semana no casa con la fecha de emisión: «{ln}»")
            return f, "(corrección)" in ln
    raise Descarte("no se encuentra la fecha de emisión")


def validez(ls: list[str], emitido: date) -> date:
    """Último día de validez del pronóstico, con el día de la semana comprobado."""
    for ln in ls[:20]:
        m = RE_HASTA.match(ln)
        if m and _dia_sem(m.group(1)) is not None and _mes(m.group(3)):
            for y in (emitido.year, emitido.year + 1):
                f = _fecha(y, _mes(m.group(3)), int(m.group(2)))
                if f >= emitido and (f - emitido).days <= 7:
                    if f.weekday() != _dia_sem(m.group(1)):
                        raise Descarte(f"el día de la semana no casa con la validez: «{ln}»")
                    return f
            raise Descarte(f"la validez queda lejos de la emisión: «{ln}»")
        m = RE_PARA.match(ln)
        if m and _dia_sem(m.group(1)) is not None:
            for k in range(0, 8):
                f = emitido + timedelta(days=k)
                if f.day == int(m.group(2)) and f.weekday() == _dia_sem(m.group(1)):
                    return f
            raise Descarte(f"la validez no casa con la emisión: «{ln}»")
    raise Descarte("no se encuentra la validez del pronóstico")


# ------------------------------------------------------------------------------------------------------------- niveles
RE_NIVEL = re.compile(r"^(?:([1-5])\s*[-–·]?\s*)?(Débil|Limitado|Notable|Fuerte|Muy fuerte)\b(.*)$", re.I)


def nivel_de(num: str | None, palabra: str) -> int:
    """Nivel (1 a 5) de una palabra de la escala; si trae número, tiene que coincidir con la palabra."""
    n = NIVELES.get(_l(palabra).lower())
    if n is None:
        raise Descarte(f"nivel desconocido «{palabra}»")
    if num is not None:
        if not num.isdigit() or not 1 <= int(num) <= 5:
            raise Descarte(f"nivel fuera de 1 a 5: «{num}»")
        if int(num) != n:
            raise Descarte(f"el número {num} no casa con la palabra «{palabra}»")
    return n


def _resto_valido(resto: str) -> bool:
    """Lo que sigue a la palabra del nivel en la misma línea: solo problemas de aludes y/o la fecha de innivación."""
    r = RE_FECHA_ISO.sub("", resto.strip()).strip()
    if not r:
        return True
    for p in sorted(PROBLEMAS, key=len, reverse=True):
        r = re.sub(re.escape(p), "", r, flags=re.I).strip()
    return not r


def _es_nivel(ln: str):
    m = RE_NIVEL.match(ln)
    if m and _resto_valido(m.group(3)):
        return m
    return None


def _problemas_en(texto: str) -> list[str]:
    return [p for p in PROBLEMAS if re.search(re.escape(p), texto, re.I)]


# ---------------------------------------------------------------------------------------------------------------- tabla
RUIDO = (re.compile(r"^Boletín de información nivológica", re.I), re.compile(r"^Grupo de Predicción", re.I),
         re.compile(r"^AEMET\. Se autoriza", re.I), re.compile(r"^\d+/\d+$"), re.compile(r"^\[\[PAGE", re.I),
         re.compile(r"^\[…\]$"), re.compile(r"^Macizo Peligro", re.I), re.compile(r"^Innivación$", re.I),
         re.compile(r"^observada \(m\)$", re.I))


def _limpia_tabla(ls: list[str], titulo: str) -> list[str]:
    out = []
    for ln in ls:
        if any(r.match(ln) for r in RUIDO) or _l(ln) == _l(titulo):
            continue
        out.append(ln)
    return out


def _nombre_zona(trozos: list[str]) -> str:
    """Une las líneas del nombre; un «-» suelto es el guion del nombre (Ribagorzana-Vall Fosca)."""
    s = ""
    for t in trozos:
        if t == "-":
            s = s.rstrip() + "-"
        else:
            s = (s + ("" if s.endswith("-") or not s else " ") + t)
    return _l(s)


def parsear_tabla(ls: list[str]) -> tuple[list[dict], list[str]]:
    """Filas (zona, nivel, problemas) de la tabla del Pirineo y los problemas de aludes de la cabecera."""
    try:
        i0 = next(i for i, ln in enumerate(ls) if re.match(r"^observada \(m\)$", ln, re.I))
    except StopIteration as e:
        raise Descarte("no se encuentra la tabla de zonas") from e
    try:
        i1 = next(i for i, ln in enumerate(ls) if i > i0 and re.match(r"^Estado del manto", ln, re.I))
    except StopIteration as e:
        raise Descarte("no se encuentra el final de la tabla") from e
    titulo = ls[1] if len(ls) > 1 else ""
    cab = " ".join(ls[:i0])
    filas, nombre, nivel, probs = [], [], None, []
    for ln in _limpia_tabla(ls[i0 + 1:i1], titulo):
        m = _es_nivel(ln)
        if m and nivel is None:
            if not nombre:
                raise Descarte("fila de la tabla sin nombre de zona")
            nivel = nivel_de(m.group(1), m.group(2))
            resto = m.group(3).strip()
            probs += _problemas_en(RE_FECHA_ISO.sub("", resto))
            if RE_FECHA_ISO.search(resto):
                filas.append({"nombre": _nombre_zona(nombre), "nivel": nivel, "problemas": probs})
                nombre, nivel, probs = [], None, []
            continue
        if nivel is None:
            # un nombre de zona nunca lleva problemas de aludes ni fecha: si los lleva, falta el nivel de la fila
            if _problemas_en(ln) or re.search(r"\d{4}-\d{2}-\d{2}", ln) or RE_NIVEL.match(ln):
                raise Descarte(f"fila de la tabla sin nivel reconocible: «{ln}»")
            nombre.append(ln)
            continue
        tiene_fecha = bool(re.search(r"\d{4}-\d{2}-\d{2}$", ln))
        resto = RE_FECHA_ISO.sub("", ln).strip()
        if resto:
            ps = _problemas_en(resto)
            if not ps or not _resto_valido(resto):
                raise Descarte(f"línea inesperada en una fila de la tabla: «{ln}»")
            probs += ps
        if tiene_fecha:
            filas.append({"nombre": _nombre_zona(nombre), "nivel": nivel, "problemas": probs})
            nombre, nivel, probs = [], None, []
    if nombre or nivel is not None:
        raise Descarte("la tabla de zonas termina a medias")
    if not filas:
        raise Descarte("la tabla no trae ninguna zona con nivel")
    for f in filas:
        f["problemas"] = list(dict.fromkeys(f["problemas"]))
    return filas, _problemas_en(cab)


# ----------------------------------------------------------------------------------------------------------- estimación
def parsear_estimacion(ls: list[str]) -> tuple[int, int | None, list[str]]:
    """Nivel único de los boletines semanales, el nivel entre paréntesis si lo hay y los problemas de aludes."""
    try:
        i = next(k for k, ln in enumerate(ls) if re.match(r"^ESTIMACIÓN DEL NIVEL$", ln, re.I))
    except StopIteration as e:
        raise Descarte("no se encuentra «ESTIMACIÓN DEL NIVEL»") from e
    resto = [ln.upper() for ln in ls[i + 1:i + 3]]
    if resto != ["DE PELIGRO EN", "LA ESCALA EUROPEA"]:
        raise Descarte("la estimación del nivel no tiene la cabecera conocida")
    j = i + 3
    m = _es_nivel(ls[j]) if j < len(ls) else None
    if not m or m.group(3).strip():
        raise Descarte("no se encuentra el nivel tras la estimación")
    nivel = nivel_de(m.group(1), m.group(2))
    alt = None
    j += 1
    mp = re.match(r"^\((Débil|Limitado|Notable|Fuerte|Muy fuerte)\)$", ls[j], re.I) if j < len(ls) else None
    if mp:
        alt = nivel_de(None, mp.group(1))
        j += 1
    fin = next((k for k in range(j, len(ls)) if re.match(r"^Avance para", ls[k], re.I)), len(ls))
    tabla = " ".join(ls[j:fin])
    return nivel, alt, _problemas_en(tabla)


# ---------------------------------------------------------------------------------------------------------- situación
def situacion(ls: list[str]) -> str | None:
    """Primera frase literal bajo «Evolución del manto y peligro de aludes para …»; None si no es del tipo conocido."""
    for i, ln in enumerate(ls):
        if re.match(r"^Evolución del manto y peligro de aludes para", ln, re.I):
            trozos = []
            for ln2 in ls[i + 1:i + 5]:
                if ln2 == "[…]" or re.match(r"^\[\[PAGE", ln2):
                    break
                trozos.append(ln2)
                if ln2.endswith("."):
                    break
            txt = _l(" ".join(trozos))
            if not txt.endswith("."):
                return None
            frase = re.split(r"(?<=\.)\s+(?=[A-ZÁÉÍÓÚ])", txt)[0]
            if not re.match(r"^(Situación|Problemas?|Nieve|Placas|Capas|Aludes|Deslizamientos|Sin problema)\b", frase) or len(frase) > 220:
                return None
            return frase
    return None


# --------------------------------------------------------------------------------------------------------------- boletín
def parsear(texto: str, b: dict) -> dict:
    """Interpreta el texto de un boletín. Lanza Descarte si algo no casa. Devuelve el dict del boletín (sin vigencia)."""
    ls = lineas(texto)
    if not ls:
        raise Descarte("texto vacío")
    base = {"id": b["id"], "nombre": b["nombre"], "url_pdf": url_pdf(b), "periodicidad": b["periodicidad"],
            "macizo": b["macizo"], "provincias": list(b["provincias"]), "emitido": None, "valido_desde": None,
            "valido_hasta": None, "nivel": None, "nivel_texto": None, "subzonas": [], "situacion": None,
            "problemas": [], "cambio_nivel": None, "fin_campana": False, "motivo_descartado": None}
    for slug, nombre in (b.get("opcional") or {}).items():      # p. ej. Barcelona, solo si el boletín la nombra
        if re.search(rf"\b{nombre}\b", " ".join(ls)):
            base["provincias"].append(slug)
    if RE_FIN.search(" ".join(ls)):
        for ln in ls[:8]:
            m = RE_ELABORADO.match(ln)
            if m and _mes(m.group(2)):
                base["emitido"] = _fecha(int(m.group(3)), _mes(m.group(2)), int(m.group(1))).isoformat()
                break
        base["fin_campana"] = True
        return base
    if not any(re.match(r"^Boletín de información nivológica y de peligro de aludes$", ln, re.I) for ln in ls[:3]):
        raise Descarte("formato desconocido: no es un boletín ni una nota de fin de campaña")
    emitido, correccion = fecha_emision(ls)
    hasta = validez(ls, emitido)
    base.update(emitido=emitido.isoformat(), valido_desde=emitido.isoformat(), valido_hasta=hasta.isoformat())
    if any(RE_HASTA.match(ln) for ln in ls[:20]):
        filas, cab = parsear_tabla(ls)
        nivel = max(f["nivel"] for f in filas)
        base["subzonas"] = [{"nombre": f["nombre"], "nivel": f["nivel"], "nivel_texto": NIVEL_TEXTO[f["nivel"]],
                             "nota": ", ".join(f["problemas"]) or None} for f in filas]
        base["problemas"] = cab or list(dict.fromkeys(p for f in filas for p in f["problemas"]))
    else:
        nivel, alt, probs = parsear_estimacion(ls)
        base["problemas"] = probs
        if alt is not None:
            base["cambio_nivel"] = f"El boletín añade entre paréntesis el nivel {NIVEL_TEXTO[alt]}"
    base["nivel"], base["nivel_texto"] = nivel, NIVEL_TEXTO[nivel]
    base["situacion"] = situacion(ls)
    base["correccion"] = correccion
    return base


def interpretar(textos: list[str], b: dict) -> dict:
    """Prueba los textos (modo normal y «layout» de pypdf) y se queda con el primero que case; si ninguno, el descarte."""
    motivos = []
    for t in textos:
        if not t:
            continue
        try:
            return parsear(t, b)
        except Descarte as e:
            motivos.append(str(e))
    d = _vacio(b)
    d["motivo_descartado"] = "; ".join(dict.fromkeys(motivos)) or "sin texto"
    return d


def _vacio(b: dict) -> dict:
    return {"id": b["id"], "nombre": b["nombre"], "url_pdf": url_pdf(b), "periodicidad": b["periodicidad"],
            "macizo": b["macizo"], "provincias": list(b["provincias"]), "emitido": None, "valido_desde": None,
            "valido_hasta": None, "nivel": None, "nivel_texto": None, "subzonas": [], "situacion": None,
            "problemas": [], "cambio_nivel": None, "fin_campana": False, "motivo_descartado": None}


# ---------------------------------------------------------------------------------------------------------------- vigencia
def vigente(bol: dict, hoy: date) -> bool:
    """Vigente solo si hoy (Europe/Madrid) cae dentro de su validez (y, en los semanales, a ≤ 8 días de la emisión)."""
    if not bol or bol.get("motivo_descartado") or bol.get("fin_campana") or bol.get("nivel") not in (1, 2, 3, 4, 5):
        return False
    try:
        d, h, e = (date.fromisoformat(bol[k]) for k in ("valido_desde", "valido_hasta", "emitido"))
    except (TypeError, ValueError):
        return False
    if not d <= hoy <= h:
        return False
    return not (bol.get("periodicidad") == "semanal" and (hoy - e).days > MAX_DIAS_SEMANAL)


def en_temporada(hoy: date) -> bool:
    return hoy.month in MESES_TEMPORADA


def reparto(boletines: list[dict], hoy: date) -> dict:
    """Nivel máximo vigente por macizo y por provincia, con el boletín del que sale."""
    mac, prov = {}, {}

    def poner(d, clave, bol):
        if clave not in d or bol["nivel"] > d[clave]["nivel"]:
            d[clave] = {"nivel": bol["nivel"], "nivel_texto": bol["nivel_texto"], "boletin": bol["id"],
                        "zona": bol["nombre"], "valido_hasta": bol["valido_hasta"]}

    for bol in boletines:
        if not vigente(bol, hoy):
            continue
        poner(mac, bol["macizo"], bol)
        for p in bol["provincias"]:
            poner(prov, p, bol)
    return {"macizos": mac, "provincias": prov}


# ------------------------------------------------------------------------------------------------------------------ pasada
def _huella(texto: str) -> str:
    return hashlib.sha256("\n".join(lineas(texto)).encode("utf-8")).hexdigest()[:16]


def guardar_crudo(carpeta: Path, nombre: str, contenido: str, ahora: datetime, ext: str = "txt") -> bool:
    """Guarda el texto crudo si cambió respecto al último guardado de ese nombre. Así las muestras de diciembre se recogen solas."""
    carpeta.mkdir(parents=True, exist_ok=True)
    previos = sorted(carpeta.glob(f"{nombre}_*.{ext}"))
    if previos:
        try:
            if _huella(previos[-1].read_text(encoding="utf-8")) == _huella(contenido):
                return False
        except OSError:
            pass
    (carpeta / f"{nombre}_{ahora:%Y-%m-%d_%H%M}.{ext}").write_text(contenido if contenido.endswith("\n") else contenido + "\n",
                                                                    encoding="utf-8")
    return True


def _bajar_boletin(b: dict) -> tuple[str, bytes | None, str | None]:
    try:
        return b["id"], _get(url_pdf(b)), None
    except Exception as e:      # noqa: BLE001
        return b["id"], None, str(e)


def _bajar_opendata(area: int, clave: str) -> tuple[int, dict | None, str | None]:
    try:
        meta = json.loads(_get(URL_OPENDATA + str(area), {"api_key": clave, "Accept": "application/json"}).decode("utf-8"))
        datos = _get(meta["datos"]).decode("utf-8", "replace") if meta.get("datos") else ""
        return area, {"meta": meta, "datos": datos}, None
    except Exception as e:      # noqa: BLE001
        return area, None, str(e)


def leer_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def anadir_hist(ruta: Path, boletines: list[dict]) -> int:
    """Una línea por boletín y por emisión nueva (fecha de emisión, boletín, nivel máximo). No se repite."""
    ya = set()
    if ruta.exists():
        with ruta.open(encoding="utf-8") as f:
            for fila in csv.reader(f):
                if len(fila) >= 2:
                    ya.add((fila[0], fila[1]))
    nuevas = [b for b in boletines if b.get("nivel") in (1, 2, 3, 4, 5) and not b.get("motivo_descartado") and b.get("emitido")
              and (b["emitido"], b["id"]) not in ya]
    if not nuevas:
        return 0
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    with ruta.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["emitido", "boletin", "nivel_maximo"])
        for b in nuevas:
            w.writerow([b["emitido"], b["id"], b["nivel"]])
    return len(nuevas)


def construir_json(boletines: list[dict], ahora: datetime) -> dict:
    hoy = ahora.astimezone(TZ).date()
    out = []
    for b in boletines:
        x = {k: b.get(k) for k in ("id", "nombre", "url_pdf", "emitido", "valido_desde", "valido_hasta")}
        x["periodicidad"] = b.get("periodicidad")
        x["vigente"] = vigente(b, hoy)
        x.update({k: b.get(k) for k in ("nivel", "nivel_texto", "subzonas", "situacion", "problemas", "macizo", "provincias",
                                        "motivo_descartado")})
        x["fin_campana"] = bool(b.get("fin_campana"))
        x["cambio_nivel"] = b.get("cambio_nivel")
        out.append(x)
    r = reparto(boletines, hoy)
    return {"generado": ahora.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fuente": FUENTE,
            "licencia": LICENCIA, "indice": URL_INDICE, "temporada": en_temporada(hoy), "boletines": out,
            "macizos": r["macizos"], "provincias": r["provincias"]}


def actualizar(ruta_json: Path, ruta_hist: Path, carpeta_crudo: Path, ahora: datetime, bajar=None,
               bajar_opendata=None, clave: str | None = None, leer=None) -> tuple[dict, str]:
    """Una pasada: descarga los cinco boletines (en paralelo), guarda el texto crudo si cambió, interpreta y escribe
    aludes.json y aludes_hist.csv. Si un boletín falla, se conserva el anterior (su vigencia se vuelve a comprobar).
    Devuelve (datos, mensaje). Nunca lanza."""
    t0 = time.time()
    previo = leer_json(ruta_json) or {}
    previos = {b["id"]: b for b in previo.get("boletines", [])}
    bajar = bajar or _bajar_boletin
    notas, boletines, crudos = [], [], 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(bajar, b) for b in BOLETINES]
        fut_od = []
        clave = clave if clave is not None else os.environ.get("AEMET_API_KEY", "")
        if clave:
            for area in sorted({b["area"] for b in BOLETINES if b["area"] is not None}):
                fut_od.append(ex.submit(bajar_opendata or _bajar_opendata, area, clave))
        res = {f.result()[0]: f.result() for f in futs}
        od = [f.result() for f in fut_od]
    for b in BOLETINES:
        _, datos, err = res[b["id"]]
        if datos is None:
            antes = previos.get(b["id"])
            notas.append(f"{b['id']}: descarga fallida ({err})" + ("; se conserva el anterior" if antes else ""))
            boletines.append(antes if antes else {**_vacio(b), "motivo_descartado": f"descarga fallida: {err}"})
            continue
        try:
            normal, lay = (leer or textos_pdf)(datos)
        except Exception as e:      # noqa: BLE001
            notas.append(f"{b['id']}: no se pudo leer el PDF ({type(e).__name__}: {e})")
            boletines.append({**_vacio(b), "motivo_descartado": f"no se pudo leer el PDF: {type(e).__name__}"})
            continue
        bol = interpretar([normal, lay], b)
        # el texto crudo se guarda siempre que cambie; si el modo normal no casó, también el «layout»
        crudo = normal if not bol.get("motivo_descartado") else normal + "\n=== layout ===\n" + (lay or "")
        try:
            crudos += guardar_crudo(carpeta_crudo, b["id"], crudo, ahora)
        except OSError as e:
            notas.append(f"{b['id']}: no se pudo guardar el texto crudo ({e})")
        if bol.get("motivo_descartado"):
            notas.append(f"{b['id']}: descartado ({bol['motivo_descartado']})")
        boletines.append(bol)
    for area, datos, err in od:
        if datos is None:
            notas.append(f"OpenData área {area}: {err}")
            continue
        try:
            crudos += guardar_crudo(carpeta_crudo, f"opendata_area{area}", datos["datos"], ahora, "txt")
            crudos += guardar_crudo(carpeta_crudo, f"opendata_area{area}_meta", json.dumps(datos["meta"], ensure_ascii=False,
                                                                                         indent=1), ahora, "json")
        except OSError as e:
            notas.append(f"OpenData área {area}: no se pudo guardar ({e})")
    datos = construir_json(boletines, ahora)
    try:
        ruta_json.parent.mkdir(parents=True, exist_ok=True)
        ruta_json.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        nuevas = anadir_hist(ruta_hist, boletines)
    except OSError as e:
        notas.append(f"no se pudo escribir ({e})")
        nuevas = 0
    vig = sum(1 for b in datos["boletines"] if b["vigente"])
    msg = (f"{vig} boletín(es) vigente(s) de {len(BOLETINES)}, {crudos} texto(s) crudo(s) nuevo(s), {nuevas} línea(s) de histórico"
           + (" · " + "; ".join(notas) if notas else "") + f" · {time.time() - t0:.1f} s")
    return datos, msg


# ------------------------------------------------------------------------------------------------------------- HTML
def _esc(s) -> str:
    return escape(str(s), quote=True)


def fecha_larga(f: date) -> str:
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}"


def _chip(nivel: int) -> str:
    return f'<span class="cgnv-al-chip cgnv-al-n{nivel}">{nivel} · {_esc(NIVEL_TEXTO[nivel])}</span>'


def _validez(bol: dict) -> str:
    h = date.fromisoformat(bol["valido_hasta"])
    e = date.fromisoformat(bol["emitido"])
    if bol["periodicidad"] == "diario":
        return f"válido hasta las 24 horas del {fecha_larga(h)} (emitido el {fecha_larga(e)})"
    return f"válido para el {fecha_larga(h)} (emitido el {fecha_larga(e)})"


def _bloque_bol(bol: dict) -> str:
    p = ['<div class="cgnv-al-b">',
         f'<p class="cgnv-psub">{_chip(bol["nivel"])} <b>{_esc(bol["nombre"])}</b>: {_esc(_validez(bol))}</p>']
    if len(bol["subzonas"]) > 0:
        p.append('<ul class="cgnv-pt-l">' + "".join(
            f'<li><b>{_esc(z["nombre"])}</b> {_chip(z["nivel"])}' + (f' <span>{_esc(z["nota"])}</span>' if z.get("nota") else "")
            + "</li>" for z in bol["subzonas"]) + "</ul>")
    elif bol.get("problemas"):
        p.append(f'<p class="cgnv-psub">Problemas de aludes según el boletín: {_esc(", ".join(bol["problemas"]).lower())}.</p>')
    if bol.get("situacion"):
        p.append(f'<p class="cgnv-psub">«{_esc(bol["situacion"])}» (AEMET)</p>')
    p.append(f'<p class="cgnv-pie"><a href="{_esc(bol["url_pdf"])}">Boletín completo de AEMET (PDF)</a></p></div>')
    return "".join(p)


def _enlaces_cat(ambito: str, clave: str | None) -> str:
    if (ambito == "macizo" and clave == "pirineo") or (ambito == "provincia" and clave in ("lleida", "girona")):
        return (f' Para el Pirineo catalán, el boletín del <a href="{URL_ICGC}">ICGC (Institut Cartogràfic i Geològic de '
                f'Catalunya)</a> y el del Conselh Generau d\'Aran.')
    return ""


def bloque(datos: dict | None, ambito: str, clave: str | None, lugar: str | None, macizos: dict, ahora: datetime) -> str:
    """HTML del bloque «Peligro de aludes». ambito: «hub», «macizo» o «provincia»; clave: id del macizo o slug de la
    provincia; macizos: {id: (slug de página, nombre)} para el hub. Solo pinta boletines vigentes (su vigencia se
    comprueba aquí con la fecha de hoy); sin ninguno vigente, una línea en las páginas con boletín y nada en el hub."""
    if not datos:
        return ""
    hoy = ahora.astimezone(TZ).date()
    todos = datos.get("boletines", [])
    vig = [b for b in todos if vigente(b, hoy)]
    if ambito == "hub":
        if not vig:
            return ""
        li = []
        for b in sorted(vig, key=lambda x: (-x["nivel"], x["nombre"])):
            slug = macizos.get(b["macizo"], (None, None))[0]
            nombre = _esc(b["nombre"])
            li.append('<li class="cgnv-chip-n">' + (f'<a href="/nieve/{_esc(slug)}/">{nombre}</a>' if slug else nombre)
                      + f' {_chip(b["nivel"])} {_esc(_validez(b))}</li>')
        return ('<div class="cgnv-pt cgnv-al"><h2 class="cgnv-panel-h2">Peligro de aludes: boletines de AEMET en vigor</h2>'
                '<ul class="cgnv-chips">' + "".join(li) + '</ul><p class="cgnv-pie">Fuente: AEMET. ' + _esc(ESCALA_PIE)
                + f' <a href="{URL_INDICE}">Boletines de AEMET</a>.</p></div>')
    if ambito == "macizo":
        mios = [b for b in vig if b["macizo"] == clave]
        con_boletin = clave in MACIZOS_CON_BOLETIN
    else:
        mios = [b for b in vig if clave in b["provincias"]]
        con_boletin = clave in PROVINCIAS_CON_BOLETIN
    if not con_boletin and not mios:
        return ""
    titulo = "Peligro de aludes" + (f" en {lugar}" if lugar else "")
    if not mios:
        if en_temporada(hoy):
            linea = "AEMET no tiene hoy un boletín de aludes en vigor para esta zona."
        else:
            linea = "AEMET publica el boletín de peligro de aludes de diciembre a mayo."
        return (f'<div class="cgnv-pt cgnv-al"><h2 class="cgnv-panel-h2">{_esc(titulo)}</h2><p class="cgnv-psub">{linea} '
                f'<a href="{URL_INDICE}">Boletines de aludes de AEMET</a>.{_enlaces_cat(ambito, clave)}</p></div>')
    p = ['<div class="cgnv-pt cgnv-al">', f'<h2 class="cgnv-panel-h2">{_esc(titulo)}</h2>']
    for b in sorted(mios, key=lambda x: (-x["nivel"], x["nombre"])):
        p.append(_bloque_bol(b))
    p.append('<p class="cgnv-pie">' + _esc(ESCALA_PIE) + f' Fuente: AEMET. <a href="{URL_INDICE}">Boletines de AEMET</a>.'
             + _enlaces_cat(ambito, clave) + "</p></div>")
    return "".join(p)


def ficha_macizo(datos: dict | None, mid: str, ahora: datetime) -> dict | None:
    """Campo `aludes` de fichas.json: solo en los macizos con boletín vigente (se recalcula con la fecha de hoy)."""
    if not datos:
        return None
    hoy = ahora.astimezone(TZ).date()
    r = reparto(datos.get("boletines", []), hoy)["macizos"].get(mid)
    if not r:
        return None
    return {"nivel": r["nivel"], "nivel_texto": r["nivel_texto"], "zona": r["zona"], "valido_hasta": r["valido_hasta"]}
