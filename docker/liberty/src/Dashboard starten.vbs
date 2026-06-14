' Startet den White-House-Dashboard-Server OHNE schwarzes Konsolenfenster.
' Doppelklick genuegt - der Server laeuft danach im Hintergrund weiter,
' es bleibt kein Terminal-Fenster offen.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\V2026_Kofi_Twitch_Script_sanitized"
' window style 0 = unsichtbar, False = nicht warten
sh.Run """C:\Python314\pythonw.exe"" white_house_dashboard_server.py", 0, False
