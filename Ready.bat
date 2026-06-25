@echo off
chcp 65001 >nul
title LaklyConvert

:: Проверяем, есть ли флаг пропуска проверки
if exist ".skip_check" (
    goto :run
)

:: Если флага нет, выполняем полную проверку
echo ========================================
echo   LaklyConvert - Image to Braille Converter
echo ========================================
echo.
echo [Проверка зависимостей...]
echo.

:: Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    cls
    echo ========================================
    echo   ❌ Python не найден!
    echo ========================================
    echo.
    echo Пожалуйста, установите Python:
    echo https://www.python.org/downloads/
    echo.
    echo После установки запустите Setup.bat
    echo.
    pause
    exit /b 1
)

:: Проверка библиотек
set MISSING=0
python -c "import numpy" >nul 2>&1
if errorlevel 1 ( set MISSING=1 )
python -c "import PIL" >nul 2>&1
if errorlevel 1 ( set MISSING=1 )

if %MISSING% EQU 1 (
    cls
    echo ========================================
    echo   ❌ Отсутствуют зависимости!
    echo ========================================
    echo.
    echo Запустите Setup.bat для установки библиотек.
    echo.
    echo Или установите вручную:
    echo   pip install numpy pillow
    echo.
    pause
    exit /b 1
)

:: Проверка наличия Main.py
if not exist "Main.py" (
    cls
    echo ========================================
    echo   ❌ Файл Main.py не найден!
    echo ========================================
    echo.
    echo Убедитесь, что Main.py находится в этой папке.
    echo.
    pause
    exit /b 1
)

:: Спрашиваем про создание флага пропуска проверки
cls
echo ========================================
echo   LaklyConvert - Настройка запуска
echo ========================================
echo.
echo Все проверки пройдены успешно! ✅
echo.
echo Вы можете пропускать проверку при следующих запусках
echo для более быстрого старта программы.
echo.
choice /C YN /M "Создать ярлык для быстрого запуска? "
if errorlevel 2 (
    echo.
    echo Хорошо, проверка будет выполняться при каждом запуске.
) else (
    echo.
    echo ✅ Создаём файл .skip_check...
    echo. > ".skip_check"
    echo Теперь при запуске Ready.bat проверка будет пропускаться.
    echo Для отключения быстрого запуска удалите файл .skip_check
)
echo.
echo Запуск программы...
timeout /t 1 /nobreak >nul

:run
:: Запуск программы с автоматическим закрытием батника
start /b "" python Main.py

:: Ждём 2 секунды, чтобы программа успела запуститься
timeout /t 2 /nobreak >nul

:: Закрываем батник без лишних сообщений
exit /b 0