"""Lluvia medida por AEMET, pluviómetro a pluviómetro.

Dos historias (cada una con versión para cada provincia que tenga datos):

1. «El otoño, pluviómetro a pluviómetro» (docs/otonio_municipios.json, método «pluviometro»): lo que lleva cada
   pluviómetro de AEMET desde el 1 de septiembre frente a su propia referencia para el mismo tramo de calendario
   (normal 1991-2020 si la estación tiene 20 otoños o más; si no, la media de sus otoños medidos). La cifra es de la
   estación («en»), nunca del municipio que la usa: un municipio puede tomar un pluviómetro de hasta 15 km.
2. «La lluvia de los últimos 7 días» (historico_estaciones.json: total diario de cada estación con la máscara de
   horas observadas): seis días cerrados completos más lo que va de hoy, hasta la última hora seguida con dato de esa
   estación. Si llueve fuerte, el titular es el acumulado del temporal; si no, el ranking de la semana.

No hay historia de «lluvia en una hora»: el repositorio solo guarda el total diario de cada estación (con su máscara
de 24 horas), no la lluvia hora a hora.
"""
from __future__ import annotations

import collections
import re
from datetime import date, timedelta

SECCION = "agua"
COMPLETO = (1 << 24) - 1
AZUL, AZUL_CLARO, ROJO_SECO = "#1F5FA8", "#8EB1DA", "#C4461A"


# ============================================================================ estaciones
class _Est:
    """Nombre y provincia de cada estación de AEMET por su indicativo."""

    def __init__(self, R):
        self.R = R
        self.inv = R.leer(R.PRENSA / "aemet_inventario.json", {}) or {}
        rec = R.leer(R.DOCS / "records" / "hoy.json", {}) or {}
        self.rn = {e["id"]: e.get("n") for e in rec.get("estaciones") or [] if e.get("id") and e.get("n")}
        self.on = {}

    def nombre(self, c):
        n = self.rn.get(c) or self.on.get(c)
        if not n and c in self.inv:
            n = self.inv[c][0].title()
        n = (n or c).replace("/ ", "/").strip()
        return re.sub(r",(?=\S)", ", ", n)

    def prov(self, c):
        if c not in self.inv:
            return None
        cod = self.R.H.cod_provincia(self.inv[c][1])
        return cod if cod in self.R.PROV else None


def _nprov(R, cod):
    return R.nprov(cod)


def _donde(R, est, c):
    p = est.prov(c)
    return f"{est.nombre(c)} ({_nprov(R, p)})" if p else est.nombre(c)


def _lugar_prov(lugar, prov_n):
    """«Pego (Alicante)»; sin repetir cuando la estación se llama como la provincia («Cádiz»)."""
    return lugar if not prov_n or prov_n.split("/")[0].lower() in lugar.lower() else f"{lugar} ({prov_n})"


UNIPROV = {"30": "la Región de Murcia", "28": "la Comunidad de Madrid", "33": "Asturias", "39": "Cantabria", "26": "La Rioja",
           "31": "Navarra", "07": "Baleares", "51": "Ceuta", "52": "Melilla"}


def _ambito(R, cod):
    """Cómo se nombra el territorio en la prensa regional: «la Región de Murcia», «la provincia de Alicante»."""
    return UNIPROV.get(cod) or f"la provincia de {R.nprov(cod)}"


def _litros(v):
    return "1 litro por metro cuadrado" if v == "1" else f"{v} litros por metro cuadrado"


def _ref_txt(x):
    p = x.get("periodo") or ""
    return "normal 1991-2020" if p == "1991-2020" else f"media de sus otoños {p}"


# ============================================================================ gráficos
def _barras_pct(R, filas, nombre, titulo, pie, etiqueta):
    """Barras horizontales del % de la referencia, con la línea del 100 %."""
    if not filas:
        return None
    ml = int(min(300, 24 + 7.2 * max(len(etiqueta(x)) for x in filas)))
    W, fila, mr, mt = 720 + max(0, ml - 200), 28, 150, 22
    Hh = mt + fila * len(filas) + 30
    mx = max(150.0, max(x["pct"] for x in filas) * 1.05)
    X = lambda v: ml + min(v, mx) / mx * (W - ml - mr)
    s = [R._t(X(100), 13, "100 % = lo habitual", 11.5, R.GRIS, "middle")]
    for i, x in enumerate(filas):
        y = mt + i * fila
        col = AZUL if x["pct"] >= 100 else ROJO_SECO
        s.append(R._t(ml - 10, y + 18, etiqueta(x), 13, R.TINTA, "end", 500))
        s.append(f'<rect x="{ml}" y="{y + 5}" width="{max(2, X(x["pct"]) - ml):.1f}" height="17" fill="{col}" opacity="0.88"></rect>')
        s.append(R._t(X(x["pct"]) + 6, y + 18, f"{x['pct']} % · {R.f1(x['mm'])} mm", 12.5, R.TINTA, "start", 600))
    s.append(f'<line x1="{X(100):.1f}" x2="{X(100):.1f}" y1="{mt - 2}" y2="{Hh - 24}" stroke="{R.TINTA}" stroke-width="1.2" stroke-dasharray="4 3"></line>')
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(x["en"], x.get("prov_n", ""), x["est"], x["mm"], x["normal"], x["pct"], x.get("periodo"), x.get("hasta"), x.get("h"))
                                           for x in filas],
                             ["estacion", "provincia", "indicativo", "mm_otono", "referencia_mm", "pct", "periodo_referencia", "hasta", "hora"],
                             titulo, [{"t": "banda", "c": AZUL, "l": "Por encima de lo habitual"}, {"t": "banda", "c": ROJO_SECO, "l": "Por debajo"}], pie)


