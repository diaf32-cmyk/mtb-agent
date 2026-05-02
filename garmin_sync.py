#!/usr/bin/env python3
"""
MTB Agent · Garmin Sync
Extrae actividades y MTB Dynamics via garmin-connect CLI
Genera garmin_data.json para el dashboard
"""

import json
import subprocess
import os
import sys
from datetime import datetime

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "garmin_data.json")

# Credenciales desde variables de entorno o .env
EMAIL = os.getenv("GARMIN_EMAIL")
PASSWORD = os.getenv("GARMIN_PASSWORD")

# Si no hay env vars, intentar leer desde .env local
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

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

def get_client():
    """Get authenticated Garmin client"""
    try:
        from garminconnect import Garmin
        client = Garmin(EMAIL, PASSWORD)
        client.login()
        return client
    except Exception as e:
        print(f"  ✗ Error conectando a Garmin: {e}")
        return None

def get_activities(count=20):
    print(f"  → Obteniendo últimas {count} actividades...")
    # Try garminconnect Python library first
    client = get_client()
    if client:
        try:
            activities = client.get_activities(0, count)
            return activities, client
        except Exception as e:
            print(f"  ✗ Error obteniendo actividades: {e}")

    # Fallback to CLI
    raw = run(f"garmin-connect activities list --limit {count} 2>/dev/null || garmin-connect activities list")
    if not raw:
        return [], None
    try:
        activities = json.loads(raw)
        return (activities if isinstance(activities, list) else []), None
    except:
        return [], None

def get_activity_detail_api(client, activity_id):
    """Get activity detail via Python API"""
    try:
        return client.get_activity(activity_id)
    except:
        return {}

def get_activity_detail(activity_id):
    print(f"  → Detalle actividad {activity_id}...")
    raw = run(f"garmin-connect activities get {activity_id}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except:
        return {}

def extract_mtb_dynamics(detail):
    """Extrae MTB Dynamics desde summaryDTO"""
    summary = detail.get('summaryDTO', {})
    metadata = detail.get('metadataDTO', {})

    # Battery info
    battery_usage = metadata.get('eBikeBatteryUsage', None)
    battery_remaining = metadata.get('eBikeBatteryRemaining', None)

    return {
        'grit': summary.get('grit'),
        'avgFlow': summary.get('avgFlow'),
        'jumpCount': summary.get('jumpCount'),
        'waterEstimated': summary.get('waterEstimated'),
        'avgRespirationRate': summary.get('avgRespirationRate'),
        'minRespirationRate': summary.get('minRespirationRate'),
        'maxRespirationRate': summary.get('maxRespirationRate'),
        'trainingEffect': summary.get('trainingEffect'),
        'anaerobicTrainingEffect': summary.get('anaerobicTrainingEffect'),
        'trainingEffectLabel': summary.get('trainingEffectLabel'),
        'activityTrainingLoad': summary.get('activityTrainingLoad'),
        'avgEbikeAssistLevelPercent': summary.get('avgEbikeAssistLevelPercent'),
        'eBikeBatteryUsage': battery_usage,
        'eBikeBatteryRemaining': battery_remaining,
        'locationName': detail.get('locationName'),
    }

def extract_summary(detail):
    """Extrae resumen de actividad"""
    summary = detail.get('summaryDTO', {})
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
        'maxElevation': summary.get('maxElevation'),
        'minElevation': summary.get('minElevation'),
        'locationName': detail.get('locationName'),
        'mtbDynamics': extract_mtb_dynamics(detail)
    }

def main():
    print("\n══════════════════════════════════")
    print("  MTB Agent · Garmin Sync")
    print("══════════════════════════════════\n")

    if not EMAIL or not PASSWORD:
        print("  ✗ Credenciales no encontradas")
        print("  Configura GARMIN_EMAIL y GARMIN_PASSWORD")
        sys.exit(1)

    print(f"  → Usuario: {EMAIL}")

    # Get activity list
    activities, client = get_activities(20)
    if not activities:
        print("  ✗ No se pudieron obtener actividades")
        sys.exit(1)

    print(f"  ✓ {len(activities)} actividades encontradas\n")

    # Get detail for last 5 activities
    enriched = []
    for act in activities[:5]:
        act_id = act.get('activityId')
        if not act_id:
            continue
        print(f"  → Detalle actividad {act_id}...")
        if client:
            detail = get_activity_detail_api(client, act_id)
        else:
            detail = get_activity_detail(act_id)

        if detail:
            enriched.append(extract_summary(detail))
        else:
            enriched.append({
                'activityId': act_id,
                'activityName': act.get('activityName'),
                'startTimeLocal': act.get('startTimeLocal'),
                'distance': act.get('distance'),
                'elevationGain': act.get('elevationGain'),
                'avgHR': act.get('averageHR'),
                'duration': act.get('duration'),
                'mtbDynamics': {}
            })

    # Add basic info for remaining
    for act in activities[5:]:
        enriched.append({
            'activityId': act.get('activityId'),
            'activityName': act.get('activityName'),
            'startTimeLocal': act.get('startTimeLocal'),
            'distance': act.get('distance'),
            'elevationGain': act.get('elevationGain'),
            'avgHR': act.get('averageHR'),
            'duration': act.get('duration'),
            'mtbDynamics': {}
        })

    output = {
        'lastSync': datetime.now().isoformat(),
        'activities': enriched,
        'latestDynamics': enriched[0].get('mtbDynamics', {}) if enriched else {}
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n  ✓ Datos guardados en garmin_data.json")

    dyn = output['latestDynamics']
    if dyn:
        print(f"\n  ═══ MTB DYNAMICS (última salida) ═══")
        print(f"  Grit:        {dyn.get('grit', '—'):.1f}" if dyn.get('grit') else "  Grit:        —")
        print(f"  Flow:        {dyn.get('avgFlow', '—'):.2f}" if dyn.get('avgFlow') else "  Flow:        —")
        print(f"  Jumps:       {dyn.get('jumpCount', '—')}")
        print(f"  Batería uso: {dyn.get('eBikeBatteryUsage', '—')}%")
        print(f"  Training FX: {dyn.get('trainingEffectLabel', '—')}")

    print("\n══════════════════════════════════\n")

if __name__ == '__main__':
    main()
