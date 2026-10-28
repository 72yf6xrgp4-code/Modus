# Crea (o actualiza) la tarea del vigia en el Programador de tareas de
# Windows: una sola tarea, "Modus Vigia", que arranca el vigia
#
#   - al empezar cada ventana (hora de Madrid = hora del portatil):
#       lunes a miercoles  09:59 -> 16:00   (Grupo A 10:30)
#       jueves y viernes   13:29 -> 03:00   (Grupo C 14:00, B 21:00)
#       sabado             20:09 -> 03:00   (Final 20:40)
#   - al iniciar sesion en Windows (al encender el PC)
#   - al desbloquear el PC (al volver de suspension)
#
# Dentro de la ventana el vigia avisa y apunta resultados hasta que termina;
# fuera de ella solo apunta los resultados pendientes y sale. Asi, al
# encender el PC se pone al dia solo. Si ya hay un vigia en marcha, no se
# arranca otro. El vigia NO para entre la jornada de las 14:00 y la de las
# 21:00.
#
# Uso (PowerShell, desde la carpeta del repo):
#   powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1
# Si dice "Acceso denegado", abre PowerShell como administrador y repitelo.
# Para borrarla:
#   Get-ScheduledTask -TaskName "Modus Vigia*" | Unregister-ScheduledTask -Confirm:$false

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "No encuentro $Python. Crea antes el entorno virtual (ver README_VIGIA.md)."
}
if (-not (Test-Path (Join-Path $Repo ".env"))) {
    throw "Falta el archivo .env en $Repo (copia .env.example)."
}

# Quitar las tareas anteriores ('Modus Vigia', 'Modus Vigia L-X', 'J-V', 'S')
Get-ScheduledTask -TaskName "Modus Vigia*" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$Usuario = "$env:USERDOMAIN\$env:USERNAME"

$Disparadores = @(
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday -At "09:59"),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday, Friday -At "13:29"),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "20:09")
)
# Al iniciar sesion (con un minuto de margen para que haya red)
$AlEntrar = New-ScheduledTaskTrigger -AtLogOn -User $Usuario
$AlEntrar.Delay = "PT1M"
$Disparadores += $AlEntrar
# Al desbloquear (StateChange 8 = SessionUnlock)
$Clase = Get-CimClass -Namespace "Root/Microsoft/Windows/TaskScheduler" `
    -ClassName MSFT_TaskSessionStateChangeTrigger
$AlDesbloquear = New-CimInstance -CimClass $Clase -ClientOnly
$AlDesbloquear.StateChange = 8
$AlDesbloquear.UserId = $Usuario
$AlDesbloquear.Delay = "PT30S"
$Disparadores += $AlDesbloquear

# Sin --hasta: el vigia espera a que empiece la ventana y sale al acabar
$Accion = New-ScheduledTaskAction -Execute $Python -Argument "-m vigia" -WorkingDirectory $Repo
$Ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 16)
Register-ScheduledTask -TaskName "Modus Vigia" -Action $Accion -Trigger $Disparadores `
    -Settings $Ajustes -Force `
    -Description "Vigia de cuotas minimas de Modus (avisos por ntfy y resultados). No usa Winamax ni apuesta." | Out-Null

Write-Host "Tarea 'Modus Vigia' creada:"
Write-Host "  L-X 09:59, J-V 13:29, S 20:09, al iniciar sesion y al desbloquear"
Write-Host "Log: $Repo\logs\vigia.log"