def _barras_semana(R, filas, nombre, titulo, pie):
    """Barras de los 7 días: días anteriores + lo que va de hoy."""
    if not filas:
        return None
    ml = int(min(300, 24 + 7.2 * max(len(x["et"]) for x in filas)))
    W, fila, mr, mt = 680 + max(0, ml - 200), 28, 82, 6
    Hh = mt + fila * len(filas) + 10
    mx = max(x["total"] for x in filas) or 1
    X = lambda v: ml + v / mx * (W - ml - mr)
    s = []
    for i, x in enumerate(filas):
        y = mt + i * fila
        s.append(R._t(ml - 10, y + 18, x["et"], 13, R.TINTA, "end", 600 if i == 0 else 400))
        w_prev = max(0.0, X(x["previos"]) - ml)
        if w_prev > 0:
            s.append(f'<rect x="{ml}" y="{y + 5}" width="{w_prev:.1f}" height="17" fill="{AZUL_CLARO}"></rect>')
        w_hoy = max(0.0, X(x["total"]) - ml - w_prev)
        if w_hoy > 0:
            s.append(f'<rect x="{ml + w_prev:.1f}" y="{y + 5}" width="{w_hoy:.1f}" height="17" fill="{AZUL}"></rect>')
        s.append(R._t(X(x["total"]) + 6, y + 18, f"{R.f1(x['total'])} mm", 12.5, R.TINTA, "start", 700 if i == 0 else 500))
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(x["nombre"], x["prov_n"], x["c"], x["previos"], x["hoy"], x["total"], x["horas_hoy"]) for x in filas],
                             ["estacion", "provincia", "indicativo", "mm_6_dias_anteriores", "mm_hoy", "mm_7_dias", "horas_de_hoy"],
                             titulo, [{"t": "banda", "c": AZUL_CLARO, "l": "Días anteriores"}, {"t": "banda", "c": AZUL, "l": "Lo que va del día de hoy"}], pie)


# ============================================================================ 1 · el otoño, pluviómetro a pluviómetro
def _otono(R, est):
    O = R.leer(R.DOCS / "otonio_municipios.json", {}) or {}
    if O.get("metodo") != "pluviometro" or not O.get("municipios"):
        return [], {}
    por_est = {}
    for k, m in O["municipios"].items():
        c = m.get("est")
        if not c or c in por_est or m.get("pct") is None or m.get("mm") is None or not m.get("normal"):
            continue
        if m.get("huecos"):  # días de este otoño rellenados con lo normal: no es todo medida
            continue
        est.on[c] = m.get("en")
        x = dict(m)
        x["est"] = c
        x["en"] = est.nombre(c)
        x["prov"] = est.prov(c)
        x["prov_n"] = _nprov(R, x["prov"]) if x["prov"] else ""
        por_est[c] = x
    hoy = R.HOY.isoformat()
    vivos = [x for x in por_est.values() if x.get("hasta") and (R.HOY - date.fromisoformat(x["hasta"][:10])).days <= 1 and x["prov"]]
    return vivos, O


def _cuenta(xs):
    """Por encima (pct > 100), justo en el 100 % y por debajo (pct < 100)."""
    return (sum(1 for x in xs if x["pct"] > 100), sum(1 for x in xs if x["pct"] == 100), sum(1 for x in xs if x["pct"] < 100))


def _frase_cuenta(inicio, n, arriba, igual, abajo):
    """«De los 282 pluviómetros…, 89 llevan este otoño más lluvia de la habitual para estas fechas, 1, justo la habitual y 192, menos.»"""
    if arriba == n:
        return f"{inicio}, los {n} llevan este otoño más lluvia de la habitual para estas fechas."
    if abajo == n:
        return f"{inicio}, los {n} llevan este otoño menos lluvia de la habitual para estas fechas."
    trozos = ["ninguno lleva más lluvia de la habitual para estas fechas" if arriba == 0 else
              f"{arriba} {'lleva' if arriba == 1 else 'llevan'} este otoño más lluvia de la habitual para estas fechas"]
    if igual:
        trozos.append(f"{igual}, justo la habitual")
    if abajo:
        trozos.append(f"{abajo}, menos")
    return f"{inicio}, " + (", ".join(trozos[:-1]) + " y " + trozos[-1] if len(trozos) > 1 else trozos[0]) + "."


def _hasta(R, x):
    h = x.get("h")
    return (f"hasta las {int(h)}:00 del {R.dia(x['hasta'])}" if h is not None and x["hasta"] == R.HOY.isoformat()
            else f"hasta el {R.dia(x['hasta'])} incluido")


