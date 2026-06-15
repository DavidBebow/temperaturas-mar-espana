#!/usr/bin/env python3
"""
GENERADOR (una sola vez) de municipios.json para "Tu municipio en 2050".

Para cada municipio consulta la API de Clima de Open-Meteo (CMIP6 reducido a 10 km,
1950-2050) y calcula, para el periodo PRESENTE y el de ~2050:
  - días de calor extremo al año (Tmax >= 35 °C)
  - noches tropicales al año (Tmin >= 20 °C)
  - meses secos al año (precipitación mensual < 30 mm)
Después calcula la "ciudad análoga": el municipio cuyo clima ACTUAL más se parece
al clima de 2050 de cada uno.

Cómo usarlo (en tu ordenador o en Google Colab, NO en GitHub Actions: tarda):
  1) Descarga un CSV de municipios con columnas de nombre, provincia, lat y lon
     (p. ej. de https://github.com/codeforspain/ds-organizacion-administrativa
     o cualquier dataset INE con coordenadas) y guárdalo como municipios_fuente.csv
  2) pip install requests
  3) python gen_municipios_2050.py
     - Es REANUDABLE: si lo paras, al volver a lanzarlo sigue donde iba.
     - Para una prueba rápida:  LIMIT=200 python gen_municipios_2050.py
  4) Sube el municipios.json resultante a docs/ de tu repo.

Open-Meteo es gratis pero tiene límite diario (~10.000 peticiones). Con ~8.100
municipios cabe en un día. El script va despacio a propósito (THROTTLE).
"""
import csv, json, os, sys, time, socket, urllib.request, urllib.parse, math

# Forzar IPv4 (evita cuelgues de conexión)
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda h,p,f=0,t=0,pr=0,fl=0: _gai(h,p,socket.AF_INET,t,pr,fl)

SRC   = os.environ.get("SRC", "municipios_fuente.csv")
OUT   = os.environ.get("OUT", "municipios.json")
MODELS= ["MRI_AGCM3_2_S", "EC_Earth3P_HR", "CMCC_CM2_VHR4"]   # ensemble HighResMIP
PRES  = (1991, 2020)     # periodo "hoy"
FUT   = (2036, 2050)     # periodo "~2050" (Open-Meteo Climate llega a 2050)
THROTTLE = 1.2           # segundos entre municipios (respeta límites)
LIMIT = int(os.environ.get("LIMIT", "0"))   # 0 = todos
BASE  = "https://climate-api.open-meteo.com/v1/climate"

# ---------------- lectura del CSV de municipios -------------------------------
def col(headers, *cands):
    low = [h.lower().strip() for h in headers]
    for c in cands:
        for i,h in enumerate(low):
            if c in h: return i
    return -1

def open_src(path):
    if str(path).startswith("http"):
        import io
        data = urllib.request.urlopen(path, timeout=60).read().decode("utf-8-sig", errors="replace")
        return io.StringIO(data)
    return open(path, encoding="utf-8-sig")

def load_municipios(path):
    with open_src(path) as f:
        # autodetecta separador , o ;
        sample = f.read(2048); f.seek(0)
        delim = ";" if sample.count(";") > sample.count(",") else ","
        r = csv.reader(f, delimiter=delim)
        headers = next(r)
        iN  = col(headers,"municipio","nombre","localidad","poblacion","name")
        iP  = col(headers,"provincia","prov")
        iLa = col(headers,"latitud","lat","geo_lat")
        iLo = col(headers,"longitud","lon","lng","geo_lon")
        if min(iN,iLa,iLo) < 0:
            sys.exit("No encuentro columnas de nombre/lat/lon en el CSV. Cabeceras: "+str(headers))
        seen=set(); out=[]
        for row in r:
            try:
                n=row[iN].strip(); la=float(str(row[iLa]).replace(",",".")); lo=float(str(row[iLo]).replace(",","."))
            except Exception: continue
            p=row[iP].strip() if iP>=0 and iP<len(row) else ""
            key=(n.lower(),p.lower())
            if not n or key in seen: continue
            seen.add(key); out.append({"n":n,"prov":p,"lat":la,"lon":lo})
        return out

