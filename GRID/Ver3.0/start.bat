@echo off
chcp 65001 >nul
echo.
echo  =============================================
echo   Lotto Grid AI Ver3.0  Web App
echo  =============================================
echo.

REM Python 경로 자동 탐색
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] python 을 찾을 수 없습니다. Python 3.10 이상을 설치해 주세요.
    pause
    exit /b 1
)

REM 의존성 확인 및 설치
python -c "import fastapi, uvicorn, pandas, openpyxl" >nul 2>&1
if %errorlevel% neq 0 (
    echo [설치] 필요한 패키지를 설치합니다...
    pip install -r requirements.txt
)

echo [시작] http://127.0.0.1:8000  에서 접속 가능합니다.
echo [종료] Ctrl+C 를 누르면 서버가 종료됩니다.
echo.

python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
pause
