#!/usr/bin/env python3
"""
Noticia completa de las piezas propias de la mesa · calentamientoglobal.es (26-11-2026).

Las historias de redaccion_prensa.py tienen página propia (/prensa/noticia/<id>/) con texto, hechos comprobados, gráfico,
método y versión por provincia. Las de la mesa (marcos de periodo) solo tenían titular, entradilla y una tabla. Este módulo
les da el mismo fondo, con lo que solo sale de escudriñar la serie diaria validada de AEMET de cada capital:

  · la serie año a año del mismo tramo (gráfico y CSV), no solo el dato de este año;
  · el margen sobre el récord anterior, capital a capital: el mayor, el más ajustado y qué año cae;
  · la diferencia con la media de 1991-2020 de la misma estación y el mismo tramo;
  · los cinco registros más altos de la serie y cuántos de los diez primeros son de este siglo;
  · lo que queda de periodo, cuando no está cerrado;
  · una versión para cada capital en puesto 1-3, con su propia serie.

Escribe docs/prensa/noticias/historias/<id>.json en el mismo formato que redaccion_prensa.py (la pinta cg-sala-prensa) y sus
gráficos en docs/prensa/portada/fondo/ (con nombre fijo: se reescriben en cada pasada). El id empieza por la fecha de corte del dato: la limpieza de redaccion_prensa.py borra
las historias con fecha de hace más de 60 días y las que no llevan fecha delante.

Sin red y sin texto libre: cada frase es una plantilla sobre cifras calculadas aquí, con las mismas reglas que
mesa_redaccion.puesto_periodo (años con ≥ 95 % de días con dato; empate práctico no es récord). Si algo falla, devuelve None y la
pieza se queda como estaba.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesa_redaccion as M      # noqa: E402

SUB = "prensa/portada/fondo"
VIDA_DIAS = 60
NORMAL = (1991, 2020)
MIN_NORMAL = 20                       # años con dato para dar la media de 1991-2020
FUENTE_H = "AEMET, serie diaria validada de la estación, y cálculo propio"
FUENTES = "AEMET OpenData (series diarias validadas de las estaciones de las capitales)"
PAGINA = "https://calentamientoglobal.es/cambio-climatico-por-provincias/"
ORD = {1: "primer", 2: "segundo", 3: "tercer"}
KICKER = {"calor": "Calor", "noches": "Calor · noches", "lluvioso": "Lluvia", "seco": "Sequía", "frio": "Frío"}
TONO = {"calor": "calor", "noches": "calor", "lluvioso": "lluvia", "seco": "seco", "frio": "frio"}
VAR = {"calor": "media de las temperaturas máximas", "noches": "media de las temperaturas mínimas", "frio": "media de las temperaturas máximas"}
COLOR = {"calor": "#B3261E", "noches": "#B3261E", "lluvioso": "#1F5FA8", "seco": "#A8641F", "frio": "#1F5FA8"}


# ----------------------------------------------------------------------------- utilidades
def _n(v, dec=1) -> str:
    """Número a la española, con signo menos tipográfico."""
    s = f"{abs(float(v)):.{dec}f}".replace(".", ",")
    return ("−" if float(v) < 0 and float(s.replace(",", ".")) > 0 else "") + s


def _dif(a, b, dec) -> float:
    """Diferencia entre dos cifras tal como se publican (ya redondeadas): el lector puede restarlas y le sale lo mismo."""
    return round(round(float(a), dec) - round(float(b), dec), dec)


def _dia(d: date, anio=True) -> str:
    return f"{d.day} de {M.MESES[d.month - 1]}" + (f" de {d.year}" if anio else "")


def _lista(xs) -> str:
    xs = [str(x) for x in xs]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _provincias() -> dict:
    try:
        import hallazgos_prensa as H
        return dict(H.PROVINCIAS)
    except Exception:
        return {}


def anual(serie: dict, ini: date, hasta: date, idx: int, min_frac: float = 0.95) -> list[tuple[int, float]]:
    """[(año, valor)] del tramo ini..hasta en cada año de la serie (incluido el actual), con la regla de puesto_periodo."""
    largo = (hasta - ini).days + 1
    out = []
    for y in sorted({d.year for d in serie}):
        if y > ini.year:
            continue
        try:
            a = ini.replace(year=y)
            b = hasta.replace(year=y + (hasta.year - ini.year))
        except ValueError:
            continue
        vals, d = [], a
        while d <= b:
            v = serie.get(d)
            if v and v[idx] is not None:
                vals.append(v[idx])
            d += timedelta(days=1)
        if len(vals) < min_frac * largo:
            continue
        val = sum(vals) if idx == 2 else sum(vals) / len(vals)
        if idx == 2 and largo >= 30 and y < ini.year and val <= 0:
            continue                                   # tramo largo a cero exacto: hueco codificado como cero
        out.append((y, val))
    return out


def ficha(ind: str, ini: date, hasta: date, cola: str, raiz: Path) -> dict | None:
    """Lo que la serie de una estación dice del tramo: serie anual, puesto, anterior, top 5, media 1991-2020 y siglo."""
    idx, signo, _ = M.COLAS[cola]
    s = anual(M.serie_diaria(ind, raiz), ini, hasta, idx)
    if not s or s[-1][0] != ini.year or len(s) < 2:
        return None
    act = s[-1][1]
    prev = s[:-1]
    orden = sorted(prev, key=lambda x: -signo * x[1])
    puesto = 1 + sum(1 for _, v in prev if signo * (v - act) >= 0)
    todos = sorted(s, key=lambda x: -signo * x[1])
    base = [v for y, v in prev if NORMAL[0] <= y <= NORMAL[1]]
    normal = sum(base) / len(base) if len(base) >= MIN_NORMAL else None
    return {"serie": s, "valor": act, "puesto": puesto, "n": len(s), "desde": prev[0][0], "anterior": orden[0],
            "top5": todos[:5], "siglo": sum(1 for y, _ in todos[:10] if y >= 2001) if len(todos) >= 10 else None,
            "normal": normal, "anom": (act - normal) if normal is not None else None,
            "pct": (100 * act / normal) if (normal and idx == 2) else None}


# ----------------------------------------------------------------------------- gráfico: la serie, año a año
def svg_serie(titulo: str, s: list[tuple[int, float]], unidad: str, cola: str, normal, pie: str) -> tuple[str, int, int]:
    idx, signo, _ = M.COLAS[cola]
    W, H, ml, mr, mt, mb = 820, 400, 52, 138, 50, 52
    col = COLOR.get(cola, "#B3261E")
    ys = [v for _, v in s] + ([normal] if normal is not None else [])
    lo, hi = (0.0, max(ys) * 1.08 or 1.0) if idx == 2 else (min(ys) - 0.4, max(ys) + 0.4)
    a0, a1 = s[0][0], s[-1][0]

    def X(a):
        return ml + (W - ml - mr) * (a - a0) / max(1, a1 - a0)

    def Y(v):
        return mt + (H - mt - mb) * (1 - (v - lo) / (hi - lo))
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{_esc(titulo)}" '
         f'font-family="Public Sans, DejaVu Sans, Arial, sans-serif"><rect width="{W}" height="{H}" fill="#FFFFFF"></rect>',
         f'<text x="16" y="26" font-size="15" font-weight="700" fill="#16130F">{_esc(titulo[:100])}</text>']
    paso = max(0.5, round((hi - lo) / 5, 1)) if idx != 2 else max(10, round((hi - lo) / 5 / 10) * 10)
    t = (int(lo / paso) + (1 if lo > 0 else 0)) * paso
    while t <= hi:
        o.append(f'<line x1="{ml}" y1="{Y(t):.1f}" x2="{W - mr}" y2="{Y(t):.1f}" stroke="#E3DED5" stroke-width="1"></line>'
                 f'<text x="{ml - 6}" y="{Y(t) + 4:.1f}" font-size="11" fill="#5E574E" text-anchor="end">{_n(t, 0 if idx == 2 or float(t).is_integer() else 1)}</text>')
        t = round(t + paso, 4)
    for a in range((a0 // 10 + 1) * 10, a1, 10):
        o.append(f'<text x="{X(a):.1f}" y="{H - mb + 16}" font-size="11" fill="#5E574E" text-anchor="middle">{a}</text>')
    if normal is not None:
        o.append(f'<line x1="{ml}" y1="{Y(normal):.1f}" x2="{W - mr}" y2="{Y(normal):.1f}" stroke="#16130F" stroke-width="1.2" stroke-dasharray="5 4"></line>'
                 f'<text x="{ml + 6}" y="{Y(normal) - 6:.1f}" font-size="11" fill="#16130F">Media de 1991-2020: {_n(normal, 1 if idx == 2 else 2)} {_esc(unidad)}</text>')
    ant = sorted(s[:-1], key=lambda x: -signo * x[1])[0]
    if idx == 2:
        bw = max(1.5, (W - ml - mr) / max(1, a1 - a0) * 0.72)
        for a, v in s:
            c = col if a == a1 else ("#16130F" if a == ant[0] else "#C9C1B6")
            o.append(f'<rect x="{X(a) - bw / 2:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" height="{max(0.5, Y(0) - Y(v)):.1f}" fill="{c}"></rect>')
    else:
        seg = []
        for i, (a, v) in enumerate(s):
            if i and a - s[i - 1][0] == 1:
                seg[-1].append((a, v))
            else:
                seg.append([(a, v)])
        for g in seg:
            if len(g) > 1:
                o.append('<polyline fill="none" stroke="#B9AC9A" stroke-width="1.5" points="' + " ".join(f"{X(a):.1f},{Y(v):.1f}" for a, v in g) + '"></polyline>')
        for a, v in s[:-1]:
            o.append(f'<circle cx="{X(a):.1f}" cy="{Y(v):.1f}" r="{3.6 if a == ant[0] else 2}" fill="{"#16130F" if a == ant[0] else "#8E8478"}"></circle>')
        o.append(f'<circle cx="{X(a1):.1f}" cy="{Y(s[-1][1]):.1f}" r="5.5" fill="{col}"></circle>')
    dec = 1 if idx == 2 else 2
    ya, yb = Y(s[-1][1]), Y(ant[1])
    if abs(ya - yb) < 15:                               # las dos etiquetas no se pisan
        yb = ya + (15 if yb >= ya else -15)
    o.append(f'<text x="{W - mr + 8}" y="{ya + 4:.1f}" font-size="12.5" font-weight="700" fill="{col}">{a1}: {_n(s[-1][1], dec)} {_esc(unidad)}</text>')
    o.append(f'<text x="{W - mr + 8}" y="{yb + 4:.1f}" font-size="11.5" fill="#16130F">{ant[0]}: {_n(ant[1], dec)} {_esc(unidad)}</text>')
    o.append(f'<text x="16" y="{H - 22}" font-size="10.5" fill="#5E574E">{_esc(pie[:150])}</text>'
             f'<text x="16" y="{H - 8}" font-size="10.5" fill="#5E574E">Gráfico: Observatorio climático de calentamientoglobal.es (CC BY 4.0)</text></svg>')
    return "".join(o), W, H


def _guardar_grafico(raiz: Path, nombre: str, titulo: str, s, unidad, cola, normal, pie, csv_txt: str) -> dict:
    base = raiz / "docs" / SUB
    base.mkdir(parents=True, exist_ok=True)
    svg, w, h = svg_serie(titulo, s, unidad, cola, normal, pie)
    (base / f"{nombre}.svg").write_text(svg, encoding="utf-8")
    (base / f"{nombre}.csv").write_text(csv_txt, encoding="utf-8")
    ley = [{"t": "punto", "c": COLOR.get(cola, "#B3261E"), "l": "Este año"}, {"t": "punto", "c": "#16130F", "l": "Registro anterior"}]
    if normal is not None:
        ley.append({"t": "discontinua", "c": "#16130F", "l": "Media 1991-2020"})
    return {"titulo": titulo, "leyenda": ley, "pie": pie, "svg": f"{SUB}/{nombre}.svg", "png": None, "ancho": w, "alto": h, "csv": f"{SUB}/{nombre}.csv"}


def limpiar(raiz: Path, hoy: date) -> int:
    lim = (hoy - timedelta(days=VIDA_DIAS)).isoformat()
    n = 0
    for f in (raiz / "docs" / SUB).glob("*"):
        if re.match(r"\d{4}-\d{2}-\d{2}-", f.name) and f.name[:10] < lim:
            f.unlink()
            n += 1
    return n


# ----------------------------------------------------------------------------- frases
def _palabras(cola: str) -> dict:
    idx, signo, adj = M.COLAS[cola]
    alto = "alto" if signo > 0 else "bajo"
    return {"idx": idx, "signo": signo, "adj": adj, "u": M._unidad(cola), "alto": alto, "alta": alto[:-1] + "a",
            "var": VAR.get(cola, "lluvia acumulada"), "dec": 1 if idx == 2 else 2}


def _hechos_capital(ciudad, estacion, fc, puesto, empate, largo, cola, cerrado, i0, h0, per, lag) -> list[dict]:
    w = _palabras(cola)
    u, dec = w["u"], w["dec"]
    val = _n(fc["valor"], dec)
    H = []

    def add(k, txt):
        H.append({"id": f"mf_{k}", "dice": txt, "fuente": FUENTE_H})
    pos = (f"iguala el registro más {w['alto']}" if empate else (f"el registro más {w['alto']}" if puesto == 1 else f"el {ORD.get(puesto, str(puesto) + '.º')} más {w['alto']}"))
    art = "una" if w["idx"] != 2 else "una"
    add("valor", f"La estación de AEMET de {estacion} registra en {largo} {art} {w['var']} de {val} {u}: {pos} de su serie de {fc['n']} años, "
                 f"que empieza en {fc['desde']}. Dato validado hasta el {_dia(h0)}.")
    a_y, a_v = fc["anterior"]
    if puesto == 1 and not empate:
        add("anterior", f"El registro más {w['alto']} de {ciudad} para este tramo era hasta ahora el de {a_y}, con {_n(a_v, dec)} {u}; "
                        f"la diferencia es de {_n(abs(_dif(fc['valor'], a_v, dec)), dec)} {u}.")
    elif empate:
        add("anterior", f"Iguala el registro de {a_y} ({_n(a_v, dec)} {u}): una diferencia de menos de {'0,05 °C' if w['idx'] != 2 else 'un 1 %'} no se cuenta como récord.")
    else:
        delante = [(y, v) for y, v in fc["top5"] if y != i0.year][: max(1, puesto - 1)]
        add("anterior", f"Por delante en {ciudad} {'está' if len(delante) == 1 else 'están'} "
                        + _lista([f"{y} ({_n(v, dec)} {u})" for y, v in delante]) + ".")
    if fc["normal"] is not None:
        if w["idx"] == 2:
            add("normal", f"La media de 1991-2020 del mismo tramo en esa estación es de {_n(fc['normal'], 1)} {u}; este año lleva el {_n(fc['pct'], 0)} % de esa cantidad.")
        else:
            d = _dif(fc["valor"], fc["normal"], dec)
            add("normal", f"La media de 1991-2020 del mismo tramo en esa estación es de {_n(fc['normal'], dec)} {u}; este año va {_n(abs(d), dec)} {u} "
                          f"{'por encima' if d >= 0 else 'por debajo'}.")
    t5 = fc["top5"]
    if len(t5) >= 5:
        txt = f"Los cinco registros más {w['alto']}s de la serie de {ciudad} para este tramo son, por orden, " + _lista([y for y, _ in t5]) + "."
        if fc["siglo"] is not None:
            txt += f" De los diez primeros, {fc['siglo']} son posteriores al año 2000."
        add("top", txt)
    if not cerrado:
        fin = M.fin_periodo(i0, per)
        add("pendiente", f"El periodo termina el {_dia(fin)}: quedan {(fin - h0).days} días por contar y AEMET valida sus datos con unos {lag} días de retraso, "
                         f"así que el puesto puede cambiar.")
    return H


def _titular_capital(ciudad, fc, puesto, empate, largo, cola) -> str:
    w = _palabras(cola)
    a_y, a_v = fc["anterior"]
    if empate:
        return f"{ciudad}: {largo} iguala el {w['adj']} en {fc['n']} años de serie de AEMET ({_n(fc['valor'], w['dec'])} {w['u']}; {_n(a_v, w['dec'])} en {a_y})"
    if puesto == 1:
        return f"{ciudad}: {largo}, el {w['adj']} en {fc['n']} años de serie de AEMET ({_n(fc['valor'], w['dec'])} {w['u']}; el anterior, {_n(a_v, w['dec'])} en {a_y})"
    return f"{ciudad}: {largo}, el {ORD.get(puesto, str(puesto) + '.º')} {w['adj']} en {fc['n']} años de serie de AEMET"


def _texto(titular, hechos, n_claves=3) -> dict:
    d = [h["dice"] for h in hechos]
    return {"titular": titular, "subtitulo": d[1] if len(d) > 1 else "", "entradilla": d[0],
            "cuerpo": [" ".join(d[i:i + 2]) for i in range(1, len(d), 2)], "claves": d[:n_claves]}


def _version_capital(cod, ciudad, estacion, ind, puesto_mesa, c_nac, i0, h0, per, cola, cerrado, largo, corto, lag, raiz, ident, con_grafico, PROV) -> dict | None:
    fc = ficha(ind, i0, h0, cola, raiz)
    if not fc:
        return None
    w = _palabras(cola)
    empate = (fc["puesto"] == 1 and puesto_mesa == 2)          # la mesa trata el empate práctico como segundo puesto
    hechos = _hechos_capital(ciudad, estacion, fc, puesto_mesa, empate, largo, cola, cerrado, i0, h0, per, lag)
    tit = _titular_capital(ciudad, fc, puesto_mesa, empate, largo, cola)
    cif = [{"n": f"{_n(fc['valor'], w['dec'])} {w['u']}", "l": f"{w['var']} en {largo}, estación de {estacion}", "tono": TONO.get(cola, "calor")},
           {"n": ("Iguala" if empate else f"{puesto_mesa}.º") + f" de {fc['n']}", "l": f"puesto en su serie, que empieza en {fc['desde']}", "tono": TONO.get(cola, "calor")}]
    if fc["anom"] is not None and w["idx"] != 2:
        an = _dif(fc["valor"], fc["normal"], w["dec"])
        cif.append({"n": f"{'+' if an >= 0 else ''}{_n(an, w['dec'])} {w['u']}", "l": "sobre la media de 1991-2020 del mismo tramo", "tono": TONO.get(cola, "calor")})
    g = None
    if con_grafico:
        csv_txt = "anio,valor,unidad\n" + "\n".join(f"{y},{v:.2f},{w['u']}" for y, v in reversed(fc["serie"])) + "\n"
        g = _guardar_grafico(raiz, f"{ident}-{cod}", f"{ciudad}: {w['var']}, {corto}, año a año", fc["serie"], w["u"], cola, fc["normal"],
                             f"Mismo tramo de cada año ({_dia(i0, False)} a {_dia(h0, False)}). Estación de AEMET de {estacion}. Años con al menos el 95 % de los días.", csv_txt)
    nom, slug = PROV.get(cod, (ciudad, None))
    return {"provincia": nom, "slug": slug, "hechos": hechos, "puntos": round(100 - 10 * puesto_mesa + fc["n"] / 10, 1), "cifras": cif, "grafico": g,
            "texto": _texto(tit, hechos), "redaccion": {"modo": "plantilla", "verificado": True}, "_ficha": fc, "_empate": empate}


# ----------------------------------------------------------------------------- la noticia
def _contexto(c: dict) -> tuple | None:
    try:
        per, cola = c["periodo"], c["cola"]
        i0 = date.fromisoformat(str((c.get("clave") or {})["periodo"])[:10])
        h0 = date.fromisoformat(str(c["fecha_dato"])[:10])
    except Exception:
        return None
    if per not in M.PERIODOS or cola not in M.COLAS:
        return None
    corto, largo = M.nombre_periodo(i0, per, h0)
    return per, cola, i0, h0, corto, largo, h0 >= M.fin_periodo(i0, per)


def noticia_de_mesa(c: dict, hoy: date, raiz: Path, graficos_provinciales: bool = True, lag: int | None = None) -> dict | None:
    """Historia completa (formato de noticias/historias) de un marco de la mesa. La escribe y la devuelve; None si no aplica."""
    tipo = c.get("tipo_mesa")
    if tipo not in ("marco_nacional", "marco_capital"):
        return None
    ctx = _contexto(c)
    if not ctx:
        return None
    per, cola, i0, h0, corto, largo, cerrado = ctx
    if lag is None:
        try:
            lag = max(1, (date.fromisoformat(str(c.get("fecha_disponible"))[:10]) - h0).days)
        except Exception:
            lag = 8
    w = _palabras(cola)
    u, dec = w["u"], w["dec"]
    est = M.estaciones_capital(raiz)                              # {cod: (ind, ciudad, estación)}
    por_ciudad = {v[1]: (cod, v[0], v[2]) for cod, v in est.items()}
    PROV = _provincias()
    terr = "es" if tipo == "marco_nacional" else M._slug(c.get("territorio") or "")
    ident = f"{h0.isoformat()}-mesa-{per}-{cola}-{terr}"[:88]
    # los gráficos llevan nombre fijo (sin fecha): cada pasada los reescribe en vez de acumular medio mega de ficheros nuevos al día
    gid = f"mesa-{per}-{cola}-{terr}"[:70]
    limites = [x.strip()[0].upper() + x.strip()[1:] for x in str(c.get("invalidar") or "").split(";") if x.strip()]
    limites.append("La media de 1991-2020 es la de la misma estación y el mismo tramo, calculada con sus datos diarios.")
    metodo = (f"Para cada capital con estación de AEMET en la propia ciudad y al menos 40 años de serie se calcula la {w['var']} del tramo "
              f"{_dia(i0)} - {_dia(h0)} y se compara con el mismo tramo de cada año anterior de esa estación. Solo cuentan los años con al menos "
              f"el 95 % de los días con dato. Una diferencia con el récord de menos de {'0,05 °C' if w['idx'] != 2 else 'un 1 %'} se trata como empate, no como récord. "
              f"Cada capital se compara con su propia serie: no es una media de España.")
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    base = {"id": ident, "tipo": f"mesa_{tipo}", "fecha": hoy.isoformat(), "kicker": f"{KICKER.get(cola, 'Clima')} · {corto}", "tono": TONO.get(cola, "calor"),
            "puntos": (c.get("puntuacion") or {}).get("puntos"), "fuentes": FUENTES, "metodo": metodo, "limites": limites, "pagina": PAGINA,
            "seccion": "analisis", "generador": "mesa", "redaccion": {"modo": "plantilla", "verificado": True}, "actualizada": ahora, "corte": h0.isoformat()}

    if tipo == "marco_capital":
        ciudad = c.get("territorio")
        if ciudad not in por_ciudad:
            return None
        cod, ind, estacion = por_ciudad[ciudad]
        puesto = int((c.get("comparacion") or {}).get("puesto") or 0) or 1
        v = _version_capital(cod, ciudad, estacion, ind, puesto, c, i0, h0, per, cola, cerrado, largo, corto, lag, raiz, gid, True, PROV)
        if not v:
            return None
        v.pop("_ficha"), v.pop("_empate")
        h = {**base, "hechos": v["hechos"], "cifras": v["cifras"], "provincias": {}, "grafico": v["grafico"],
             "texto": {**v["texto"], "titular": c.get("titular") or v["texto"]["titular"]}}
        return _escribir(h, raiz)

    # --- marco nacional
    tabla = [f for f in (c.get("tabla") or []) if f.get("ciudad") in por_ciudad]
    vers, fichas = {}, {}
    for f in tabla:
        cod, ind, estacion = por_ciudad[f["ciudad"]]
        v = _version_capital(cod, f["ciudad"], estacion, ind, int(f["puesto"]), c, i0, h0, per, cola, cerrado, largo, corto, lag, raiz, gid,
                             graficos_provinciales, PROV)
        if v:
            fichas[f["ciudad"]] = (v.pop("_ficha"), v.pop("_empate"), f)
            vers[cod] = v
    prim = [(ci, fc, f) for ci, (fc, emp, f) in fichas.items() if int(f["puesto"]) == 1]
    if len(prim) < 3:
        return None
    marco = c.get("marco") or {}
    n, total = int(marco.get("n_primeros") or len(prim)), int(marco.get("total") or len(est))
    lider = max(prim, key=lambda x: x[1]["n"])
    H = []

    def add(k, txt):
        H.append({"id": f"mf_{k}", "dice": txt, "fuente": FUENTE_H})
    add("cuenta", f"En {n} de las {total} capitales con estación de AEMET en la propia ciudad, {largo} es el {w['adj']} de su serie, entre las de 40 años o más. "
                  f"Dato validado de AEMET hasta el {_dia(h0)}{'' if cerrado else '; el periodo no ha terminado'}.")
    lc, lf, lt = lider
    add("lider", f"La serie más larga es la de {lt['estacion']}, con {lf['n']} años (desde {lf['desde']}): {_n(lf['valor'], dec)} {u} de {w['var']} en {largo}, "
                 f"frente a {_n(lf['anterior'][1], dec)} {u} en {lf['anterior'][0]}, el registro más {w['alto']} hasta ahora.")
    marg = sorted(((abs(_dif(fc["valor"], fc["anterior"][1], dec)), ci, fc) for ci, fc, _ in prim), key=lambda x: -x[0])
    mx, mn = marg[0], marg[-1]
    add("margen_max", f"El mayor margen sobre el registro anterior es el de {mx[1]}: {_n(mx[2]['valor'], dec)} {u} frente a {_n(mx[2]['anterior'][1], dec)} {u} en "
                      f"{mx[2]['anterior'][0]}, una diferencia de {_n(mx[0], dec)} {u}.")
    if mn[1] != mx[1]:
        add("margen_min", f"El más ajustado es el de {mn[1]}: {_n(mn[0], dec)} {u} sobre {mn[2]['anterior'][0]}"
                          + ("." if cerrado else "; con el periodo sin cerrar, es el que más fácilmente puede cambiar."))
    cae = Counter(fc["anterior"][0] for _, fc, _ in prim).most_common(3)
    add("cae", "El registro que cae es " + _lista([f"el de {y} en {k} {'capital' if k == 1 else 'capitales'}" for y, k in cae]) + ".")
    anoms = sorted(((_dif(fc["valor"], fc["normal"], dec), ci) for ci, fc, _ in prim if fc["normal"] is not None and w["idx"] != 2), key=lambda x: x[0])
    if len(anoms) >= 3:
        lado = "por encima" if anoms[0][0] >= 0 else "de diferencia"
        add("normal", f"Frente a la media de 1991-2020 del mismo tramo en cada estación, esas capitales van entre {_n(abs(anoms[0][0]), dec)} y {_n(abs(anoms[-1][0]), dec)} {u} {lado}; "
                      f"la mayor diferencia es la de {anoms[-1][1] if w['signo'] > 0 else anoms[0][1]}.")
    if len(lf["top5"]) >= 5:
        txt = f"En {lc}, los cinco registros más {w['alto']}s de la serie para este tramo son, por orden, " + _lista([y for y, _ in lf["top5"]]) + "."
        if lf["siglo"] is not None:
            txt += f" De los diez primeros, {lf['siglo']} son posteriores al año 2000."
        add("top", txt)
    sig = [fc["siglo"] for _, fc, _ in prim if fc["siglo"] is not None]
    if len(sig) >= 3:
        add("siglo", f"En el conjunto de esas {len(sig)} capitales, de los diez registros más {w['alto']}s de cada serie una media de {_n(sum(sig) / len(sig), 1)} son posteriores al año 2000.")
    otras = [ci for ci, (fc, emp, f) in fichas.items() if int(f["puesto"]) > 1]
    if otras:
        add("otras", f"{'Otra capital está' if len(otras) == 1 else f'Otras {len(otras)} capitales están'} en segundo o tercer puesto de su serie: {_lista(sorted(otras))}.")
    if not cerrado:
        fin = M.fin_periodo(i0, per)
        add("pendiente", f"El periodo termina el {_dia(fin)}: quedan {(fin - h0).days} días por contar y AEMET valida sus datos con unos {lag} días de retraso, "
                         f"así que la cuenta de capitales puede cambiar.")
    cif = [{"n": f"{n} de {total}", "l": "capitales con estación de AEMET en la propia ciudad en primer puesto de su serie", "tono": TONO.get(cola, "calor")},
           {"n": f"{_n(lf['valor'], dec)} {u}", "l": f"{lt['estacion']}; el anterior, {_n(lf['anterior'][1], dec)} en {lf['anterior'][0]}", "tono": TONO.get(cola, "calor")},
           {"n": f"{_n(mx[0], dec)} {u}", "l": f"el mayor margen sobre el registro anterior, en {mx[1]}", "tono": TONO.get(cola, "calor")}]
    # gráfico nacional: la serie de la capital con la serie más larga; el CSV lleva todas las que van primeras
    orden = [ci for ci, _, _ in sorted(prim, key=lambda x: -x[1]["n"])]
    por_anio = {}
    for ci, fc, _ in prim:
        for y, v in fc["serie"]:
            por_anio.setdefault(y, {})[ci] = v
    csv_txt = "anio," + ",".join(f'"{ci}"' for ci in orden) + "\n" + "\n".join(
        f"{y}," + ",".join("" if ci not in por_anio[y] else f"{por_anio[y][ci]:.2f}" for ci in orden) for y in sorted(por_anio, reverse=True)) + "\n"
    g = _guardar_grafico(raiz, f"{gid}-serie", f"{lc}: {w['var']}, {corto}, año a año", lf["serie"], u, cola, lf["normal"],
                         f"Mismo tramo de cada año ({_dia(i0, False)} a {_dia(h0, False)}). Estación de AEMET de {lt['estacion']}. El CSV trae las {len(orden)} capitales.", csv_txt)
    d = [x["dice"] for x in H]
    texto = {"titular": c.get("titular"), "subtitulo": d[1], "entradilla": d[0],
             "cuerpo": [" ".join(d[i:i + 2]) for i in range(1, len(d), 2)], "claves": [d[0], d[2]] + ([d[4]] if len(d) > 4 else [])}
    return _escribir({**base, "hechos": H, "cifras": cif, "provincias": vers, "grafico": g, "texto": texto}, raiz)


def _escribir(h: dict, raiz: Path) -> dict:
    p = raiz / "docs" / "prensa" / "noticias" / "historias"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{h['id']}.json").write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return h


# ----------------------------------------------------------------------------- piezas agregadas por la mesa (una versión por capital)
def noticia_agregada(c: dict, it: dict, hoy: date, raiz: Path) -> dict | None:
    """Historia completa de una pieza que la mesa ha agregado a partir de hallazgos con versión propia por territorio
    (huella del mes, rachas, récords del mes). No calcula nada nuevo: ordena lo que cada versión ya dice y le da página,
    hechos uno a uno y versión por provincia. `it` es el elemento de portada (trae titular, entradilla, fuente y gráfico)."""
    vers = [v for v in (c.get("_versiones_reales") or c.get("versiones_provinciales") or []) if isinstance(v, dict) and v.get("titular")]
    if len(vers) < 3 or not it.get("titular"):
        return None
    PROV = _provincias()
    por_slug = {v[1]: k for k, v in PROV.items()}
    try:
        corte = date.fromisoformat(str(c.get("fecha_dato") or it.get("corte"))[:10])
    except Exception:
        corte = hoy
    ind = M._slug(str((c.get("clave") or {}).get("indicador") or c.get("tipo_mesa") or c.get("tipo") or "pieza"))[:40]
    ident = f"{corte.isoformat()}-mesa-{ind}-es"[:88]

    def pr(v):
        x = (v.get("rareza") or {}).get("PR")
        return float(x) if isinstance(x, (int, float)) else None
    con_pr = all(pr(v) is not None for v in vers)
    if con_pr:
        vers = sorted(vers, key=lambda v: -pr(v))
    ent = re.sub(r"\s*Capitales:\s*[^.]+\.", "", str(it.get("entradilla") or "")).strip()
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ])", ent) if f.strip()]
    fuente = it.get("fuente") or c.get("fuente") or "AEMET y cálculo propio"
    H = [{"id": f"ag_{i}", "dice": f, "fuente": fuente} for i, f in enumerate(frases[:4])]
    if not H:
        H = [{"id": "ag_0", "dice": it["titular"], "fuente": fuente}]
    H.append({"id": "ag_lista", "dice": f"Son {len(vers)} capitales: {_lista([v.get('territorio') or '' for v in vers])}.", "fuente": fuente})
    if con_pr:
        H.append({"id": "ag_ext", "dice": f"La mayor diferencia entre los dos climas es la de {vers[0].get('territorio')} ({_n(pr(vers[0]), 0)} veces más probable ahora); "
                                          f"la menor, la de {vers[-1].get('territorio')} ({_n(pr(vers[-1]), 0)} veces).", "fuente": fuente})
    for i, v in enumerate(vers[:6]):
        H.append({"id": f"ag_v{i}", "dice": str(v["titular"]).rstrip(".") + ".", "fuente": fuente})
    provs = {}
    for v in vers:
        cod = por_slug.get(v.get("provincia_slug") or M._slug(v.get("territorio") or ""))
        if not cod:
            continue
        t = str(v["titular"]).rstrip(".") + "."
        hv = [{"id": "ag_p0", "dice": t, "fuente": fuente}] + [{"id": f"ag_p{i + 1}", "dice": f, "fuente": fuente} for i, f in enumerate(frases[1:3])]
        cif = []
        if isinstance(v.get("valor"), (int, float)):
            cif.append({"n": _n(v["valor"], 1) + (" °C" if v.get("serie") == "huella" else ""), "l": f"valor de {v.get('territorio')} ({_dia(corte)})", "tono": "calor"})
        if pr(v) is not None:
            cif.append({"n": f"× {_n(pr(v), 0)}", "l": "veces más probable ahora que en 1961-1990", "tono": "calor"})
        provs[cod] = {"provincia": PROV[cod][0], "slug": PROV[cod][1], "hechos": hv, "puntos": pr(v) or 0, "cifras": cif, "grafico": None,
                      "texto": {"titular": v["titular"], "subtitulo": frases[0] if frases else "", "entradilla": t,
                                "cuerpo": [f"{len(vers)} capitales están en la misma situación: {_lista([x.get('territorio') or '' for x in vers])}."] + frases[1:3],
                                "claves": [t]},
                      "redaccion": {"modo": "plantilla", "verificado": True}}
    limites = [x.strip()[0].upper() + x.strip()[1:] for x in str(it.get("invalidar") or c.get("invalidar") or "; ".join(c.get("limites") or [])).split(";") if x.strip()]
    # el intervalo de remuestreo es el de una sola capital: va en su versión, no en la nacional
    limites = [y for y in (" ".join(f for f in re.split(r"(?<=\.)\s+", x) if "ntervalo" not in f).strip() for x in limites) if y]
    d = [x["dice"] for x in H]
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    h = {"id": ident, "tipo": f"mesa_{c.get('tipo_mesa') or c.get('tipo') or 'agregada'}", "fecha": hoy.isoformat(), "kicker": "Calor · capital a capital" if con_pr else "Capital a capital",
         "tono": "calor", "puntos": (c.get("puntuacion") or {}).get("puntos"), "hechos": H,
         "cifras": [{"n": str(len(vers)), "l": "capitales, cada una frente a su propia serie", "tono": "calor"}]
                   + ([{"n": f"× {_n(pr(vers[0]), 0)}", "l": f"la mayor diferencia, en {vers[0].get('territorio')}", "tono": "calor"}] if con_pr else []),
         "fuentes": fuente, "metodo": "Cada capital se compara con su propia serie. El cálculo de cada una está en su versión provincial y en la página de su provincia.",
         "limites": limites, "pagina": PAGINA, "provincias": provs, "seccion": "analisis", "grafico": it.get("grafico") if (it.get("grafico") or {}).get("svg") else None,
         "generador": "mesa", "texto": {"titular": it["titular"], "subtitulo": d[1] if len(d) > 1 else "", "entradilla": d[0],
                                        "cuerpo": [" ".join(d[i:i + 2]) for i in range(1, len(d), 2)], "claves": d[:3]},
         "redaccion": {"modo": "plantilla", "verificado": True}, "actualizada": ahora, "corte": corte.isoformat()}
    return _escribir(h, raiz)