def _hecho_est(R, x, id_, con_prov=True):
    """«En Pego (Alicante), el pluviómetro de AEMET lleva 765,6 mm desde el 1 de septiembre, hasta las 9:00 del lunes 19
    de octubre: el 583 % de lo habitual para estas fechas (131,3 mm, media de sus otoños 2011-2025).»"""
    lugar = x["en"]
    donde = _lugar_prov(lugar, x["prov_n"]) if con_prov else lugar
    mm, nor = f"{R.f1(x['mm'])} mm", f"{R.f1(x['normal'])} mm"
    if x["mm"] == 0:
        dice = (f"El pluviómetro de AEMET de {donde} no ha recogido lluvia desde el 1 de septiembre, {_hasta(R, x)}: {mm} frente a {nor} de lo "
                f"habitual para estas fechas ({_ref_txt(x)}), el {x['pct']} %.")
    else:
        dice = (f"El pluviómetro de AEMET de {donde} lleva {mm} desde el 1 de septiembre, {_hasta(R, x)}: el {x['pct']} % de lo habitual "
                f"para estas fechas ({nor}, {_ref_txt(x)}).")
    return R.hecho(id_, dice, "AEMET OpenData (diarios validados y observación horaria)", [mm, f"{x['pct']} %", nor], lugar=lugar,
                   liga=[mm, f"{x['pct']} %", nor])


def _hecho_otono_entero(R, x, id_):
    """Si ya ha recogido más que un otoño normal completo."""
    if not x.get("normal_total") or x["mm"] <= x["normal_total"]:
        return None
    tot = f"{R.f1(x['normal_total'])} mm"
    return R.hecho(id_, f"{x['en']} ya ha recogido más lluvia que en un otoño completo habitual ({tot}, de septiembre a noviembre, {_ref_txt(x)}).",
                   "AEMET OpenData", [tot], lugar=x["en"], liga=[tot])


def _titular_est(R, x):
    quien = f"El pluviómetro de {x['en']}," if "," in x["en"] else x["en"]
    if x["mm"] == 0:
        return f"{quien} no ha recogido lluvia este otoño: el {x['pct']} % de lo habitual para estas fechas"
    if x["pct"] >= 100:
        return f"{quien} lleva {_litros(R.f1(x['mm']))} este otoño, el {x['pct']} % de lo habitual para estas fechas"
    return f"{quien} solo lleva {_litros(R.f1(x['mm']))} este otoño, el {x['pct']} % de lo habitual para estas fechas"


