Option Explicit
Dim fso, folder, fl, target, ws, content
Set fso = CreateObject("Scripting.FileSystemObject")
Set folder = fso.GetFolder(fso.GetParentFolderName(WScript.ScriptFullName))
target = ""
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
If target = "" Then
    MsgBox "Cannot locate the pet app script (entry marker not found).", vbCritical, "DaFeiYu Pet"
    WScript.Quit 1
End If
Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = folder.Path
' 清理宿主环境变量，防止干扰便携运行时解析 stdlib/site-packages
ws.Environment("Process")("PYTHONHOME") = ""
ws.Environment("Process")("PYTHONPATH") = ""
ws.Run """" & folder.Path & "\pythonw.exe"" """ & target & """", 0, False
