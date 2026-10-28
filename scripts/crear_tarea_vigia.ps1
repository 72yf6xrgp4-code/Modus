# Crea (o actualiza) la tarea "Modus Vigia" en el Programador de tareas de
# Windows: de lunes a sabado a las 11:55 arranca el vigia, que espera a la
# hora de --desde y para solo cuando no quedan partidos de Modus.
#
# Uso (PowerShell, desde la carpeta del repo):
#   powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1 -Hora 10:15 -Desde 10:20
#
# Para borrarla:  Unregister-ScheduledTask -TaskName "Modus Vigia"

param(
    [string]$Hora = "11:55",
    [string]$Desde = "12:00",
    [string]$Extra = ""
)

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "No encuentro $Python. Crea antes el entorno virtual (ver README_VIGIA.md)."
}
if (-not (Test-Path (Join-Path $Repo ".env"))) {
    throw "Falta el archivo .env en $Repo (copia .env.example)."
}

$Argumentos = "-m vigia --desde $Desde $Extra".Trim()
$Accion = New-ScheduledTaskAction -Execute $Python -Argument $Argumentos -WorkingDirectory $Repo
$Disparador = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday, Saturday -At $Hora
$Ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 16)

Register-ScheduledTask -TaskName "Modus Vigia" -Action $Accion -Trigger $Disparador `
    -Settings $Ajustes -Force `
    -Description "Vigia de value bets de Modus (Winamax -> ntfy). Solo lee; nunca apuesta."

Write-Host "Tarea 'Modus Vigia' creada: L-S a las $Hora -> python $Argumentos"
Write-Host "Log: $Repo\logs\vigia.log"
