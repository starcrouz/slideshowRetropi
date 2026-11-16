# S'assurer que le script s'exécute dans le dossier du script
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$vbsPath = Join-Path $scriptPath "run_server_silent.vbs"

if (-not (Test-Path $vbsPath)) {
    Write-Error "Fichier run_server_silent.vbs introuvable dans $scriptPath."
    exit 1
}

# Nom de la tâche
$taskName = "BartopServer"

# 1. Action : Lancer le script VBS via wscript.exe (aucun affichage de console)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""

# 2. Déclencheur : Au démarrage de la session utilisateur
$trigger = New-ScheduledTaskTrigger -AtLogOn

# 3. Paramètres : Autoriser le lancement sur batterie, relancer en cas d'échec
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit 0

# 4. Enregistrement de la tâche pour l'utilisateur actuel
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop
    Write-Host "La tâche planifiée '$taskName' a été créée avec succès !" -ForegroundColor Green
    Write-Host "Le serveur server.js démarrera désormais automatiquement en arrière-plan à chaque ouverture de session." -ForegroundColor Cyan
    Write-Host "Démarrage immédiat du serveur..." -ForegroundColor Yellow
    Start-ScheduledTask -TaskName $taskName
} catch {
    Write-Error "Échec de la création de la tâche planifiée. Assurez-vous de lancer PowerShell en tant qu'Administrateur."
}
