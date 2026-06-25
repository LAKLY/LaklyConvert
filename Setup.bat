@echo off
chcp 65001 >nul
title LaklyConvert - Установка зависимостей
echo ========================================
echo   LaklyConvert - Установка зависимостей
echo ========================================
echo.

:: Проверка наличия Python
echo [1/5] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден!
    echo.
    echo Пожалуйста, установите Python с официального сайта:
    echo https://www.python.org/downloads/
    echo.
    echo После установки убедитесь, что Python добавлен в PATH.
    echo.
    pause
    exit /b 1
)
echo ✅ Python найден!
python --version
echo.

:: Проверка наличия pip
echo [2/5] Проверка pip...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo ❌ pip не найден!
    echo.
    echo Пожалуйста, установите pip:
    echo python -m ensurepip --upgrade
    echo.
    pause
    exit /b 1
)
echo ✅ pip найден!
echo.

:: Обновление pip
echo [3/5] Обновление pip...
python -m pip install --upgrade pip
echo.

:: Установка зависимостей
echo [4/5] Установка необходимых библиотек...
echo.

echo Установка numpy...
python -m pip install numpy
if errorlevel 1 (
    echo ❌ Ошибка при установке numpy
) else (
    echo ✅ numpy установлен
)
echo.

echo Установка Pillow...
python -m pip install Pillow
if errorlevel 1 (
    echo ❌ Ошибка при установке Pillow
) else (
    echo ✅ Pillow установлен
)
echo.

:: Опциональные библиотеки
echo Установка дополнительных библиотек (опционально)...
echo.

echo Установка scipy (для улучшенной обработки)...
python -m pip install scipy
if errorlevel 1 (
    echo ⚠️ scipy не установлен (опционально, можно установить позже)
) else (
    echo ✅ scipy установлен
)
echo.

echo Установка tkinterdnd2 (для Drag&Drop)...
python -m pip install tkinterdnd2
if errorlevel 1 (
    echo ⚠️ tkinterdnd2 не установлен (опционально, можно установить позже)
) else (
    echo ✅ tkinterdnd2 установлен
)
echo.

:: Проверка установленных библиотек
echo [5/5] Проверка установленных библиотек...
echo.

python -c "import numpy; print('✅ numpy:', numpy.__version__)" 2>nul || echo ❌ numpy не установлен
python -c "import PIL; print('✅ Pillow:', PIL.__version__)" 2>nul || echo ❌ Pillow не установлен
python -c "import scipy; print('✅ scipy:', scipy.__version__)" 2>nul || echo ⚠️ scipy не установлен (опционально)
python -c "import tkinterdnd2; print('✅ tkinterdnd2 установлен')" 2>nul || echo ⚠️ tkinterdnd2 не установлен (опционально)
echo.

echo ========================================
echo ✅ Установка завершена!
echo ========================================
echo.
echo Запустите программу через Ready.bat
echo.
echo Если программа не запускается, попробуйте:
echo   1. Перезапустите командную строку
echo   2. Установите недостающие библиотеки вручную:
echo      pip install numpy pillow scipy tkinterdnd2
echo.
pause