# Drawform Flutter App

Drawform ist eine desktopfokussierte Flutter-Anwendung, die ein lokal eingebettetes Python-Runtime über `python_ffi` anbindet. Das UI orientiert sich an modernen iOS-Designprinzipien, bietet einen Beispiel-Workflow für Export-Funktionalitäten und demonstriert ein leichtgewichtiges Authentifizierungs-Setup komplett in Flutter/Dart.

## Inhaltsverzeichnis

- [Architektur](#architektur)
- [Features](#features)
- [Systemvoraussetzungen](#systemvoraussetzungen)
- [Projektstruktur](#projektstruktur)
- [Lokale Entwicklung](#lokale-entwicklung)
  - [Abhängigkeiten installieren](#abhängigkeiten-installieren)
  - [App starten](#app-starten)
  - [Tests](#tests)
- [Python-Integration](#python-integration)
- [Konfiguration](#konfiguration)
- [Bekannte Einschränkungen](#bekannte-einschränkungen)

## Architektur

- **Flutter UI**: Strukturierte Navigation via `go_router`. Auf mobilen/niedrigen Breiten wird ein `CupertinoTabScaffold` eingesetzt, auf großen Displays eine Seitenleiste mit iOS-Look & Feel.
- **State**: Ein einfacher `AuthController` (ChangeNotifier) hält Authentifizierungsstatus, Beispiel-Credentials und Benutzerprofil-Daten im Speicher.
- **Python Bridge**: Über `python_ffi` wird ein eingebetteter Python-Interpreter gestartet. Der Service sorgt dafür, dass der Python-Skriptordner (`python/`) im `sys.path` liegt und stellt Wrapper für `exporter.py`-Funktionen bereit.

## Features

- iOS-inspiriertes, responsives UI für Projekte, Dashboard, Export und Profilverwaltung.
- Beispiel-Auth-Flow mit Login, Registrierung, Passwort-zurücksetzen und Profil-Sektion (Passwort/Bild ändern).
- Export-Workflow, der via Python FFI einen Dummy-Export auf Dateiebene ausführt.
- Zentraler Logout-Knopf sowohl in der Seitenleiste als auch im mobilen Navigationskopf.

## Systemvoraussetzungen

- Flutter SDK 3.10+ (getestet mit Flutter 3.35.x).
- Windows 10/11 für Desktop-Build (weitere Plattformen erfordern eigene Anpassungen).
- Visual Studio 2022 Build Tools (für Windows Desktop Builds).
- Optional: Android- oder Web-Toolchain, falls zusätzliche Targets benötigt werden.

## Projektstruktur

```
lib/
  main.dart                # Einstiegspunkt, Routing & Shell
  pages/                   # UI-Seiten (Projekte, Dashboard, Export, Auth, Profil)
  services/
    auth_service.dart      # In-Memory Authentifizierung & Profil-Verwaltung
    python_service.dart    # Python-Konnektor via python_ffi
  widgets/                 # Cupertino-Helfer-Komponenten
python/
  exporter.py              # Dummy-Funktion für Export, arbeitet auf Dateisystemebene
windows/                   # Desktop Runner
```

## Lokale Entwicklung

### Abhängigkeiten installieren

```powershell
C:\src\flutter\bin\flutter.bat pub get
```

### App starten

```powershell
C:\src\flutter\bin\flutter.bat run -d windows
```

> Tipp: Füge `C:\src\flutter\bin` permanent zu deinem `PATH` hinzu, damit du `flutter` ohne vollen Pfad aufrufen kannst.

### Tests

Aktuell existieren keine Widget-/Unit-Tests. Du kannst dennoch das Standardskript ausführen:

```powershell
C:\src\flutter\bin\flutter.bat test
```

## Python-Integration

- Die Python-Skripte liegen unter `python/` und werden beim Build als Flutter-Asset eingebunden (siehe `pubspec.yaml`).
- `python_service.dart` sorgt dafür, dass `Directory.current` plus `python/` in `sys.path` eingefügt wird. Der Aufruf `PythonService.exportToVector` lädt `exporter.py` und ruft `export_to_vector` mit Pfad + Zielformat auf.
- Die Beispielimplementierung kopiert die Eingabedatei lediglich in einen `exports/`-Unterordner und passt die Dateiendung an. Ersetze die Logik durch echte Export-Pipelines.

## Konfiguration

- **Launch-Konfiguration**: `.vscode/launch.json` setzt `PYTHONPATH`, so dass der Python-Interpreter lokal installierte Pakete sowie das Projektverzeichnis findet.
- **Theme**: Die Cupertino-Looks sind in `main.dart` über `ThemeData` und `CupertinoThemeData` parametrisiert. Passe Farben/Schatten dort an.
- **Navigation**: Neue Seiten oder Routen werden im `GoRouter` in `main.dart` ergänzt. Für geschützte Bereiche genügt die Anpassung des Redirect-Blocks.

## Bekannte Einschränkungen

- Authentifizierung ist rein In-Memory; nach App-Neustart existieren keine Benutzer.
- `python_ffi` wird auf dem Web-Target nicht unterstützt. Dort sollte `PythonFfi.initialize()` fehlschlagen und in `main.dart` abgefangen werden.
- Abhängigkeiten (z.?B. `go_router`) sind auf ältere Minor-Versionen gepinnt. Prüfe vor einem Upgrade API-Änderungen und passe Code an.
- Kein automatisiertes Testing/CI vorhanden.
