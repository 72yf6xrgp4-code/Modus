# Crea (o actualiza) las tareas del vigia en el Programador de tareas de
# Windows. Cada tarea arranca el vigia al empezar su ventana y el vigia sale
# solo al terminarla (hora de Madrid = hora del portatil):
#
#   Modus Vigia L-X   lunes a miercoles  10:00 -> 16:00   (Grupo A 10:30)
#   Modus Vigia J-V   jueves y viernes   13:30 -> 03:00   (Grupo C 14:00, B 21:00)
#   Modus Vigia S     sabado             20:10 -> 03:00   (Final 20:40)
#
# El vigia NO para entre la jornada de las 14:00 y la de las 21:00.
#
# Uso (PowerShell, desde la carpeta del repo):
#   powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1
# Para borrarlas:
#   Get-ScheduledTask -TaskName "Modus Vigia*" | Unregister-ScheduledTask -Confirm:$false

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "No encuentro $Python. Crea antes el entorno virtual (ver README_VIGIA.md)."
}
if (-not (Test-Path (Join-Path $Repo ".env"))) {
    throw "Falta el archivo .env en $Repo (copia .env.example)."
}

# La tarea de la version anterior (una sola, 'Modus Vigia') ya no se usa
Get-ScheduledTask -TaskName "Modus Vigia" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$Tareas = @(
    @{ Nombre = "Modus Vigia L-X"; Dias = @("Monday", "Tuesday", "Wednesday"); Hora = "09:59"; Horas = 7 },
    @{ Nombre = "Modus Vigia J-V"; Dias = @("Thursday", "Friday");            Hora = "13:29"; Horas = 15 },
    @{ Nombre = "Modus Vigia S";   Dias = @("Saturday");                      Hora = "20:09"; Horas = 8 }
)

foreach ($t in $Tareas) {
    # Sin --hasta: el vigia espera a que empiece la ventana y sale al acabar
    $Accion = New-ScheduledTaskAction -Execute $Python -Argument "-m vigia" -WorkingDirectory $Repo
    $Disparador = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $t.Dias -At $t.Hora
    $Ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours $t.Horas)
    Register-ScheduledTask -TaskName $t.Nombre -Action $Accion -Trigger $Disparador `
        -Settings $Ajustes -Force `
        -Description "Vigia de cuotas minimas de Modus (avisos por ntfy). No usa Winamax ni apuesta." | Out-Null
    Write-Host ("Tarea '{0}': {1} a las {2} (limite {3} h)" -f $t.Nombre, ($t.Dias -join ", "), $t.Hora, $t.Horas)
}
Write-Host "Log: $Repo\logs\vigia.log"
