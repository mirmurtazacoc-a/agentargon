#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "===> [1/3] Upgrading pip & installing Python requirements..."
pip install --upgrade pip
pip install -r requirements.txt

echo "===> [2/3] Building React Frontend..."
cd frontend
npm install
npm run build
cd ..

echo "===> [3/3] Build complete! Frontend dist ready for FastAPI static mount."