def g_otono(R, est, D):
    vivos, O = _otono(R, est)
    if len(vivos) < 30:
        return []
    fuente = "AEMET OpenData (valores climatológicos diarios y observación horaria)"
    metodo = ("Lluvia desde el 1 de septiembre en cada pluviómetro de AEMET: diarios validados más la observación horaria de los últimos días, "
              "de la misma estación. Solo entran los pluviómetros sin días de este otoño rellenados con su valor habitual. Referencia: normal 1991-2020 de esa estación para el mismo tramo de calendario si tiene 20 otoños o más; "
              "si no, la media de sus otoños medidos (al menos 15). El porcentaje compara con la referencia hasta la misma fecha y hora.")
    limites = ["Los últimos días son observación horaria de AEMET aún sin validar.",
               "La cifra es del pluviómetro, no del término municipal entero: en una tormenta, a pocos kilómetros puede llover muy distinto.",
               "Cuando la referencia no es la normal 1991-2020, es la media de los otoños que tiene medidos esa estación (se indica el periodo)."]
    pagina = "https://calentamientoglobal.es/lluvias-en-espana/"
    N = len(vivos)
    arriba, igual, abajo = _cuenta(vivos)
    utiles = [x for x in vivos if x["normal"] >= 20]
    tops = sorted([x for x in utiles if x["mm"] >= 30], key=lambda x: -x["pct"])[:3]
    ceros = sorted([x for x in vivos if x["mm"] == 0], key=lambda x: -x["normal"])
    bajos = ceros[:3] if len(ceros) >= 2 else sorted(utiles, key=lambda x: (x["pct"], x["mm"]))[:3]
    if not tops or not bajos:
        return []
    hechos = []
    for i, x in enumerate(tops):
        hechos.append(_hecho_est(R, x, f"oto_top{i}"))
        e = _hecho_otono_entero(R, x, f"oto_top{i}_entero")
        if e:
            hechos.append(e)
    hechos.append(R.hecho("oto_n", _frase_cuenta(f"De los {N} pluviómetros de AEMET con referencia propia que sigue el observatorio", N, arriba, igual, abajo),
                          fuente, [str(N), str(arriba), str(igual), str(abajo)]))
    t0 = tops[0]
    pmax = max(x["pct"] for x in vivos)
    if t0["pct"] == pmax and sum(1 for x in vivos if x["pct"] == pmax) == 1:
        hechos.append(R.hecho("oto_top_rank", f"{t0['en']} es, de esos {N} pluviómetros, el que lleva el porcentaje más alto respecto a su referencia.", fuente,
                              [str(N)], lugar=t0["en"], superlativo=True))
    for i, x in enumerate(bajos):
        hechos.append(_hecho_est(R, x, f"oto_bajo{i}"))
    b0 = bajos[0]
    if len(ceros) >= 2:
        nombres = [_lugar_prov(x["en"], x["prov_n"]) for x in ceros]
        if len(ceros) <= 4:
            dice = f"{R.lista_y(nombres)} son los {len(ceros)} pluviómetros, de esos {N}, que no han recogido lluvia desde el 1 de septiembre."
        else:
            dice = f"{len(ceros)} de esos {N} pluviómetros no han recogido lluvia desde el 1 de septiembre, entre ellos {R.lista_y(nombres[:3])}."
        hechos.append(R.hecho("oto_bajo_rank", dice, fuente, [str(len(ceros)), str(N)]))
    else:
        pmin = min(x["pct"] for x in vivos)
        empatados = [x for x in vivos if x["pct"] == pmin]
        if b0["pct"] == pmin and len(empatados) == 1:
            hechos.append(R.hecho("oto_bajo_rank", f"{b0['en']} es, de esos {N} pluviómetros, el que lleva el porcentaje más bajo respecto a su referencia.",
                                  fuente, [str(N)], lugar=b0["en"], superlativo=True))
        elif b0["pct"] == pmin and len(empatados) <= 4:
            hechos.append(R.hecho("oto_bajo_rank", f"{R.lista_y([_lugar_prov(x['en'], x['prov_n']) for x in empatados])} comparten el porcentaje más bajo de "
                                                   f"esos {N} pluviómetros respecto a su referencia: el {pmin} %.", fuente, [str(N), f"{pmin} %"],
                                  superlativo=True))
    ent = hechos[0]
    cuerpo = [" ".join(h["dice"] for h in hechos if h["id"].startswith("oto_top") and h is not ent),
              " ".join(h["dice"] for h in hechos if h["id"].startswith("oto_bajo")),
              next(h["dice"] for h in hechos if h["id"] == "oto_n")]
    if len(ceros) >= 2:
        sub = (f"En el otro extremo, {len(ceros)} pluviómetros no han recogido lluvia desde el 1 de septiembre, entre ellos "
               f"{_lugar_prov(b0['en'], b0['prov_n'])}. ")
    else:
        sub = (f"En el otro extremo, {_lugar_prov(b0['en'], b0['prov_n'])} "
               + (f"no ha recogido lluvia ({R.f1(b0['mm'])} mm, el {b0['pct']} % de lo habitual). " if b0["mm"] == 0 else
                  f"lleva {R.f1(b0['mm'])} mm, el {b0['pct']} % de lo habitual. "))
    sub += f"De los {N} pluviómetros de AEMET con referencia propia, {arriba} van por encima de lo habitual."
    pl = {"titular": _titular_est(R, t0), "subtitulo": sub, "entradilla": ent["dice"], "cuerpo": [c for c in cuerpo if c],
          "claves": [ent["dice"], hechos[[h["id"] for h in hechos].index("oto_bajo0")]["dice"], next(h["dice"] for h in hechos if h["id"] == "oto_n")]}
    # comprobar que el subtítulo solo usa lo de los hechos (el verificador lo mirará en conjunto)
    extremo = t0["pct"] >= 300 and t0["mm"] >= 150
    puntos = 62 if extremo else (50 if t0["pct"] >= 200 or b0["pct"] <= 25 else 42)
    h = R.historia("otono_pluviometros", f"{R.HOY.isoformat()}-otono-pluviometro-a-pluviometro", "Lluvia · el otoño, pluviómetro a pluviómetro",
                   "lluvia", puntos, hechos, pl,
                   [{"n": f"{t0['pct']} %", "l": f"de lo habitual en {t0['en']} ({R.f1(t0['mm'])} mm desde el 1 de septiembre)", "tono": "lluvia"},
                    ({"n": "0 mm", "l": f"en {len(ceros)} pluviómetros desde el 1 de septiembre", "tono": "calor"} if len(ceros) >= 2 else
                     {"n": f"{b0['pct']} %", "l": f"de lo habitual en {b0['en']} ({R.f1(b0['mm'])} mm)", "tono": "calor"}),
                    {"n": f"{arriba} de {N}", "l": "pluviómetros de AEMET por encima de lo habitual para estas fechas", "tono": "lluvia"}],
                   "AEMET OpenData (pluviómetros de AEMET)", metodo, limites, pagina)
    h["seccion"] = "agua"
    filas = tops[:3] + sorted([x for x in utiles if x["mm"] >= 30], key=lambda x: -x["pct"])[3:8] + sorted(bajos + sorted(utiles, key=lambda x: x["pct"])[3:8],
                                                                                                           key=lambda x: -x["pct"])
    vistos, filas_u = set(), []
    for x in sorted(filas, key=lambda x: -x["pct"]):
        if x["est"] not in vistos:
            vistos.add(x["est"])
            filas_u.append(x)
    pie = (f"Lluvia desde el 1 de septiembre en cada pluviómetro de AEMET frente a su referencia para las mismas fechas (normal 1991-2020 o media de sus "
           f"otoños medidos). Los {len(filas_u)} más alejados de lo habitual, por arriba y por abajo, de {N}. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.")
    try:
        h["grafico"] = _barras_pct(R, filas_u, f"{h['id']}", "El otoño, pluviómetro a pluviómetro: % de lo habitual", pie,
                                   lambda x: _lugar_prov(x["en"], x["prov_n"]))
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"lluvia/otoño gráfico: {e}")
    # versiones provinciales
    por_prov = collections.defaultdict(list)
    for x in vivos:
        por_prov[x["prov"]].append(x)
    caps = _capitales(R)
    for cod, xs in por_prov.items():
        v = _version_otono(R, cod, xs, caps.get(cod), hechos[next(i for i, hh in enumerate(hechos) if hh["id"] == "oto_n")], h["id"])
        if v:
            h["provincias"][cod] = v
    return [h]


