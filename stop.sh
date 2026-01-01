#!/bin/bash
sleep 1 && ps aux | grep uvicorn | grep -v grep || echo "Server stopped successfully."

