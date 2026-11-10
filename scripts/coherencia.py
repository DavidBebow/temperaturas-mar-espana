#!/usr/bin/env python3
"""
Verificador de coherencia del observatorio (calentamientoglobal.es).

Corre como un paso más del vigilante horario (scripts/salud_datos.py), sin workflow
nuevo, y también lo importa scripts/hallazgos_prensa.py para sacar de «enviables»
los hallazgos con fallo. No llama a ninguna API de pago, no recalcula nada: solo
compara lo que ya está publicado en docs/.

Comprueba, en cada pasada:
  1. clave          la misma clave (indicador + territorio + periodo + corte) tiene el
                    mismo valor en todos los JSON donde aparece (hallazgos, antes_raro,
                    huella por capital, índice de huella).
  2. titular        el número del titular y del «dato» de un hallazgo es el de su
                    campo estructurado (PR, «una vez cada N años», valor).
  3. hoy            ningún bloque que diga «hoy» tiene fecha_dato anterior a ayer.
  4. niveles        una lista titulada por nivel («Avisos rojos») solo contiene
                    elementos de ese nivel (se mira en la página publicada, si se
                    alcanza; la función lista_por_nivel() es la regla).

Escribe docs/estado/coherencia.json:
  {generado, comprobaciones:[{id, descripcion, evaluadas, fallos}], fallos:[{...}],
   bloqueados:[{id, motivo}]}

Nunca lanza una excepción hacia fuera: cada comprobación va aislada y el conjunto
está limitado a 50 s. Cabe con holgura en el minuto.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
SALIDA = DOCS / "estado" / "coherencia.json"
MADRID = ZoneInfo("Europe/Madrid")
LIMITE_S = 50.0
PAGINA_HUB = "https://calentamientoglobal.es/el-tiempo/"

# Colores de nivel de aviso que pinta cg-lluvia-municipal (COLOR_AV) y su nombre.
COLOR_NIVEL = {"#d7261e": "rojo", "#f08a24": "naranja", "#f5c518": "amarillo"}


# ----------------------------------------------------------------------------- utilidades
def slug(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def leer(p: Path):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def num_es(txt: str):
    """'1.234,5' → 1234.5 · '47' → 47.0 · '3,3' → 3.3. None si no es número."""
    t = txt.strip()
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", t):
        return None
    return float(t.replace(".", "").replace(",", "."))


def hoy_madrid(ahora: datetime | None = None) -> date:
    return (ahora or datetime.now(MADRID)).astimezone(MADRID).date()


# ----------------------------------------------------------------------------- 1 · clave
def _periodo(ambito_tiempo, fecha):
    f = str(fecha or "")
    if (ambito_tiempo or "") == "mes":
        return "mes:" + f[:7]
    if (ambito_tiempo or "") in ("temporada", "anio", "año"):
        return f"{ambito_tiempo}:{f[:4]}"
    return "dia:" + f


def registros(docs: Path = DOCS):
    """Genera (clave, campo, valor, ruta) de cada JSON publicado donde un dato se repite."""
    out = []

    def add(ind, terr, per, corte, campo, valor, ruta):
        if valor is None or isinstance(valor, bool):
            return
        out.append(((ind, slug(terr), per, str(corte)), campo, valor, ruta))

    # hallazgos.json (nacional + provinciales + en revisión + locales)
    h = leer(docs / "prensa" / "hallazgos.json") or {}
    for lista in ("enviables", "en_revision", "contexto", "locales"):
        for i, x in enumerate(h.get(lista) or []):
            if x.get("serie") != "huella":
                continue
            terr = x.get("provincia_slug") or x.get("territorio")
            if x.get("ambito") == "nacional":
                continue
            per = _periodo(x.get("ambito_tiempo"), x.get("fecha_dato"))
            ruta = f"prensa/hallazgos.json#{lista}[{i}]({x.get('id')})"
            ind = x.get("indicador")
            add(ind, terr, per, x.get("fecha_dato"), "valor", x.get("valor"), ruta)
            r = x.get("rareza") or {}
            for c in ("PR", "T_antes", "T_ahora"):
                add(ind, terr, per, x.get("fecha_dato"), c, r.get(c), ruta)

    # huella/antes_raro.json (candidatos del último cálculo)
    a = leer(docs / "huella" / "antes_raro.json") or {}
    for i, x in enumerate(a.get("candidatos") or []):
        per = _periodo(x.get("ambito_tiempo"), x.get("fecha"))
        ruta = f"huella/antes_raro.json#candidatos[{i}]({x.get('slug')})"
        ind = x.get("indicador")
        add(ind, x.get("provincia") or x.get("slug"), per, x.get("fecha"), "valor", x.get("valor"), ruta)
        r = x.get("rareza") or {}
        for c in ("PR", "T_antes", "T_ahora"):
            add(ind, x.get("provincia") or x.get("slug"), per, x.get("fecha"), c, r.get(c), ruta)

    # índice del día: huella/index.json frente a huella/<slug>.json
    idx = leer(docs / "huella" / "index.json") or {}
    for i, c in enumerate(idx.get("capitales") or []):
        s = c.get("slug")
        corte = c.get("fecha_dato")
        add("huella_indice", s, "dia:" + str(corte), corte, "indice", c.get("indice"), f"huella/index.json#capitales[{i}]")
        f = leer(docs / "huella" / f"{s}.json") or {}
        hoy = f.get("hoy") or {}
        if f.get("fecha_dato") == corte:
            add("huella_indice", s, "dia:" + str(corte), corte, "indice", hoy.get("indice"), f"huella/{s}.json#hoy")
    return out


def c_clave(docs: Path = DOCS):
    grupos = {}
    for clave, campo, valor, ruta in registros(docs):
        grupos.setdefault((clave, campo), []).append((valor, ruta))
    fallos, evaluadas = [], 0
    for (clave, campo), vs in grupos.items():
        if len(vs) < 2:
            continue
        evaluadas += 1
        base = vs[0][0]
        tol = 0.051 if campo in ("valor", "T_ahora") else 0.51
        if any(abs(float(v) - float(base)) > tol for v, _ in vs[1:]):
            fallos.append({
                "comprobacion": "clave", "clave": "|".join(clave) + "|" + campo,
                "valores": [{"ruta": r, "valor": v} for v, r in vs],
                "detalle": "la misma clave tiene valores distintos"})
    return evaluadas, fallos


# ----------------------------------------------------------------------------- 2 · titular
_RE_VECES = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s+veces\s+m[aá]s\s+probable")
_RE_CADA = re.compile(r"una\s+vez\s+cada\s+(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s+a[nñ]os")


def fallos_hallazgo(x: dict) -> list[dict]:
    """Coherencia interna de un hallazgo: titular y dato frente a rareza.*"""
    out = []
    r = x.get("rareza") or {}
    for campo in ("titular", "dato"):
        t = x.get(campo) or ""
        m = _RE_VECES.search(t)
        if m and r.get("PR") is not None:
            v = num_es(m.group(1))
            if v is not None and abs(v - float(r["PR"])) > 0.51:
                out.append({"comprobacion": "titular", "clave": f"{x.get('id')}|{campo}|PR",
                            "valores": [{"ruta": f"hallazgo {x.get('id')} · {campo}", "valor": v},
                                        {"ruta": "rareza.PR", "valor": r["PR"]}],
                            "detalle": "el texto no da el mismo PR que el campo estructurado"})
        m = _RE_CADA.search(t)
        if m and r.get("T_antes") is not None and "ocurr" in t:
            v = num_es(m.group(1))
            if v is not None and abs(v - float(r["T_antes"])) > 0.51:
                out.append({"comprobacion": "titular", "clave": f"{x.get('id')}|{campo}|T_antes",
                            "valores": [{"ruta": f"hallazgo {x.get('id')} · {campo}", "valor": v},
                                        {"ruta": "rareza.T_antes", "valor": r["T_antes"]}],
                            "detalle": "el texto no da el mismo T_antes que el campo estructurado"})
    return out


def c_titular(docs: Path = DOCS):
    h = leer(docs / "prensa" / "hallazgos.json") or {}
    fallos, n = [], 0
    for lista in ("enviables", "en_revision", "contexto", "locales"):
        for x in h.get(lista) or []:
            if x.get("rareza"):
                n += 1
                for f in fallos_hallazgo(x):
                    f["valores"][0]["ruta"] = f"prensa/hallazgos.json#{lista}({x.get('id')})"
                    fallos.append(f)
    return n, fallos


# ----------------------------------------------------------------------------- 3 · «hoy»
# «es hoy al menos X veces más probable» = «en el clima actual»: no es una etiqueta de fecha
_RE_HOY = re.compile(r"(?<!\bes )\bhoy\b(?! al menos)", re.I)


def fallo_hoy(texto: str, fecha_dato: str, ahora: datetime | None = None) -> bool:
    """True si el texto dice «hoy» y la fecha del dato es anterior a ayer."""
    if not texto or not fecha_dato or not _RE_HOY.search(texto):
        return False
    try:
        f = date.fromisoformat(str(fecha_dato)[:10])
    except ValueError:
        return False
    return f < hoy_madrid(ahora) - timedelta(days=1)


def c_hoy(docs: Path = DOCS, ahora: datetime | None = None):
    fallos, n = [], 0
    h = leer(docs / "prensa" / "hallazgos.json") or {}
    for lista in ("enviables", "en_revision", "contexto", "locales"):
        for x in h.get(lista) or []:
            n += 1
            for campo in ("titular", "dato"):
                if fallo_hoy(x.get(campo), x.get("fecha_dato"), ahora):
                    fallos.append({"comprobacion": "hoy", "clave": f"{x.get('id')}|{campo}",
                                   "valores": [{"ruta": f"prensa/hallazgos.json#{lista}({x.get('id')})",
                                                "valor": f"fecha_dato {x.get('fecha_dato')}"}],
                                   "detalle": "dice «hoy» con un dato anterior a ayer"})
    return n, fallos


# ----------------------------------------------------------------------------- 4 · niveles
def lista_por_nivel(titulo_nivel: str, elementos: list[tuple[str, str]]) -> list[str]:
    """Regla 2.5: devuelve los nombres cuyo nivel no es el de la lista.
    elementos = [(nombre, nivel)] con niveles 'rojo'/'naranja'/'amarillo'."""
    return [n for n, nivel in elementos if nivel != titulo_nivel]


_RE_LISTA = re.compile(r'<b class="cgh-dest-t"><i style="background:([^"]+)"></i>([^<]+)</b><ul>(.*?)</ul>', re.S)
_RE_ITEM = re.compile(r'<a href="[^"]*">([^<]+)</a>.*?<b class="cgh-avn" style="background:(#[0-9a-fA-F]{6})', re.S)


def listas_de_html(html: str):
    """[(titulo, nivel_del_titulo, [(nombre, nivel)])] de los bloques 'Avisos <nivel>s de AEMET'."""
    res = []
    for color, titulo, cuerpo in _RE_LISTA.findall(html):
        m = re.match(r"Avisos (rojos|naranjas|amarillos)", titulo.strip())
        if not m:
            continue
        nivel = {"rojos": "rojo", "naranjas": "naranja", "amarillos": "amarillo"}[m.group(1)]
        items = [(n.strip(), COLOR_NIVEL.get(c.lower(), c.lower())) for n, c in _RE_ITEM.findall(cuerpo)]
        res.append((titulo.strip(), nivel, items))
    return res


def c_niveles(html: str | None = None):
    if html is None:
        try:
            req = urllib.request.Request(PAGINA_HUB, headers={"User-Agent": "cg-coherencia/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception:
            return 0, []  # sin red: no se evalúa, no es un fallo
    fallos, n = [], 0
    for titulo, nivel, items in listas_de_html(html):
        n += 1
        malos = lista_por_nivel(nivel, items)
        if malos:
            fallos.append({"comprobacion": "niveles", "clave": titulo,
                           "valores": [{"ruta": PAGINA_HUB, "valor": f"{nom}: {niv}"} for nom, niv in items if nom in malos],
                           "detalle": f"«{titulo}» contiene elementos de otro nivel"})
    return n, fallos


# ----------------------------------------------------------------------------- orquestación
COMPROBACIONES = [
    ("clave", "Misma clave (indicador+territorio+periodo+corte), mismo valor en todos los JSON", c_clave),
    ("titular", "El número del titular y del dato es el del campo estructurado", c_titular),
    ("hoy", "Ningún bloque «hoy» con fecha_dato anterior a ayer", c_hoy),
    ("niveles", "Las listas por nivel solo contienen elementos de su nivel", c_niveles),
]


def ejecutar(docs: Path = DOCS, salida: Path | None = SALIDA, **kw) -> dict:
    t0 = time.time()
    comprobaciones, fallos = [], []
    for cid, desc, fn in COMPROBACIONES:
        if time.time() - t0 > LIMITE_S:
            comprobaciones.append({"id": cid, "descripcion": desc, "evaluadas": 0, "fallos": 0, "nota": "omitida por tiempo"})
            continue
        try:
            if cid == "niveles":
                n, fs = fn(kw.get("html_hub"))
            elif cid == "hoy":
                n, fs = fn(docs, kw.get("ahora"))
            else:
                n, fs = fn(docs)
        except Exception as e:  # una comprobación rota no tumba el paso
            n, fs = 0, []
            comprobaciones.append({"id": cid, "descripcion": desc, "evaluadas": 0, "fallos": 0, "nota": f"no se pudo: {str(e)[:120]}"})
            continue
        comprobaciones.append({"id": cid, "descripcion": desc, "evaluadas": n, "fallos": len(fs)})
        fallos.extend(fs)

    # hallazgos con fallo: no salen como enviables hasta que se resuelva
    ids = {}
    for f in fallos:
        if f["comprobacion"] in ("titular", "hoy"):
            ids.setdefault(f["clave"].split("|")[0], f["detalle"])
        elif f["comprobacion"] == "clave":
            for v in f["valores"]:
                mm = re.search(r"\(([^()]+)\)$", v["ruta"])
                if mm and v["ruta"].startswith("prensa/hallazgos.json"):
                    ids.setdefault(mm.group(1), f["detalle"] + " · " + f["clave"])
    estado = {
        "generado": datetime.now(MADRID).astimezone().isoformat(timespec="seconds"),
        "duracion_s": round(time.time() - t0, 2),
        "comprobaciones": comprobaciones,
        "n_fallos": len(fallos),
        "fallos": fallos[:200],
        "bloqueados": [{"id": k, "motivo": v} for k, v in sorted(ids.items())],
    }
    if salida is not None:
        salida.parent.mkdir(parents=True, exist_ok=True)
        with open(salida, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=1)
    return estado


def marcar_hallazgos(hallazgos: list[dict]) -> list[dict]:
    """Para hallazgos_prensa.py: marca requiere_revision + motivo en los que fallan la regla 2
    (titular frente a rareza) o tienen un «hoy» viejo. Devuelve los marcados."""
    marcados = []
    for x in hallazgos:
        motivos = [f["detalle"] for f in fallos_hallazgo(x)]
        for campo in ("titular", "dato"):
            if fallo_hoy(x.get(campo), x.get("fecha_dato")):
                motivos.append("dice «hoy» con un dato anterior a ayer")
                break
        if motivos:
            x["requiere_revision"] = True
            x["motivo_revision"] = "coherencia: " + "; ".join(dict.fromkeys(motivos))
            x.setdefault("limites", []).append("COMPROBAR: " + x["motivo_revision"])
            marcados.append(x)
    return marcados


if __name__ == "__main__":
    est = ejecutar()
    print(json.dumps({k: est[k] for k in ("generado", "duracion_s", "comprobaciones", "n_fallos", "bloqueados")}, ensure_ascii=False, indent=1))
    sys.exit(0)
