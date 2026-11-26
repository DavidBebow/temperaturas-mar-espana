"""Noticia completa de las piezas de la mesa (scripts/portada_fondo.py). Series sintéticas: no depende del archivo real."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import mesa_redaccion as M      # noqa: E402
import portada_fondo as F       # noqa: E402

INI, HASTA = date(2026, 1, 1), date(2026, 11, 17)


def _serie(base, extra_2026, desde=1960):
    """Máxima constante por año: base + 0,01·(año − desde); 2026 lleva además `extra_2026`."""
    s = {}
    for y in range(desde, 2027):
        v = base + 0.01 * (y - desde) + (extra_2026 if y == 2026 else 0)
        d = date(y, 1, 1)
        while d <= date(y, 12, 31) and (y < 2026 or d <= HASTA):
            s[d] = (v, v - 10, 0.0)
            d += timedelta(days=1)
    return s


def _monta(monkeypatch, tmp_path, extras):
    est = {f"{i + 1:02d}": (f"X{i}", c, f"{c}, Estación") for i, c in enumerate(extras)}
    monkeypatch.setattr(M, "estaciones_capital", lambda raiz=None, solo_capital=True: est)
    monkeypatch.setattr(M, "_SERIES", {f"X{i}": _serie(20 + i, e) for i, e in enumerate(extras.values())})
    monkeypatch.setattr(F, "_provincias", lambda: {c: (v[1], v[1].lower()) for c, v in est.items()})
    tabla = []
    for cod, (ind, ciudad, estn) in est.items():
        fc = F.ficha(ind, INI, HASTA, "calor", tmp_path)
        tabla.append({"ciudad": ciudad, "estacion": estn, "puesto": fc["puesto"], "valor": round(fc["valor"], 2), "anterior": (fc["anterior"][1], fc["anterior"][0]),
                      "n": fc["n"], "desde": fc["desde"]})
    return {"tipo_mesa": "marco_nacional", "periodo": "anio", "cola": "calor", "clave": {"periodo": str(INI)}, "fecha_dato": str(HASTA),
            "fecha_disponible": str(HASTA + timedelta(days=9)), "titular": "Lo que va de 2026 es el más cálido registrado en 3 capitales",
            "marco": {"n_primeros": 3, "total": 3}, "tabla": tabla, "invalidar": "AEMET valida con retraso; cambios de emplazamiento",
            "puntuacion": {"puntos": 78.2}}


def test_marco_nacional_completo(monkeypatch, tmp_path):
    c = _monta(monkeypatch, tmp_path, {"Alfa": 0.50, "Beta": 0.20, "Gamma": 1.00})
    h = F.noticia_de_mesa(c, date(2026, 11, 26), tmp_path)
    assert h and h["id"] == "2026-11-17-mesa-anio-calor-es"
    f = tmp_path / "docs" / "prensa" / "noticias" / "historias" / f"{h['id']}.json"
    assert json.loads(f.read_text(encoding="utf-8"))["texto"]["cuerpo"]
    assert set(h["provincias"]) == {"01", "02", "03"}
    dice = " ".join(x["dice"] for x in h["hechos"])
    assert "El mayor margen sobre el registro anterior es el de Gamma" in dice and "El más ajustado es el de Beta" in dice
    assert "histór" not in json.dumps(h, ensure_ascii=False).lower()
    assert (tmp_path / "docs" / h["grafico"]["svg"]).exists() and (tmp_path / "docs" / h["provincias"]["01"]["grafico"]["csv"]).exists()
    # el formato que lee cg-sala-prensa
    for k in ("id", "kicker", "tono", "hechos", "cifras", "fuentes", "metodo", "limites", "provincias", "grafico", "texto", "actualizada"):
        assert k in h
    for k in ("titular", "subtitulo", "entradilla", "cuerpo", "claves"):
        assert k in h["texto"] and k in h["provincias"]["01"]["texto"]


def test_la_diferencia_se_puede_restar(monkeypatch, tmp_path):
    """El margen publicado es la resta de las dos cifras publicadas (redondeadas), no la de los valores sin redondear."""
    c = _monta(monkeypatch, tmp_path, {"Alfa": 0.50, "Beta": 0.20, "Gamma": 1.00})
    v = F.noticia_de_mesa(c, date(2026, 11, 26), tmp_path)["provincias"]["01"]
    import re
    val = float(re.search(r"de ([\d,]+) °C:", v["hechos"][0]["dice"]).group(1).replace(",", "."))
    ant, dif = [float(x.replace(",", ".")) for x in re.search(r"con ([\d,]+) °C; la diferencia es de ([\d,]+) °C", v["hechos"][1]["dice"]).groups()]
    assert abs((val - ant) - dif) < 1e-9


def test_empate_no_es_record(monkeypatch, tmp_path):
    c = _monta(monkeypatch, tmp_path, {"Alfa": 0.50, "Beta": 0.20, "Gamma": 1.00, "Delta": 0.02})
    c["marco"] = {"n_primeros": 3, "total": 4}
    for f in c["tabla"]:
        if f["ciudad"] == "Delta":
            f["puesto"] = 2                    # así lo deja la mesa: empate práctico = segundo puesto
    v = F.noticia_de_mesa(c, date(2026, 11, 26), tmp_path)["provincias"]["04"]
    assert "iguala el más cálido" in v["texto"]["titular"] and ", el más cálido en" not in v["texto"]["titular"]
    assert v["hechos"][1]["dice"].startswith("Iguala el registro de 2025")


def test_tipo_ajeno_no_escribe(tmp_path):
    assert F.noticia_de_mesa({"tipo_mesa": "racha"}, date(2026, 11, 26), tmp_path) is None
    assert not (tmp_path / "docs").exists()


def test_limpieza(tmp_path):
    d = tmp_path / "docs" / F.SUB
    d.mkdir(parents=True)
    (d / "2026-09-01-mesa-anio-calor-es-serie.svg").write_text("x")
    (d / "2026-11-17-mesa-anio-calor-es-serie.svg").write_text("x")
    assert F.limpiar(tmp_path, date(2026, 11, 26)) == 1
    assert [f.name for f in d.iterdir()] == ["2026-11-17-mesa-anio-calor-es-serie.svg"]