def _capitales(R):
    out = {}
    for cod in R.PROV:
        p = R.leer(R.PRENSA / "partes" / f"{cod}.json", {}) or {}
        c = p.get("capital")
        if isinstance(c, dict):
            c = c.get("nombre")
        if c:
            out[cod] = c
    return out


def _version_otono(R, cod, xs, capital, hecho_nac, hid):
    P = R.nprov(cod)
    utiles = [x for x in xs if x["normal"] >= 15] or xs
    if not utiles:
        return None
    n = len(xs)
    arriba, igual, abajo = _cuenta(xs)
    ext = max(utiles, key=lambda x: abs(x["pct"] - 100) * (1 if x["mm"] >= 10 or x["pct"] < 100 else 0.3))
    hechos = [_hecho_est(R, ext, "oto_p_ext", con_prov=False)]
    e = _hecho_otono_entero(R, ext, "oto_p_ext_entero")
    if e:
        hechos.append(e)
    otros = sorted([x for x in utiles if x is not ext], key=lambda x: -x["pct"])
    if otros:
        contrario = otros[-1] if ext["pct"] >= 100 else otros[0]
        hechos.append(_hecho_est(R, contrario, "oto_p_otro", con_prov=False))
    cap = None
    if capital:
        cn = R.H._norm(capital)
        for x in xs:
            if x is ext or (otros and x is (otros[-1] if ext["pct"] >= 100 else otros[0])):
                continue
            if cn and cn.split()[0] in R.H._norm(x["en"]) and (x.get("km") is None or x["km"] <= 5):
                cap = x
                break
        if cap:
            hechos.append(_hecho_est(R, cap, "oto_p_cap", con_prov=False))
    if n == 1:
        hechos.append(R.hecho("oto_p_n", f"Es el único pluviómetro de AEMET con referencia propia que sigue el observatorio en {_ambito(R, cod)}.", "AEMET OpenData", ["1"]))
    else:
        dice = _frase_cuenta(f"En {_ambito(R, cod)}, de los {n} pluviómetros de AEMET con referencia propia que sigue el observatorio", n, arriba, igual, abajo)
        hechos.append(R.hecho("oto_p_n", dice, "AEMET OpenData", [str(arriba), str(igual), str(abajo), str(n)]))
    hechos.append(dict(hecho_nac, id="oto_p_nac"))
    pl = {"titular": _titular_est(R, ext), "subtitulo": hechos[-2]["dice"], "entradilla": hechos[0]["dice"],
          "cuerpo": [" ".join(h["dice"] for h in hechos[1:-2]) or hechos[-1]["dice"], hechos[-1]["dice"]],
          "claves": [h["dice"] for h in hechos[:3]]}
    pl["cuerpo"] = [c for c in pl["cuerpo"] if c]
    puntos = 38 + min(22, abs(ext["pct"] - 100) / 15)
    v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hechos, "plantilla": pl, "puntos": round(puntos, 1),
         "cifras": [{"n": f"{ext['pct']} %", "l": f"de lo habitual en {ext['en']} ({R.f1(ext['mm'])} mm desde el 1 de septiembre)",
                     "tono": "lluvia" if ext["pct"] >= 100 else "calor"}]
                   + ([{"n": f"{arriba} de {n}", "l": f"pluviómetros de AEMET de {P} por encima de lo habitual", "tono": "lluvia"}] if n > 1 else [])}
    try:
        filas = sorted(xs, key=lambda x: -x["pct"])[:15]
        v["grafico"] = _barras_pct(R, filas, f"{hid}-{cod}", f"El otoño en los pluviómetros de AEMET de {P}: % de lo habitual",
                                   f"Lluvia desde el 1 de septiembre en cada pluviómetro de AEMET de {P} frente a su referencia para las mismas fechas "
                                   f"(normal 1991-2020 o media de sus otoños medidos). Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.",
                                   lambda x: x["en"])
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"lluvia/otoño gráfico {cod}: {e}")
    return v


