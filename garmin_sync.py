#!/usr/bin/env python3
import json, os, sys
from datetime import datetime
from senderos_match import load_reference_trails, detect_segments

REF_TRAILS = []

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "garmin_data.json")
TOKEN_DIR = os.path.expanduser("~/.garth")

EMAIL = os.getenv("GARMIN_EMAIL")
PASSWORD = os.getenv("GARMIN_PASSWORD")

if not EMAIL or not PASSWORD:
    env_file = os.path.expanduser("~/.mtb_agent.env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("GARMIN_EMAIL="):
                    EMAIL = line.split("=", 1)[1].strip('"').strip("'")
                elif line.startswith("GARMIN_PASSWORD="):
                    PASSWORD = line.split("=", 1)[1].strip('"').strip("'")

from garminconnect import Garmin

def get_client():
    import garth
    try:
        # Try loading saved tokens first
        if os.path.exists(TOKEN_DIR):
            client = Garmin()
            client.garth.load(TOKEN_DIR)
            client.get_full_name()  # test if token works
            print("  → Usando tokens guardados")
            return client
    except Exception:
        pass
    # Login and save tokens
    print("  → Login con usuario/contraseña")
    client = Garmin(EMAIL, PASSWORD)
    client.login()
    client.garth.dump(TOKEN_DIR)
    return client

def extract_mtb_dynamics(detail):
    summary = detail.get('summaryDTO', {})
    metadata = detail.get('metadataDTO', {})
    return {
        'grit': summary.get('grit'),
        'avgFlow': summary.get('avgFlow'),
        'jumpCount': summary.get('jumpCount'),
        'waterEstimated': summary.get('waterEstimated'),
        'avgRespirationRate': summary.get('avgRespirationRate'),
        'trainingEffect': summary.get('trainingEffect'),
        'anaerobicTrainingEffect': summary.get('anaerobicTrainingEffect'),
        'trainingEffectLabel': summary.get('trainingEffectLabel'),
        'activityTrainingLoad': summary.get('activityTrainingLoad'),
        'avgEbikeAssistLevelPercent': summary.get('avgEbikeAssistLevelPercent'),
        'eBikeBatteryUsage': metadata.get('eBikeBatteryUsage'),
        'eBikeBatteryRemaining': metadata.get('eBikeBatteryRemaining'),
        'locationName': detail.get('locationName'),
        'maxSpeed': summary.get('maxSpeed'),
    }

def extract_summary(detail):
    summary = detail.get('summaryDTO', {})
    dyn = extract_mtb_dynamics(detail)
    return {
        'activityId': detail.get('activityId'),
        'activityName': detail.get('activityName'),
        'startTimeLocal': summary.get('startTimeLocal'),
        'distance': summary.get('distance'),
        'duration': summary.get('duration'),
        'movingDuration': summary.get('movingDuration'),
        'elevationGain': summary.get('elevationGain'),
        'elevationLoss': summary.get('elevationLoss'),
        'avgSpeed': summary.get('averageSpeed'),
        'maxSpeed': summary.get('maxSpeed'),
        'avgHR': summary.get('averageHR'),
        'maxHR': summary.get('maxHR'),
        'calories': summary.get('calories'),
        'avgTemperature': summary.get('averageTemperature'),
        'locationName': detail.get('locationName'),
        'mtbDynamics': dyn
    }

def main():
    print("\n══════════════════════════════════")
    print("  MTB Agent · Garmin Sync")
    print("══════════════════════════════════\n")

    client = get_client()
    if not client:
        print("  ✗ No se pudo conectar a Garmin")
        sys.exit(1)

    # Cargar senderos de referencia (Trailforks GPX/KML) desde ./senderos/
    SEN_DIR = os.path.join(OUTPUT_DIR, 'senderos')
    global REF_TRAILS
    REF_TRAILS = load_reference_trails(SEN_DIR)
    if REF_TRAILS:
        print(f"  ✓ {len(REF_TRAILS)} senderos de referencia cargados")
    else:
        print("  · Sin senderos en ./senderos/ (matcheo desactivado)")

    activities = client.get_activities(0, 20)
    if not activities:
        print("  ✗ No se encontraron actividades")
        sys.exit(1)

    print(f"  ✓ {len(activities)} actividades encontradas\n")

    # Correcciones manuales de fecha (Garmin a veces registra con timezone incorrecto)
    MANUAL_FIXES = {
        22715298923: {'startTimeLocal': '2026-05-09T09:50:44'},
        22962218472: {'startTimeLocal': '2026-05-30T09:59:00'},
        23070007352: {'startTimeLocal': '2026-05-30T10:05:00'},
    }

    # Cargar datos previos ANTES de enriquecer: sirve para (a) decidir qué falta
    # por enriquecer y (b) preservar/sanar el histórico rico más abajo.
    old_map = {}
    old_activities = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                old_data_pre = json.load(f)
            old_activities = old_data_pre.get('activities', [])
            old_map = {a['activityId']: a for a in old_activities if a.get('activityId')}
        except Exception:
            pass

    def _has_rich(a):
        return bool(a.get('mtbDynamics')) or a.get('maxSpeed') is not None

    def _needs(aid):
        old = old_map.get(aid, {})
        if not _has_rich(old):
            return True                                   # falta enriquecer
        if REF_TRAILS and not old.get('segments'):
            return True                                   # falta matchear senderos
        return False

    # Qué actividades pedir en detalle:
    #   - siempre las 5 más recientes (capturan salidas nuevas)
    #   - + cualquiera más antigua que falte enriquecer O que aún no tenga
    #     senderos detectados (backfill), hasta un tope para no saturar Garmin.
    #   Como cada salida procesada queda guardada con sus segmentos, en 2-3
    #   syncs todo el histórico queda cubierto y ya no se vuelve a bajar.
    MAX_ENRICH = 12
    to_enrich = set()
    for i, act in enumerate(activities):
        aid = act.get('activityId')
        if not aid:
            continue
        if i < 5 or _needs(aid):
            to_enrich.add(aid)
        if len(to_enrich) >= MAX_ENRICH:
            break

    enriched = []
    for act in activities:
        act_id = act.get('activityId')
        if not act_id:
            continue
        if act_id not in to_enrich:
            # Esqueleto — se sanará con los datos ricos del histórico si existen.
            enriched.append({
                'activityId': act_id,
                'activityName': act.get('activityName'),
                'startTimeLocal': act.get('startTimeLocal'),
                'distance': act.get('distance'),
                'elevationGain': act.get('elevationGain'),
                'mtbDynamics': {}
            })
            continue
        print(f"  → Detalle {act_id}...")
        try:
            detail = client.get_activity_evaluation(act_id)
            if not isinstance(detail, dict):
                detail = {}
            summary = extract_summary(detail)
            # Extraer saltos desde archivo FIT (unknown_285 = jump records)
            try:
                import fitparse, zipfile, io
                zip_data = client.download_activity(act_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
                z = zipfile.ZipFile(io.BytesIO(zip_data))
                fit_data = z.read(z.namelist()[0])
                fit = fitparse.FitFile(io.BytesIO(fit_data))
                jump_records = []
                for record in fit.get_messages('unknown_285'):
                    d = {f.name: f.value for f in record}
                    hang_time = d.get('unknown_0')
                    speed_raw = d.get('unknown_4')
                    score = d.get('unknown_7')
                    dist_raw = d.get('unknown_3')
                    if score is not None and dist_raw is not None:
                        dist = round(hang_time, 2) if hang_time else 0
                        ht = round(dist_raw, 3) if dist_raw else 0
                        spd = round((hang_time / dist_raw) * 3.6, 1) if hang_time and dist_raw > 0 else 0
                        sc = round(speed_raw) if speed_raw else 0
                        jump_records.append({
                            'score': sc,
                            'hangTime': ht,
                            'speed': spd,
                            'distance': dist
                        })
                if jump_records:
                    best = max(jump_records, key=lambda j: j['score'])
                    # Solo sobreescribir si el nuevo salto es mayor en distancia
                    existing_jump = summary.get("bestJump")
                    if not existing_jump or best['distance'] > existing_jump.get('distance', 0):
                        summary["bestJump"] = best
                    print(f"     → {len(jump_records)} saltos, mejor: {best['distance']}m score {best['score']}")

                # ── Matcheo de senderos (usa el GPS del mismo FIT) ──
                if REF_TRAILS:
                    try:
                        ride_pts = []
                        for rec in fit.get_messages('record'):
                            d = {f.name: f.value for f in rec}
                            lat = d.get('position_lat'); lon = d.get('position_long'); ts = d.get('timestamp')
                            if lat is None or lon is None or ts is None:
                                continue
                            # fitparse a veces entrega semicírculos (enteros grandes) → convertir a grados
                            if abs(lat) > 360: lat = lat * (180.0 / 2**31)
                            if abs(lon) > 360: lon = lon * (180.0 / 2**31)
                            ride_pts.append((lat, lon, ts.timestamp()))
                        if len(ride_pts) >= 10:
                            segs = detect_segments(ride_pts, REF_TRAILS)
                            if segs:
                                summary['segments'] = [{'name': s['name'], 'seconds': s['seconds'], 'passes': s.get('passes', 1), 'dist_m': s.get('dist_m')} for s in segs]
                                print(f"     → senderos: " + ", ".join(f"{s['name']} {s['seconds']}s" for s in segs))
                    except Exception:
                        pass
            except Exception as je:
                pass
            enriched.append(summary)
        except Exception as e:
            print(f"  ⚠ Error: {e}")
            enriched.append({
                'activityId': act_id,
                'activityName': act.get('activityName'),
                'startTimeLocal': act.get('startTimeLocal'),
                'distance': act.get('distance'),
                'mtbDynamics': {}
            })

    # ── Preservar / SANAR el histórico rico ──────────────────────────────
    # Clave para los records: si una salida cae del top-5 y vuelve como
    # esqueleto, aquí le devolvemos maxSpeed, mtbDynamics, descenso, etc.
    existing_ids = {a['activityId'] for a in enriched if a.get('activityId')}
    RICH_FIELDS = ('maxSpeed', 'avgSpeed', 'elevationGain', 'elevationLoss',
                   'duration', 'movingDuration', 'avgHR', 'maxHR', 'calories',
                   'avgTemperature', 'locationName', 'activityName')
    for act in enriched:
        aid = act.get('activityId')
        old = old_map.get(aid)
        if not old:
            continue
        # Restaurar dynamics si el nuevo viene vacío pero el viejo tenía datos
        if not act.get('mtbDynamics') and old.get('mtbDynamics'):
            act['mtbDynamics'] = old['mtbDynamics']
        # Restaurar segmentos detectados si el nuevo no trae y el viejo sí
        if not act.get('segments') and old.get('segments'):
            act['segments'] = old['segments']
        # Restaurar cualquier campo rico que falte en el nuevo
        for f in RICH_FIELDS:
            if act.get(f) in (None, '') and old.get(f) not in (None, ''):
                act[f] = old[f]
        # bestJump: conservar siempre el de mayor distancia
        old_jump = old.get('bestJump')
        new_jump = act.get('bestJump')
        if old_jump and (not new_jump or old_jump.get('distance', 0) > new_jump.get('distance', 0)):
            act['bestJump'] = old_jump
        # startTimeLocal histórico siempre gana (correcciones de timezone)
        if old.get('startTimeLocal'):
            act['startTimeLocal'] = old['startTimeLocal']

    # Agregar actividades históricas que ya no aparecen en el sync actual
    for old_act in old_activities:
        if old_act.get('activityId') not in existing_ids:
            enriched.append(old_act)

    # Aplicar correcciones manuales permanentes
    for act in enriched:
        aid = act.get('activityId')
        if aid in MANUAL_FIXES:
            for key, val in MANUAL_FIXES[aid].items():
                act[key] = val

    output = {
        'lastSync': datetime.now().isoformat(),
        'activities': enriched,
        'latestDynamics': enriched[0].get('mtbDynamics', {}) if enriched else {}
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n  ✓ Guardado en garmin_data.json")
    dyn = output['latestDynamics']
    if dyn:
        print(f"  Grit: {dyn.get('grit', '—')}")
        print(f"  Flow: {dyn.get('avgFlow', '—')}")
        print(f"  Jumps: {dyn.get('jumpCount', '—')}")
        print(f"  Batería: {dyn.get('eBikeBatteryUsage', '—')}%")
        print(f"  MaxSpeed: {round(dyn.get('maxSpeed',0)*3.6,1) if dyn.get('maxSpeed') else '—'} km/h")

    print("\n══════════════════════════════════\n")

if __name__ == '__main__':
    main()
