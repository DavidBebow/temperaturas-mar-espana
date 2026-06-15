#!/usr/bin/env python3
"""
GENERADOR (una sola vez) de municipios.json para "Tu municipio en 2050".
Agrupa municipios en rejilla ~0,25° (1 consulta de clima por celda) + geocodifica
por nombre. Reanudable. Solo librería estándar (no hace falta pip install).
Variables de entorno: SRC, OUT, GEO, CLIM, MAXSECONDS, LIMIT.
"""
import csv, json, os, sys, time, socket, urllib.request, urllib.parse, urllib.error, io

_gai = socket.getaddrinfo
socket.getaddrinfo = lambda h,p,f=0,t=0,pr=0,fl=0: _gai(h,p,socket.AF_INET,t,pr,fl)

SRC   = os.environ.get("SRC", "scripts/municipios_fuente.csv")
OUT   = os.environ.get("OUT", "docs/municipios.json")
GEO   = os.environ.get("GEO", "scripts/geocode_cache.json")
CLIM  = os.environ.get("CLIM","scripts/clima_cache.json")
MODELS= ["MRI_AGCM3_2_S"]
PRES  = (1991, 2020)
FUT   = (2036, 2050)
GRID  = 0.25
THROTTLE = 3.0
LIMIT = int(os.environ.get("LIMIT", "0"))
MAXSECONDS = int(os.environ.get("MAXSECONDS", "0"))
CLIMATE = "https://climate-api.open-meteo.com/v1/climate"
GEOAPI  = "https://geocoding-api.open-meteo.com/v1/search"

def col(headers,*cands):
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
        return io.StringIO(urllib.request.urlopen(path,timeout=60).read().decode("utf-8-sig","replace"))
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
        if iN<0: sys.exit("No encuentro la columna del NOMBRE. Cabeceras: "+str(headers))
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
            seen.add(key); out.append({"n":n,"prov":prov,"code":code,"lat":la,"lon":lo})
        return out

def kf(d): return d.get("code") or (d["n"].lower()+"|"+d.get("prov","").lower())

def get_json(url, attempts=6):
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url,timeout=120) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            wait = 35*(i+1) if e.code==429 else 4*(i+1)
            print(f"    HTTP {e.code}, espero {wait}s", file=sys.stderr); time.sleep(wait)
        except Exception as e:
            print("    reintento",i+1,e,file=sys.stderr); time.sleep(4*(i+1))
    return None

GEOCACHE={}; CLIMCACHE={}
def geocode(name):
    if name in GEOCACHE: return GEOCACHE[name]
    q=name.split("/")[0].split(",")[0].strip()
    url=GEOAPI+"?"+urllib.parse.urlencode({"name":q,"count":1,"country":"ES","language":"es","format":"json"})
    j=get_json(url,attempts=4); res=(j or {}).get("results")
    c=[res[0]["latitude"],res[0]["longitude"]] if res else None
    GEOCACHE[name]=c; return c

def cell_of(lat,lon): return (round(lat/GRID)*GRID, round(lon/GRID)*GRID)

def climate_metrics(lat,lon):
    url=CLIMATE+"?"+urllib.parse.urlencode({
        "latitude":round(lat,3),"longitude":round(lon,3),
        "start_date":f"{PRES[0]}-01-01","end_date":f"{FUT[1]}-12-31",
        "models":",".join(MODELS),
        "daily":"temperature_2m_max,temperature_2m_min,precipitation_sum"})
    d=get_json(url)
    dd=(d or {}).get("daily",{}); times=dd.get("time")
    if not times: return None
    years=[int(t[:4]) for t in times]; months=[t[:7] for t in times]
    tx=dd.get("temperature_2m_max_"+MODELS[0]) or dd.get("temperature_2m_max")
    tn=dd.get("temperature_2m_min_"+MODELS[0]) or dd.get("temperature_2m_min")
    pr=dd.get("precipitation_sum_"+MODELS[0]) or dd.get("precipitation_sum")
    if not tx: return None
    out={}
    for win,(y0,y1) in {"p":PRES,"f":FUT}.items():
        hot=nig=0; mp={}
        for i,y in enumerate(years):
            if y<y0 or y>y1: continue
            if tx[i] is not None and tx[i]>=35: hot+=1
            if tn and tn[i] is not None and tn[i]>=20: nig+=1
            if pr and pr[i] is not None: mp[months[i]]=mp.get(months[i],0)+pr[i]
        ny=y1-y0+1
        out[win]=(round(hot/ny),round(nig/ny),round(sum(1 for v in mp.values() if v<30)/ny,1))
    return out

