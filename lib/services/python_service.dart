import 'dart:io';
import 'package:python_ffi/python_ffi.dart';

/// Wrapper für exporter.py → verlangt in Dart 3 ein Klassen-Modifizierer,
/// weil die Basisklasse `PythonModule` als `base` markiert ist.
base class ExporterModule extends PythonModule {
  ExporterModule.from(super.module) : super.from();

  String exportToVector(String inputPath, String outputFormat) {
    final fn = getFunction('export_to_vector');
    final result = fn.call(<Object?>[inputPath, outputFormat]);
    return result as String;
  }
}

/// Eigener Wrapper für das eingebaute `sys`-Modul, damit wir keinen
/// Konstruktor-Tear-off auf einer abstrakten Klasse verwenden müssen.
base class SysModule extends PythonModule {
  SysModule.from(super.module) : super.from();
  List<dynamic> get path => getAttribute<List<dynamic>>('path');
}

class PythonService {
  static final PythonService instance = PythonService();
  void _ensureSysPath(String scriptDir) {
    final sys = PythonModule.import<SysModule>('sys', SysModule.from);
    final p = sys.path;
    if (!p.contains(scriptDir)) {
      p.add(scriptDir);
    }
  }

  Future<String> export(String inputPath, String format, {String? scriptDir}) async {
    final defaultScriptDir =
        '${Directory.current.path}${Platform.pathSeparator}python';
    _ensureSysPath(defaultScriptDir);

    if (scriptDir != null && scriptDir != defaultScriptDir) {
      _ensureSysPath(scriptDir);
    }

    final exporter =
        PythonModule.import<ExporterModule>('exporter', ExporterModule.from);
    return exporter.exportToVector(inputPath, format);
  }

  // Komfort-Alias, damit Aufrufer wie export_page.dart funktionieren
  Future<String> exportToVector(String inputPath, String format,
      {String? scriptDir}) {
    return export(inputPath, format, scriptDir: scriptDir);
  }

}
