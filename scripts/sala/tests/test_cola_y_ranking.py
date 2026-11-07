"""Pruebas de la cola provisional (atribucion.py) y de la frescura/regla de rareza (hallazgos_prensa.py).
Open-Meteo no se alcanza desde el sandbox: las respuestas son ficheros simulados con la misma forma (openmeteo_*_sim.json).
Uso: python scripts/sala/tests/test_cola_y_ranking.py   (o pytest)"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SCRIPTS = AQUI.parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "sala"))
from sala import atribucion as at  # noqa: E402

HOY = date(2026, 11, 7)
ARCH = json.loads((AQUI / "openmeteo_archive_sim.json").read_text(encoding="utf-8"))
FORE = json.loads((AQUI / "openmeteo_forecast_sim.json").read_text(encoding="utf-8"))


class Http:
    def __init__(self, falla=False, sin=None):
        self.llamadas, self.falla, self.sin = [], falla, sin or set()

    def __call__(self, url):
        self.llamadas.append(url)
        if self.falla:
            raise OSError("sin red")
        r = json.loads(json.dumps(ARCH if "archive-api" in url else FORE))
        if self.sin:
            d = r["daily"]
            k = [i for i, f in enumerate(d["time"]) if f not in self.sin]
            for c in d:
                d[c] = [d[c][i] for i in k]
        return r


def serie_madrid():
    S = at.cargar_serie("28", HOY)
    S.ultima_validada = S.ultima
    return S


def test_cola_completa_hasta_ayer():
    at.OM_CACHE = Path(tempfile.mkdtemp())
    S, http = serie_madrid(), Http()
    validado = S.ultima
    assert validado < date(2026, 11, 6), validado
    n = at.cola_provisional(S, HOY, http=http)
    assert S.ultima == date(2026, 11, 6) and n == (date(2026, 11, 6) - validado).days
    assert S.ultima_validada == validado
    assert min(S.prov_dias) == (validado.replace(day=validado.day) and (date.fromordinal(validado.toordinal() + 1)).isoformat())
    assert max(S.prov_dias) == "2026-11-06"
    assert len(http.llamadas) == 2 and "archive-api" in http.llamadas[0] and "past_days=7" in http.llamadas[1]
    # la cola del archivo (hasta 5 días antes de hoy) y la del forecast no se mezclan
    assert (at.OM_CACHE / f"{S.slug}.json").exists()
    c = json.loads((at.OM_CACHE / f"{S.slug}.json").read_text(encoding="utf-8"))["dias"]
    assert c["2026-11-01"][2] == "archive" and c["2026-11-06"][2] == "forecast", c


def test_cache_una_llamada_por_capital_y_dia():
    at.OM_CACHE = Path(tempfile.mkdtemp())
    at.cola_provisional(serie_madrid(), HOY, http=Http())
    S2, http2 = serie_madrid(), Http(falla=True)     # segunda pasada del mismo día: ni una petición
    at.cola_provisional(S2, HOY, http=http2)
    assert http2.llamadas == [] and S2.ultima == date(2026, 11, 6)


def test_fallo_de_red_no_rompe_y_publica_el_validado():
    at.OM_CACHE = Path(tempfile.mkdtemp())
    S = serie_madrid()
    validado = S.ultima
    assert at.cola_provisional(S, HOY, http=Http(falla=True)) == 0
    assert S.ultima == validado and not S.prov_dias
    memo = {}
    o, _ = at.procesar(S, HOY, memo)
    assert o["fecha_dato"] == validado.isoformat() and o["provisional"] is False
    assert o["hoy_validado"]["fecha"] == validado.isoformat()


def test_un_hueco_corta_la_cola():
    at.OM_CACHE = Path(tempfile.mkdtemp())
    S = serie_madrid()
    at.cola_provisional(S, HOY, http=Http(sin={"2026-11-04"}))
    assert S.ultima == date(2026, 11, 3), S.ultima      # nunca se salta un día: «ayer» sería mentira


def test_indice_se_publica_con_fecha_de_ayer():
    at.OM_CACHE = Path(tempfile.mkdtemp())
    S = serie_madrid()
    validado = S.ultima
    at.cola_provisional(S, HOY, http=Http())
    o, _ = at.procesar(S, HOY, {})
    assert o["fecha_dato"] == "2026-11-06" and o["provisional"] is True
    assert o["fuente_dia"] == at.FUENTE_DIA_PROV
    assert o["hoy_validado"]["fecha"] == validado.isoformat() and o["hoy_validado"]["provisional"] is False
    assert o["fuente_diaria"] == "aemet" and o["fuente_mensual"] in ("aemet", "era5")
    assert "Open-Meteo" in o["textos"]["frase_hoy"]


def test_frescura_y_regla_de_rareza():
    sys.argv = ["x"]
    import hallazgos_prensa as H
    base = {"serie": "huella", "tipo": "antes_raro", "indicador": "mes_media_alta", "ambito_tiempo": "mes", "cierre_mes": "cerrado",
            "fecha_dato": "2026-10-31"}
    f, vida = H.frescura_y_vida(base, 8)
    assert f == 1.0 and vida >= 30                      # mes cerrado: sin pérdida hasta el 20 del mes siguiente (20 días)
    assert H.frescura_y_vida(base, 25)[0] < 1.0
    diario = {"serie": "capitales", "tipo": "record_fecha", "indicador": "tmax", "fecha_dato": "2026-10-31"}
    assert abs(H.frescura_y_vida(diario, 8)[0] - 0.51) < 1e-9
    temp = {"serie": "temporadas", "tipo": "temporada", "indicador": "x", "fecha_dato": "2026-10-31"}
    assert H.frescura_y_vida(temp, 30)[0] == 1.0 and H.frescura_y_vida(temp, 31)[0] < 1.0
    a = {"id": "a", "tipo": "antes_raro", "ambito": "nacional", "citabilidad": "alta", "fuerza": 60.0,
         "rareza": {"significativo": True, "PR_num": 8.0}}
    b = {"id": "b", "tipo": "lluvia_dia", "ambito": "nacional", "citabilidad": "alta", "fuerza": 85.0}
    c = {"id": "c", "tipo": "lluvia_dia", "ambito": "provincial", "citabilidad": "alta", "fuerza": 85.0}
    assert H.regla_rareza([a, b, c]) == ["b"] and b["fuerza"] < a["fuerza"] and c["fuerza"] == 85.0


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            n += 1
            print("ok", k)
    print(f"{n} pruebas OK")
