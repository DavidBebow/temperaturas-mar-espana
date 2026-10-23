#!/usr/bin/env python3
"""Dossier de un episodio de lluvia (una DANA, un temporal) para la prensa · calentamientoglobal.es

Todo lo que el observatorio ha medido durante el episodio, en un JSON que pinta el plugin de la sala de prensa
(/prensa/episodio/<id>/) y en un CSV para descargar:

  · Lluvia día a día en cada estación de AEMET (historico_estaciones.json: la observación horaria sumada por día de
    hora local, con la máscara de horas con dato). Total del episodio solo en las estaciones con todos los días
    completos; las demás, «al menos».
  · Contra su historia: el día más lluvioso de cualquier otoño con dato en esa estación (archivo/otonio, valores
    diarios de AEMET 1991-2025), sus tres días seguidos más lluviosos de otoño y, en las estaciones con serie diaria
    larga (archivo/aemet_diario) o mensual desde 1940 (archivo/aemet_mensual, máximo diario de cada mes), su día más
    lluvioso de cualquier mes.
  · El otoño hasta hoy frente a la normal 1991-2020 del mismo pluviómetro (docs/otonio_municipios.json).
  · Avisos de AEMET por provincia y día (docs/avisos_historico.json).
  · Ríos: pico de caudal en los aforos oficiales (Confederación Hidrográfica del Júcar, Agència Catalana de l'Aigua,
    Gobierno de Navarra) desde que empezó el episodio (docs/caudal/aforos.json). Los picos se guardan de una pasada a
    otra: la serie de los aforos solo cubre los últimos 7 días.
  · El Mediterráneo: temperatura del agua (NOAA OISST, análisis de satélite y boyas) y su puesto para la fecha.

Un episodio se cierra solo cuando pasan dos días completos sin ninguna estación con 30 mm o más ni avisos naranja o
rojo. Los episodios se declaran en EPISODIOS (o en docs/prensa/episodios/config.json, que manda si existe).
Solo biblioteca estándar. Uso: python scripts/dossier_episodio.py
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import re
import statistics as st
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
SALIDA = DOCS / "prensa" / "episodios"
MADRID = ZoneInfo("Europe/Madrid")
AHORA = datetime.now(timezone.utc)
HOY = AHORA.astimezone(MADRID).date()
COMPLETO = (1 << 24) - 1
VERSION = "1.0.0"

EPISODIOS = [
    {"id": "dana-adam-2026", "nombre": "dana Adam", "titulo": "La dana Adam, en datos",
     "desde": "2026-10-17", "hasta": None,
     "nota": "AEMET llamó «Adam» a esta DANA el 16 de octubre de 2026, la primera con nombre de la temporada.",
     "nota_fuente": "https://rtvc.es/adam-asi-se-llama-la-primera-dana-de-esta-temporada-16-de-octubre-de-2026/"},
]

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
LLUVIA = "#1F5FA8"
TONOS = ["#0B3C78", "#1F5FA8", "#4F86C6", "#8EB1DA", "#BFD3EA", "#DCE7F4", "#A7B7C9"]
TINTA, GRIS, RAYA = "#16130F", "#5E574E", "#E3DED5"
FUENTE_SVG = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"


# ============================================================================ utilidades
def leer(p, defecto=None):
    try:
        p = Path(p)
        if p.suffix == ".gz":
            with gzip.open(p, "rt", encoding="utf-8") as g:
                return json.load(g)
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defecto


def f1(x):
    from decimal import ROUND_HALF_UP, Decimal
    s = f"{Decimal(str(float(x))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}".replace(".", ",")
    return s[:-2] if s.endswith(",0") else s


def miles(x):
    return f"{int(round(x)):,}".replace(",", ".")


def dia(iso, semana=True, anio=False):
    d = date.fromisoformat(str(iso)[:10])
    return (f"{DIAS[d.weekday()]} " if semana else "") + f"{d.day} de {MESES[d.month - 1]}" + (f" de {d.year}" if anio else "")


def lista_y(xs):
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else (", ".join(xs[:-1]) + " y " + xs[-1] if xs else "")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower())


def tramo_txt(dias_c):
    """«entre el 17 y el 19 de octubre» · «entre el 30 de septiembre y el 2 de octubre» · «el 18 de octubre»."""
    a, b = date.fromisoformat(dias_c[0]), date.fromisoformat(dias_c[-1])
    if a == b:
        return f"el {dia(a, semana=False)}"
    if a.month == b.month:
        return f"entre el {a.day} y el {dia(b, semana=False)}"
    return f"entre el {dia(a, semana=False)} y el {dia(b, semana=False)}"


def rango_txt(ini, n):
    """«del 11 al 13 de noviembre de 2012» (n días desde ini)."""
    a = date.fromisoformat(ini)
    b = a + timedelta(n - 1)
    if a.month == b.month:
        return f"del {a.day} al {b.day} de {MESES[b.month - 1]} de {b.year}"
    return f"del {a.day} de {MESES[a.month - 1]} al {b.day} de {MESES[b.month - 1]} de {b.year}"


def lugar_aforo(x):
    """«Aforament - Sant Vicenç dels Horts (riu - canal de la Dreta)» → «Sant Vicenç dels Horts»."""
    n = re.sub(r"^Aforament\s*-\s*(Qualitat\s*-\s*)?", "", x.get("nombre") or "").strip()
    return re.sub(r"\s*\(.*?\)\s*$", "", n).strip()


def veces(a, b):
    """Cociente redondeado hacia abajo a una décima: «más de X veces» siempre es cierto."""
    return math.floor(a / b * 10) / 10 if b else None


def bonito(n):
    n = (n or "").strip()
    if n.isupper():
        n = n.title()
    n = re.sub(r"/\s+", "/", n)
    n = re.sub(r"(?<=\S) (De|Del|La|El|Los|Las)\b", lambda m: " " + m.group(1).lower(), n)
    return re.sub(r",(?=\S)", ", ", n)


# provincias: código INE ↔ nombre (las mismas que usa la sala)
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import hallazgos_prensa as H  # noqa: E402
    PROV = H.PROVINCIAS
    cod_provincia = H.cod_provincia
except Exception:  # noqa: BLE001
    PROV, cod_provincia = {}, (lambda x: None)


def nprov(cod):
    return PROV[cod][0] if cod in PROV else ""


# ============================================================================ proyección del mapa base
def ajustar_proyeccion():
    """El mapa base (IGN, cónica conforme con Canarias en recuadro) trae los municipios en píxeles; con sus coordenadas
    se ajusta un polinomio de grado 2 lon/lat → x/y, uno para la Península y Baleares y otro para Canarias."""
    M = leer(DOCS / "prensa" / "noticias" / "base" / "mapa_espana.json", {}) or {}
    muni = (leer(DOCS / "municipios.json", {}) or {}).get("items") or []
    if not M.get("mun") or not muni:
        return None, M
    pares = {"pen": [], "can": []}
    for m in muni:
        p = M["mun"].get(m.get("code"))
        if p and m.get("lat") is not None:
            pares["can" if m["code"][:2] in ("35", "38") else "pen"].append((m["lon"], m["lat"], p[0], p[1]))
    coef = {}
    for k, xs in pares.items():
        if len(xs) < 30:
            continue
        A = [[1, lo, la, lo * lo, la * la, lo * la] for lo, la, _, _ in xs]
        coef[k] = [_mc(A, [x[2] for x in xs]), _mc(A, [x[3] for x in xs])]
    return coef, M


def _mc(A, b):
    """Mínimos cuadrados por ecuaciones normales (6 incógnitas), sin numpy."""
    n = len(A[0])
    AtA = [[sum(r[i] * r[j] for r in A) for j in range(n)] for i in range(n)]
    Atb = [sum(r[i] * y for r, y in zip(A, b)) for i in range(n)]
    for i in range(n):  # Gauss-Jordan
        piv = max(range(i, n), key=lambda r: abs(AtA[r][i]))
        AtA[i], AtA[piv] = AtA[piv], AtA[i]
        Atb[i], Atb[piv] = Atb[piv], Atb[i]
        for r in range(n):
            if r != i and AtA[i][i]:
                f = AtA[r][i] / AtA[i][i]
                AtA[r] = [a - f * c for a, c in zip(AtA[r], AtA[i])]
                Atb[r] -= f * Atb[i]
    return [Atb[i] / AtA[i][i] for i in range(n)]


def proyectar(coef, lon, lat):
    if not coef or lon is None or lat is None:
        return None
    k = "can" if lat < 30 else "pen"
    if k not in coef:
        return None
    v = [1, lon, lat, lon * lon, lat * lat, lon * lat]
    return [round(sum(a * b for a, b in zip(coef[k][0], v)), 1), round(sum(a * b for a, b in zip(coef[k][1], v)), 1)]


# ============================================================================ datos
def estaciones_meta():
    """id → nombre bonito, provincia (código INE), lat, lon. De más fiable a menos: inventario de los otoños (nombres
    con mayúsculas y tildes), tabla de récords y el inventario de AEMET."""
    inv = leer(DOCS / "prensa" / "aemet_inventario.json", {}) or {}
    base = (leer(DOCS / "records" / "baseline.json", {}) or {}).get("estaciones") or {}
    crudo_inv = (leer(RAIZ / "archivo" / "otonio" / "crudo_otonios.json.gz", {}) or {}).get("inventario") or {}
    rec = leer(DOCS / "records" / "hoy.json", {}) or {}
    rn = {e["id"]: e.get("n") for e in rec.get("estaciones") or [] if e.get("id") and e.get("n")}
    out = {}
    for c in set(inv) | set(base) | set(crudo_inv):
        b, ci = base.get(c) or {}, crudo_inv.get(c) or {}
        nombre = ci.get("nom") or rn.get(c) or b.get("nombre") or (inv.get(c) or [c])[0]
        cod = b.get("cod") or (cod_provincia(inv[c][1]) if c in inv else None)
        out[c] = {"nombre": bonito(nombre), "cod": cod if cod in PROV else None,
                  "lat": ci.get("lat") or b.get("lat"), "lon": ci.get("lon") or b.get("lon"),
                  "alt": ci.get("alt") or b.get("alt") or (inv.get(c) or [None, None, None])[2]}
    return out


def historia_otono():
    """id → días de otoño (1-9 a 30-11) con dato de 1991-2025: [(fecha, mm)] y años con dato."""
    d = leer(RAIZ / "archivo" / "otonio" / "crudo_otonios.json.gz", {}) or {}
    return d.get("datos") or {}


def max_otono(serie):
    """Día de otoño más lluvioso y tres días seguidos más lluviosos de una estación (crudo de un año → {índice: mm})."""
    dia_max, tres_max, anios = (0.0, None), (0.0, None), 0
    for a, v in serie.items():
        vals = {int(i): m for i, m in v.items() if m is not None}
        if len(vals) < 80:
            continue
        anios += 1
        for i, m in vals.items():
            if m > dia_max[0]:
                dia_max = (m, (date(int(a), 9, 1) + timedelta(i)).isoformat())
            if i + 2 in vals and i + 1 in vals:
                s3 = m + vals[i + 1] + vals[i + 2]
                if s3 > tres_max[0]:
                    tres_max = (s3, (date(int(a), 9, 1) + timedelta(i)).isoformat())
    primero = min((int(a) for a, v in serie.items() if len([m for m in v.values() if m is not None]) >= 80), default=None)
    return {"dia": dia_max, "tres": tres_max, "otonos": anios, "desde": primero}


def max_serie_larga():
    """id → (mm, fecha, primer año) del día más lluvioso en las series diarias largas, y del máximo diario mensual
    desde 1940 (archivo mensual)."""
    out = {}
    est = (leer(RAIZ / "archivo" / "aemet_diario" / "estado.json", {}) or {}).get("estaciones") or {}
    for ide, e in est.items():
        f = RAIZ / "archivo" / "aemet_diario" / f"{ide}.csv.gz"
        if not e.get("completa") or not f.exists():
            continue
        best = (0.0, None)
        with gzip.open(f, "rt", encoding="utf-8") as g:
            for r in csv.DictReader(g):
                try:
                    m = float(r["prec"]) if r["prec"] else None
                except ValueError:
                    m = None
                if m is not None and m > best[0]:
                    best = (m, r["fecha"])
        if best[1]:
            out[ide] = {"mm": best[0], "fecha": best[1], "desde": int((e.get("primer_dia") or "9999")[:4]), "fuente": "diaria"}
    doc = leer(RAIZ / "archivo" / "aemet_mensual" / "mensuales.json.gz", {}) or {}
    if doc:
        ip = doc["campos"].index("p_max")
        for ide, e in (doc.get("estaciones") or {}).items():
            if ide in out:
                continue
            best = (0.0, None)
            for k, r in e["meses"].items():
                if r and r[ip] is not None and r[ip] > best[0]:
                    best = (r[ip], k)
            if best[1]:
                out[ide] = {"mm": best[0], "fecha": best[1], "desde": int(min(e["meses"])[:4]), "fuente": "mensual",
                            "hasta": max(e["meses"])}
    return out


# ============================================================================ gráficos
def _t(x, y, s, size=12, color=GRIS, anchor="start", weight=400):
    s = str(s).replace("&", "&amp;").replace("<", "&lt;")
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" '
            f'font-weight="{weight}" font-family="{FUENTE_SVG}">{s}</text>')


def _svg(w, h, aria, cuerpo):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{aria}">'
            f'<rect width="{w}" height="{h}" fill="#FFFFFF"></rect>' + "".join(cuerpo) + "</svg>")


def grafico_ranking(filas, dias, nombre, titulo):
    """Barras horizontales apiladas por día: las estaciones con más lluvia en el episodio."""
    if not filas:
        return None
    ml = int(min(300, 30 + 7.2 * max(len(f"{x['nombre']} ({nprov(x['cod'])})") for x in filas)))
    W, fila, mr, mt = 760, 28, 70, 40
    Hh = mt + fila * len(filas) + 10
    mx = max(x["total"] for x in filas)
    X = lambda v: ml + v / mx * (W - ml - mr)  # noqa: E731
    s = []
    for j, d in enumerate(dias):
        s.append(f'<rect x="{ml + j * 118}" y="10" width="12" height="12" fill="{TONOS[j % len(TONOS)]}"></rect>')
        s.append(_t(ml + j * 118 + 17, 20, dia(d, semana=False), 11.5, GRIS))
    for i, x in enumerate(filas):
        y = mt + i * fila
        s.append(_t(ml - 8, y + 18, f"{x['nombre']} ({nprov(x['cod'])})", 12.5, TINTA, "end", 600 if i < 3 else 400))
        acc = 0.0
        for j, d in enumerate(dias):
            v = x["dias"].get(d) or 0.0
            if v > 0:
                s.append(f'<rect x="{X(acc):.1f}" y="{y + 5}" width="{max(0.6, X(acc + v) - X(acc)):.1f}" height="18" fill="{TONOS[j % len(TONOS)]}"></rect>')
            acc += v
        s.append(_t(X(acc) + 6, y + 19, f"{f1(x['total'])} mm", 12.5, TINTA, "start", 700 if i < 3 else 500))
    return _svg(W, Hh, titulo, s)


def grafico_mapa(coef, M, estaciones, nombre, titulo):
    if not coef or not M.get("fondo"):
        return None
    W, Hh = M["W"], M["H"]
    s = [f'<path d="{M["fondo"]}" fill="#EFEBE4"></path>', f'<path d="{M["fronteras"]}" fill="none" stroke="#FFFFFF" stroke-width="1"></path>',
         f'<path d="{M["canarias"]}" fill="none" stroke="#C9C2B7" stroke-width="1"></path>']
    pts = []
    for x in estaciones:
        p = proyectar(coef, x.get("lon"), x.get("lat"))
        if p and 0 <= p[0] <= W and 0 <= p[1] <= Hh:
            pts.append((x["total"], p, x))
    for mm, p, x in sorted(pts, key=lambda z: z[0]):
        if mm < 1:
            s.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="1.8" fill="#C9C2B7"></circle>')
            continue
        r = 2.2 + min(16.0, math.sqrt(mm) * 0.62)
        color = TONOS[0] if mm >= 200 else TONOS[1] if mm >= 100 else TONOS[2] if mm >= 50 else TONOS[3] if mm >= 20 else TONOS[4]
        s.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="{r:.1f}" fill="{color}" fill-opacity="0.82" stroke="#fff" stroke-width="0.7"></circle>')
    # etiquetas de las que más llovió, sin pisarse: se prueba a la derecha, a la izquierda, arriba y abajo
    cajas = []
    for mm, p, x in sorted(pts, key=lambda z: -z[0])[:8]:
        txt = f"{x['nombre']} {f1(mm)}"
        w, h = 6.4 * len(txt), 13
        r = 2.2 + min(16.0, math.sqrt(mm) * 0.62)
        for dx, dy, anc in ((r + 4, 4, "start"), (-r - 4, 4, "end"), (0, -r - 5, "middle"), (0, r + 13, "middle")):
            x0 = p[0] + dx - (w if anc == "end" else w / 2 if anc == "middle" else 0)
            caja = (x0, p[1] + dy - 11, x0 + w, p[1] + dy - 11 + h)
            if caja[0] < 2 or caja[2] > W - 2 or any(not (caja[2] < c[0] or caja[0] > c[2] or caja[3] < c[1] or caja[1] > c[3]) for c in cajas):
                continue
            cajas.append(caja)
            s.append(f'<text x="{p[0] + dx:.1f}" y="{p[1] + dy:.1f}" font-size="11" font-weight="700" text-anchor="{anc}" font-family="{FUENTE_SVG}" '
                     f'fill="{TINTA}" stroke="#FFFFFF" stroke-width="3" paint-order="stroke">{txt.replace("&", "&amp;")}</text>')
            break
    leyenda = [(TONOS[0], "200 mm o más"), (TONOS[1], "100-200"), (TONOS[2], "50-100"), (TONOS[3], "20-50"), (TONOS[4], "1-20")]
    for j, (c, l) in enumerate(leyenda):
        s.append(f'<circle cx="{W - 120}" cy="{Hh - 110 + j * 18}" r="6" fill="{c}"></circle>')
        s.append(_t(W - 108, Hh - 106 + j * 18, l, 11, GRIS))
    return _svg(W, Hh, titulo, s)


def grafico_dias(dias_res, nombre, titulo):
    """Columnas: estaciones con 50 mm o más y con 100 mm o más cada día."""
    W, Hh, ml, mr, mt, mb = 640, 260, 40, 16, 44, 40
    mx = max([d["n50"] for d in dias_res] + [1])
    tope = max(5, math.ceil(mx * 1.15 / 5) * 5)
    Y = lambda v: mt + (1 - v / tope) * (Hh - mt - mb)  # noqa: E731
    bw = (W - ml - mr) / max(1, len(dias_res))
    s = [f'<rect x="{ml}" y="8" width="12" height="12" fill="{TONOS[2]}"></rect>', _t(ml + 18, 18, "Estaciones con 50 mm o más", 12, GRIS),
         f'<rect x="{ml + 220}" y="8" width="12" height="12" fill="{TONOS[0]}"></rect>', _t(ml + 238, 18, "con 100 mm o más", 12, GRIS)]
    for t in range(0, tope + 1, max(1, tope // 5)):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{RAYA}"></line>')
        s.append(_t(ml - 6, Y(t) + 4, str(t), 11, GRIS, "end"))
    for i, d in enumerate(dias_res):
        x0 = ml + i * bw + 8
        w = (bw - 22) / 2
        s.append(f'<rect x="{x0:.1f}" y="{Y(d["n50"]):.1f}" width="{w:.1f}" height="{Y(0) - Y(d["n50"]):.1f}" fill="{TONOS[2]}"></rect>')
        s.append(f'<rect x="{x0 + w + 4:.1f}" y="{Y(d["n100"]):.1f}" width="{w:.1f}" height="{Y(0) - Y(d["n100"]):.1f}" fill="{TONOS[0]}"></rect>')
        s.append(_t(x0 + w / 2, Y(d["n50"]) - 5, str(d["n50"]), 11, TINTA, "middle", 700))
        s.append(_t(x0 + w + 4 + w / 2, Y(d["n100"]) - 5, str(d["n100"]), 11, TINTA, "middle", 700))
        s.append(_t(x0 + w + 2, Hh - mb + 16, dia(d["fecha"], semana=False), 11, GRIS, "middle"))
        if not d.get("completo"):
            s.append(_t(x0 + w + 2, Hh - mb + 30, f"hasta las {d.get('hasta_hora', 0)}:00", 10, GRIS, "middle"))
    return _svg(W, Hh, titulo, s)


def diarios_validados():
    """{día: {estación: mm}} con los valores diarios VALIDADOS de AEMET de 2026 (archivo/otonio/diarios_2026.json, que baja
    el flujo del otoño por pluviómetro). Son días pluviométricos: de las 07:00 UTC del día a las 07:00 UTC del siguiente."""
    d = leer(RAIZ / "archivo" / "otonio" / "diarios_2026.json", {}) or {}
    out = {}
    for ini, tr in (d.get("trozos") or {}).items():
        try:
            d0 = date.fromisoformat(ini)
        except ValueError:
            continue
        # 23-10-2026: la clave de cada valor es el día del otoño contado desde el 1 de septiembre (0 = 1-9), no desde el
        # inicio del trozo: el trozo del 16-10 trae 45..49 (16 a 20 de octubre).
        base = date(d0.year, 9, 1)
        for e, vals in (tr.get("datos") or {}).items():
            for k, v in (vals or {}).items():
                if v is not None:
                    out.setdefault((base + timedelta(int(k))).isoformat(), {})[e] = float(v)
    return out


# ============================================================================ episodio
def construir(ep, prev):
    hist = leer(RAIZ / "historico_estaciones.json", {}) or {}
    # 21-10-2026: el día de lluvia de AEMET va de 07:00 a 07:00 UTC. Sumando de 0 a 24 h, la tromba de Pego quedaba partida
    # en 168 y 465,2 mm (18 y 19 de octubre), cuando AEMET y la prensa dan 620,6 en el día pluviométrico del 18; y los
    # récords con los que se compara salen de días de AEMET. Por estación, si todos los días del episodio están validados o
    # en el histórico pluviométrico (07-07 UTC) se usan esos; si no, la suma de 0 a 24 h, y se dice.
    hist_p = leer(RAIZ / "historico_pluviometrico.json", {}) or {}
    validados = diarios_validados()
    meta = estaciones_meta()
    oto = historia_otono()
    largas = max_serie_larga()
    avh = (leer(DOCS / "avisos_historico.json", {}) or {}).get("dias") or {}
    O = leer(DOCS / "otonio_municipios.json", {}) or {}
    desde = date.fromisoformat(ep["desde"])
    tope = date.fromisoformat(ep["hasta"]) if ep.get("hasta") else HOY
    dias_todos = [desde + timedelta(i) for i in range((tope - desde).days + 1)]
    dias_todos = [d for d in dias_todos if d.isoformat() in hist]
    if not dias_todos:
        return None

    # qué días están completos: la mayoría de la red con las 24 horas
    def completo(d):
        v = hist.get(d.isoformat()) or {}
        return sum(1 for x in v.values() if x and int(x[1]) == COMPLETO) >= 0.6 * max(1, len(v))
    cerrados = [d for d in dias_todos if completo(d)]
    abierto = [d for d in dias_todos if not completo(d)]

    # ¿sigue el episodio? Día activo: alguna estación con 30 mm o más, o aviso naranja o rojo ese día
    def activo(d):
        v = hist.get(d.isoformat()) or {}
        mx = max((x[0] for x in v.values() if x and x[0] is not None and int(x[1]) == COMPLETO), default=0)
        a = avh.get(d.isoformat()) or {}
        return mx >= 30 or (a.get("rojo") or 0) + (a.get("naranja") or 0) > 0
    act = [d for d in cerrados if activo(d)]
    cierre = None
    if ep.get("hasta"):
        cierre = date.fromisoformat(ep["hasta"])
    elif act and cerrados and (cerrados[-1] - act[-1]).days >= 2:
        cierre = act[-1]
    if cierre:
        cerrados = [d for d in cerrados if d <= cierre]
        abierto = [] if cierre < HOY else abierto
    dias_c = [d.isoformat() for d in cerrados]

    # estación a estación
    est = []
    for c in sorted({k for d in dias_c for k in (hist.get(d) or {})} | {k for d in abierto for k in (hist.get(d.isoformat()) or {})}):
        m = meta.get(c) or {}
        if not m.get("cod"):
            continue
        valores, todos = {}, True
        pluv = {}
        for d in dias_c:
            v_ok = (validados.get(d) or {}).get(c)
            xp = (hist_p.get(d) or {}).get(c)
            if v_ok is not None:
                pluv[d] = (round(v_ok, 1), "validado")
            elif xp and xp[0] is not None and int(xp[1]) == COMPLETO:
                pluv[d] = (round(float(xp[0]), 1), "pluviometrico")
        if dias_c and len(pluv) == len(dias_c):
            valores = {d: v for d, (v, _) in pluv.items()}
            fuente_dias = "validado" if all(f == "validado" for _, f in pluv.values()) else "pluviometrico"
        else:
            fuente_dias = "horario_0_24"
            for d in dias_c:
                x = (hist.get(d) or {}).get(c)
                if x and x[0] is not None and int(x[1]) == COMPLETO:
                    valores[d] = round(float(x[0]), 1)
                else:
                    valores[d] = None
                    todos = False
        conocido = [v for v in valores.values() if v is not None]
        if not conocido:
            continue
        total = round(sum(conocido), 1)
        hoy = None
        for d in abierto:
            x = (hist.get(d.isoformat()) or {}).get(c)
            if x and x[0] is not None:
                h = bin(int(x[1])).count("1")
                if int(x[1]) == (1 << h) - 1:
                    hoy = {"fecha": d.isoformat(), "mm": round(float(x[0]), 1), "horas": h}
        mx = max(((v, d) for d, v in valores.items() if v is not None), default=(0.0, None))
        alineado = fuente_dias in ("validado", "pluviometrico")
        r = {"id": c, "nombre": m["nombre"], "cod": m["cod"], "lat": m.get("lat"), "lon": m.get("lon"), "alt": m.get("alt"),
             "dias": valores, "total": total, "completo": todos, "max": mx[0], "max_fecha": mx[1], "hoy": hoy, "fuente_dias": fuente_dias,
             "validados": sorted(d for d, (_v, f) in pluv.items() if f == "validado") if fuente_dias != "horario_0_24" else []}
        # contra su historia de otoño (1991-2025)
        if c in oto:
            h = max_otono(oto[c])
            if h["otonos"] >= 10:
                tres, tres_ini = 0.0, None
                for i in range(len(dias_c) - 2):
                    vs = [valores[dias_c[i + k]] for k in range(3)]
                    if all(v is not None for v in vs) and sum(vs) > tres:
                        tres, tres_ini = sum(vs), dias_c[i]
                r["otono_hist"] = {"otonos": h["otonos"], "desde": h["desde"], "dia_max": h["dia"][0], "dia_fecha": h["dia"][1],
                                   "tres_max": round(h["tres"][0], 1), "tres_fecha": h["tres"][1], "tres_ep": round(tres, 1) if tres else None,
                                   "tres_ep_ini": tres_ini.isoformat() if hasattr(tres_ini, "isoformat") else tres_ini,
                                   # 21-10-2026 (David): un récord de un día o de tres solo se da con días de AEMET (07-07 UTC),
                                   # los mismos de la serie con la que se compara; con la suma de 0 a 24 h, no.
                                   "record_dia": alineado and mx[0] > h["dia"][0], "record_tres": bool(alineado and tres and tres > h["tres"][0])}
        if c in largas:
            L = largas[c]
            r["serie_larga"] = dict(L, record=alineado and mx[0] > L["mm"])
        est.append(r)
    # otoño hasta hoy en el mismo pluviómetro
    por_est = {}
    for k, m in (O.get("municipios") or {}).items():
        if m.get("propia") and m.get("est") and m.get("normal") and m.get("mm") is not None:
            por_est.setdefault(m["est"], m)
    for r in est:
        m = por_est.get(r["id"])
        if m:
            r["otono"] = {"mm": m["mm"], "normal": m["normal"], "pct": m.get("pct"), "normal_total": m.get("normal_total"),
                          "hasta": m.get("hasta"), "periodo": m.get("periodo")}

    # dos estaciones con el mismo nombre en la misma provincia (Grazalema): se distinguen por su indicativo
    vistos = {}
    for r in est:
        vistos.setdefault((r["cod"], r["nombre"]), []).append(r)
    for (_, _), rs in vistos.items():
        if len(rs) > 1:
            for r in rs:
                r["nombre"] = f"{r['nombre']} ({r['id']})"
    completas = sorted((r for r in est if r["completo"]), key=lambda r: -r["total"])
    # resumen por día
    dias_res = []
    for d in dias_c + [x.isoformat() for x in abierto]:
        v = hist.get(d) or {}
        ok = d in dias_c
        vals = [(round(float(x[0]), 1), k) for k, x in v.items() if x and x[0] is not None and (int(x[1]) == COMPLETO if ok else True)
                and (meta.get(k) or {}).get("cod")]
        top = max(vals, default=(0.0, None))
        a = avh.get(d) or {}
        pp = a.get("por_provincia") or {}
        hh = None
        if not ok:
            masks = [int(x[1]) for x in v.values() if x]
            hh = max((bin(m).count("1") for m in masks if m == (1 << bin(m).count("1")) - 1), default=0)
        dias_res.append({"fecha": d, "completo": ok, "hasta_hora": hh, "estaciones": len(vals),
                         "max": {"mm": top[0], "id": top[1], "nombre": (meta.get(top[1]) or {}).get("nombre"), "cod": (meta.get(top[1]) or {}).get("cod")},
                         "n50": sum(1 for m, _ in vals if m >= 50), "n100": sum(1 for m, _ in vals if m >= 100), "n200": sum(1 for m, _ in vals if m >= 200),
                         "rojo": sorted(p for p, x in pp.items() if x.get("rojo")), "naranja": sorted(p for p, x in pp.items() if x.get("naranja") and not x.get("rojo")),
                         "avisos": {"rojo": a.get("rojo", 0), "naranja": a.get("naranja", 0), "amarillo": a.get("amarillo", 0)}})
    # provincias
    provs = {}
    for r in est:
        p = provs.setdefault(r["cod"], {"cod": r["cod"], "nombre": nprov(r["cod"]), "estaciones": 0, "max": None, "max_dia": None, "n100": 0, "n50": 0})
        p["estaciones"] += 1
        if r["completo"]:
            if not p["max"] or r["total"] > p["max"]["total"]:
                p["max"] = {"id": r["id"], "nombre": r["nombre"], "total": r["total"]}
            p["n100"] += r["total"] >= 100
            p["n50"] += r["total"] >= 50
        if r["max_fecha"] and r.get("fuente_dias") != "horario_0_24" and (not p["max_dia"] or r["max"] > p["max_dia"]["mm"]):
            p["max_dia"] = {"id": r["id"], "nombre": r["nombre"], "mm": r["max"], "fecha": r["max_fecha"]}
    for d in dias_res:
        for nivel in ("rojo", "naranja"):
            for pn in d[nivel]:
                c = cod_provincia(pn)
                if c in provs:
                    provs[c].setdefault("avisos", []).append({"fecha": d["fecha"], "nivel": nivel})
    # ríos: pico desde que empezó el episodio, guardado de una pasada a otra
    picos = {x["id"]: x for x in (prev or {}).get("rios") or []}
    A = leer(DOCS / "caudal" / "aforos.json", {}) or {}
    t0 = datetime.combine(desde, datetime.min.time(), MADRID).astimezone(timezone.utc)
    t1 = datetime.combine(cierre + timedelta(days=1), datetime.min.time(), MADRID).astimezone(timezone.utc) if cierre else AHORA
    for e in A.get("estaciones") or []:
        serie = [(datetime.fromisoformat(t.replace("Z", "+00:00")), q) for t, q in e.get("serie") or [] if q is not None]
        antes = [q for t, q in serie if t < t0]
        durante = [(q, t) for t, q in serie if t0 <= t <= t1]
        if not durante:
            continue
        if re.search(r"salida del embalse", e.get("nombre") or "", re.I):
            continue  # es lo que suelta una presa, no la crecida del río
        q, t = max(durante)
        base = st.median(antes) if len(antes) >= 6 else None
        x = picos.get(e["id"])
        if x and x["pico"] >= q:
            continue
        cod = e.get("prov") or (x or {}).get("cod")
        picos[e["id"]] = {"id": e["id"], "nombre": e.get("nombre"), "rio": e.get("rio"), "fuente": e.get("fuente_n") or e.get("fuente"),
                          "cod": cod, "pico": round(q, 2), "pico_t": t.astimezone(MADRID).isoformat(timespec="minutes"),
                          "base": round(base, 2) if base is not None else (x or {}).get("base"), "lat": e.get("lat"), "lon": e.get("lon")}
    rios = sorted((x for x in picos.values() if x["pico"] >= 10 and (x.get("base") is None or x["pico"] >= 5 * max(x["base"], 0.5))),
                  key=lambda x: -x["pico"])[:20]
    # el mar
    med = leer(DOCS / "dana" / "mediterraneo.json", {}) or {}
    mar = None
    if med.get("ultimo") and med["ultimo"] >= (desde - timedelta(days=3)).isoformat():
        segundo = None
        hist_m = (leer(DOCS / "dana" / "mediterraneo_historico.json", {}) or {}).get("v") or {}
        try:
            md = med["ultimo"][5:]
            otros = sorted(((float(v), int(f[:4])) for f, v in hist_m.items() if f[5:] == md and f[:4] != med["ultimo"][:4] and v is not None),
                           reverse=True)
            if otros:
                segundo = [otros[0][1], otros[0][0]]
        except Exception:  # noqa: BLE001
            segundo = None
        mar = {"fecha": med["ultimo"], "sst": med.get("sst"), "normal": med.get("normal"), "anomalia": med.get("anomalia"), "segundo": segundo,
               "desde": int(min(hist_m)[:4]) if hist_m else None,
               "puesto": med.get("puesto_para_la_fecha"), "de": med.get("de"), "zona": med.get("zona"), "fuente": med.get("fuente")}
    return {"est": est, "completas": completas, "dias": dias_res, "dias_c": dias_c, "abierto": [d.isoformat() for d in abierto],
            "provs": provs, "rios": rios, "mar": mar, "cierre": cierre.isoformat() if cierre else None}


def claves(ep, B):
    """Las frases para la prensa: cada una con su cifra y su fuente. Solo lo que dicen los datos."""
    out = []
    F_OBS = "AEMET OpenData (observación horaria sumada por día); cálculo de calentamientoglobal.es"
    dias_c, comp = B["dias_c"], B["completas"]
    if not dias_c:
        return out
    tramo = tramo_txt(dias_c)
    # el día más lluvioso del episodio
    top_dia = max((r for r in B["est"] if r["max_fecha"]), key=lambda r: r["max"], default=None)
    # 21-10-2026 (David): la cifra de un solo día solo se da con el día de AEMET (07-07 UTC); la suma de 0 a 24 h no coincide
    # con la oficial (Pego: 465,2 el 19 frente a 620,6 en el día pluviométrico del 18). Hasta entonces, solo totales.
    if top_dia and top_dia.get("fuente_dias") == "horario_0_24":
        top_dia = None
    if top_dia:
        cero24 = False
        t = (f"La estación de AEMET de {top_dia['nombre']} ({nprov(top_dia['cod'])}) recogió {f1(top_dia['max'])} mm "
             + (f"el {dia(top_dia['max_fecha'])}, contando de 0 a 24 h (AEMET cuenta el día de lluvia de 07:00 a 07:00 UTC y publica el dato "
                "validado unos días después)" if cero24 else f"en el día pluviométrico del {dia(top_dia['max_fecha'])} (de 07:00 a 07:00 UTC)")
             + ", la cifra diaria más alta del episodio")
        oh = top_dia.get("otono_hist")
        if oh and oh["record_dia"]:
            v = veces(top_dia["max"], oh["dia_max"])
            t += (f"; es el día de otoño más lluvioso en los registros de la estación desde {oh['desde']}: su máximo anterior eran "
                  f"{f1(oh['dia_max'])} mm, el {dia(oh['dia_fecha'], semana=False, anio=True)}"
                  + (f" (ahora, más de {f1(v)} veces esa cifra)" if v and v >= 1.5 else ""))
        out.append({"t": t + ".", "fuente": F_OBS})
    # el total del episodio
    if comp:
        top = comp[:3]
        partes = [f"{r['nombre']} ({nprov(r['cod'])}) sumó {f1(r['total'])} mm" for r in top[:1]]
        partes += [f"{r['nombre']} ({nprov(r['cod'])}), {f1(r['total'])}" for r in top[1:]]
        out.append({"t": f"{tramo[0].upper() + tramo[1:]}, {lista_y(partes)}: son los totales más altos entre las estaciones con datos de "
                         f"todas las horas de esos días.", "fuente": F_OBS})
        n100 = sum(1 for r in comp if r["total"] >= 100)
        n200 = sum(1 for r in comp if r["total"] >= 200)
        n400 = sum(1 for r in comp if r["total"] >= 400)
        partes = [f"{n100} superaron los 100 mm"] + ([f"{n200}, los 200"] if n200 else []) + ([f"{n400}, los 400"] if n400 else [])
        out.append({"t": f"De las {miles(len(comp))} estaciones de AEMET con todas las horas {tramo} y provincia identificada, {lista_y(partes)}.", "fuente": F_OBS})
    # récords de otoño
    recs = sorted((r for r in B["est"] if (r.get("otono_hist") or {}).get("record_dia")), key=lambda r: -r["max"])
    if recs:
        nombres = lista_y([f"{r['nombre']} ({f1(r['max'])} mm; antes, {f1(r['otono_hist']['dia_max'])})" for r in recs[:6]])
        out.append({"t": f"En {len(recs)} estaciones, el día más lluvioso del episodio es su día de otoño más lluvioso de la serie "
                         f"(otoños con dato desde 1991 o desde que empieza la estación, con al menos 10): {nombres}"
                         + (f", entre otras." if len(recs) > 6 else "."),
                    "fuente": "AEMET OpenData (valores climatológicos diarios 1991-2025 y observación); cálculo de calentamientoglobal.es"})
    recs3 = sorted((r for r in B["est"] if (r.get("otono_hist") or {}).get("record_tres")), key=lambda r: -r["otono_hist"]["tres_ep"])
    if recs3:
        r = recs3[0]
        out.append({"t": f"En tres días seguidos, {r['nombre']} ({nprov(r['cod'])}) recogió {f1(r['otono_hist']['tres_ep'])} mm; su máximo anterior en tres días "
                         f"de otoño eran {f1(r['otono_hist']['tres_max'])} mm ({rango_txt(r['otono_hist']['tres_fecha'], 3)})."
                         + (f" Otras {len(recs3) - 1} estaciones superan también su máximo de tres días de otoño." if len(recs3) > 1 else ""),
                    "fuente": "AEMET OpenData (valores climatológicos diarios 1991-2025 y observación); cálculo de calentamientoglobal.es"})
    # serie larga
    sl = sorted((r for r in B["est"] if (r.get("serie_larga") or {}).get("record")), key=lambda r: -r["max"])
    for r in sl[:2]:
        L = r["serie_larga"]
        desde_t = f"desde {L['desde']}" if L["fuente"] == "diaria" else "desde 1940 (máximo diario de cada mes en el archivo mensual de AEMET)"
        out.append({"t": f"{r['nombre']} ({nprov(r['cod'])}): {f1(r['max'])} mm el {dia(r['max_fecha'], semana=False)}, su día más lluvioso {desde_t}; "
                         f"el anterior, {f1(L['mm'])} mm ({L['fecha'][:7] if L['fuente'] == 'mensual' else dia(L['fecha'], semana=False, anio=True)}).",
                    "fuente": "AEMET OpenData (valores climatológicos); cálculo de calentamientoglobal.es"})
    # otoño: la estación donde el episodio pesa más, con lo que aporta y la media de su propio periodo
    ot = sorted((r for r in B["est"] if r.get("otono") and r["otono"].get("normal_total") and r["completo"] and r["total"] >= 100),
                key=lambda r: -(r["otono"]["mm"] / r["otono"]["normal_total"]))
    if ot:
        r = ot[0]
        o = r["otono"]
        v = veces(o["mm"], o["normal_total"])
        per = o.get("periodo") or "1991-2020"
        media_t = "la normal 1991-2020" if per == "1991-2020" else f"la media de sus otoños de {per}"
        out.append({"t": f"Con este episodio, {r['nombre']} ({nprov(r['cod'])}) suma {f1(o['mm'])} mm desde el 1 de septiembre, {f1(r['total'])} de ellos {tramo}: "
                         + (f"más de {f1(v)} veces lo que llueve en un otoño entero en ese pluviómetro ({f1(o['normal_total'])} mm, {media_t})."
                            if v and v >= 1.2 else f"el {o['pct']} % de lo habitual hasta esta fecha ({media_t})."),
                    "fuente": "AEMET OpenData; media del mismo pluviómetro; cálculo de calentamientoglobal.es"})
    # avisos
    rojos = [(d["fecha"], d["rojo"]) for d in B["dias"] if d["rojo"]]
    if rojos:
        partes = [f"en {lista_y(ps)}, el {dia(f, semana=False) if i == 0 else date.fromisoformat(f).day}" for i, (f, ps) in enumerate(rojos)]
        out.append({"t": f"AEMET activó el aviso rojo, el más alto: " + ("; ".join(partes[:-1]) + "; y " + partes[-1] if len(partes) > 1 else partes[0]) + ".",
                    "fuente": "AEMET (avisos de Meteoalerta, vía MeteoAlarm)"})
    # ríos: el pico más alto de cada río
    if B["rios"]:
        rr, vistos = [], set()
        for x in B["rios"]:
            k = norm(x.get("rio") or x["nombre"])
            if k not in vistos:
                vistos.add(k)
                rr.append(x)
        partes = []
        for x in rr[:3]:
            lugar = lugar_aforo(x)
            rio = (x.get("rio") or "").replace(" Sobre el Azud", "").strip()
            donde = "" if norm(lugar) == norm(rio) else f" en {lugar}"
            desde_t = f", desde {f1(x['base'])} m³/s antes del episodio" if x.get("base") is not None and x["base"] < x["pico"] / 5 else ""
            partes.append(f"el {rio or lugar}{donde} llegó al menos a {f1(x['pico'])} m³/s{desde_t} ({x['fuente']}, lectura de "
                          f"{'la' if int(x['pico_t'][11:13]) == 1 else 'las'} {int(x['pico_t'][11:13])}:{x['pico_t'][14:16]} del {dia(x['pico_t'], semana=False)})")
        out.append({"t": "En los aforos oficiales, " + "; ".join(partes) + ". Son la lectura más alta registrada, no necesariamente el pico real.",
                    "fuente": "Confederación Hidrográfica del Júcar, Agència Catalana de l'Aigua y Gobierno de Navarra (datos en tiempo real, sin validar)"})
    # el mar
    if B["mar"] and B["mar"].get("sst"):
        m = B["mar"]
        an = math.floor(m["anomalia"] * 10) / 10
        t = f"El Mediterráneo occidental estaba a {f1(m['sst'])} °C el {dia(m['fecha'], semana=False)}, más de {f1(an)} °C por encima de su media para esa fecha"
        if m.get("puesto") == 1:
            t += f": la más alta para ese día desde {m.get('desde') or 1981}"
            if m.get("segundo"):
                dif = m["sst"] - m["segundo"][1]
                # 23-10-2026: con una diferencia de centésimas decía «0 °C por encima de 2023»
                t += (f", {f1(dif)} °C por encima de {m['segundo'][0]}" if dif >= 0.05 else f", por centésimas sobre {m['segundo'][0]}")
            t += " (dato provisional)"
        out.append({"t": t + ".", "fuente": "NOAA OISST v2.1 (análisis diario con satélites y boyas)"})
    return out


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    cfg = leer(SALIDA / "config.json")
    episodios = (cfg or {}).get("episodios") or EPISODIOS
    coef, M = ajustar_proyeccion()
    indice = []
    for ep in episodios:
        destino = SALIDA / f"{ep['id']}.json"
        prev = leer(destino, {}) or {}
        if prev.get("cerrado") and not ep.get("rehacer"):
            indice.append({k: prev.get(k) for k in ("id", "nombre", "titulo", "desde", "hasta", "en_curso", "cerrado", "generado", "resumen")})
            continue
        B = construir(ep, prev)
        if not B:
            continue
        dias_c = B["dias_c"]
        comp = B["completas"]
        g = SALIDA / "graficos"
        g.mkdir(exist_ok=True)
        graf = {}
        svg = grafico_ranking(comp[:20], dias_c, f"{ep['id']}-ranking", f"Lluvia del episodio, estación a estación ({ep['nombre']})")
        if svg:
            (g / f"{ep['id']}-ranking.svg").write_text(svg, encoding="utf-8")
            graf["ranking"] = {"svg": f"prensa/episodios/graficos/{ep['id']}-ranking.svg", "titulo": "Las 20 estaciones con más lluvia en el episodio",
                               "pie": "Estaciones de AEMET con datos de todas las horas de cada día; un color por día. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es."}
        svg = grafico_mapa(coef, M, comp, f"{ep['id']}-mapa", f"Lluvia acumulada en el episodio ({ep['nombre']})")
        if svg:
            (g / f"{ep['id']}-mapa.svg").write_text(svg, encoding="utf-8")
            graf["mapa"] = {"svg": f"prensa/episodios/graficos/{ep['id']}-mapa.svg", "titulo": "Lluvia acumulada en cada estación",
                            "pie": f"Cada punto, una de las {miles(len(comp))} estaciones de AEMET con todos los días completos. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es."}
        svg = grafico_dias(B["dias"], f"{ep['id']}-dias", "Estaciones con 50 y 100 mm o más, día a día")
        if svg:
            (g / f"{ep['id']}-dias.svg").write_text(svg, encoding="utf-8")
            graf["dias"] = {"svg": f"prensa/episodios/graficos/{ep['id']}-dias.svg", "titulo": "Cuántas estaciones pasaron de 50 y de 100 mm cada día",
                            "pie": "Estaciones de AEMET; el último día, hasta la última hora con dato. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es."}
        # CSV: todas las estaciones, todos los días
        with open(SALIDA / f"{ep['id']}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["indicativo", "estacion", "provincia", "lat", "lon", "altitud_m"] + [f"mm_{d}" for d in dias_c]
                       + ["total_mm", "todos_los_dias_completos", "max_dia_mm", "fecha_max", "hoy_mm", "hoy_horas",
                          "otono_mm", "otono_normal_hasta_hoy_mm", "otono_normal_entero_mm", "max_dia_otono_previo_mm", "fecha_max_otono_previo", "otonos_con_dato"])
            for r in sorted(B["est"], key=lambda r: -r["total"]):
                o, oh = r.get("otono") or {}, r.get("otono_hist") or {}
                w.writerow([r["id"], r["nombre"], nprov(r["cod"]), r.get("lat"), r.get("lon"), r.get("alt")] + [r["dias"].get(d) for d in dias_c]
                           + [r["total"], "si" if r["completo"] else "no", r["max"], r["max_fecha"], (r["hoy"] or {}).get("mm"), (r["hoy"] or {}).get("horas"),
                              o.get("mm"), o.get("normal"), o.get("normal_total"), oh.get("dia_max"), oh.get("dia_fecha"), oh.get("otonos")])
        en_curso = not B["cierre"]
        top = comp[0] if comp else None
        topd = max((r for r in B["est"] if r["max_fecha"]), key=lambda r: r["max"], default=None)
        if topd and topd.get("fuente_dias") == "horario_0_24":
            topd = None  # la cifra de un día, solo con el día de AEMET (07-07 UTC)
        resumen = {"estaciones": len(B["est"]), "completas": len(comp),
                   "max_total": {"nombre": top["nombre"], "cod": top["cod"], "mm": top["total"]} if top else None,
                   "max_dia": {"nombre": topd["nombre"], "cod": topd["cod"], "mm": topd["max"], "fecha": topd["max_fecha"]} if topd else None,
                   "n100": sum(1 for r in comp if r["total"] >= 100), "n200": sum(1 for r in comp if r["total"] >= 200),
                   "rojo": sorted({p for d in B["dias"] for p in d["rojo"]}),
                   "rios": len(B["rios"])}
        cifras = []
        if topd and topd.get("fuente_dias") != "horario_0_24":
            cifras.append({"n": f"{f1(topd['max'])} mm", "l": f"en {topd['nombre']} ({nprov(topd['cod'])}) el {dia(topd['max_fecha'], semana=False)}"
                                                           + (", de 0 a 24 h" if topd.get("fuente_dias") == "horario_0_24" else " (día pluviométrico de AEMET)")
                                                           + ": el día más lluvioso"})
        if top:
            cifras.append({"n": f"{f1(top['total'])} mm", "l": f"en {top['nombre']} ({nprov(top['cod'])}), el total del episodio más alto"})
        cifras.append({"n": str(resumen["n100"]), "l": "estaciones de AEMET con 100 mm o más en el episodio"})
        recs = sum(1 for r in B["est"] if (r.get("otono_hist") or {}).get("record_dia"))
        if recs:
            cifras.append({"n": str(recs), "l": "estaciones con su día de otoño más lluvioso desde 1991 o desde que tienen datos"})
        if B["rios"]:
            r0 = B["rios"][0]
            lugar = lugar_aforo(r0)
            rio = (r0.get("rio") or lugar).replace(" Sobre el Azud", "")
            cifras.append({"n": f"{f1(r0['pico'])} m³/s", "l": f"pico del río {rio}" + ("" if norm(lugar) == norm(rio) else f" en {lugar}") + f" ({r0['fuente']})"})
        hasta = B["cierre"] or (dias_c[-1] if dias_c else None)
        doc = {"version": VERSION, "id": ep["id"], "nombre": ep["nombre"], "titulo": ep["titulo"], "desde": ep["desde"], "hasta": hasta,
               "en_curso": en_curso, "cerrado": B["cierre"], "generado": AHORA.strftime("%Y-%m-%dT%H:%MZ"),
               "nota": ep.get("nota"), "nota_fuente": ep.get("nota_fuente"),
               "dias_completos": dias_c, "dia_en_curso": B["abierto"][0] if B["abierto"] else None,
               "resumen": resumen, "cifras": cifras, "claves": claves(ep, B), "dias": B["dias"],
               "ranking": [{k: r.get(k) for k in ("id", "nombre", "cod", "total", "dias", "max", "max_fecha", "hoy", "otono", "otono_hist", "serie_larga", "fuente_dias", "validados")}
                           for r in comp[:40]],
               "incompletas": [{k: r.get(k) for k in ("id", "nombre", "cod", "total", "dias", "max", "max_fecha")}
                               for r in sorted((r for r in B["est"] if not r["completo"]), key=lambda r: -r["total"])
                               if comp and r["total"] >= comp[min(19, len(comp) - 1)]["total"]][:10],
               "provincias": dict(sorted(B["provs"].items(), key=lambda kv: -((kv[1].get("max") or {}).get("total") or 0))),
               "rios": B["rios"], "mar": B["mar"], "graficos": graf, "csv": f"prensa/episodios/{ep['id']}.csv",
               "metodo": ("Lluvia: el día pluviométrico de AEMET (de 07:00 a 07:00 UTC): el valor diario validado de AEMET cuando ya está publicado o, "
                          "si no, la observación horaria de la estación sumada en ese tramo. Mientras una estación no tiene así todos los días del "
                          "episodio, se usa la suma de 0 a 24 h (hora peninsular) de la observación horaria, y se indica. Un día cuenta como completo con sus 24 horas con dato; el total del episodio, solo con "
                          "todos los días completos. Historia de cada estación: valores climatológicos diarios de AEMET de los otoños (1 de septiembre-30 de "
                          "noviembre) de 1991 a 2025 con al menos 80 días con dato; series diarias largas y archivo mensual desde 1940 donde los hay. "
                          "Otoño: normal 1991-2020 del mismo pluviómetro."),
               "limites": ["La observación horaria no está validada: AEMET publica el dato diario validado unos 4 días después y puede corregirlo.",
                           "Solo estaciones de AEMET. Las redes autonómicas (AVAMET, Meteocat, SAIH) tienen más pluviómetros y pueden dar cifras más altas.",
                           "«Día más lluvioso de otoño de sus registros»: entre los otoños con dato de la estación desde 1991; muchas son más antiguas."],
               "cita": "Fuente: AEMET OpenData y organismos de cuenca. Cálculo y elaboración: calentamientoglobal.es (CC BY 4.0)."}
        destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        indice.append({k: doc.get(k) for k in ("id", "nombre", "titulo", "desde", "hasta", "en_curso", "cerrado", "generado", "resumen")})
        print(f"{ep['id']}: {len(B['est'])} estaciones, {len(comp)} completas, días {dias_c}, en curso {en_curso}")
        for c in doc["claves"]:
            print("  ·", c["t"])
    (SALIDA / "index.json").write_text(json.dumps({"generado": AHORA.strftime("%Y-%m-%dT%H:%MZ"), "episodios": indice}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
