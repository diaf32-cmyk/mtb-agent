#!/bin/bash
export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:~/.local/bin

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR" || exit

echo "⚡ Iniciando Decodificador de Vuelo Factory (Modo Agresivo)..."
echo "---------------------------------------------------"

cat << 'EOF' > cerebro_vuelo.py
import os, glob, csv
from fitparse import FitFile

archivos_fit = glob.glob('*.fit') + glob.glob('*.FIT')
if not archivos_fit:
    print("❌ No se encontró ningún archivo .FIT en esta misma carpeta.")
    exit()

for ruta_fit in archivos_fit:
    print(f"🛸 Escaneando profundamente la telemetría de: {ruta_fit}...")
    archivo = FitFile(ruta_fit)
    saltos = []
    
    # Leemos TODOS los mensajes pieza por pieza
    for registro in archivo.get_messages():
        # Garmin registra los saltos bajo el nombre 'jump' o el número de hardware 285
        if registro.name == 'jump' or getattr(registro, 'mesg_num', None) == 285:
            saltos.append(registro.get_values())
            continue
            
        # Respaldo: Si el registro tiene la variable "hang_time", lo atrapamos sí o sí
        valores = registro.get_values()
        if 'hang_time' in valores:
            saltos.append(valores)
    
    if saltos:
        nombre_csv = ruta_fit.replace('.fit', '_saltos.csv').replace('.FIT', '_saltos.csv')
        # Extraemos todos los nombres de las columnas que encuentre
        encabezados = set()
        for s in saltos:
            encabezados.update(s.keys())
            
        with open(nombre_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(encabezados))
            writer.writeheader()
            writer.writerows(saltos)
        print(f"✅ ¡Éxito brutal! Se extrajeron {len(saltos)} saltos en: {nombre_csv}")
    else:
        print(f"⚠️ El motor escaneó todo pero los saltos están ocultos o vacíos en {ruta_fit}.")
EOF

python3 cerebro_vuelo.py
rm cerebro_vuelo.py

echo "---------------------------------------------------"
echo "🏁 ¡Desencriptación completada!"
open . 
echo "⚠️ Presiona ENTER para cerrar..."
read