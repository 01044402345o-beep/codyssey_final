' Runs serve_phoneme.bat with no window (used by the scheduled task).
' Log: phoneme-node\logs\server.log
Option Explicit
Dim sh, fso, here, bat
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
bat = here & "\serve_phoneme.bat"
If Not fso.FileExists(bat) Then
  WScript.Quit 1
End If
sh.CurrentDirectory = here
' 0 = hidden window, False = do not wait (the batch keeps running)
sh.Run "cmd.exe /c """ & bat & """ hidden", 0, False
