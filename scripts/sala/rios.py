"""Ríos en crecida: caudal MEDIDO en las estaciones de aforo de los organismos de cuenca.

Fuente: docs/caudal/crecidas.json (lista «aforos»: estado de cada estación con su caudal, el de 24 horas antes y su
caudal de base) y docs/caudal/aforos.json (serie de los últimos días de cada estación, para el gráfico).

Solo cifras medidas: Confederación Hidrográfica del Júcar, Agència Catalana de l'Aigua, Gobierno de Navarra (las
redes que hoy entran en el mapa). Los puntos del modelo GloFAS NO se usan como medida; tampoco hay historia de
caudal bajo, porque los percentiles de la época del año salen del modelo, no de los aforos (auditoría del 17-10-2026).

Criterios de crecidas.py (clima-scripts): crecida fuerte = q ≥ 20 m³/s, ≥ 10 × su base y +15; subida brusca =
q ≥ 2 y (≥ 4 × base y +1,5) o (≥ 3 × el de hace 24 h y +2). Aquí además: lectura de 12 horas como mucho y, en la
historia, solo estaciones con ≥ 5 m³/s (por debajo, una subida es ruido de un caudal mínimo).
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SECCION = "agua"
PAGINA = "https://calentamientoglobal.es/caudal-rios-espana-mapa/"
NOMBRE_FUENTE = {"CH Júcar": "Confederación Hidrográfica del Júcar", "jucar": "Confederación Hidrográfica del Júcar",
                 "Agència Catalana de l'Aigua": "Agència Catalana de l'Aigua", "cataluna": "Agència Catalana de l'Aigua",
                 "Gobierno de Navarra": "Gobierno de Navarra", "navarra": "Gobierno de Navarra"}
SIGLA = {"Confederación Hidrográfica del Júcar": "CHJ", "Agència Catalana de l'Aigua": "ACA", "Gobierno de Navarra": "Gobierno de Navarra"}
# Estaciones cuya provincia no se puede afirmar: las coordenadas publicadas no casan con el río (JUC-13568 «Vernissa»
# cae en la Marina Alta, Alicante, pero el Vernissa corre por la Safor, Valencia). Salen sin provincia.
PROV_DUDOSA = {"JUC-13568"}
# Estaciones sin coordenadas en el feed pero con lugar inequívoco: el azud de Font d'en Carròs (Serpis) y Huerto Mulet
# (Júcar, en la Ribera) están en la provincia de Valencia.
PROV_MANUAL = {"JUC-14099": "46", "JUC-13070": "46"}
MAX_EDAD_H = 12
Q_MIN = 5.0


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _t(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _lugar(a):
    """(río, lugar) legibles a partir del nombre de la estación."""
    rio = (a.get("rio") or "").strip()
    n = (a.get("nombre") or "").strip()
    for pref in ("Aforament - ", "Qualitat - "):
        while n.startswith(pref):
            n = n[len(pref):]
    if " en " in n and not rio:
        rio, n = n.split(" en ", 1)
    elif " en " in n and n.split(" en ", 1)[0].strip().lower() == rio.lower():
        n = n.split(" en ", 1)[1]
    if rio and n.endswith(f"({rio})"):
        n = n[: -len(rio) - 2].strip()
    if rio and n.lower() == rio.lower():
        n = ""
    if rio.lower().startswith("serpis sobre"):
        rio = "Serpis"
    return rio, n


ART_FUENTE = {"Confederación Hidrográfica del Júcar": "la", "Agència Catalana de l'Aigua": "la", "Gobierno de Navarra": "el"}


def _en(lugar):
    """«Embalse de Terrateig» → «el embalse de Terrateig»; «Azud Font D'en Carrós» → «el azud de Font D'en Carrós»."""
    for pref, txt in (("Embalse de ", "el embalse de "), ("Embalse ", "el embalse de "), ("Azud de ", "el azud de "), ("Azud ", "el azud de "),
                      ("Presa de ", "la presa de "), ("Salida del embalse de ", "la salida del embalse de ")):
        if lugar.startswith(pref):
            return txt + lugar[len(pref):]
    return lugar


def _dudosa(a):
    return a.get("id") in PROV_DUDOSA


def _quien(a):
    if _dudosa(a):
        return f"la estación de aforo {a.get('nombre')} de la {SIGLA.get(NOMBRE_FUENTE.get(a.get('fuente')), 'CHJ')}"
    rio, lugar = _lugar(a)
    if rio and lugar:
        return f"el {rio} en {_en(lugar)}"
    if rio:
        return f"el {rio}"
    return f"la estación de {lugar}"


def _estacion(a):
    rio, lugar = _lugar(a)
    return lugar or rio or a.get("nombre", "")


def _hora_local(d, cod):
    tz = ZoneInfo("Atlantic/Canary" if cod in ("35", "38") else "Europe/Madrid")
    return d.astimezone(tz)


def _hecho(R, a, i, con_prov=True):
    q, q24, base = _num(a["q"]), _num(a.get("q24")), _num(a.get("base"))
    d = _hora_local(a["_t"], a.get("prov"))
    fuente = NOMBRE_FUENTE.get(a.get("fuente"), a.get("fuente") or "organismo de cuenca")
    prov = f" ({R.nprov(a['prov'])})" if con_prov and a.get("prov") in R.PROV else ""
    quien = _quien(a)
    cuando = f"a las {d:%-H:%M} del {R.dia(d.date().isoformat())}"
    if q24 is not None and q24 < 0.05:
        antes = "24 horas antes no llevaba agua"
        vals = []
    elif q24 is not None:
        antes = f"24 horas antes llevaba {R.f1(q24)} m³/s"
        vals = [R.f1(q24)]
        if q24 >= 1 and q / q24 >= 3:
            antes += f": {R.f1(q / q24)} veces más"
            vals.append(R.f1(q / q24))
    else:
        antes, vals = "", []
    art = ART_FUENTE.get(fuente, "la")
    if _dudosa(a):
        dice = (f"La estación de aforo {a.get('nombre')} {'del' if art == 'el' else 'de ' + art} {fuente} midió {R.f1(q)} m³/s {cuando}"
                + (f"; {antes}." if antes else "."))
    else:
        dice = (f"La estación de aforo {'del' if art == 'el' else 'de ' + art} {fuente} midió en {quien}{prov} {R.f1(q)} m³/s {cuando}"
                + (f"; {antes}." if antes else "."))
    dice = dice[0].upper() + dice[1:]
    return R.hecho(f"aforo_{i}", dice, f"{fuente} (estación de aforo, dato en tiempo real)",
                   [R.f1(q), f"{d:%-H:%M}"] + vals, lugar=_estacion(a))


def _grafico(R, sel, series, nombre, titulo):
    """Pequeños múltiplos: la serie de los últimos 3 días de hasta 4 estaciones, cada una con su escala."""
    paneles = []
    for a in sel[:4]:
        s = [(t, _num(v)) for t, v in (series.get(a["id"]) or []) if _num(v) is not None]
        s = [(_t(t), v) for t, v in s]
        s = [(t, v) for t, v in s if t and (a["_t"] - t).total_seconds() <= 3 * 86400 and t <= a["_t"]]
        if len(s) >= 3:
            paneles.append((a, s))
    if not paneles:
        return None
    cols = 2 if len(paneles) > 1 else 1
    filas_n = (len(paneles) + cols - 1) // cols
    W = 960 if cols == 2 else 640
    pw, ph = (W - 40) / cols, 190
    Hh = filas_n * (ph + 18) + 6
    out, csvf = [], []
    for k, (a, s) in enumerate(paneles):
        cx, cy = 20 + (k % cols) * pw, 6 + (k // cols) * (ph + 18)
        ml, mr, mt, mb = 52, 18, 34, 26
        t0, t1 = s[0][0], s[-1][0]
        span = max(1.0, (t1 - t0).total_seconds())
        vmax = max(v for _, v in s) * 1.12 or 1
        X = lambda t: cx + ml + (t - t0).total_seconds() / span * (pw - ml - mr)
        Y = lambda v: cy + mt + (1 - v / vmax) * (ph - mt - mb)
        rio, lugar = _lugar(a)
        tit_p = (f"Estación de aforo {a.get('nombre')} (CHJ)" if _dudosa(a) else
                 (f"{rio} en {lugar}" if rio and lugar else (rio or lugar)) + (f" ({R.nprov(a['prov'])})" if a.get("prov") in R.PROV else ""))
        out.append(R._t(cx + 4, cy + 16, tit_p, 13.5, R.TINTA, "start", 700))
        for frac in (0, 0.5, 1):
            v = vmax / 1.12 * frac
            out.append(f'<line x1="{cx + ml}" x2="{cx + pw - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>')
            out.append(R._t(cx + ml - 6, Y(v) + 4, R.f1(v), 11, R.GRIS, "end"))
        pts = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in s)
        area = f"{X(s[0][0]):.1f},{Y(0):.1f} " + pts + f" {X(s[-1][0]):.1f},{Y(0):.1f}"
        out.append(f'<polygon points="{area}" fill="#DCE8F5"></polygon>')
        out.append(f'<polyline points="{pts}" fill="none" stroke="{R.LLUVIA}" stroke-width="2.4" stroke-linejoin="round"></polyline>')
        tl, vl = s[-1]
        out.append(f'<circle cx="{X(tl):.1f}" cy="{Y(vl):.1f}" r="4.5" fill="{R.LLUVIA}"></circle>')
        out.append(R._t(X(tl) - 6, Y(vl) - 9, f"{R.f1(vl)} m³/s", 12.5, R.TINTA, "end", 700))
        for t in (t0, t1):
            dl = _hora_local(t, a.get("prov"))
            out.append(R._t(X(t), cy + ph - 8, f"{R.dia_corto(dl.date().isoformat())} {dl:%-H:%M}", 11, R.GRIS, "start" if t == t0 else "end"))
        for t, v in s:
            csvf.append((a["nombre"], rio, R.nprov(a.get("prov")) if a.get("prov") in R.PROV else "", t.strftime("%Y-%m-%dT%H:%MZ"), v,
                         NOMBRE_FUENTE.get(a.get("fuente"), a.get("fuente"))))
    svg = R._svg(W, Hh, titulo, out)
    return R.guardar_grafico(nombre, svg, csvf, ["estacion", "rio", "provincia", "hora_utc", "caudal_m3s", "fuente"], titulo, [],
                             "Caudal medido en las estaciones de aforo (m³/s), últimos 3 días; cada panel con su propia escala. Dato en tiempo real, "
                             "sujeto a validación del organismo de cuenca. Fuentes: Confederación Hidrográfica del Júcar, Agència Catalana de l'Aigua, "
                             "Gobierno de Navarra. Gráfico: calentamientoglobal.es.")


def _cuenta(R, nf, ns):
    """«3 estaciones de aforo marcan una crecida fuerte y otras 5, una subida brusca del caudal»."""
    a = (f"{R.plural(nf, 'estación de aforo marca', 'estaciones de aforo marcan')} una crecida fuerte" if nf else "")
    if ns:
        b = ((f"otras {ns}, una subida brusca del caudal" if ns > 1 else "otra, una subida brusca del caudal") if nf else
             f"{R.plural(ns, 'estación de aforo marca', 'estaciones de aforo marcan')} una subida brusca del caudal")
        return f"{a} y {b}" if a else b
    return a


def generar(R, D):
    C = R.leer(R.DOCS / "caudal" / "crecidas.json", {}) or {}
    A = R.leer(R.DOCS / "caudal" / "aforos.json", {}) or {}
    series = {e["id"]: e.get("serie") or [] for e in A.get("estaciones") or []}
    vivas = []
    for a in C.get("aforos") or []:
        t, q = _t(a.get("t")), _num(a.get("q"))
        if not t or q is None or a.get("estado") not in ("crecida", "subida"):
            continue
        edad = (R.AHORA - t).total_seconds() / 3600
        if edad > MAX_EDAD_H or edad < -1 or q < Q_MIN:
            continue
        a = dict(a, _t=t, _edad=edad)
        if a.get("id") in PROV_DUDOSA:
            a["prov"] = None
        elif not a.get("prov") and a.get("id") in PROV_MANUAL:
            a["prov"] = PROV_MANUAL[a["id"]]
        vivas.append(a)
    if not vivas:
        return []
    # orden: crecida fuerte primero, después por caudal; una estación dudosa nunca abre la historia
    vivas.sort(key=lambda a: (-(a.get("n") or 0), -_num(a["q"])))
    if _dudosa(vivas[0]):
        firme = next((i for i, a in enumerate(vivas) if not _dudosa(a)), None)
        if firme is None:
            return []
        vivas.insert(0, vivas.pop(firme))
    fuertes = [a for a in vivas if a.get("estado") == "crecida"]
    ultima = max(a["_t"] for a in vivas)
    dl = _hora_local(ultima, "46").date().isoformat()
    hid = f"{dl}-rios-crecida"

    hechos = []
    for i, a in enumerate(vivas[:6]):
        hechos.append(_hecho(R, a, i))
    fuentes = sorted({NOMBRE_FUENTE.get(a.get("fuente"), a.get("fuente")) for a in vivas})
    hechos.append(R.hecho("aforos_n", f"En las últimas lecturas publicadas, {_cuenta(R, len(fuertes), len(vivas) - len(fuertes))}, según el criterio del observatorio.",
                          "; ".join(fuentes) + "; criterio de crecida de calentamientoglobal.es",
                          [str(len(fuertes)), str(len(vivas) - len(fuertes))]))
    hechos.append(R.hecho("aforos_metodo", "Son datos en tiempo real de las estaciones de aforo de los organismos de cuenca, sujetos a su validación.",
                          "; ".join(fuentes)))
    a0 = vivas[0]
    q0 = _num(a0["q"])
    d0 = _hora_local(a0["_t"], a0.get("prov"))
    prov0 = f" ({R.nprov(a0['prov'])})" if a0.get("prov") in R.PROV else ""
    q24 = _num(a0.get("q24"))
    if q24 is not None and q24 < 0.05:
        tit = f"{_quien(a0)[0].upper() + _quien(a0)[1:]}{prov0} lleva {R.f1(q0)} m³/s: 24 horas antes no llevaba agua"
    elif q24 is not None and q24 >= 1 and q0 / q24 >= 3:
        tit = f"{_quien(a0)[0].upper() + _quien(a0)[1:]}{prov0} multiplica su caudal por {R.f1(q0 / q24)} y llega a {R.f1(q0)} m³/s"
    else:
        tit = f"{_quien(a0)[0].upper() + _quien(a0)[1:]}{prov0} sube a {R.f1(q0)} m³/s"
    if len(tit) > 165:
        tit = f"{_quien(a0)[0].upper() + _quien(a0)[1:]} lleva {R.f1(q0)} m³/s"
    otros = hechos[1:min(6, len(vivas))]
    pl = {"titular": tit,
          "subtitulo": hechos[len(vivas[:6])]["dice"],
          "entradilla": hechos[0]["dice"],
          "cuerpo": [" ".join(h["dice"] for h in otros[:3]), " ".join(h["dice"] for h in otros[3:]), hechos[-1]["dice"]],
          "claves": [h["dice"] for h in hechos[:3]]}
    pl["cuerpo"] = [c for c in pl["cuerpo"] if c]
    cifras = [{"n": f"{R.f1(q0)} m³/s", "l": f"{_quien(a0)}{prov0} a las {d0:%-H:%M} del {R.dia(d0.date().isoformat())}", "tono": "lluvia"},
              {"n": str(len(fuertes)), "l": "estaciones de aforo en crecida fuerte (criterio del observatorio)", "tono": "lluvia"},
              {"n": str(len(vivas) - len(fuertes)), "l": "con subida brusca del caudal (criterio del observatorio)", "tono": "lluvia"}]
    puntos = (70 if fuertes else 52) + min(15, 3 * len(fuertes)) + (8 if q0 >= 100 else 0) - min(10, int(a0["_edad"]) // 2)
    h = R.historia("rios", hid, "Ríos en crecida · aforos oficiales", "lluvia", puntos, hechos, pl, cifras,
                   fuentes="; ".join(fuentes),
                   metodo="Caudal medido en las estaciones de aforo (último dato publicado). Crecida fuerte: 20 m³/s o más y diez veces su caudal "
                          "de base (mediana de la semana sin las últimas 24 horas). Subida brusca: cuatro veces su base o tres veces el caudal de "
                          "24 horas antes. Solo estaciones con 5 m³/s o más y lecturas de menos de 12 horas.",
                   limites=["Dato en tiempo real, sujeto a validación del organismo de cuenca.",
                            "Hoy entran las redes de la Confederación Hidrográfica del Júcar, la Agència Catalana de l'Aigua y el Gobierno de Navarra: "
                            "el resto de cuencas no publica sus aforos en abierto en el mapa.",
                            "No es un aviso oficial: los avisos de crecida los dan los organismos de cuenca y Protección Civil."],
                   pagina=PAGINA)
    h["seccion"] = "ultima" if fuertes else SECCION
    h["fecha"] = dl
    g = _grafico(R, vivas, series, hid, "Caudal medido en las estaciones de aforo en crecida, últimos 3 días")
    if g:
        h["grafico"] = g
    h["ultima_hora"] = [{"hora": f"{_hora_local(a['_t'], a.get('prov')):%-H:%M}",
                         "texto": f"{_quien(a)[0].upper() + _quien(a)[1:]}" + (f" ({R.nprov(a['prov'])})" if a.get("prov") in R.PROV else "")
                                  + f" lleva {R.f1(_num(a['q']))} m³/s", "tono": "lluvia"} for a in [x for x in fuertes if not _dudosa(x)][:2]]

    # versiones provinciales
    por_prov = {}
    for a in vivas:
        if a.get("prov") in R.PROV:
            por_prov.setdefault(a["prov"], []).append(a)
    ctx = R.hecho("aforos_nac", f"En el conjunto de las redes de aforo que sigue el observatorio, {_cuenta(R, len(fuertes), len(vivas) - len(fuertes))}, "
                  "según el criterio del observatorio.",
                  "; ".join(fuentes), [str(len(fuertes)), str(len(vivas) - len(fuertes))])
    for cod, lista in por_prov.items():
        P = R.nprov(cod)
        hp = [_hecho(R, a, i, con_prov=False) for i, a in enumerate(lista[:5])]
        hp.append(R.hecho("aforos_metodo", hechos[-1]["dice"], hechos[-1]["fuente"]))
        hp.append(ctx)
        b = lista[0]
        qb, q24b = _num(b["q"]), _num(b.get("q24"))
        Q = _quien(b)
        Q = Q[0].upper() + Q[1:]
        if q24b is not None and q24b < 0.05:
            tp = f"{Q} lleva {R.f1(qb)} m³/s: 24 horas antes no llevaba agua"
        elif q24b is not None and q24b >= 1 and qb / q24b >= 3:
            tp = f"{Q} multiplica su caudal por {R.f1(qb / q24b)} y llega a {R.f1(qb)} m³/s"
        else:
            tp = f"{Q} sube a {R.f1(qb)} m³/s"
        nf = sum(1 for a in lista if a.get("estado") == "crecida")
        plp = {"titular": tp, "subtitulo": (" ".join(h["dice"] for h in hp[1:3]) if len(lista) > 1 else ctx["dice"]),
               "entradilla": hp[0]["dice"],
               "cuerpo": [c for c in [" ".join(h["dice"] for h in hp[3:len(lista[:5])]), hp[len(lista[:5])]["dice"], ctx["dice"]] if c],
               "claves": [h["dice"] for h in hp[:2]]}
        if len(lista) == 1:
            plp["subtitulo"] = ""
        db = _hora_local(b["_t"], cod)
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hp, "plantilla": plp,
             "cifras": [{"n": f"{R.f1(qb)} m³/s", "l": f"{_quien(b)} a las {db:%-H:%M} del {R.dia(db.date().isoformat())}", "tono": "lluvia"}],
             "puntos": (72 if nf else 50) + min(12, 4 * nf) + (8 if qb >= 100 else 0) - min(10, int(b["_edad"]) // 2)}
        gp = _grafico(R, lista, series, f"{hid}-{cod}", f"Caudal medido en las estaciones de aforo de {P}, últimos 3 días")
        if gp:
            v["grafico"] = gp
        h["provincias"][cod] = v
    return [h]
