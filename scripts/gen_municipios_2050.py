#!/usr/bin/env python3
"""
GENERADOR (una sola vez) de municipios.json para "Tu municipio en 2050".

Lee un CSV de municipios (basta con que tenga el NOMBRE; las coordenadas las
obtiene solo con el geocodificador de Open-Meteo si el CSV no las trae). Para
cada municipio consulta la API de Clima de Open-Meteo (CMIP6 reducido a 10 km,
1950-2050) y calcula, para el PRESENTE y para ~2050:
  - días de calor extremo al año (Tmax >= 35 °C)
  - noches tropicales al año (Tmin >= 20 °C)
  - meses secos al año (precipitación mensual < 30 mm)
Después calcula la "ciudad análoga": el municipio cuyo clima ACTUAL más se parece
al clima de 2050 de cada uno.

Variables de entorno (opcionales):
  SRC=scripts/municipios_fuente.csv   OUT=docs/municipios.json
  MAXSECONDS=18000 (para GitHub Actions, ~5 h y se detiene guardando el avance)
  LIMIT=200 (para una prueba rápida)
Es REANUDABLE: si se para, al volver a lanzarlo continúa donde iba.
Solo usa la librería estándar de Python (no hace falta pip install).
"""
import csv, json, os, sys, time, socket, urllib.request, urllib.parse, io

# Forzar IPv4 (evita cuelgues de conexión)
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda h,p,f=0,t=0,pr=0,fl=0: _gai(h,p,socket.AF_INET,t,pr,fl)

SRC   = os.environ.get("SRC", "scripts/municipios_fuente.csv")
OUT   = os.environ.get("OUT", "docs/municipios.json")
GEO   = os.environ.get("GEO", "scripts/geocode_cache.json")
MODELS= ["MRI_AGCM3_2_S", "EC_Earth3P_HR", "CMCC_CM2_VHR4"]
PRES  = (1991, 2020)
FUT   = (2036, 2050)
THROTTLE = 1.0
LIMIT = int(os.environ.get("LIMIT", "0"))
MAXSECONDS = int(os.environ.get("MAXSECONDS", "0"))
CLIMATE = "https://climate-api.open-meteo.com/v1/climate"
GEOAPI  = "https://geocoding-api.open-meteo.com/v1/search"

def col(headers, *cands):
    low=[h.lower().strip() for h in headers]
    for c in cands:
        for i,h in enumerate(low):
            if c==h: return i
    for c in cands:
        for i,h in enumerate(low):
            if c in h: return i
    return -1

def open_src(path):
    if str(path).startswith("http"):
        data=urllib.request.urlopen(path,timeout=60).read().decode("utf-8-sig",errors="replace")
        return io.StringIO(data)
    return open(path, encoding="utf-8-sig")

def load_municipios(path):
    with open_src(path) as f:
        sample=f.read(2048); f.seek(0)
        delim=";" if sample.count(";")>sample.count(",") else ","
        r=csv.reader(f,delimiter=delim); headers=next(r)
        iN =col(headers,"nameunit","municipio","nombre","localidad","name")
        iP =col(headers,"provincia","prov")
        iC =col(headers,"codigoine","natcode","cod_ine","codigo","ine")
        iLa=col(headers,"latitud","lat","geo_lat")
        iLo=col(headers,"longitud","lon","lng","geo_lon")
        if iN<0: sys.exit("No encuentro la columna del NOMBRE del municipio. Cabeceras: "+str(headers))
        seen=set(); out=[]
        for row in r:
            if iN>=len(row): continue
            n=row[iN].strip()
            if not n: continue
            prov=row[iP].strip() if 0<=iP<len(row) else ""
            code=row[iC].strip() if 0<=iC<len(row) else ""
            la=lo=None
            if 0<=iLa<len(row) and 0<=iLo<len(row):
                try: la=float(str(row[iLa]).replace(",",".")); lo=float(str(row[iLo]).replace(",","."))
                except Exception: la=lo=None
            key=code or (n.lower()+"|"+prov.lower())
            if key in seen: continue
            seen.add(key)
            out.append({"n":n,"prov":prov,"code":code,"lat":la,"lon":lo})
        return out

def kf(d): return d.get("code") or (d["n"].lower()+"|"+d.get("prov","").lower())

