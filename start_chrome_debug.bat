@echo off
echo Closing existing Chrome instances...
taskkill /F /IM chrome.exe >nul 2>&1

echo Starting Chrome in Remote Debugging Mode (Port 9222)...
echo Please keep this window open or minimized.

set "USER_DATA=d:\my_program\Playlist\ChromeProfile"

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USER_DATA%" --incognito --disable-blink-features=AutomationControlled --disable-infobars --disable-extensions --disable-plugins-discovery --profile-directory=Default --start-maximized --disable-notifications --disable-background-networking --disable-sync --metrics-recording-only --disable-default-apps --no-first-run --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USER_DATA%" --incognito --disable-blink-features=AutomationControlled --disable-infobars --disable-extensions --disable-plugins-discovery --profile-directory=Default --start-maximized --disable-notifications --disable-background-networking --disable-sync --metrics-recording-only --disable-default-apps --no-first-run --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    start "" "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USER_DATA%" --incognito --disable-blink-features=AutomationControlled --disable-infobars --disable-extensions --disable-plugins-discovery --profile-directory=Default --start-maximized --disable-notifications --disable-background-networking --disable-sync --metrics-recording-only --disable-default-apps --no-first-run --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
) else (
    echo Chrome executable not found in standard locations.
    echo Please run the following command manually in your terminal:
    echo chrome.exe --remote-debugging-port=9222 --user-data-dir="%USER_DATA%" --incognito --disable-blink-features=AutomationControlled --disable-infobars --disable-extensions --disable-plugins-discovery --profile-directory=Default --start-maximized --disable-notifications --disable-background-networking --disable-sync --metrics-recording-only --disable-default-apps --no-first-run --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
    pause
)

echo Chrome started. Please navigate to Tidal.com and log in.
