#!/usr/bin/env bash
# run.sh — make executable (chmod +x run.sh)
REPO_DIR="/home/youruser/yourrepo"   # EDIT this path
cd "$REPO_DIR" || exit 1
git pull origin main || true
# activate venv
source venv/bin/activate
exec python bot.py
