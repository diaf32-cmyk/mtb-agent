#!/bin/bash
export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:~/.local/bin

echo "⚡ Extrayendo Telemetría Base..."
DIR="$HOME/Desktop/Garmin_Enduro"
mkdir -p "$DIR"
cd "$DIR" || exit

LAST_ID=$(garmin-connect activities list | grep -m 1 -oE '"activityId": [0-9]+' | grep -oE '[0-9]+')

if [ -z "$LAST_ID" ]; then
    echo "❌ Error de conexión."
    exit 1
fi

echo "✅ ID: $LAST_ID"
echo "🚀 Extrayendo JSON (Grit/Flow/HR)..."
garmin-connect activities get "$LAST_ID" > "ultima_salida_$LAST_ID.json"

echo "🏁 Listo. Archivo en el escritorio."
echo "Nota: Para telemetría de aire (Saltos), bajar el ZIP manualmente desde Garmin Connect Web."