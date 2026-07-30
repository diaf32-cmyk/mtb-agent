#!/bin/bash
cd ~/Desktop/Garmin_Enduro

echo "🚵 Sincronizando datos Garmin..."
python3 garmin_sync.py

echo "📤 Subiendo a GitHub..."
git add garmin_data.json
git commit -m "sync manual garmin" 2>/dev/null || echo "Sin cambios nuevos"
git push

echo ""
echo "✅ ¡Listo! Recarga el agente en tu iPhone."
echo "Presiona cualquier tecla para cerrar..."
read -n 1
