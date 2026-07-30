#!/bin/bash
cd ~/Desktop/Garmin_Enduro
echo ""
echo "══════════════════════════════════"
echo "  MTB Agent · Sync Post Salida"
echo "══════════════════════════════════"
echo ""
echo "→ Sincronizando Garmin..."
python3 -B garmin_sync.py
if [ $? -ne 0 ]; then
    echo "  Error en sync. Presiona Enter..."
    read
    exit 1
fi
echo ""
echo "→ Subiendo a GitHub..."
git add garmin_data.json
git commit -m "sync post salida $(date '+%Y-%m-%d %H:%M')"
git push
echo ""
echo "  Listo! Abre https://mtb-agent.vercel.app/"
echo "  Presiona Enter para cerrar..."
read
