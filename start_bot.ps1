# Clear all __pycache__ to ensure fresh imports
Get-ChildItem -Path "C:\hvf_trader" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Start the bot with output redirection
Start-Process -FilePath "C:\hvf_trader\venv\Scripts\python.exe" -ArgumentList "C:\hvf_trader\main.py" -WorkingDirectory "C:\hvf_trader" -RedirectStandardOutput "C:\hvf_trader\logs\stdout.log" -RedirectStandardError "C:\hvf_trader\logs\stderr.log" -WindowStyle Hidden -PassThru | Select-Object Id
