Dim WshShell, fso, scriptDir, scriptPath
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = WScript.ScriptFullName
scriptDir = fso.GetParentFolderName(scriptPath)
WshShell.CurrentDirectory = scriptDir
WshShell.Run "cmd /c node server.js > server.log 2>&1", 0, false
