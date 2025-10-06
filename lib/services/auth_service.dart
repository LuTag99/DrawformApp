import 'package:flutter/foundation.dart';

/// Einfache, rein lokale Authentifizierungs-Logik.
///
/// Die Implementierung dient nur als Platzhalter: Daten werden im Speicher
/// gehalten und gehen beim Neustart der App verloren. Für ein echtes Projekt
/// sollte sie durch einen sicheren Backend-Service ersetzt werden.
class AuthController extends ChangeNotifier {
  bool _isAuthenticated = false;
  String? _email;
  String? _password;
  String? _avatarUrl;

  bool get isAuthenticated => _isAuthenticated;
  String? get email => _email;
  String? get avatarUrl => _avatarUrl;

  Future<String?> login(String email, String password) async {
    if (_email == null || _password == null) {
      return 'Es ist kein Benutzer registriert.';
    }
    if (email.trim().isEmpty || password.isEmpty) {
      return 'Bitte geben Sie E-Mail und Passwort ein.';
    }
    if (_email != email.trim() || _password != password) {
      return 'Ungültige Anmeldedaten.';
    }
    _isAuthenticated = true;
    notifyListeners();
    return null;
  }

  Future<String?> register(String email, String password) async {
    final trimmedEmail = email.trim();
    if (trimmedEmail.isEmpty) {
      return 'Die E-Mail darf nicht leer sein.';
    }
    if (password.length < 6) {
      return 'Das Passwort muss mindestens 6 Zeichen lang sein.';
    }
    _email = trimmedEmail;
    _password = password;
    _isAuthenticated = true;
    notifyListeners();
    return null;
  }

  Future<String?> resetPassword(String email) async {
    if (_email == null) {
      return 'Es ist kein Benutzer registriert.';
    }
    if (_email != email.trim()) {
      return 'Diese E-Mail ist unbekannt.';
    }
    // In einer echten App würde hier eine Mail versendet werden.
    return 'Wir haben Ihnen eine E-Mail zum Zurücksetzen gesendet.';
  }

  Future<String?> updatePassword(
      {required String currentPassword, required String newPassword}) async {
    if (!_isAuthenticated || _password == null) {
      return 'Sie sind nicht angemeldet.';
    }
    if (_password != currentPassword) {
      return 'Das aktuelle Passwort ist falsch.';
    }
    if (newPassword.length < 6) {
      return 'Das neue Passwort muss mindestens 6 Zeichen haben.';
    }
    _password = newPassword;
    return null;
  }

  void updateAvatar(String? url) {
    _avatarUrl = url?.trim().isEmpty ?? true ? null : url?.trim();
    notifyListeners();
  }

  void logout() {
    _isAuthenticated = false;
    notifyListeners();
  }
}
