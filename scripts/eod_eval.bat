@echo off
REM End-of-day per-strategy evaluation — appends a dated 90-day report to a
REM rolling log. Scheduled to run weekdays after market close (see AlgoEODEval).
cd /d D:\repos\Algotime
set PYTHONIOENCODING=utf-8
>> logs\algo_eval_daily.log echo.
>> logs\algo_eval_daily.log echo ================= %date% %time% =================
".venv\Scripts\python.exe" scripts\algo_eval.py --days 90 >> logs\algo_eval_daily.log 2>&1