def add_analogs(items):
    import statistics as st
    cols=list(zip(*[[it[k] for k in ("ch","nh","sh")] for it in items]))
    pst=[(st.mean(c),(st.pstdev(c) or 1)) for c in cols]
    def z(it,ks): return [ (it[ks[i]]-pst[i][0])/pst[i][1] for i in range(3) ]
    P=[z(it,("ch","nh","sh")) for it in items]
    for i,it in enumerate(items):
        f=z(it,("c5","n5","s5")); best=-1; bd=1e9
        for j,pj in enumerate(P):
            if j==i: continue
            dd=(f[0]-pj[0])**2+(f[1]-pj[1])**2+(f[2]-pj[2])**2
            if dd<bd: bd=dd; best=j
        a=items[best]; it["an"]=a["n"]; it["alat"]=a["lat"]; it["alon"]=a["lon"]

def jsave(path,obj):
    os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
    json.dump(obj,open(path,"w",encoding="utf8"),ensure_ascii=False)

def main():
    global GEOCACHE,CLIMCACHE
    if os.path.exists(GEO):
        try: GEOCACHE=json.load(open(GEO,encoding="utf8"))
        except Exception: pass
    if os.path.exists(CLIM):
        try: CLIMCACHE=json.load(open(CLIM,encoding="utf8"))
        except Exception: pass
    munis=load_municipios(SRC)
    if LIMIT: munis=munis[:LIMIT]
    print(f"Municipios: {len(munis)} · celdas de clima en caché: {len(CLIMCACHE)}")
    done={}
    if os.path.exists(OUT):
        try:
            for it in json.load(open(OUT,encoding="utf8")).get("items",[]): done[kf(it)]=it
        except Exception: pass
    print(f"Reanudando: {len(done)} municipios ya hechos")
    items=list(done.values()); t0=time.time(); n=0
    for k,mu in enumerate(munis,1):
        if kf(mu) in done: continue
        if MAXSECONDS and time.time()-t0>MAXSECONDS:
            jsave(OUT,{"items":items}); jsave(GEO,GEOCACHE); jsave(CLIM,CLIMCACHE)
            print(f"PARCIAL por tiempo: {len(done)}/{len(munis)}. Relánzalo."); return
        if mu["lat"] is None:
            c=geocode(mu["n"]); time.sleep(0.4)
            if not c: print(f"  [{k}] {mu['n']}: no geocodificado",file=sys.stderr); continue
            mu["lat"],mu["lon"]=c
        cl,co=cell_of(mu["lat"],mu["lon"]); ck=f"{cl:.2f},{co:.2f}"
        m=CLIMCACHE.get(ck)
        if m is None:
            mx=climate_metrics(cl,co)
            if not mx: print(f"  [{k}] {mu['n']}: sin clima",file=sys.stderr); time.sleep(THROTTLE); continue
            m=[mx["p"][0],mx["f"][0],mx["p"][1],mx["f"][1],mx["p"][2],mx["f"][2]]
            CLIMCACHE[ck]=m
            print(f"  [{k}/{len(munis)}] {mu['n']} (celda nueva {ck}): calor {m[0]}->{m[1]}, noches {m[2]}->{m[3]}")
            time.sleep(THROTTLE)
        ch,c5,nh,n5,sh,s5=m
        it={"n":mu["n"],"prov":mu["prov"],"code":mu["code"],"lat":round(mu["lat"],4),"lon":round(mu["lon"],4),
            "ch":ch,"c5":c5,"nh":nh,"n5":n5,"sh":sh,"s5":s5}
        items.append(it); done[kf(it)]=it; n+=1
        if n%100==0: jsave(OUT,{"items":items}); jsave(GEO,GEOCACHE); jsave(CLIM,CLIMCACHE)

    if len([1 for mu in munis if kf(mu) in done])<len(munis):
        jsave(OUT,{"items":items}); jsave(GEO,GEOCACHE); jsave(CLIM,CLIMCACHE)
        print(f"PARCIAL: {len(done)}/{len(munis)}. Relánzalo para continuar."); return
    print("Calculando ciudades análogas…")
    add_analogs(items)
    meta={"fuente":"Open-Meteo Climate API (CMIP6 HighResMIP, ~2050)","modelo":MODELS[0],"presente":PRES,"futuro":FUT,"n":len(items)}
    jsave(OUT,{"meta":meta,"items":items}); jsave(GEO,GEOCACHE); jsave(CLIM,CLIMCACHE)
    print(f"OK -> {OUT} ({len(items)} municipios) COMPLETO")

if __name__=="__main__":
    main()