def get_json(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(url,timeout=120) as r:
                return json.load(r)
        except Exception as e:
            print("    reintento",i+1,e,file=sys.stderr); time.sleep(3*(i+1))
    return None

# ---- geocodificación (cache para no repetir) --------------------------------
GEOCACHE={}
def geocode(name):
    if name in GEOCACHE: return GEOCACHE[name]
    q=name.split("/")[0].split(",")[0].strip()   # limpia nombres bilingües "A/B"
    url=GEOAPI+"?"+urllib.parse.urlencode({"name":q,"count":1,"country":"ES","language":"es","format":"json"})
    j=get_json(url); res=(j or {}).get("results")
    c=(res[0]["latitude"],res[0]["longitude"]) if res else None
    GEOCACHE[name]=c
    return c

def climate(lat,lon):
    url=CLIMATE+"?"+urllib.parse.urlencode({
        "latitude":round(lat,3),"longitude":round(lon,3),
        "start_date":f"{PRES[0]}-01-01","end_date":f"{FUT[1]}-12-31",
        "models":",".join(MODELS),
        "daily":"temperature_2m_max,temperature_2m_min,precipitation_sum"})
    return get_json(url)

def metrics(d):
    dd=(d or {}).get("daily",{}); times=dd.get("time")
    if not times: return None
    years=[int(t[:4]) for t in times]; months=[t[:7] for t in times]
    res={}
    for win,(y0,y1) in {"p":PRES,"f":FUT}.items():
        H=[];N=[];S=[]
        for m in MODELS:
            tx=dd.get("temperature_2m_max_"+m); tn=dd.get("temperature_2m_min_"+m); pr=dd.get("precipitation_sum_"+m)
            if tx is None: tx=dd.get("temperature_2m_max"); tn=dd.get("temperature_2m_min"); pr=dd.get("precipitation_sum")
            if not tx: continue
            hot=nig=0; mp={}
            for i,y in enumerate(years):
                if y<y0 or y>y1: continue
                if tx[i] is not None and tx[i]>=35: hot+=1
                if tn and tn[i] is not None and tn[i]>=20: nig+=1
                if pr and pr[i] is not None: mp[months[i]]=mp.get(months[i],0)+pr[i]
            ny=y1-y0+1
            H.append(hot/ny); N.append(nig/ny); S.append(sum(1 for v in mp.values() if v<30)/ny)
        if H: res[win]=(round(sum(H)/len(H)),round(sum(N)/len(N)),round(sum(S)/len(S),1))
    return res if "p" in res and "f" in res else None

def add_analogs(items):
    import statistics as st
    keys=("ch","nh","sh")
    cols=list(zip(*[[it[k] for k in keys] for it in items]))
    pst=[(st.mean(c),(st.pstdev(c) or 1)) for c in cols]
    def z(it,kk): return [ (it[kk[i]]-pst[i][0])/pst[i][1] for i in range(3) ]
    P=[z(it,("ch","nh","sh")) for it in items]
    for i,it in enumerate(items):
        f=z(it,("c5","n5","s5")); best=-1; bd=1e9
        for j,pj in enumerate(P):
            if j==i: continue
            dd=(f[0]-pj[0])**2+(f[1]-pj[1])**2+(f[2]-pj[2])**2
            if dd<bd: bd=dd; best=j
        a=items[best]; it["an"]=a["n"]; it["alat"]=a["lat"]; it["alon"]=a["lon"]

def save_partial(items):
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    json.dump({"items":items},open(OUT,"w",encoding="utf8"),ensure_ascii=False)
def save_geocache():
    os.makedirs(os.path.dirname(GEO) or ".", exist_ok=True)
    json.dump(GEOCACHE,open(GEO,"w",encoding="utf8"),ensure_ascii=False)

def main():
    global GEOCACHE
    if os.path.exists(GEO):
        try: GEOCACHE=json.load(open(GEO,encoding="utf8"))
        except Exception: GEOCACHE={}
    munis=load_municipios(SRC)
    if LIMIT: munis=munis[:LIMIT]
    print(f"Municipios a procesar: {len(munis)}")
    done={}
    if os.path.exists(OUT):
        try:
            for it in json.load(open(OUT,encoding="utf8")).get("items",[]): done[kf(it)]=it
            print(f"Reanudando: {len(done)} ya hechos")
        except Exception: pass
    items=list(done.values())
    t0=time.time(); n=0
    for k,mu in enumerate(munis,1):
        if kf(mu) in done: continue
        if MAXSECONDS and time.time()-t0>MAXSECONDS:
            save_partial(items); save_geocache()
            print(f"PARCIAL por tiempo: {len(done)}/{len(munis)}. Vuelve a lanzarlo."); return
        if mu["lat"] is None:
            c=geocode(mu["n"]); time.sleep(0.4)
            if not c:
                print(f"  [{k}] {mu['n']}: no geocodificado, se omite",file=sys.stderr); continue
            mu["lat"],mu["lon"]=c
        mx=metrics(climate(mu["lat"],mu["lon"]))
        if not mx:
            print(f"  [{k}] {mu['n']}: sin datos clima, se omite",file=sys.stderr); time.sleep(THROTTLE); continue
        ch,nh,sh=mx["p"]; c5,n5,s5=mx["f"]
        it={"n":mu["n"],"prov":mu["prov"],"code":mu["code"],"lat":round(mu["lat"],4),"lon":round(mu["lon"],4),
            "ch":ch,"c5":c5,"nh":nh,"n5":n5,"sh":sh,"s5":s5}
        items.append(it); done[kf(it)]=it; n+=1
        print(f"  [{k}/{len(munis)}] {mu['n']}: calor {ch}->{c5}, noches {nh}->{n5}")
        if n%25==0: save_partial(items); save_geocache()
        time.sleep(THROTTLE)

    if len([1 for mu in munis if kf(mu) in done])<len(munis):
        save_partial(items); save_geocache()
        print(f"PARCIAL: {len(done)}/{len(munis)} hechos. Vuelve a lanzarlo para continuar."); return
    print("Calculando ciudades análogas…")
    add_analogs(items)
    meta={"fuente":"Open-Meteo Climate API (CMIP6 HighResMIP, ~2050)","modelos":MODELS,"presente":PRES,"futuro":FUT,"n":len(items)}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    json.dump({"meta":meta,"items":items},open(OUT,"w",encoding="utf8"),ensure_ascii=False)
    save_geocache()
    print(f"OK -> {OUT} ({len(items)} municipios) COMPLETO")

if __name__=="__main__":
    main()
