// Remote access tools the download guard asks about. One line each:
//
//   TOOL(name shown, file name token, vendor download host)
//
// The token is lowercase letters and digits only. It is looked for in the
// file name with spaces, dots, dashes and underscores taken out, so
// "Quick Assist" and "quick_assist" both read quickassist. Leave it empty
// when the word is too common inside other names to trust (todesk is in
// photodesk): that tool is then recognised by its host alone.
//
// The host is the vendor's own server, for a setup file whose name says
// nothing. It matches itself and its subdomains only, never a longer name:
// anydesk.com.evil.example is not AnyDesk. Leave it empty when there is no
// server of their own (Quick Assist comes from the Microsoft Store).
//
// Add a tool by adding a line. components/boring/guards is the only place
// this list is read.

TOOL("AnyDesk", "anydesk", "anydesk.com")
TOOL("TeamViewer", "teamviewer", "teamviewer.com")
TOOL("Quick Assist", "quickassist", "")
TOOL("UltraViewer", "ultraviewer", "ultraviewer.net")
TOOL("RustDesk", "rustdesk", "rustdesk.com")
TOOL("ScreenConnect", "screenconnect", "screenconnect.com")
TOOL("ConnectWise", "connectwise", "connectwise.com")
TOOL("LogMeIn", "logmein", "logmein.com")
TOOL("Splashtop", "splashtop", "splashtop.com")
TOOL("Zoho Assist", "zohoassist", "assist.zoho.com")
TOOL("Supremo", "supremo", "supremocontrol.com")
TOOL("AeroAdmin", "aeroadmin", "aeroadmin.com")
TOOL("Ammyy", "ammyy", "ammyy.com")
TOOL("Chrome Remote Desktop", "chromeremotedesktop", "remotedesktop.google.com")
TOOL("Atera", "ateraagent", "atera.com")
TOOL("SimpleHelp", "simplehelp", "simple-help.com")
TOOL("HopToDesk", "hoptodesk", "hoptodesk.com")
TOOL("ToDesk", "", "todesk.com")