# ---------------- Open-Meteo --------------------------------------------------
def fetch(lat, lon):
    qs = urllib.parse.urlencode({
        "latitude": round(lat,3), "longitude": round(lon,3),
        "start_date": f"{PRES[0]}-01-01", "end_date": f"{FUT[1]}-12-31",
        "models": ",".join(MODELS),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"})
    url = BASE + "?" + qs
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            print("    reintento", i+1, e, file=sys.stderr); time.sleep(4*(i+1))
    return None

def metrics(d):
    dd = d.get("daily", {}); times = dd.get("time")
    if not times: return None
    years=[int(t[:4]) for t in times]; months=[t[:7] for t in times]
    res={}
    for win,(y0,y1) in {"p":PRES,"f":FUT}.items():
        H=[];N=[];S=[]
        for m in MODELS:
            tx=dd.get("temperature_2m_max_"+m); tn=dd.get("temperature_2m_min_"+m); pr=dd.get("precipitation_sum_"+m)
            if tx is None: tx=dd.get("temperature_2m_max"); tn=dd.get("temperature_2m_min"); pr=dd.get("precipitation_sum")
            if not tx: continue
            hot=0; nig=0; mp={}
            for i,y in enumerate(years):
                if y<y0 or y>y1: continue
                if tx[i] is not None and tx[i]>=35: hot+=1
                if tn[i] is not None and tn[i]>=20: nig+=1
                if pr[i] is not None: mp[months[i]]=mp.get(months[i],0)+pr[i]
            ny=y1-y0+1
            H.append(hot/ny); N.append(nig/ny); S.append(sum(1 for v in mp.values() if v<30)/ny)
        if H: res[win]=(round(sum(H)/len(H)), round(sum(N)/len(N)), round(sum(S)/len(S),1))
    return res if "p" in res and "f" in res else None

# ---------------- ciudad análoga ---------------------------------------------
def add_analogs(items):
    import statistics as st
    def stats(key3):
        cols=list(zip(*[(it[k] for k in key3) for it in items]))
        return [ (st.mean(c), (st.pstdev(c) or 1)) for c in cols ]
    pst=stats(("ch","nh","sh"))   # normaliza por el presente
    def zp(it): return [ (it[k]-pst[i][0])/pst[i][1] for i,k in enumerate(("ch","nh","sh")) ]
    def zf(it): return [ (it[k]-pst[i][0])/pst[i][1] for i,k in enumerate(("c5","n5","s5")) ]
    P=[zp(it) for it in items]
    for i,it in enumerate(items):
        f=zf(it); best=-1; bd=1e9
        for j,pj in enumerate(P):
            if j==i: continue
            dd=(f[0]-pj[0])**2+(f[1]-pj[1])**2+(f[2]-pj[2])**2
            if dd<bd: bd=dd; best=j
        a=items[best]
        it["an"]=a["n"]; it["alat"]=a["lat"]; it["alon"]=a["lon"]

# ---------------- main --------------------------------------------------------
def main():
    munis=load_municipios(SRC)
    if LIMIT: munis=munis[:LIMIT]
    print(f"Municipios a procesar: {len(munis)}")
    done={}
    if os.path.exists(OUT):
        try:
            prev=json.load(open(OUT,encoding="utf8"))
            for it in prev.get("items",[]): done[(it["n"].lower(),it["prov"].lower())]=it
            print(f"Reanudando: {len(done)} ya hechos")
        except Exception: pass

    items=list(done.values())
    MAXSECONDS=int(os.environ.get("MAXSECONDS","0"))   # 0 = sin límite; en GitHub usa p.ej. 18000 (5 h)
    t0=time.time()
    for k,mu in enumerate(munis,1):
        key=(mu["n"].lower(),mu["prov"].lower())
        if key in done: continue
        if MAXSECONDS and time.time()-t0 > MAXSECONDS:
            json.dump({"items":items},open(OUT,"w",encoding="utf8"),ensure_ascii=False)
            print(f"PARCIAL: alcanzado el límite de tiempo con {len(done)}/{len(munis)}. "
                  f"Vuelve a lanzarlo para continuar.")
            return
        d=fetch(mu["lat"],mu["lon"]);
        mx=metrics(d) if d else None
        if not mx:
            print(f"  [{k}/{len(munis)}] {mu['n']}: sin datos, se omite", file=sys.stderr); time.sleep(THROTTLE); continue
        ch,nh,sh=mx["p"]; c5,n5,s5=mx["f"]
        it={"n":mu["n"],"prov":mu["prov"],"lat":round(mu["lat"],4),"lon":round(mu["lon"],4),
            "ch":ch,"c5":c5,"nh":nh,"n5":n5,"sh":sh,"s5":s5}
        items.append(it); done[key]=it
        print(f"  [{k}/{len(munis)}] {mu['n']}: calor {ch}->{c5}, noches {nh}->{n5}")
        if k%25==0:
            json.dump({"items":items},open(OUT,"w",encoding="utf8"),ensure_ascii=False)
        time.sleep(THROTTLE)

    # ¿están todos? Solo entonces calculamos análogos y cerramos el archivo final
    if len([1 for mu in munis if (mu["n"].lower(),mu["prov"].lower()) in done]) < len(munis):
        json.dump({"items":items},open(OUT,"w",encoding="utf8"),ensure_ascii=False)
        print(f"PARCIAL: {len(done)}/{len(munis)} hechos. Vuelve a lanzarlo para continuar.")
        return
    print("Calculando ciudades análogas…")
    add_analogs(items)
    meta={"fuente":"Open-Meteo Climate API (CMIP6 HighResMIP, ~2050)","modelos":MODELS,
          "presente":PRES,"futuro":FUT,"n":len(items)}
    json.dump({"meta":meta,"items":items},open(OUT,"w",encoding="utf8"),ensure_ascii=False)
    print(f"OK -> {OUT}  ({len(items)} municipios) COMPLETO")

if __name__=="__main__":
    main()
