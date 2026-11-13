#!/usr/bin/env python3
"""Carreteras con nieve · lector de las incidencias de la DGT (DATEX II v3.7, perfil DGT) para nieve.py.

Fuente: https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml (se renueva cada minuto, licencia CC BY:
«Fuente: DGT»). Cubre toda España menos Cataluña y el País Vasco.

Cómo marca la DGT la nieve (comprobado en el XSD del perfil 3.7_1.0 y en el fichero real):
  nieve o hielo      sit:poorEnvironmentType = snowfall | frost (en sit:cause/sit:detailedCauseType de cualquier registro
                     o como valor de un registro sit:PoorEnvironmentConditions) y sit:roadMaintenanceType = snowploughsInUse
  cadenas            sit:WinterDrivingManagement con sit:winterEquipmentManagementType = useSnowChainsOrTyres
                     (sit:complianceOption = mandatory; si es advisory no cuenta como obligatorio)
  cerrado            sit:roadOrCarriagewayOrLaneManagementType = roadClosed | carriagewayClosures
  pesados            com:vehicleType = heavyVehicle | largeGoodsVehicle | bus (sin anyVehicle) en un registro de nieve
  nivel de color     no existe en el fichero: nivel_dgt = null
No cuenta sit:avalanches (la DGT lo usa para aludes de tierra, p. ej. un cierre en Gran Canaria).

Sin dependencias: solo la biblioteca estándar.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
URL_MAPA = "https://etraffic.dgt.es/etrafficWEB/"
URL_CATALUNYA = "https://mct.gencat.cat/"            # Servei Català de Trànsit, mapa continu de trànsit
URL_EUSKADI = "https://www.trafikoa.euskadi.eus/"    # Dirección de Tráfico del Gobierno Vasco
TZ = ZoneInfo("Europe/Madrid")
UA = "calentamientoglobal.es/nieve (+https://calentamientoglobal.es/nieve/)"
TIMEOUT_S = 60
REINTENTOS = 2
MAX_HORAS = 6                      # más antiguo que esto, el bloque no se pinta
MAX_HUB = 12                       # tramos del hub

COBERTURA = "Toda España salvo Cataluña y el País Vasco"
FUENTE = "DGT (Dirección General de Tráfico), incidencias DATEX II v3.7"
ESTADOS = ("cerrado", "cadenas", "pesados", "nieve")          # de más a menos grave
CLAVE = {"cerrado": "cerrados", "cadenas": "cadenas", "pesados": "pesados", "nieve": "nieve"}
ETIQUETA = {"cerrado": "Cerrado", "cadenas": "Cadenas", "pesados": "Pesados", "nieve": "Nieve o hielo"}
NIEVE_ENTORNO = {"snowfall", "frost"}
PESADOS = {"heavyVehicle", "largeGoodsVehicle", "bus"}
CIERRES = {"roadClosed", "carriagewayClosures"}
SENTIDOS = {"northBound": "norte", "southBound": "sur", "eastBound": "este", "westBound": "oeste",
            "northEastBound": "noreste", "northWestBound": "noroeste", "southEastBound": "sureste",
            "southWestBound": "suroeste", "clockwise": "horario", "anticlockwise": "antihorario",
            "inboundTowardsTown": "hacia el centro", "outboundFromTown": "desde el centro"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
PUERTO_RE = re.compile(r"\b((?:Puerto|Collado|Alto|Port)\s+(?:de\s+|del\s+|de\s+la\s+|d')?[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]+"
                       r"(?:\s+(?:de\s+la|de\s+los|de\s+las|del|de|la|las|los|el)\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]+"
                       r"|\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]+)*)")


def log(m: str) -> None:
    print(f"[puertos] {m}", flush=True)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _l(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hora(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def _km(x) -> str:
    return (str(int(x)) if float(x) == int(x) else f"{x:.1f}".replace(".", ","))


# ------------------------------------------------------------------------------------------------------ descarga
def descargar(url: str = URL) -> bytes:
    ultimo = None
    for i in range(REINTENTOS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return r.read()
        except Exception as e:           # noqa: BLE001 - se reintenta y se cuenta
            ultimo = e
            if i < REINTENTOS:
                time.sleep(3 * (i + 1))
    raise RuntimeError(f"descarga fallida tras {REINTENTOS + 1} intentos: {type(ultimo).__name__}: {ultimo}")


# ------------------------------------------------------------------------------------------------------- lectura
def _hojas(nodo) -> dict:
    out: dict = {}
    for e in nodo.iter():
        if len(e) == 0 and e.text and e.text.strip():
            out.setdefault(_l(e.tag), []).append(e.text.strip())
    return out


def _punto(nodo) -> dict:
    h = _hojas(nodo)
    g = lambda k: (h.get(k) or [None])[0]
    try:
        lat, lon = float(g("latitude")), float(g("longitude"))
    except (TypeError, ValueError):
        lat = lon = None
    try:
        pk = float(g("kilometerPoint"))
    except (TypeError, ValueError):
        pk = None
    return {"lat": lat, "lon": lon, "pk": pk, "municipio": g("municipality"), "provincia": g("province")}


def _registro(rec) -> dict:
    v = _hojas(rec)
    desde = hasta = None
    for e in rec.iter():
        if _l(e.tag) == "from":
            desde = _punto(e)
        elif _l(e.tag) == "to":
            hasta = _punto(e)
    if desde is None and hasta is None:
        desde = _punto(rec)
    try:
        version = int((rec.get("version") or "0"))
    except ValueError:
        version = 0
    nivel = None
    for e in rec.iter():           # nivel de color de la DGT: solo si el fichero lo trae en las extensiones propias (sse/cse)
        if len(e) == 0 and e.text and e.text.strip() and "SpanishExtension" in e.tag.split("}")[0] \
                and re.search(r"nivel|level|colou?r", _l(e.tag), re.I):
            nivel = e.text.strip()
            break
    return {"id": rec.get("id"), "version": version, "tipo": (rec.get(XSI_TYPE) or "").split(":")[-1], "v": v,
            "desde": desde, "hasta": hasta, "nivel": nivel,
            "textos": " ".join(sum((v.get(k, []) for k in ("generalPublicComment", "roadDestination", "comment")), []))}


def activo(r: dict, ahora: datetime) -> bool:
    v = r["v"]
    if (v.get("informationStatus") or [""])[0] == "test":
        return False
    estado = (v.get("validityStatus") or ["active"])[0]
    if estado not in ("active", "definedByValidityTimeSpec"):
        return False
    fin, ini = _hora((v.get("overallEndTime") or [None])[0]), _hora((v.get("overallStartTime") or [None])[0])
    if fin and fin < ahora:
        return False
    if ini and ini > ahora + timedelta(hours=1):
        return False
    return True


def estado_de(r: dict) -> str | None:
    """El estado más grave del registro, o None si no tiene que ver con la nieve o el hielo."""
    v, tipo = r["v"], r["tipo"]
    equipo = v.get("winterEquipmentManagementType", [])
    nieve = bool(set(v.get("poorEnvironmentType", [])) & NIEVE_ENTORNO) \
        or "snowploughsInUse" in v.get("roadMaintenanceType", []) or tipo == "WinterDrivingManagement" or bool(equipo)
    if not nieve:
        return None
    veh = set(v.get("vehicleType", []))
    solo_pesados = bool(veh & PESADOS) and not (veh - PESADOS)
    if set(v.get("roadOrCarriagewayOrLaneManagementType", [])) & CIERRES:
        return "pesados" if solo_pesados else "cerrado"
    if "useSnowChainsOrTyres" in equipo and "advisory" not in v.get("complianceOption", []):
        return "cadenas"
    if solo_pesados or "weightRestrictionInOperation" in v.get("roadOrCarriagewayOrLaneManagementType", []):
        return "pesados"
    return "nieve"


def _distancia(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class Territorio:
    """provincia de la DGT → slug, y provincia → macizo (por el punto vigilado más cercano si toca dos)."""

    def __init__(self, provincias: list):
        self.por_nombre: dict = {}
        self.provincias = {p["slug"]: p for p in provincias}
        for p in provincias:
            for n in p["nombres"]:
                for parte in [n] + n.split("/"):
                    self.por_nombre[norm(parte)] = p["slug"]

    def slug(self, nombre: str | None) -> str | None:
        return self.por_nombre.get(norm(nombre)) if nombre else None

    def macizo(self, slug: str | None, lat, lon) -> str | None:
        if not slug:
            return None
        ptos = [q for q in self.provincias[slug]["puntos"] if q[2]]
        macs = {q[2] for q in ptos}
        if len(macs) <= 1:
            return next(iter(macs), None)
        if lat is None or lon is None:
            return ptos[0][2]
        return min(ptos, key=lambda q: _distancia((lat, lon), (q[0], q[1])))[2]


def _tramo(r: dict, estado: str, terr: Territorio) -> dict:
    d, h = r["desde"] or {}, r["hasta"] or {}
    prov = d.get("provincia") or h.get("provincia")
    slug = terr.slug(prov) or terr.slug(h.get("provincia"))
    lat, lon = (d.get("lat"), d.get("lon")) if d.get("lat") is not None else (h.get("lat"), h.get("lon"))
    v = r["v"]
    nombre = None
    m = PUERTO_RE.search(r["textos"])
    if m:
        nombre = m.group(1).strip()
    return {"id": r["id"], "carretera": (v.get("roadName") or [None])[0], "pk_ini": d.get("pk"), "pk_fin": h.get("pk"),
            "sentido": SENTIDOS.get((v.get("tpegDirection") or [""])[0]),
            "municipio": d.get("municipio") or h.get("municipio"), "provincia": prov, "provincia_slug": slug,
            "macizo": terr.macizo(slug, lat, lon), "estado": estado, "nivel_dgt": r["nivel"], "puerto": nombre,
            "desde": (lambda t: t.astimezone(TZ).isoformat(timespec="minutes") if t else None)(
                _hora((v.get("overallStartTime") or [None])[0])), "lat": lat, "lon": lon}


def _cuenta(tramos: list) -> dict:
    c = {k: 0 for k in CLAVE.values()}
    for t in tramos:
        c[CLAVE[t["estado"]]] += 1
    return c


def leer(contenido: bytes, terr: Territorio, ahora: datetime) -> dict:
    """Lee el XML con iterparse, vaciando cada registro tras procesarlo."""
    corte, vistos, n_reg = None, {}, 0
    for _ev, el in ET.iterparse(io.BytesIO(contenido), events=("end",)):
        n = _l(el.tag)
        if n == "publicationTime" and corte is None:
            corte = el.text
        elif n == "situationRecord":
            n_reg += 1
            r = _registro(el)
            if r["id"] and activo(r, ahora):
                est = estado_de(r)
                if est:
                    ant = vistos.get(r["id"])
                    if ant is None or r["version"] >= ant[0]["version"]:
                        vistos[r["id"]] = (r, est)
            el.clear()
        elif n == "situation":
            el.clear()
    if n_reg == 0:
        raise RuntimeError("el fichero no trae ningún situationRecord")
    tramos = [_tramo(r, est, terr) for r, est in vistos.values()]
    tramos.sort(key=lambda t: (ESTADOS.index(t["estado"]), t["provincia"] or "", t["carretera"] or "", t["id"]))
    tc = _hora(corte) or ahora
    macs, provs = {}, {}
    for t in tramos:
        if t["macizo"]:
            macs.setdefault(t["macizo"], []).append(t)
        if t["provincia_slug"]:
            provs.setdefault(t["provincia_slug"], []).append(t)
    return {"generado": ahora.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "corte": tc.astimezone(TZ).isoformat(timespec="seconds"), "fuente": FUENTE, "licencia": "CC BY 4.0 (Fuente: DGT)",
            "cobertura": COBERTURA + ": la DGT no publica las carreteras de esos dos territorios.",
            "registros_leidos": n_reg, "totales": _cuenta(tramos),
            "macizos": {k: _cuenta(v) for k, v in sorted(macs.items())},
            "provincias": {k: _cuenta(v) for k, v in sorted(provs.items())}, "tramos": tramos}


# ------------------------------------------------------------------------------------------------ pasada completa
def leer_json(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def anadir_hist(ruta: Path, datos: dict, ahora: datetime) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    t = ahora.astimezone(TZ)
    fila = [t.date().isoformat(), t.strftime("%H:%M")] + [datos["totales"][k] for k in CLAVE.values()]
    nuevo = not ruta.exists()
    if not nuevo:
        ult = ruta.read_text(encoding="utf-8").strip().splitlines()[-1].split(",")
        if ult[:2] == [str(fila[0]), fila[1]]:
            return
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if nuevo:
            w.writerow(["fecha", "hora", "cerrados", "cadenas", "pesados", "nieve"])
        w.writerow(fila)


def actualizar(ruta: Path, ruta_hist: Path, terr: Territorio, ahora: datetime, bajar=descargar):
    """Devuelve (datos, mensaje). Si falla la descarga o la lectura, conserva el puertos.json anterior."""
    previo = leer_json(ruta)
    try:
        datos = leer(bajar(), terr, ahora)
    except Exception as e:                # noqa: BLE001 - nunca para nieve.py
        msg = f"FALLO ({type(e).__name__}: {e}); se conserva el puertos.json anterior" + \
              (f" (corte {previo.get('corte')})" if previo else " (no hay anterior)")
        return previo, msg
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta).write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    anadir_hist(ruta_hist, datos, ahora)
    t = datos["totales"]
    return datos, (f"ok: {datos['registros_leidos']} registros, corte {datos['corte']}; cerrados {t['cerrados']}, cadenas "
                   f"{t['cadenas']}, pesados {t['pesados']}, nieve {t['nieve']}")


def vigente(datos: dict | None, ahora: datetime) -> bool:
    c = _hora((datos or {}).get("corte"))
    return bool(c) and ahora - c <= timedelta(hours=MAX_HORAS)


# ------------------------------------------------------------------------------------------------------- bloque
def _esc(s) -> str:
    return escape(str(s), quote=True)


def _fecha_hora(corte: str) -> str:
    t = _hora(corte).astimezone(TZ)
    return f"las {t:%H:%M} del {t.day} de {MESES[t.month - 1]}"


def _nombre_tramo(t: dict) -> str:
    p = []
    if t.get("carretera"):
        p.append(f"<b>{_esc(t['carretera'])}</b>")
    ks = sorted(x for x in (t.get("pk_ini"), t.get("pk_fin")) if x is not None)
    if len(ks) == 2 and ks[0] != ks[1]:
        p.append(f"pk {_km(ks[0])}-{_km(ks[1])}")
    elif ks:
        p.append(f"pk {_km(ks[0])}")
    mp, pv = t.get("municipio"), t.get("provincia")
    if mp and pv and norm(mp) != norm(pv):
        p.append(f"{_esc(mp)} ({_esc(pv)})")
    elif mp or pv:
        p.append(_esc(mp or pv))
    return " · ".join(p) if p else "Tramo sin identificar"


def _li(t: dict) -> str:
    puerto = f" · {_esc(t['puerto'])}" if t.get("puerto") else ""
    return (f'<li><span class="cgnv-pt-chip cgnv-pt-{t["estado"]}">{ETIQUETA[t["estado"]]}</span> '
            f'{_nombre_tramo(t)}{puerto}</li>')


def frase(c: dict, lugar: str | None, corte: str) -> str:
    partes = []
    n = c["cerrados"]
    if n:
        partes.append(f"{n} tramo{'s' if n != 1 else ''} cerrado{'s' if n != 1 else ''} por nieve o hielo")
    for k, txt in (("cadenas", "con cadenas obligatorias"), ("pesados", "con restricción a camiones y autobuses"),
                   ("nieve", "con nieve o hielo en la calzada")):
        if c[k]:
            partes.append((f"{c[k]} tramo{'s' if c[k] != 1 else ''} " if not partes else f"{c[k]} ") + txt)
    j = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    donde = f" en {lugar}" if lugar else ""
    return f"A {_fecha_hora(corte)}, la DGT tiene{donde} {j}."


def bloque(datos: dict | None, ambito: str, clave: str | None, lugar: str | None, macizos: dict, ahora: datetime,
           enlaces: list | None = None) -> str:
    """HTML del bloque del día. ambito: «hub», «macizo» o «provincia»; clave: id del macizo o slug de la provincia.
    macizos: {id: (slug de página, nombre)} para los enlaces del hub. enlaces: [«cat»|«eus»] de las líneas de cobertura."""
    if not vigente(datos, ahora):
        return ""
    if ambito == "hub":
        tr = datos["tramos"]
        titulo = "Carreteras con nieve ahora: puertos cerrados y con cadenas"
    else:
        tr = [t for t in datos["tramos"] if t["macizo" if ambito == "macizo" else "provincia_slug"] == clave]
        titulo = f"Carreteras con nieve ahora en {lugar}"
    corte = datos["corte"]
    if not tr and ahora.astimezone(TZ).month not in (11, 12, 1, 2, 3, 4, 5):
        return ""
    p = ['<div class="cgnv-pt">', f'<h2 class="cgnv-panel-h2">{_esc(titulo)}</h2>']
    if not tr:
        donde = f" de {lugar}" if ambito != "hub" else ""
        p.append(f'<p class="cgnv-psub">Sin restricciones por nieve en las carreteras{donde} que vigila la DGT, a '
                 f'{_fecha_hora(corte)}.</p>')
    else:
        c = _cuenta(tr)
        p.append(f'<p class="cgnv-psub">{_esc(frase(c, None if ambito == "hub" else lugar, corte))}</p>')
        if ambito == "hub":
            li = []
            for mid, (slug, nombre) in macizos.items():
                cm_ = datos["macizos"].get(mid)
                if not cm_ or not sum(cm_.values()):
                    continue
                det = " · ".join(x for x in (
                    f"{cm_['cerrados']} cerrado{'s' if cm_['cerrados'] != 1 else ''}" if cm_["cerrados"] else "",
                    f"{cm_['cadenas']} con cadenas" if cm_["cadenas"] else "",
                    f"{cm_['pesados']} con restricción a pesados" if cm_["pesados"] else "",
                    f"{cm_['nieve']} con nieve en la calzada" if cm_["nieve"] else "") if x)
                li.append(f'<li class="cgnv-chip-n"><a href="/nieve/{_esc(slug)}/">{_esc(nombre)}</a> '
                          f'<b>{sum(cm_.values())}</b> · {_esc(det)}</li>')
            if li:
                p.append('<ul class="cgnv-chips">' + "".join(li) + "</ul>")
            mostrar = tr[:MAX_HUB]
        else:
            mostrar = tr
        p.append('<ul class="cgnv-pt-l">' + "".join(_li(t) for t in mostrar) + "</ul>")
        if ambito == "hub" and len(tr) > MAX_HUB:
            p.append(f'<p class="cgnv-pie">Los {MAX_HUB} tramos más graves de {len(tr)}. Todos, en las páginas de cada macizo '
                     f'y provincia y en <a href="https://davidbebow.github.io/temperaturas-mar-espana/nieve/puertos.json">'
                     f'puertos.json</a>.</p>')
    extra = ""
    if enlaces and "cat" in enlaces:
        extra += f' Para Cataluña, el <a href="{URL_CATALUNYA}">mapa del Servei Català de Trànsit</a>.'
    if enlaces and "eus" in enlaces:
        extra += f' Para el País Vasco, <a href="{URL_EUSKADI}">Trafikoa, la Dirección de Tráfico del Gobierno Vasco</a>.'
    p.append('<p class="cgnv-pie">Fuente: DGT. No incluye Cataluña ni el País Vasco.' + extra +
             f' <a href="{URL_MAPA}">Mapa de tráfico en vivo de la DGT</a>. El estado cambia en minutos: este bloque se '
             'actualiza tres veces al día y puede ir por detrás de la carretera.</p></div>')
    return "".join(p)
