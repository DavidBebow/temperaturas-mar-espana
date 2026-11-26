#!/usr/bin/env python3
"""
Portada de la sala de prensa · calentamientoglobal.es (25-11-2026, chat 2 de la mesa de redacción).

Corre en el workflow «Hallazgos de prensa», después de redaccion_prensa.py. Con scripts/mesa_redaccion.py (criterio, agrupación,
escala única, marcos grandes) junta:
  · los marcos grandes, los récords y las rachas de estación (serie validada de AEMET, archivo/aemet_diario);
  · los hallazgos de docs/prensa/hallazgos.json (agrupados por la mesa);
  · las historias de docs/prensa/noticias/hoy.json,
las puntúa con la escala única, aplica los cinco criterios y la novedad frente a ayer y escribe:
  docs/prensa/portada.json        historia del día (o «sin noticia»), hasta cuatro más, «Datos del día» y «Contexto»
  docs/prensa/mesa_emitidos.json  estado de lo emitido (novedad frente a ayer; no cambia si se relanza el mismo día)
  docs/prensa/portada/<id>.md|svg|csv   nota, gráfico y datos de las historias propias de la mesa que abren o acompañan

Sin APIs, sin red: solo ficheros del repositorio. Nunca lanza una excepción hacia fuera: si una fuente falta o está rota, la portada
sale con lo demás y lo dice en `avisos`; si no queda nada, «sin noticia» con el marco vigente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesa_redaccion as M      # noqa: E402
import mesa_repaso as R         # noqa: E402
import portada_bloques as B     # noqa: E402

RAIZ = M.RAIZ
VERSION = 2
HISTORIAL_DIAS = 30                   # cuánto se recuerda de qué abrió cada día
MAX_SEGUIDOS = 2                      # la misma historia no abre más de 2 días seguidos sin cifra nueva
SELLOS = {"excepcional": "Excepcional", "dato_del_dia": "Dato del día", "en_seguimiento": "En seguimiento"}
SELLO_EXPLICA = {
    "excepcional": "Cumple los cinco criterios de la mesa (alcance, rareza, por qué hoy, una frase, se sostiene) con 55 puntos o más, o es una emergencia.",
    "dato_del_dia": "Es la pieza con más puntos de hoy; no cumple los cinco criterios y no se presenta como récord.",
    "en_seguimiento": "Misma historia que ayer con una cifra nueva.",
}
CADUCA_HORAS = 36                     # el plugin ignora una portada con más horas
EMITIDOS_DIAS = 120                   # cuánto se recuerda lo emitido
MAX_DATOS, MAX_CONTEXTO = 12, 12
CITAR = ("Observatorio climático de calentamientoglobal.es, con datos de AEMET (series diarias validadas) y cálculo propio. "
         "Licencia CC BY 4.0. https://calentamientoglobal.es/prensa/")


# ----------------------------------------------------------------------------- utilidades
def leer_json(p: Path, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def escribir_json(p: Path, d, indent=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=indent, default=str, separators=None if indent else (",", ":")), encoding="utf-8")
    tmp.replace(p)


def dia_es(d: date) -> str:
    return f"{d.day} de {M.MESES[d.month - 1]} de {d.year}"


def medir_retraso(hoy: date, raiz: Path = RAIZ, minimo: int = 15) -> tuple[int, date | None]:
    """Retraso real del dato validado: días entre hoy y la última fecha que alcanzan al menos `minimo` estaciones de
    archivo/aemet_diario (25-11-2026: el 17-11, o sea 8 días). Si el archivo no se puede leer, 8 (lo medido) y None."""
    import collections
    import gzip
    ult = collections.Counter()
    try:
        for f in (raiz / "archivo" / "aemet_diario").glob("*.csv.gz"):
            ultima = None
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for linea in fh:
                    ultima = linea
            if ultima and ultima[:4].isdigit():
                ult[ultima[:10]] += 1
    except Exception:
        ult.clear()
    acum = 0
    for fecha in sorted(ult, reverse=True):
        acum += ult[fecha]
        if acum >= minimo:
            d = date.fromisoformat(fecha)
            return max(1, (hoy - d).days), d
    return 8, None


# ----------------------------------------------------------------------------- candidatos
def candidatos_hallazgos(hall: dict, dia: date) -> list[dict]:
    """enviables + locales de hallazgos.json, agrupados por la mesa y con sus rasgos. Lo marcado para revisión no entra
    (incluye el almacén: sus reglas ya aplican «estación primero» y sin umbrales absolutos en reanálisis)."""
    lista = [h for h in (hall.get("enviables") or []) + (hall.get("locales") or []) if not h.get("requiere_revision")
             and h.get("fecha_dato")]
    vistos, uniq = set(), []
    for h in lista:
        if h.get("id") in vistos:
            continue
        vistos.add(h.get("id"))
        uniq.append(h)
    out = []
    for h in M.agrupar(uniq):
        r = M.rasgos(h, dia)
        if h.get("serie") == "capitales" and h.get("tipo") in ("record_fecha", "record_absoluto") and h.get("ambito") != "nacional":
            r["seccion"] = "noticia"
        if not r.get("invalidar"):
            r["invalidar"] = "; ".join(h.get("limites") or [])[:200] or None
        h["rasgos"], h["origen"] = r, "hallazgos"
        out.append(h)
    return out


def candidatos_noticias(hoy_json: dict, dia: date) -> list[dict]:
    hist = hoy_json.get("historias") or []
    out = R.de_noticias(hoy_json, dia)
    for c, h in zip(out, hist):
        c["_orig"] = h
    return out


def candidatos_mesa(dia: date, lag: int) -> list[dict]:
    R.LAG = lag
    return R.de_mesa(dia)


def unir_versiones(cands: list[dict]) -> list[dict]:
    """Las historias de capital de un marco nacional van dentro de él (no compiten): se les cuelga como versiones provinciales."""
    nac = {(c["periodo"], c["cola"], c["clave"]["periodo"]): c for c in cands if c.get("tipo_mesa") == "marco_nacional"}
    out = []
    for c in cands:
        if c.get("tipo_mesa") == "marco_capital":
            n = nac.get((c["periodo"], c["cola"], c["clave"]["periodo"]))
            if n is not None:
                n.setdefault("_versiones_reales", []).append(c)
                continue
        out.append(c)
    return out


# ----------------------------------------------------------------------------- gráfico, nota y datos de las historias de la mesa
def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def svg_barras(titulo: str, filas: list[tuple], unidad: str, pie: str, color="#B3261E", ref_txt="récord anterior") -> tuple[str, int, int]:
    """Barras horizontales (etiqueta, valor, referencia|None). Devuelve (svg, ancho, alto). Sin scripts, sin fuentes externas."""
    filas = filas[:30]
    w, fila_h, izq, der = 760, 24, 190, 120
    top = 54
    h = top + fila_h * len(filas) + 56
    vmax = max([f[1] for f in filas] + [f[2] for f in filas if f[2] is not None] + [1e-9])
    vmin = min([0] + [f[1] for f in filas] + [f[2] for f in filas if f[2] is not None])
    escala = (w - izq - der) / (vmax - vmin if vmax > vmin else 1)

    def x(v):
        return izq + (v - vmin) * escala
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{_esc(titulo)}" '
         f'font-family="Public Sans, Helvetica, Arial, sans-serif">',
         f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>',
         f'<text x="16" y="26" font-size="15" font-weight="700" fill="#1F1B16">{_esc(titulo[:95])}</text>']
    if any(f[2] is not None for f in filas):
        o.append(f'<line x1="16" y1="40" x2="30" y2="40" stroke="#1F1B16" stroke-width="3"/><text x="36" y="44" font-size="11" fill="#5E574E">{_esc(ref_txt)}</text>')
    for i, (lab, val, ref) in enumerate(filas):
        y = top + i * fila_h
        o.append(f'<text x="{izq - 8}" y="{y + 16}" font-size="12" text-anchor="end" fill="#1F1B16">{_esc(lab[:30])}</text>')
        o.append(f'<rect x="{izq}" y="{y + 4}" width="{max(1.0, x(val) - izq):.1f}" height="{fila_h - 9}" fill="{color}"/>')
        if ref is not None:
            o.append(f'<line x1="{x(ref):.1f}" y1="{y + 1}" x2="{x(ref):.1f}" y2="{y + fila_h - 3}" stroke="#1F1B16" stroke-width="3"/>')
        txt = (f"{val:.2f}".replace(".", ",") if abs(val) < 100 and not float(val).is_integer() else f"{val:g}".replace(".", ","))
        o.append(f'<text x="{max(x(val), x(ref) if ref is not None else 0) + 6:.1f}" y="{y + 16}" font-size="12" font-weight="600" fill="#1F1B16">{_esc(txt)} {_esc(unidad)}</text>')
    o.append(f'<text x="16" y="{h - 30}" font-size="10.5" fill="#5E574E">{_esc(pie[:140])}</text>')
    o.append(f'<text x="16" y="{h - 14}" font-size="10.5" fill="#5E574E">Gráfico: Observatorio climático de calentamientoglobal.es (CC BY 4.0)</text></svg>')
    return "".join(o), w, h


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def filas_grafico(c: dict) -> tuple[list[tuple], str, str]:
    """(filas, unidad, etiqueta de referencia) con lo que lleve la historia; filas vacías si no hay nada que dibujar."""
    t = c.get("tipo_mesa")
    if t == "marco_nacional" and c.get("tabla"):
        u = M._unidad(c.get("cola"))
        return ([(f["ciudad"], f["valor"], (f["anterior"] or [None])[0]) for f in c["tabla"] if f["puesto"] == 1], u, "récord anterior")
    if t == "marco_capital" and c.get("top"):
        u = M._unidad(c.get("cola"))
        fs = [(f"{a}", v, None) for v, a in c["top"]]
        fs.append((f"{c['fecha_dato'][:4]} (este año)", c["valor"], None))
        return (sorted(fs, key=lambda f: -f[1]) if c.get("cola") != "seco" else sorted(fs, key=lambda f: f[1])), u, ""
    vers = [v for v in (c.get("versiones_provinciales") or []) if isinstance(v, dict)]
    if vers and all(isinstance((v.get("rareza") or {}).get("PR"), (int, float)) for v in vers):
        return [(v.get("territorio", ""), float(v["rareza"]["PR"]), None) for v in vers], "veces más probable", ""
    if vers and t == "racha":
        fs = []
        for v in vers:
            m = re.search(r"lleva (\d+) días", v.get("titular", ""))
            if m:
                fs.append((v.get("territorio", ""), float(m.group(1)), None))
        return fs, "días", ""
    if vers and t == "record_mes":
        fs = [(v.get("territorio", ""), _num((v.get("cifra") or {}).get("valor")), _num(((v.get("cifra") or {}).get("anterior") or [None])[0])) for v in vers]
        fs = [f for f in fs if f[1] is not None]
        return fs, "mm" if c.get("cola") == "lluvioso" else "°C", "récord anterior"
    return [], "", ""


def nota_md(c: dict, hoy: date, filas, unidad) -> str:
    L = [f"# {c['titular']}", "", c.get("entradilla") or "", ""]
    if filas:
        L += ["| Lugar | Valor | Referencia |", "|---|---|---|"]
        for lab, v, ref in filas:
            L.append(f"| {lab} | {v:g} {unidad} | {'' if ref is None else format(ref, 'g')} |")
        L.append("")
    vers = [v for v in (c.get("versiones_provinciales") or c.get("_versiones_reales") or []) if isinstance(v, dict)]
    if vers:
        L += ["## Versiones provinciales", ""] + [f"- {v.get('territorio', '')}: {v.get('titular', '')}" for v in vers[:60]] + [""]
    L += ["## Fuente y método", "", c.get("fuente") or "AEMET, series diarias validadas.", ""]
    L += ["## Qué lo podría invalidar", "", c.get("invalidar") or "; ".join(c.get("limites") or []) or "—", ""]
    L += ["## Cómo citar", "", f"{CITAR} Consultado el {dia_es(hoy)}.", ""]
    return "\n".join(L)


def csv_filas(filas, unidad) -> str:
    return "lugar,valor,referencia,unidad\n" + "\n".join(f'"{l}",{v},{"" if r is None else r},{unidad}' for l, v, r in filas) + "\n"


def producir_ficheros(c: dict, ident: str, hoy: date, raiz: Path) -> dict:
    """Escribe nota, gráfico y csv de una historia propia de la mesa. Devuelve {nota, grafico} (rutas relativas a docs/)."""
    filas, unidad, ref_txt = filas_grafico(c)
    base = raiz / "docs" / "prensa" / "portada"
    base.mkdir(parents=True, exist_ok=True)
    rel = f"prensa/portada/{ident}"
    (raiz / "docs" / f"{rel}.md").write_text(nota_md(c, hoy, filas, unidad), encoding="utf-8")
    g = None
    if filas:
        tit = c["titular"] if len(c["titular"]) <= 95 else c["titular"][:92] + "…"
        svg, w, h = svg_barras(tit, filas, unidad, c.get("fuente") or "AEMET, series diarias validadas", ref_txt=ref_txt or "referencia")
        (raiz / "docs" / f"{rel}.svg").write_text(svg, encoding="utf-8")
        (raiz / "docs" / f"{rel}.csv").write_text(csv_filas(filas, unidad), encoding="utf-8")
        g = {"titulo": tit, "leyenda": [], "pie": c.get("fuente") or "AEMET, series diarias validadas", "svg": f"{rel}.svg", "png": None,
             "ancho": w, "alto": h, "csv": f"{rel}.csv"}
    return {"nota": f"{rel}.md", "grafico": g}


# ----------------------------------------------------------------------------- de candidato a elemento de portada.json
def ident(c: dict) -> str:
    base = c.get("id") or (c.get("_orig") or {}).get("id") or c.get("_k") or c.get("titular", "")
    s = M._slug(base)[:70] or "h"
    return s if (c.get("id") or (c.get("_orig") or {}).get("id")) else f"{s[:50]}-{hashlib.sha1(str(base).encode()).hexdigest()[:8]}"


def _cifras(c: dict) -> list[dict]:
    if (c.get("_orig") or {}).get("cifras"):
        return c["_orig"]["cifras"][:4]
    if c.get("marco"):
        m = c["marco"]
        return [{"n": f"{m['n_primeros']} de {m['total']}", "l": "capitales con estación de AEMET en la propia ciudad en primer puesto de su serie", "tono": "calor"}]
    comp = c.get("comparacion") or {}
    if c.get("tipo_mesa") in ("marco_capital", "record_mes", "racha") and comp.get("de"):
        return [{"n": f"{comp.get('puesto', 1)}.º de {comp['de']}", "l": f"puesto en su serie de AEMET ({comp.get('periodo', '')})", "tono": "calor"}]
    cf = c.get("cifra")
    if isinstance(cf, dict) and cf.get("valor") is not None:
        return [{"n": str(cf["valor"]), "l": c.get("titular", "")[:90], "tono": "calor"}]
    return []


def _versiones(c: dict) -> list[dict]:
    src = c.get("_versiones_reales") or c.get("versiones_provinciales") or []
    out = []
    for v in src:
        if isinstance(v, dict):
            out.append({"territorio": v.get("territorio"), "titular": v.get("titular"), "id": v.get("id"),
                        "puesto": (v.get("comparacion") or {}).get("puesto"),
                        "dossier": v.get("dossier"), "pagina": v.get("pagina"), "serie": v.get("serie"), "indicador": v.get("indicador"),
                        "provincia_slug": v.get("provincia_slug"), "ambito_tiempo": v.get("ambito_tiempo"), "fecha_dato": v.get("fecha_dato"),
                        "valor": v.get("valor"), "PR": (v.get("rareza") or {}).get("PR")})
        else:
            out.append({"territorio": str(v)})
    return out


def elemento(c: dict, hoy: date, raiz: Path, completo: bool) -> dict:
    p = c["puntuacion"]
    o = c.get("_orig") or {}
    it = {"clave": c.get("_k"), "id": ident(c), "origen": c.get("origen"), "tipo": c.get("tipo_mesa") or c.get("tipo"),
          "titular": c.get("titular"), "entradilla": c.get("entradilla") or o.get("subtitulo") or "",
          "kicker": o.get("kicker"), "tono": o.get("tono"), "cifras": _cifras(c), "corte": c.get("fecha_dato"),
          "calidad": c["rasgos"].get("calidad"), "fuente": c.get("fuente") or ("" if not o else "AEMET y organismos oficiales, ver la nota"),
          "invalidar": c.get("invalidar") or "", "ambito": c["rasgos"].get("ambito"), "medio": p["medio"],
          "puntos": p["puntos"], "componentes": {k: p[k] for k in ("A", "R", "N", "F", "Q")}, "puertas": p["puertas"],
          "citar": CITAR, "versiones_provinciales": _versiones(c), "provincias": o.get("provincias") or [],
          "n_miembros": len(c.get("miembros") or []) or None if c.get("agregada_por_mesa") else None,
          "emergencia": bool(c["rasgos"].get("emergencia")), "nota": None, "grafico": None, "noticia_id": o.get("id")}
    if o:                                                   # historia de redaccion_prensa.py: su nota y su gráfico ya existen
        it["grafico"] = o.get("grafico")
        it["nota"] = f"prensa/noticias/historias/{o.get('id')}.json"
    elif c.get("dossier") and (raiz / "docs" / str(c["dossier"])).exists():          # hallazgo con dossier
        d = str(c["dossier"])
        it["nota"] = d
        stem = d[:-3]
        g = {"titulo": c.get("titular"), "leyenda": [], "pie": c.get("fuente") or "", "svg": None, "png": None, "csv": None}
        for k, ext in (("png", "png"), ("csv", "csv")):
            if (raiz / "docs" / f"{stem}.{ext}").exists():
                g[k] = f"{stem}.{ext}"
        it["grafico"] = g if g["png"] or g["csv"] else None
        if it["grafico"] and it["grafico"]["png"]:
            it["grafico"]["imagen"] = it["grafico"]["png"]      # el plugin usa `svg`; esta pieza solo tiene PNG
    elif completo and (c.get("origen") == "mesa" or c.get("agregada_por_mesa")):
        r = producir_ficheros(c, it["id"], hoy, raiz)
        it["nota"], it["grafico"] = r["nota"], r["grafico"]
    if c.get("pagina"):
        it["pagina"] = c["pagina"]
    return it


# ----------------------------------------------------------------------------- estado de lo emitido (novedad frente a ayer)
# ----------------------------------------------------------------------------- A · dato del día (la mesa pasa a ser un sello)
RIGOR_PROHIBIDO = re.compile(r"hist[óo]ric", re.I)


def rigor_ok(c: dict) -> bool:
    """Reglas del 25-11: nada de «histórico»; «el más…» solo con primer puesto y sin empate."""
    t = c.get("titular") or ""
    if RIGOR_PROHIBIDO.search(t):
        return False
    if re.search(r"\b(el|la|los|las) m[áa]s\b", t, re.I):
        comp = c.get("comparacion") or {}
        if comp and comp.get("puesto") not in (None, 1):
            return False
    return True


def _cifra_txt(c: dict) -> str:
    return json.dumps(c.get("_cifra"), sort_keys=True, default=str)


def historial_previo(estado: dict, hoy: date) -> list[dict]:
    h = (estado.get("portada_diaria") or {}).get("historial") or []
    return sorted([e for e in h if e.get("fecha") and e["fecha"] < str(hoy)], key=lambda e: e["fecha"])


def seguidos(hist: list[dict], clave: str, hoy: date) -> tuple[int, str | None]:
    """Días seguidos (hasta ayer) en que `clave` abrió la portada y la cifra con que lo hizo el último."""
    n, cifra, esperado = 0, None, hoy - timedelta(days=1)
    for e in reversed(hist):
        if date.fromisoformat(e["fecha"]) != esperado or e.get("clave") != clave:
            break
        n += 1
        cifra = cifra if cifra is not None else e.get("cifra")
        esperado -= timedelta(days=1)
    return n, cifra


def sello_de(c: dict, hist: list[dict], hoy: date) -> str:
    p = c["puntuacion"]
    if (p.get("portada") and p["puntos"] >= 55) or c["rasgos"].get("emergencia"):
        return "excepcional"
    n, cifra = seguidos(hist, c.get("_k"), hoy)
    if n >= 1 and c.get("_cifra") is not None and _cifra_txt(c) != cifra:
        return "en_seguimiento"
    return "dato_del_dia"


def elegible(c: dict, hist: list[dict], hoy: date, sello: str) -> bool:
    """La misma historia no abre un tercer día seguido sin cifra nueva ni sello excepcional."""
    n, cifra = seguidos(hist, c.get("_k"), hoy)
    if n >= MAX_SEGUIDOS and sello == "dato_del_dia" and _cifra_txt(c) == cifra:
        return False
    return True


def pieza_de_carrera(r: dict, sello: str = "dato_del_dia") -> dict:
    unidad = r.get("unidad") or ""
    cifras = [{"n": f"{str(r['valor_hoy']).replace('.', ',')} {unidad}".strip(), "l": f"valor de hoy; récord {str(r['record']).replace('.', ',')} {unidad} ({r['anio_record']})".strip(), "tono": "calor"}]
    return {"clave": r["id"], "id": r["id"], "origen": "carrera", "tipo": "carrera", "titular": r["titulo"], "entradilla": r["frase"], "kicker": "Carrera hacia el récord",
            "cifras": cifras, "corte": r.get("dato_hasta"), "calidad": "validado", "fuente": "AEMET, series diarias validadas, y cálculo propio",
            "citar": CITAR, "versiones_provinciales": [], "provincias": [], "puntos": None, "emergencia": False, "nota": None, "grafico": None,
            "sello": sello, "sello_texto": SELLOS[sello], "sello_explica": SELLO_EXPLICA[sello]}


def bloque_dato_del_dia(p: dict, pool: list[dict], carreras: dict, hoy: date, raiz: Path, hist: list[dict], escribir: bool) -> tuple[dict, list[dict], dict | None]:
    """(dato_del_dia, mas_historias, clave_emitida). Nunca vacío: si no queda pieza de la mesa, la mejor carrera del bloque B."""
    vistos, orden = set(), []
    cola = ([p["historia_del_dia"]] if p.get("historia_del_dia") else []) + list(p["mas"]) + list(p["datos_del_dia"]) + list(p["contexto"])
    for c in sorted(cola, key=lambda c: (-int(bool(c["rasgos"].get("emergencia"))), -c["puntuacion"]["puntos"])):
        k = c.get("_k") or c.get("titular")
        if k in vistos or not rigor_ok(c) or not c.get("titular"):
            continue
        vistos.add(k)
        orden.append(c)
    elegidos = []
    for c in orden:
        sl = sello_de(c, hist, hoy)
        if elegible(c, hist, hoy, sl):
            elegidos.append((c, sl))
    # primero las excepcionales; dentro de cada grupo, por puntos (ya ordenado)
    elegidos.sort(key=lambda x: 0 if x[1] == "excepcional" else 1)
    items = []
    for c, sl in elegidos[:5]:
        it = elemento(c, hoy, raiz, escribir)
        it.update({"sello": sl, "sello_texto": SELLOS[sl], "sello_explica": SELLO_EXPLICA[sl]})
        items.append((c, it))
    # relleno con carreras si faltan piezas (la portada nunca se queda sin «Más historias» ni sin dato)
    piezas_c = carreras.get("piezas") or []
    usadas = 0
    while len(items) < 3 and usadas < len(piezas_c):
        items.append((None, pieza_de_carrera(piezas_c[usadas])))
        usadas += 1
    if not items:
        items.append((None, pieza_de_carrera({"id": "sin-carreras", "titulo": "Dato del día: la serie de AEMET llega hasta " + str(carreras.get("dato_hasta")),
                                              "frase": "La mesa no ha producido piezas hoy y las carreras no tienen serie con cobertura suficiente.", "valor_hoy": "", "record": "", "anio_record": ""})))
    cab_c, cab = items[0]
    emitida = None
    if cab_c is not None:
        emitida = {"clave": cab_c.get("_k"), "cifra": _cifra_txt(cab_c), "sello": cab["sello"]}
    else:
        emitida = {"clave": cab["clave"], "cifra": str(cab.get("cifras")), "sello": cab["sello"]}
    return cab, [it for _, it in items[1:5]], emitida


def guardar_historial(estado: dict, hoy: date, emitida: dict | None) -> dict:
    h = [e for e in ((estado.get("portada_diaria") or {}).get("historial") or []) if e.get("fecha") != str(hoy)]
    if emitida:
        h.append({"fecha": str(hoy), **emitida})
    corte = str(hoy - timedelta(days=HISTORIAL_DIAS))
    return {"historial": sorted([e for e in h if e["fecha"] >= corte], key=lambda e: e["fecha"])}


def vista_de_ayer(estado: dict, hoy: date) -> dict:
    """Lo emitido antes de hoy. Relanzar el workflow el mismo día no hace que lo de hoy «ya fuera verdad ayer»."""
    h = str(hoy)
    out = {}
    for k, e in (estado.get("claves") or {}).items():
        base = e.get("previo") if e.get("fecha") == h else e.get("estado")
        if base:
            out[k] = json.loads(json.dumps(base))
    return out


def guardar_estado(estado: dict, emitidos_nuevo: dict, ayer: dict, hoy: date) -> dict:
    h = str(hoy)
    claves = estado.get("claves") or {}
    for k, nuevo in emitidos_nuevo.items():
        if ayer.get(k) == nuevo and (claves.get(k) or {}).get("fecha") != h:
            continue                                   # sin cambios frente a ayer: no se toca
        antiguo = claves.get(k)
        if antiguo and antiguo.get("fecha") == h:
            antiguo["estado"] = nuevo
        else:
            claves[k] = {"fecha": h, "estado": nuevo, "previo": (antiguo or {}).get("estado")}
    corte = str(hoy - timedelta(days=EMITIDOS_DIAS))
    claves = {k: e for k, e in claves.items() if e.get("fecha", h) >= corte}
    return {"version": VERSION, "actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "claves": claves}


# ----------------------------------------------------------------------------- marco vigente (para el día sin noticia)
def marco_vigente(marcos: list[dict], estado: dict, raiz: Path) -> dict | None:
    nac = [m for m in marcos if m.get("tipo_mesa") == "marco_nacional"]
    pref = [m for m in nac if m["periodo"] == "anio" and m["cola"] == "calor"] or sorted(nac, key=lambda m: -m["marco"]["n_primeros"])
    if pref:
        m = pref[0]
        return {"titular": m["titular"], "hasta": m["fecha_dato"], "clave": json.dumps(m["clave"], ensure_ascii=False),
                "n_primeros": m["marco"]["n_primeros"], "total": m["marco"]["total"]}
    prev = leer_json(raiz / "docs" / "prensa" / "portada.json", {}) or {}
    return prev.get("marco_vigente")


def sin_noticia(mv: dict | None) -> dict:
    if mv:
        hasta = date.fromisoformat(mv["hasta"])
        marco = f"{mv['titular']} (dato validado de AEMET hasta el {dia_es(hasta)})"
        bajo = mv["titular"][0].lower() + mv["titular"][1:]
        tit = M.PLANTILLAS["sin_noticia"][0].format(marco_vigente=bajo)
        ent = M.ENTRADILLAS["sin_noticia"].format(marco_vigente=bajo + f" (dato validado de AEMET hasta el {dia_es(hasta)})")
    else:
        tit = "Hoy no hay nada excepcional en los datos"
        ent = ("Ningún dato de hoy cumple los cinco criterios: alcance, rareza en una serie larga, algo nuevo desde ayer, una frase y un dato que se sostiene. "
               "Debajo, los datos del día.")
    return {"titular": tit, "entradilla": ent, "marco_vigente": mv}


# ----------------------------------------------------------------------------- generador
def generar(hoy: date, raiz: Path = RAIZ, escribir: bool = True, hall: dict | None = None, hoy_json: dict | None = None) -> dict:
    avisos, fuentes = [], {}
    cands, marcos = [], []
    lag, hasta = medir_retraso(hoy, raiz)
    if hasta is None:
        avisos.append("no se pudo medir el retraso del dato validado en archivo/aemet_diario: se usan 8 días")

    try:
        mesa = candidatos_mesa(hoy, lag)
        marcos = [c for c in mesa if c.get("tipo_mesa") in ("marco_nacional", "marco_capital")]
        cands += mesa
        fuentes["mesa"] = len(mesa)
    except Exception as e:           # noqa: BLE001
        avisos.append(f"mesa (marcos, récords y rachas): {type(e).__name__}: {str(e)[:120]}")
    if hall is None:
        hall = leer_json(raiz / "docs" / "prensa" / "hallazgos.json")
    if isinstance(hall, dict) and hall:
        try:
            c = candidatos_hallazgos(hall, hoy)
            cands += c
            fuentes["hallazgos"] = len(c)
        except Exception as e:       # noqa: BLE001
            avisos.append(f"hallazgos.json: {type(e).__name__}: {str(e)[:120]}")
    else:
        avisos.append("hallazgos.json falta o está roto")
    hj = hoy_json if hoy_json is not None else leer_json(raiz / "docs" / "prensa" / "noticias" / "hoy.json")
    if isinstance(hj, dict) and hj.get("historias"):
        try:
            c = candidatos_noticias(hj, date.fromisoformat(str(hj.get("fecha") or hoy)[:10]))
            cands += c
            fuentes["noticias"] = len(c)
        except Exception as e:       # noqa: BLE001
            avisos.append(f"noticias/hoy.json: {type(e).__name__}: {str(e)[:120]}")
    else:
        avisos.append("noticias/hoy.json falta o está roto")

    cands = unir_versiones([c for c in cands if c.get("rasgos", {}).get("seccion") != "version"])
    estado = leer_json(raiz / "docs" / "prensa" / "mesa_emitidos.json", {}) or {}
    ayer = vista_de_ayer(estado, hoy)
    emitidos = json.loads(json.dumps(ayer))
    p = M.portada(cands, hoy, emitidos)

    # lo que no abre pero es un dato (la exclusiva contra una serie corta, un récord de estación pequeña) va a «Datos del día»
    datos = list(p["datos_del_dia"])
    contexto = []
    for c in p["contexto"]:
        (datos if c.get("origen") == "noticias" and c.get("tipo_mesa") in ("exclusiva", "record") else contexto).append(c)
    datos.sort(key=lambda c: -c["puntuacion"]["puntos"])

    # ---- la portada diaria: seis bloques, ninguno vacío
    previo = leer_json(raiz / "docs" / "prensa" / "portada.json", {}) or {}
    hist = historial_previo(estado, hoy)
    hasta_v = hasta or (hoy - timedelta(days=8))
    def _bloque(nombre, fn, minimo):
        try:
            return fn()
        except Exception as e:       # noqa: BLE001
            avisos.append(f"bloque {nombre}: {type(e).__name__}: {str(e)[:120]}")
            ant = previo.get(nombre)
            return ant if ant else minimo
    carreras = _bloque("carreras", lambda: B.bloque_carreras(hasta_v, raiz), {"dato_hasta": str(hasta_v), "piezas": [], "avisos": ["sin cálculo en esta pasada"]})
    dato, mas_h, emitida = bloque_dato_del_dia(p, cands, carreras, hoy, raiz, hist, escribir)
    tal = _bloque("tal_dia_como_hoy", lambda: B.bloque_tal_dia(hoy, raiz, hasta_v), {"fecha": str(hoy), "dato_hasta": None, "portada": [], "por_capital": {}, "nota": "sin cálculo en esta pasada"})
    espana = _bloque("espana_ayer", lambda: B.bloque_espana(hoy, raiz, previo.get("espana_ayer")), {"dato_hasta": None, "cifras": []})
    carr_mes = {}
    try:
        carr_mes = B.carrera_mes(hasta_v, raiz)
    except Exception as e:           # noqa: BLE001
        avisos.append(f"carrera del mes: {type(e).__name__}: {str(e)[:100]}")
    provs = _bloque("provincias", lambda: B.bloque_provincias(hoy, hasta_v, [c for c in cands if c.get("puntuacion")], tal, carr_mes, raiz), {"dato_hasta": None, "n": 0, "por_slug": {}})
    viene = _bloque("lo_que_viene", lambda: B.bloque_viene(hoy, raiz), {"dato_hasta": str(hoy), "prevision": {"etiqueta": "previsión", "textos": []}, "agenda": B.agenda(hoy)})
    est = guardar_estado(estado, {k: v for k, v in emitidos.items() if ayer.get(k) != v}, ayer, hoy)
    est["portada_diaria"] = guardar_historial(estado, hoy, emitida)

    datos_item = [elemento(c, hoy, raiz, False) for c in datos[:MAX_DATOS]]
    ctx_item = [elemento(c, hoy, raiz, False) for c in contexto[:MAX_CONTEXTO]]
    salida = {"version": VERSION, "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": str(hoy),
              "caduca_horas": CADUCA_HORAS, "retraso_validado_dias": lag, "dato_validado_hasta": str(hasta) if hasta else None,
              "fuentes": fuentes, "avisos": avisos, "sin_noticia": False, "sin_noticia_texto": None, "marco_vigente": None,
              "dato_del_dia": dato, "mas_historias": mas_h,
              "historia_del_dia": dato, "mas": mas_h,                       # nombres anteriores, para el plugin 7.2.x
              "carreras": carreras, "tal_dia_como_hoy": tal, "espana_ayer": espana, "provincias": provs, "lo_que_viene": viene,
              "dato_hasta": {"dato_del_dia": dato.get("corte"), "carreras": carreras.get("dato_hasta"), "tal_dia_como_hoy": tal.get("dato_hasta"),
                             "espana_ayer": espana.get("dato_hasta"), "provincias": provs.get("dato_hasta"), "lo_que_viene": viene.get("dato_hasta")},
              "datos_del_dia": datos_item, "contexto": ctx_item,
              "totales": {"datos_del_dia": len(datos), "contexto": len(contexto)}}
    if escribir:
        escribir_json(raiz / "docs" / "prensa" / "portada.json", salida, indent=1)
        escribir_json(raiz / "docs" / "prensa" / "mesa_emitidos.json", est, indent=1)
    return salida


def sembrar(desde: date, hasta: date, raiz: Path = RAIZ, escribir: bool = True) -> dict:
    """Estado inicial de mesa_emitidos.json: repite día a día (solo con lo que sabe la mesa desde la serie validada de AEMET, con el
    retraso medido) lo que habría emitido, para que el primer día en producción no trate como nuevo lo que ya era verdad. Es el
    mismo método del repaso de 60 días del chat 1. No escribe portada ni ficheros de historias."""
    lag, _ = medir_retraso(hasta, raiz)
    estado = {}
    d = desde
    while d <= hasta:
        cands = unir_versiones([c for c in candidatos_mesa(d, lag) if c.get("rasgos", {}).get("seccion") != "version"])
        ayer = vista_de_ayer(estado, d)
        emit = json.loads(json.dumps(ayer))
        M.portada(cands, d, emit)
        estado = guardar_estado(estado, {k: v for k, v in emit.items() if ayer.get(k) != v}, ayer, d)
        d += timedelta(days=1)
    if escribir:
        escribir_json(raiz / "docs" / "prensa" / "mesa_emitidos.json", estado, indent=1)
    return estado


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sembrar", default="", help="AAAA-MM-DD: repite desde esa fecha hasta ayer y escribe mesa_emitidos.json")
    ap.add_argument("--hoy", default="")
    ap.add_argument("--raiz", default=str(RAIZ))
    ap.add_argument("--no-escribir", action="store_true")
    a = ap.parse_args()
    raiz = Path(a.raiz)
    hoy = date.fromisoformat(a.hoy) if a.hoy else datetime.now(ZoneInfo("Europe/Madrid")).date()
    if a.sembrar:
        est = sembrar(date.fromisoformat(a.sembrar), hoy - timedelta(days=1), raiz)
        print(f"sembrado: {len(est['claves'])} claves")
        return 0
    try:
        if not a.no_escribir:
            carpeta = raiz / "docs" / "prensa" / "portada"
            if carpeta.exists():
                shutil.rmtree(carpeta)
        s = generar(hoy, raiz, not a.no_escribir)
    except Exception as e:           # noqa: BLE001  nunca tumba la pasada: se queda la portada anterior
        print(f"portada: ERROR {type(e).__name__}: {e}")
        return 0
    d = s["historia_del_dia"]
    print(f"portada {s['fecha']}: {d['titular'][:110]} [{d['sello']}] · +{len(s['mas'])} · datos {s['totales']['datos_del_dia']} · "
          f"contexto {s['totales']['contexto']} · retraso {s['retraso_validado_dias']} d · avisos {s['avisos']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
