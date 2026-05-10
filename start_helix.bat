@echo off
title HELIX AI SYSTEM

color 0A

echo =====================================
echo        HELIX AI - BOOT SEQUENCE
echo =====================================

cd /d D:\Helix

echo [1/3] Ativando ambiente virtual...
call .venv\Scripts\activate

echo [2/3] Inicializando backend...
start "Helix Backend" cmd /k uvicorn backend.main:app --reload

echo [3/3] Abrindo interface...
timeout /t 3 >nul
start "" http://127.0.0.1:8000/app

echo.
echo =====================================
echo Helix ONLINE
echo =====================================

pause