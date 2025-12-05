#!/bin/bash
set -e

# Crear directorio temporal si no existe
mkdir -p /tmp/downloads

# Instalar dependencias si es necesario
# (Render ya ejecuta pip install -r requirements.txt en build)

# Iniciar la aplicación
exec gunicorn --bind 0.0.0.0:$PORT server:app --workers 2 --threads 4 --timeout 300
