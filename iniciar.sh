#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
fi

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual con python3..."
    if python3 -m venv venv 2>/dev/null; then
        source venv/bin/activate
        pip install -r requirements.txt
    else
        echo "Instalando dependencias directamente con pip3..."
        python3 -m pip install --user --break-system-packages -r requirements.txt || python3 -m pip install --user -r requirements.txt
    fi
else
    source venv/bin/activate
fi

echo "Iniciando servidor Taqueria POS (Auxiliar, Cocina y Admin) en http://localhost:8000 ..."
python3 -m app.server
