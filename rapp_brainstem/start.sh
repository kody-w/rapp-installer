#!/bin/bash
set -e
cd "$(dirname "$0")"

# Install deps if needed
if ! python3 -c "import flask, requests, dotenv" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt -q
fi

# Create .env from example if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — edit it if needed (or just run gh auth login)"
fi

python3 brainstem.py
