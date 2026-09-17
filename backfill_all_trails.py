#!/usr/bin/env python3
"""
Backfill de UNA VEZ: reprocesa TODAS las actividades que ya tienen datos
ricos en garmin_data.json, para agregarles maxSpeedTrail / bestJump.trail
y los start_t/end_t de sus segmentos — campos que no existían antes de
este cambio. El sync normal no las toca porque ya tienen `segments`
guardado (ver _needs() en garmin_sync.py), así que hace falta este
empujón manual una sola vez.

Uso: colocar en ~/Desktop/Garmin_Enduro/ y correr:
    python3 backfill_all_trails.py
Puede tardar varios minutos si tienes muchas actividades (una descarga de
FIT por actividad). Reintenta solo, si Garmin corta la conexión vuelve a
correrlo — ya no repite las que quedaron con maxSpeedTrail asignado.
"""
import json, os, sys, io, zipfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from garmin_sync import get_client, OUTPUT_FILE, OUTPUT_DIR
from senderos_match import load_reference_trails, detect_segments
from garminconnect import Garmin
import fitparse


def process_one(client, trails, act):
    act_id = act['activityId']
    zip_data = client.download_activity(act_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    z = zipfile.ZipFile(io.BytesIO(zip_data))
    fit_data = z.read(z.namelist()[0])
    fit = fitparse.FitFile(io.BytesIO(fit_data))

    ride_pts, speed_pts = [], []
    for rec in fit.get_messages('record'):
        d = {f.name: f.value for f in rec}
        lat = d.get('position_lat'); lon = d.get('position_long'); ts = d.get('timestamp')
        if lat is None or lon is None or ts is None:
            continue
        if abs(lat) > 360: lat = lat * (180.0 / 2**31)
        if abs(lon) > 360: lon = lon * (180.0 / 2**31)
        ride_pts.append((lat, lon, ts.timestamp()))
        spd = d.get('enhanced_speed', d.get('speed'))
        if spd is not None:
            speed_pts.append((spd, ts.timestamp()))

    if len(ride_pts) < 10:
        return False

    segs = detect_segments(ride_pts, trails)
    act['segments'] = [
        {'name': s['name'], 'seconds': s['seconds'], 'passes': s.get('passes', 1),
         'dist_m': s.get('dist_m'), 'start_t': s.get('start_t'), 'end_t': s.get('end_t')}
        for s in segs
    ]

    def trail_at(t):
        if t is None:
            return None
        for s in segs:
            if s.get('start_t') is not None and s['start_t'] <= t <= s['end_t']:
                return s['name']
        return None

    changed = False
    if speed_pts:
        _, top_t = max(speed_pts, key=lambda x: x[0])
        tn = trail_at(top_t)
        if tn:
            act['maxSpeedTrail'] = tn
            changed = True

    for record in fit.get_messages('unknown_285'):
        d = {f.name: f.value for f in record}
        score = d.get('unknown_7')
        dist_raw = d.get('unknown_3')
        jts = d.get('timestamp')
        if score is None or dist_raw is None:
            continue
        tn = trail_at(jts.timestamp() if jts else None)
        if tn and act.get('bestJump'):
            act['bestJump']['trail'] = tn
            changed = True
        break  # solo nos interesa si el mejor salto guardado cae en un sendero; con uno alcanza

    return changed or bool(segs)


def main():
    with open(OUTPUT_FILE) as f:
        data = json.load(f)
    activities = data['activities']

    candidates = [a for a in activities if a.get('activityId') and (a.get('mtbDynamics') or a.get('maxSpeed') is not None)]
    print(f"{len(candidates)} actividades con datos ricos para reprocesar")

    client = get_client()
    if not client:
        print("✗ No se pudo conectar a Garmin")
        sys.exit(1)

    SEN_DIR = os.path.join(OUTPUT_DIR, 'senderos')
    trails = load_reference_trails(SEN_DIR)
    print(f"✓ {len(trails)} senderos de referencia cargados\n")

    done, errors = 0, 0
    for i, act in enumerate(candidates):
        aid = act['activityId']
        try:
            print(f"[{i+1}/{len(candidates)}] {aid} — {act.get('activityName')} ({act.get('startTimeLocal')})...", end=' ')
            ok = process_one(client, trails, act)
            print("✓" if ok else "· sin senderos")
            done += 1
        except Exception as e:
            print(f"⚠ error: {e}")
            errors += 1
        # Guardar cada pocas para no perder progreso si se corta a mitad de camino
        if (i + 1) % 5 == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        time.sleep(0.5)  # no saturar la API de Garmin

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\n✓ Listo — {done} procesadas, {errors} con error. Guardado en garmin_data.json")


if __name__ == '__main__':
    main()