# ============================================================================ 2 · la lluvia de los últimos 7 días (con lo que va de hoy)
def _semana(R, est):
    hist = R.leer(R.DOCS.parent / "historico_estaciones.json", {}) or {}
    hoy = R.HOY
    dias = [(hoy - timedelta(days=i)).isoformat() for i in range(6, 0, -1)]
    if hoy.isoformat() not in hist or any(d not in hist for d in dias):
        return [], dias
    out = []
    H0 = hist[hoy.isoformat()]
    for c, (mm_hoy, mask) in H0.items():
        horas = bin(int(mask)).count("1")
        if horas < 1 or int(mask) != (1 << horas) - 1:   # solo horas seguidas desde la medianoche
            continue
        prev = []
        ok = True
        for d in dias:
            v = hist[d].get(c)
            if not v or int(v[1]) != COMPLETO or v[0] is None:
                ok = False
                break
            prev.append(float(v[0]))
        if not ok or mm_hoy is None:
            continue
        p = est.prov(c)
        if not p:
            continue
        total = round(sum(prev) + float(mm_hoy), 1)
        out.append({"c": c, "nombre": est.nombre(c), "prov": p, "prov_n": R.nprov(p), "previos": round(sum(prev), 1), "hoy": round(float(mm_hoy), 1),
                    "total": total, "horas_hoy": horas, "dias_lluvia": sum(1 for x in prev + [float(mm_hoy)] if x >= 1), "por_dia": prev + [float(mm_hoy)]})
    return out, dias


def _hecho_sem(R, x, id_, dias, con_prov=True, ref=None):
    mm = f"{R.f1(x['total'])} mm"
    lugar = x["nombre"]
    donde = _lugar_prov(lugar, x["prov_n"]) if con_prov else lugar
    dice = (f"La estación de AEMET de {donde} ha recogido {mm} entre el {R.dia(dias[0])} y las {x['horas_hoy']}:00 del {R.dia(R.HOY.isoformat())}"
            f", con lluvia de 1 mm o más en {x['dias_lluvia']} de esos 7 días.")
    hh = [R.hecho(id_, dice, "AEMET OpenData (observación horaria)", [mm, f"{x['horas_hoy']}:00", str(x["dias_lluvia"]), "7"], lugar=lugar, liga=[mm])]
    if x["hoy"] >= 1:
        mh = f"{R.f1(x['hoy'])} mm"
        hh.append(R.hecho(id_ + "_hoy", f"De ellos, {mh} han caído el {R.dia(R.HOY.isoformat())}, hasta las {x['horas_hoy']}:00, en {lugar}.",
                          "AEMET OpenData (observación horaria)", [mh, f"{x['horas_hoy']}:00"], lugar=lugar, liga=[mh]))
    if ref and ref.get("normal_total") and x["total"] >= 0.5 * ref["normal_total"]:
        tot = f"{R.f1(ref['normal_total'])} mm"
        if x["total"] > ref["normal_total"]:
            dice = (f"En 7 días, {lugar} ha recogido más de lo que suele llover allí en todo un otoño: {tot} de septiembre a noviembre "
                    f"({_ref_txt(ref)}).")
        else:
            pct = round(100 * x["total"] / ref["normal_total"])
            dice = (f"Lo recogido en 7 días en {lugar} equivale al {pct} % de lo que suele llover allí en todo un otoño: {tot} de septiembre a noviembre "
                    f"({_ref_txt(ref)}).")
        hh.append(R.hecho(id_ + "_ref", dice, "AEMET OpenData", [tot], lugar=lugar, liga=[tot]))
    return hh


