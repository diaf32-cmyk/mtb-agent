#!/usr/bin/env python3
import json, os, sys
from datetime import datetime

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

    activities = client.get_activities(0, 20)
    if not activities:
        print("  ✗ No se encontraron actividades")
        sys.exit(1)

    print(f"  ✓ {len(activities)} actividades encontradas\n")

    # Correcciones manuales permanentes (no sobreescribir nunca)
    MANUAL_FIXES = {
        22715298923: {
            'startTimeLocal': '2026-05-09T09:50:44',
            'bestJump': {'score': 186.0, 'distance': 9.81, 'hangTime': 0.75, 'speed': 46.9}
        },
        22811318174: {
            'bestJump': {'score': 160.0, 'distance': 8.10, 'hangTime': 0.68, 'speed': 42.9}
        },
        22962218472: {
            'bestJump': {'score': 181.0, 'distance': 9.08, 'hangTime': 0.79, 'speed': 41.3}
        },
    }

    enriched = []
    for act in activities[:5]:
        act_id = act.get('activityId')
        if not act_id:
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
                    if score is not None:
                        # Distancia: u0 si es > 3m (campo directo), sino u4*0.0675
                        dist = round(hang_time, 2) if hang_time and hang_time > 3 else round(speed_raw * 0.0675, 2) if speed_raw else 0
                        # HangTime: u3 si < 2s (segundos), sino u0/10
                        ht = round(dist_raw, 3) if dist_raw and dist_raw < 2 else round(hang_time / 10, 3) if hang_time else 0
                        jump_records.append({
                            'score': round(score / 69.7, 0),
                            'hangTime': ht,
                            'speed': round(speed_raw * 0.3228, 1) if speed_raw else 0,
                            'distance': dist
                        })
                if jump_records:
                    best = max(jump_records, key=lambda j: j['score'])
                    # Solo sobreescribir si el nuevo salto es mayor en distancia
                    existing_jump = summary.get("bestJump")
                    if not existing_jump or best['distance'] > existing_jump.get('distance', 0):
                        summary["bestJump"] = best
                    print(f"     → {len(jump_records)} saltos, mejor: {best['distance']}m score {best['score']}")
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

    for act in activities[5:]:
        enriched.append({
            'activityId': act.get('activityId'),
            'activityName': act.get('activityName'),
            'startTimeLocal': act.get('startTimeLocal'),
            'distance': act.get('distance'),
            'elevationGain': act.get('elevationGain'),
            'mtbDynamics': {}
        })

    # Preservar actividades históricas del JSON anterior
    existing_ids = {a['activityId'] for a in enriched if a.get('activityId')}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                old_data = json.load(f)
            old_map = {a['activityId']: a for a in old_data.get('activities', []) if a.get('activityId')}
            # Proteger campos históricos corregidos manualmente
            for act in enriched:
                aid = act.get('activityId')
                if aid in old_map:
                    # Proteger bestJump si el histórico tiene mayor distancia
                    old_jump = old_map[aid].get('bestJump')
                    new_jump = act.get('bestJump')
                    if old_jump and (not new_jump or old_jump.get('distance', 0) > new_jump.get('distance', 0)):
                        act['bestJump'] = old_jump
                    # Preservar startTimeLocal histórico siempre
                    old_time = old_map[aid].get('startTimeLocal', '')
                    if old_time:
                        act['startTimeLocal'] = old_time
            # Agregar actividades históricas que no están en el sync actual
            for old_act in old_data.get('activities', []):
                if old_act.get('activityId') not in existing_ids:
                    enriched.append(old_act)
        except:
            pass

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
