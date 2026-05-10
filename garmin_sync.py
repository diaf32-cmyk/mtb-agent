#!/usr/bin/env python3
import json, subprocess, os, sys
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
                    EMAIL = line.split("=", 1)[1]
                elif line.startswith("GARMIN_PASSWORD="):
                    PASSWORD = line.split("=", 1)[1]

def get_client():
    from garminconnect import Garmin
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

def run(cmd):
    import subprocess
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

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

    enriched = []
    for act in activities[:5]:
        act_id = act.get('activityId')
        if not act_id:
            continue
        print(f"  → Detalle {act_id}...")
        try:
            import subprocess as sp2
            r2 = sp2.run(f"garmin-connect activities get {act_id}", shell=True, capture_output=True, text=True)
            try:
                detail = __import__("json").loads(r2.stdout)
            except:
                detail = {}
            # Get jump details via garth
            jump_details = []
            try:
                jr = client.garth.get("connectapi", f"/activity-service/activity/{act_id}/jumpDetails")
                jump_details = jr.json() if jr.status_code == 200 else []
            except:
                pass
            summary = extract_summary(detail)
            if jump_details:
                best = max(jump_details, key=lambda j: j.get("score", 0))
                summary["bestJump"] = {
                    "score": best.get("score"),
                    "distance": round(best.get("distance", 0), 2),
                    "hangTime": round(best.get("hangTime", 0), 3),
                    "speed": round(best.get("speed", 0) * 3.6, 1)
                }
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