def g_semana(R, est, D, refs):
    filas, dias = _semana(R, est)
    if len(filas) < 50:
        return []
    filas.sort(key=lambda x: -x["total"])
    top = filas[0]
    if top["total"] < 10:
        return []
    fuente = "AEMET OpenData (observación horaria de las estaciones)"
    N = len(filas)
    n100 = sum(1 for x in filas if x["total"] >= 100)
    n1 = sum(1 for x in filas if x["total"] >= 1)
    temporal = top["hoy"] >= 30 or top["por_dia"][-2] >= 30
    corte = max(x["horas_hoy"] for x in filas)  # la hora a la que llegan casi todas
    unico = len(filas) < 2 or filas[1]["total"] < top["total"]
    hechos = []
    for i, x in enumerate(filas[:3]):
        hh = _hecho_sem(R, x, f"sem{i}", dias, ref=refs.get(x["c"]) if i == 0 else None)
        if i == 0 and unico:
            mm = f"{R.f1(top['total'])} mm"
            corta = f", aunque su último dato del {R.dia(R.HOY.isoformat())} es de las {top['horas_hoy']}:00" if top["horas_hoy"] < corte else ""
            hh.insert(1, R.hecho("sem_rank", f"Los {mm} de {top['nombre']} son la cifra más alta de las {N} estaciones de AEMET que sigue el observatorio "
                                             f"sin horas perdidas en esos días{corta}.", fuente, [str(N), mm], lugar=top["nombre"], liga=[mm], superlativo=True))
        hechos.extend(hh)
    hechos.append(R.hecho("sem_n", f"De esas {N} estaciones, {n1} han recogido 1 mm o más en esos 7 días"
                                   + (f" y {n100}, 100 mm o más." if n100 else "."), fuente, [str(N), str(n1)] + ([str(n100)] if n100 else [])))
    ref0 = next((h for h in hechos if h["id"] == "sem0_ref"), None)
    mm0 = R.f1(top["total"])
    quien = f"La estación de {top['nombre']}," if "," in top["nombre"] else top["nombre"]
    if temporal and ref0 and top["total"] > (refs.get(top["c"]) or {}).get("normal_total", 1e9):
        tit = f"{quien} suma {_litros(mm0)} en 7 días, más de lo que suele llover allí en todo un otoño"
    elif temporal:
        tit = f"{quien} suma {_litros(mm0)} en 7 días"
    elif unico:
        tit = f"{_lugar_prov(top['nombre'], top['prov_n'])}, donde más ha llovido en los últimos 7 días: {_litros(mm0)}"
    else:
        tit = f"{quien} suma {_litros(mm0)} en 7 días"
    if len(tit) > 165:
        tit = f"{quien} suma {_litros(mm0)} en 7 días"
    ent = hechos[0]
    cuerpo = [" ".join(h["dice"] for h in hechos[1:] if h["id"].startswith("sem0") or h["id"] == "sem_rank"),
              " ".join(h["dice"] for h in hechos if h["id"].startswith(("sem1", "sem2"))),
              next(h["dice"] for h in hechos if h["id"] == "sem_n")]
    sub = " ".join(h["dice"] for h in hechos if h["id"] in ("sem_rank", "sem0_hoy")) if unico else ""
    pl = {"titular": tit, "subtitulo": sub or " ".join(h["dice"] for h in hechos if h["id"] in ("sem1",)), "entradilla": ent["dice"],
          "cuerpo": [c for c in cuerpo if c], "claves": [ent["dice"], next(h["dice"] for h in hechos if h["id"] == "sem_n")]}
    puntos = 82 if top["total"] >= 300 else 74 if top["total"] >= 150 else 62 if top["total"] >= 60 else 48 if top["total"] >= 25 else 36
    kicker = "Lluvia · el temporal, acumulado" if temporal else "Lluvia · los últimos 7 días"
    metodo = ("Suma de la precipitación horaria de cada estación de AEMET: los 6 días anteriores completos (24 horas con dato) más lo que va del día de "
              "hoy, hasta la última hora seguida con dato de esa estación. Solo entran las estaciones sin horas perdidas en esos días.")
    limites = ["La observación horaria de AEMET aún no está validada: puede cambiar algo cuando AEMET publique los datos diarios.",
               "El observatorio sigue las estaciones de AEMET de referencia de los municipios de su mapa de lluvia, no toda la red.",
               "Una estación que deja de enviar datos durante el temporal sale con lo que llevaba hasta su última hora con dato."]
    h = R.historia("lluvia_semana", f"{R.HOY.isoformat()}-lluvia-7-dias", kicker, "lluvia", puntos, hechos, pl,
                   [{"n": f"{mm0} mm", "l": f"en {top['nombre']} en 7 días, hasta las {top['horas_hoy']}:00 del {R.dia(R.HOY.isoformat())}", "tono": "lluvia"}]
                   + ([{"n": str(n100), "l": "estaciones de AEMET con 100 mm o más en 7 días", "tono": "lluvia"}] if n100 else [])
                   + [{"n": f"{n1} de {N}", "l": "estaciones con 1 mm o más en 7 días", "tono": "lluvia"}],
                   fuente, metodo, limites, "https://calentamientoglobal.es/lluvias-en-espana/")
    h["seccion"] = "ultima" if temporal and top["total"] >= 100 else "agua"
    pie = (f"Lluvia de los últimos 7 días en las estaciones de AEMET, del {R.dia(dias[0], semana=False)} a lo que va del {R.dia(R.HOY.isoformat(), semana=False)}. "
           f"Fuente: AEMET OpenData (observación horaria). Cálculo: calentamientoglobal.es.")
    try:
        h["grafico"] = _barras_semana(R, [dict(x, et=_lugar_prov(x["nombre"], x["prov_n"])) for x in filas[:10]], h["id"],
                                      "La lluvia de los últimos 7 días, estación a estación", pie)
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"lluvia/semana gráfico: {e}")
    nac = next(hh for hh in hechos if hh["id"] == "sem_n")
    por_prov = collections.defaultdict(list)
    for x in filas:
        por_prov[x["prov"]].append(x)
    for cod, xs in por_prov.items():
        v = _version_semana(R, cod, xs, dias, refs, nac, top if unico else None, h["id"], corte)
        if v:
            h["provincias"][cod] = v
    return [h]


