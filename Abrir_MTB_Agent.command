#!/bin/bash
AGENT_DIR="$HOME/Desktop/Garmin_Enduro"
PORT=8765
lsof -ti:$PORT | xargs kill -9 2>/dev/null
cd "$AGENT_DIR"

echo "↻ Sincronizando Garmin..."
python3 "$AGENT_DIR/garmin_sync.py"

echo "↗ Iniciando servidor..."
python3 -m http.server $PORT &
sleep 1
open -a "Google Chrome" "http://localhost:$PORT/mtb_agent.html"
echo "MTB Agent corriendo. Cierra esta ventana para detener."
trap "kill %1 2>/dev/null; exit 0" INT
wait
