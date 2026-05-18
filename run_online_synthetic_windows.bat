@echo off
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python scripts\run_online_synthetic.py
