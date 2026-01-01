#!/bin/bash

echo "Starting Notes App..."
echo ""

if [ ! -f ".env" ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "Please update .env with your configuration"
    echo ""
fi

if [ ! -d "logs" ]; then
    echo "Creating logs directory..."
    mkdir logs
fi

echo "Starting application..."
python3 -m app.main
