Option Explicit
Dim fso, folder, fl, target, ws, content
Set fso = CreateObject("Scripting.FileSystemObject")
Set folder = fso.GetFolder(fso.GetParentFolderName(WScript.ScriptFullName))
target = ""
' v2.12.0 (r12 / legacy-1): try the explicit name main.py first -- it is the guard entry
' that performs crash auto-restart. Only if it is missing, fall back to the marker scan below
' (old packages / renamed entries). Do NOT reorder: both files carry the marker now, so the
' scan result depends on directory enumeration order and is not trustworthy.
' NOTE: keep this file pure ASCII. WSH decodes .vbs with the ANSI code page (CP936 here); a
' non-ASCII byte at end of line can swallow the newline and break the whole script (v2.12.0
' regression). tests/test_entry_chain_v2120.py pins it.
If fso.FileExists(folder.Path & "\main.py") Then
    target = "main.py"
End If
If target = "" Then
For Each fl In folder.Files
    If LCase(fso.GetExtensionName(fl.Name)) = "py" Then
        If InStr(1, fl.Name, "pet_", vbTextCompare) > 0 Then
            ' helper module, skip
        ElseIf Left(fl.Name, 1) = "_" Then
            ' helper/test, skip
        Else
            content = fso.OpenTextFile(fl.Path, 1, False).Read(4096)
            If InStr(1, content, "daifeiyu_pet_main", vbTextCompare) > 0 Then
                target = fl.Name
                Exit For
            End If
        End If
    End If
Next
End If
If target = "" Then
    MsgBox "Cannot locate the pet app script (entry marker not found).", vbCritical, "DaFeiYu Pet"
    WScript.Quit 1
End If
Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = folder.Path
' Clear host env vars so they cannot disturb the portable runtime resolving stdlib/site-packages
ws.Environment("Process")("PYTHONHOME") = ""
ws.Environment("Process")("PYTHONPATH") = ""
ws.Run """" & folder.Path & "\pythonw.exe"" """ & target & """", 0, False
