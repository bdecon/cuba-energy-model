@echo off
echo.
echo  Cuba Energy System Model - Setup
echo  =================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    echo.
    echo  Install Python from https://www.python.org/downloads/
    echo  IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo  Found Python:
python --version
echo.

:: Create virtual environment
if not exist "venv" (
    echo  Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  Done.
) else (
    echo  Virtual environment already exists.
)
echo.

:: Activate and install
echo  Installing dependencies (this may take a minute)...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: Package installation failed.
    echo  Try running: venv\Scripts\activate.bat
    echo  Then:        pip install -r requirements.txt
    echo  to see the full error.
    pause
    exit /b 1
)

echo.
echo.
echo  Setup complete! To run the model:
echo.
echo    venv\Scripts\activate.bat
echo    python cuba_model.py --scenario 6
echo.
echo  Scenario 6 is the 100%% renewable cost-optimal scenario.
echo  Use --scenario 4 for the unconstrained cost-optimal, or
echo  run without --scenario to run all 6.
echo.
pause
