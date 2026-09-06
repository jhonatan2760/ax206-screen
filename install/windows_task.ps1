# Registra o watcher como tarefa agendada no logon (sem janela, reinicia se cair).
# Alternativa a rodar pela suite: use UM dos dois, senao um mata o outro.
#   powershell -ExecutionPolicy Bypass -File install\windows_task.ps1
#   powershell -ExecutionPolicy Bypass -File install\windows_task.ps1 -Remove
param([switch]$Remove)

$Name = "AX206 Watcher"
$Dir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python.exe).Source -replace "python\.exe$", "pythonw.exe" }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "tarefa removida"
    exit 0
}

$Action = New-ScheduledTaskAction -Execute $Py -Argument "-m watcher" -WorkingDirectory $Dir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $Name
Write-Host "tarefa '$Name' registrada e iniciada: $Py -m watcher (em $Dir)"
Write-Host "status: python -m watcher --status   |   log: $Dir\watcher.log"