def _version_semana(R, cod, xs, dias, refs, nac, top_nac, hid, corte=24):
    xs = sorted(xs, key=lambda x: -x["total"])
    x0 = xs[0]
    if x0["total"] < 2:
        return None
    P = R.nprov(cod)
    n = len(xs)
    hechos = _hecho_sem(R, x0, "semp0", dias, con_prov=False, ref=refs.get(x0["c"]))
    unico = n > 1 and xs[1]["total"] < x0["total"]
    if unico:
        mm = f"{R.f1(x0['total'])} mm"
        corta = f", aunque su último dato del {R.dia(R.HOY.isoformat())} es de las {x0['horas_hoy']}:00" if x0["horas_hoy"] < corte else ""
        hechos.insert(1, R.hecho("semp_rank", f"Los {mm} de {x0['nombre']} son la cifra más alta de las {n} estaciones de AEMET de {_ambito(R, cod)} que sigue "
                                              f"el observatorio sin horas perdidas en esos días{corta}.", "AEMET OpenData", [str(n), mm], lugar=x0["nombre"], liga=[mm],
                                 superlativo=True))
    otros = [x for x in xs[1:4] if x["total"] >= 1]
    if otros:
        ls = [f"{x['nombre']} ({R.f1(x['total'])} mm)" for x in otros]
        hechos.append(R.hecho("semp_otros", f"{'Le sigue' if len(ls) == 1 else 'Le siguen'} {R.lista_y(ls)}.", "AEMET OpenData",
                              [R.f1(x["total"]) for x in otros] + [f"{R.f1(x['total'])} mm" for x in otros]))
    n1 = sum(1 for x in xs if x["total"] >= 1)
    if n > 1:
        if n1 == n:
            dice = f"En {_ambito(R, cod)}, las {n} estaciones han recogido 1 mm o más en los últimos 7 días."
        elif n1 == 0:
            dice = f"En {_ambito(R, cod)}, ninguna de las {n} estaciones ha recogido 1 mm en los últimos 7 días."
        else:
            dice = f"En {_ambito(R, cod)}, {n1} de esas {n} estaciones han recogido 1 mm o más en los últimos 7 días."
        hechos.append(R.hecho("semp_n", dice, "AEMET OpenData", [str(n1), str(n)]))
    if top_nac and top_nac["prov"] != cod:
        hechos.append(R.hecho("semp_nac", f"En toda España, la cifra más alta de los últimos 7 días es la de {top_nac['nombre']} ({top_nac['prov_n']}), con "
                                          f"{R.f1(top_nac['total'])} mm.", "AEMET OpenData",
                              [f"{R.f1(top_nac['total'])} mm"], lugar=top_nac["nombre"], liga=[f"{R.f1(top_nac['total'])} mm"], superlativo=True))
    mm0 = R.f1(x0["total"])
    tit = (f"{x0['nombre']}, donde más ha llovido en {_ambito(R, cod)} en los últimos 7 días: {_litros(mm0)}" if unico and "," not in x0["nombre"]
           else f"La estación de AEMET de {x0['nombre']}{',' if ',' in x0['nombre'] else ''} suma {_litros(mm0)} en los últimos 7 días")
    if len(tit) > 165:
        tit = f"{x0['nombre']} suma {_litros(mm0)} en los últimos 7 días"
    resto = [h["dice"] for h in hechos[1:]]
    pl = {"titular": tit, "subtitulo": next((h["dice"] for h in hechos if h["id"] == "semp_otros"), ""), "entradilla": hechos[0]["dice"],
          "cuerpo": [" ".join(d for h, d in zip(hechos[1:], resto) if h["id"] != "semp_otros") or hechos[0]["dice"]]
                    + [h["dice"] for h in hechos if h["id"] == "semp_otros"],
          "claves": [h["dice"] for h in hechos[:3]]}
    t = x0["total"]
    puntos = 74 if t >= 150 else 64 if t >= 60 else 54 if t >= 25 else 44 if t >= 8 else 32
    v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hechos, "plantilla": pl, "puntos": puntos,
         "cifras": [{"n": f"{mm0} mm", "l": f"en {x0['nombre']} en 7 días, hasta las {x0['horas_hoy']}:00 del {R.dia(R.HOY.isoformat())}", "tono": "lluvia"}]
                   + ([{"n": f"{n1} de {n}", "l": f"estaciones de AEMET de {P} con 1 mm o más", "tono": "lluvia"}] if n > 1 else [])}
    if n >= 2:
        try:
            v["grafico"] = _barras_semana(R, [dict(x, et=x["nombre"]) for x in xs[:12] if x["total"] > 0], f"{hid}-{cod}",
                                          f"La lluvia de los últimos 7 días en las estaciones de AEMET de {P}",
                                          f"Lluvia de los últimos 7 días en las estaciones de AEMET de {P}, del {R.dia(dias[0], semana=False)} a lo que va del "
                                          f"{R.dia(R.HOY.isoformat(), semana=False)}. Fuente: AEMET OpenData (observación horaria). Cálculo: calentamientoglobal.es.")
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"lluvia/semana gráfico {cod}: {e}")
    return v


# ============================================================================ entrada
def generar(R, D):
    est = _Est(R)
    out = []
    try:
        out.extend(g_otono(R, est, D))
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"lluvia/otoño: {type(e).__name__}: {e}")
    refs = {}
    O = R.leer(R.DOCS / "otonio_municipios.json", {}) or {}
    for m in (O.get("municipios") or {}).values():
        if m.get("est") and m.get("normal_total") and m["est"] not in refs:
            refs[m["est"]] = m
    out.extend(g_semana(R, est, D, refs))
    for h in out:
        h.setdefault("fecha", R.HOY.isoformat())
    return out
