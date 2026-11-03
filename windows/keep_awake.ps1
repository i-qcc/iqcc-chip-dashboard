# Keeps the kiosk laptop awake and unlocked while run_dashboard.bat is open.
# Exits on its own when the launcher window (its parent cmd.exe) is closed.
param([int]$IntervalSeconds = 50)

Add-Type -Namespace Win32 -Name Power -MemberDefinition @'
[DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
'@

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
[void][Win32.Power]::SetThreadExecutionState([uint32]2147483651)

$launcherPid = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
$shell = New-Object -ComObject WScript.Shell

while (Get-Process -Id $launcherPid -ErrorAction SilentlyContinue) {
    # F15 exists on no real keyboard and is ignored by apps, but it resets the
    # idle timer that drives the automatic lock / screensaver.
    $shell.SendKeys('{F15}')
    Start-Sleep -Seconds $IntervalSeconds
}
