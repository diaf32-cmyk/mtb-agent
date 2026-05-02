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

OUTPUT_DIR = os.path.expanduser("~/Desktop/Garmin_Enduro")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "garmin_data.json")

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

def get_activities(count=20):
    print(f"  → Obteniendo últimas {count} actividades...")
    raw = run(f"garmin-connect activities list --limit {count} 2>/dev/null || garmin-connect activities list")
    if not raw:
        return []
    try:
        activities = json.loads(raw)
        return activities if isinstance(activities, list) else []
    except:
        return []

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

    # Get activity list
    activities = get_activities(20)
    if not activities:
        print("  ✗ No se pudieron obtener actividades")
        print("  Verifica que garmin-connect esté configurado")
        sys.exit(1)

    print(f"  ✓ {len(activities)} actividades encontradas\n")

    # Get detail for last 5 activities (to have MTB dynamics)
    enriched = []
    for act in activities[:5]:
        act_id = act.get('activityId')
        if not act_id:
            continue
        detail = get_activity_detail(act_id)
        if detail:
            enriched.append(extract_summary(detail))
        else:
            # Use basic info from list
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

    # Add basic info for remaining activities
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

    # Build output
    output = {
        'lastSync': datetime.now().isoformat(),
        'activities': enriched,
        'latestDynamics': enriched[0].get('mtbDynamics', {}) if enriched else {}
    }

    # Save JSON
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n  ✓ Datos guardados en garmin_data.json")

    # Print latest MTB Dynamics
    dyn = output['latestDynamics']
    if dyn:
        print(f"\n  ═══ MTB DYNAMICS (última salida) ═══")
        print(f"  Grit:        {dyn.get('grit', '—'):.1f}" if dyn.get('grit') else "  Grit:        —")
        print(f"  Flow:        {dyn.get('avgFlow', '—'):.2f}" if dyn.get('avgFlow') else "  Flow:        —")
        print(f"  Jumps:       {dyn.get('jumpCount', '—')}")
        print(f"  Batería uso: {dyn.get('eBikeBatteryUsage', '—')}%")
        print(f"  Batería rest:{dyn.get('eBikeBatteryRemaining', '—')}%")
        print(f"  Trail Load:  {dyn.get('activityTrainingLoad', '—'):.1f}" if dyn.get('activityTrainingLoad') else "  Trail Load:  —")
        print(f"  Training FX: {dyn.get('trainingEffectLabel', '—')}")

    print("\n══════════════════════════════════\n")

if __name__ == '__main__':
    main()
