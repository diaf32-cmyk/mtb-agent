#!/usr/bin/env python3
"""
Motor de matcheo de senderos para MTB Agent.

Carga senderos de referencia (archivos GPX/KML descargados de Trailforks,
uno o varios por archivo) y detecta, en el track GPS de una salida, por
cuáles pasaste y cuánto demoraste — asignando el nombre oficial del sendero.

Sin dependencias externas: solo stdlib. Corre en el Mac dentro de garmin_sync.py.
"""
import os, math
import xml.etree.ElementTree as ET


def _localname(tag):
    return tag.rsplit('}', 1)[-1]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p = math.pi / 180
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _trail_length_m(pts):
    """Largo total del sendero de referencia en metros (para estimar km/h)."""
    total = 0.0
    for i in range(1, len(pts)):
        total += haversine(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
    return total


def _moving_seconds(ride_pts, a, b, v_stop=0.5, min_dwell=5.0, max_step=10.0):
    """Duración del tramo [a, b] en tiempo REAL de rodada.

    Descuenta las paradas largas (regroup / sesión de saltos): tramos
    sostenidos de >min_dwell segundos a menos de v_stop m/s. También
    descuenta huecos de grabación (dt > max_step). Las bajadas técnicas
    lentas de pocos segundos NO se descuentan.
    """
    total = ride_pts[b][2] - ride_pts[a][2]
    dwell = 0.0
    run_stop = 0.0
    for k in range(a + 1, b + 1):
        dd = haversine(ride_pts[k - 1][0], ride_pts[k - 1][1], ride_pts[k][0], ride_pts[k][1])
        dt = ride_pts[k][2] - ride_pts[k - 1][2]
        if dt <= 0:
            continue
        if dt > max_step:                       # hueco de grabación
            dwell += dt
            run_stop = 0.0
            continue
        if dd / dt < v_stop:                    # detenido
            run_stop += dt
        else:
            if run_stop > min_dwell:            # cierra una parada larga
                dwell += run_stop
            run_stop = 0.0
    if run_stop > min_dwell:
        dwell += run_stop
    return max(total - dwell, 0.0)


# ── Parseo de archivos de referencia ──────────────────────────────────
def parse_gpx(path):
    trails = []
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return trails
    tracks = [e for e in root.iter() if _localname(e.tag) in ('trk', 'rte')]
    if not tracks:
        pts = [(float(p.get('lat')), float(p.get('lon')))
               for p in root.iter() if _localname(p.tag) in ('trkpt', 'rtept')
               and p.get('lat') and p.get('lon')]
        if len(pts) >= 2:
            trails.append({'name': _fname(path), 'pts': pts})
        return trails
    for tk in tracks:
        name = None
        for c in tk:
            if _localname(c.tag) == 'name':
                name = (c.text or '').strip()
        pts = [(float(p.get('lat')), float(p.get('lon')))
               for p in tk.iter() if _localname(p.tag) in ('trkpt', 'rtept')
               and p.get('lat') and p.get('lon')]
        if len(pts) >= 2:
            trails.append({'name': name or _fname(path), 'pts': pts})
    return trails


def parse_kml(path):
    trails = []
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return trails
    for pm in [e for e in root.iter() if _localname(e.tag) == 'Placemark']:
        name = None
        for c in pm.iter():
            if _localname(c.tag) == 'name':
                name = (c.text or '').strip()
                break
        pts = []
        for ce in [e for e in pm.iter() if _localname(e.tag) == 'coordinates']:
            for tok in (ce.text or '').split():
                parts = tok.split(',')
                if len(parts) >= 2:
                    try:
                        lon = float(parts[0]); lat = float(parts[1])
                        pts.append((lat, lon))
                    except ValueError:
                        pass
        if len(pts) >= 2:
            trails.append({'name': name or _fname(path), 'pts': pts})
    return trails


def _fname(path):
    return os.path.splitext(os.path.basename(path))[0]


def load_reference_trails(folder):
    """Carga todos los senderos de una carpeta (.gpx / .kml)."""
    trails = []
    if not os.path.isdir(folder):
        return trails
    for fn in sorted(os.listdir(folder)):
        low = fn.lower()
        path = os.path.join(folder, fn)
        if low.endswith('.gpx'):
            trails += parse_gpx(path)
        elif low.endswith('.kml'):
            trails += parse_kml(path)
    # Downsample senderos muy densos (para acelerar el matcheo)
    for t in trails:
        if len(t['pts']) > 300:
            step = math.ceil(len(t['pts']) / 300)
            t['pts'] = t['pts'][::step] + [t['pts'][-1]]
    return trails


# ── Índice espacial (grid hash) sobre el track de la salida ───────────
class _Grid:
    def __init__(self, pts, cell_m):
        self.pts = pts
        self.cell = cell_m / 111320.0  # grados por celda (lat)
        self.d = {}
        for i, (la, lo, _t) in enumerate(pts):
            self.d.setdefault(self._key(la, lo), []).append(i)

    def _key(self, la, lo):
        return (int(la / self.cell), int(lo / self.cell))

    def nearest(self, la, lo):
        ki, kj = int(la / self.cell), int(lo / self.cell)
        best, bd = None, 1e18
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for idx in self.d.get((ki + di, kj + dj), []):
                    pla, plo, _ = self.pts[idx]
                    dd = haversine(la, lo, pla, plo)
                    if dd < bd:
                        bd, best = dd, idx
        return best, bd


# ── Detección de segmentos en una salida ──────────────────────────────
def _scan_runs(ride_pts, ref, tol_m, coverage, max_gap_pts):
    """Encuentra bajadas válidas del track sobre 'ref' (en el sentido dado).
    Devuelve lista de (cobertura, segundos) de cada tramo válido."""
    n = len(ref)
    tgrid = _Grid([(la, lo, 0) for (la, lo) in ref], tol_m)
    runs = []
    cur = None
    gap = 0
    for i, (la, lo, _t) in enumerate(ride_pts):
        tj, d = tgrid.nearest(la, lo)
        on = tj is not None and d <= tol_m
        if on:
            if cur is None:
                cur = {'a': i, 'b': i, 'hit': {tj}, 'maxtj': tj, 'first': tj, 'last': tj}
            elif cur['maxtj'] > 0.5 * n and tj < cur['maxtj'] - 0.4 * n:
                runs.append(cur)
                cur = {'a': i, 'b': i, 'hit': {tj}, 'maxtj': tj, 'first': tj, 'last': tj}
            else:
                cur['b'] = i
                cur['hit'].add(tj)
                cur['last'] = tj
                if tj > cur['maxtj']:
                    cur['maxtj'] = tj
            gap = 0
        elif cur is not None:
            gap += 1
            if gap > max_gap_pts:
                runs.append(cur)
                cur = None
                gap = 0
    if cur is not None:
        runs.append(cur)

    qual = []
    for r in runs:
        cov = len(r['hit']) / n
        if cov < coverage:
            continue
        if (r['last'] - r['first']) < 0.5 * n:   # debe avanzar >½ del sendero
            continue
        dur = _moving_seconds(ride_pts, r['a'], r['b'])   # tiempo de rodada, sin paradas
        if dur <= 0:
            continue
        qual.append((cov, dur))
    return qual


def detect_segments(ride_pts, trails, tol_m=25.0, coverage=0.6, max_gap_pts=8):
    """
    ride_pts: lista de (lat, lon, epoch_seconds) del track de la salida.
    trails:   salida de load_reference_trails().

    Detecta cada bajada del sendero como un tramo continuo que la recorre
    entera. Prueba el sendero en AMBOS sentidos (el GPX de Trailforks puede
    estar dibujado al revés de como tú lo bajas). De todas las bajadas válidas
    reporta la MÁS RÁPIDA (tu mejor vuelta = tu PR) y cuántas hiciste.

    Devuelve: [{name, seconds, coverage, passes}] por sendero detectado.
    """
    if len(ride_pts) < 10 or not trails:
        return []
    out = []
    for tr in trails:
        ref = tr['pts']
        if len(ref) < 2:
            continue
        # Probar ambas orientaciones y unir; solo la que calza con tu
        # dirección de bajada produce tramos válidos.
        qual = _scan_runs(ride_pts, ref, tol_m, coverage, max_gap_pts)
        qual += _scan_runs(ride_pts, ref[::-1], tol_m, coverage, max_gap_pts)
        if qual:
            best_dur = min(d for _, d in qual)
            best_cov = max(c for c, _ in qual)
            out.append({'name': tr['name'], 'seconds': round(best_dur, 1),
                        'coverage': round(best_cov, 2), 'passes': len(qual),
                        'dist_m': round(_trail_length_m(ref))})
    return out
    return out
    return out


# ── Autotest ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Salida sintética: línea de 200 puntos, 1 s de separación
    base_lat, base_lon = -33.35, -70.48
    ride = [(base_lat + i * 0.0001, base_lon + i * 0.00005, 1000.0 + i) for i in range(200)]
    # Sendero real = subtramo ride[50..90]; sendero falso = lejos
    trail_ok = {'name': 'El Gringo', 'pts': [(ride[i][0], ride[i][1]) for i in range(50, 91)]}
    trail_no = {'name': 'Inexistente', 'pts': [(10.0, 10.0), (10.001, 10.0), (10.002, 10.0)]}
    segs = detect_segments(ride, [trail_ok, trail_no])
    print('Detectados (1 vuelta):', segs)
    names = [s['name'] for s in segs]
    assert 'El Gringo' in names, 'debía detectar El Gringo'
    assert 'Inexistente' not in names, 'no debía detectar el falso'
    g = [s for s in segs if s['name'] == 'El Gringo'][0]
    assert 38 <= g['seconds'] <= 52, ('tiempo esperado ~40-50s, dio', g['seconds'])

    # Caso crítico: DOS vueltas a la misma pista en una salida, separadas por
    # un largo tramo de pedaleo. La vuelta rápida debe reportarse ~40s, NO el
    # span completo (~cientos de s).
    ride2 = list(ride)                     # 1ª vuelta: ride[50..90]
    t2 = ride[-1][2] + 600                 # 10 min pedaleando lejos
    for _ in range(300):                   # tramo lejos del sendero
        ride2.append((-33.40, -70.60, t2)); t2 += 2
    for i in range(50, 91):                # 2ª vuelta por el mismo sendero
        ride2.append((trail_ok['pts'][i-50][0], trail_ok['pts'][i-50][1], t2)); t2 += 1
    segs2 = detect_segments(ride2, [trail_ok])
    print('Detectados (2 vueltas):', segs2)
    g2 = [s for s in segs2 if s['name'] == 'El Gringo'][0]
    assert g2['seconds'] < 60, ('con 2 vueltas el tiempo debe ser de UNA vuelta, dio', g2['seconds'])
    assert g2['passes'] == 2, ('debía contar 2 pasadas, contó', g2.get('passes'))

    # Vuelta parcial (solo la mitad del sendero) NO debe contar como bajada
    ride3 = [(trail_ok['pts'][i - 50][0], trail_ok['pts'][i - 50][1], 100.0 + (i - 50))
             for i in range(50, 70)]  # solo ~medio sendero
    segs3 = detect_segments(ride3, [trail_ok])
    assert not segs3, ('una pasada parcial no debe contar, dio', segs3)

    # Test parseo GPX inline
    gpx = '''<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">
      <trk><name>Lomo Vetado</name><trkseg>
      <trkpt lat="-33.35" lon="-70.48"></trkpt>
      <trkpt lat="-33.351" lon="-70.481"></trkpt>
      </trkseg></trk></gpx>'''
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.gpx', delete=False) as f:
        f.write(gpx); tmp = f.name
    tr = parse_gpx(tmp)
    assert tr and tr[0]['name'] == 'Lomo Vetado' and len(tr[0]['pts']) == 2, tr
    os.unlink(tmp)

    print('OK — matcher y parsers funcionan')
