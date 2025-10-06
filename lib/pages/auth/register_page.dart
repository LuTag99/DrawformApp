import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../services/auth_service.dart';
import '../../widgets/labeled_cupertino_field.dart';

class RegisterPage extends StatefulWidget {
  const RegisterPage({super.key});

  @override
  State<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends State<RegisterPage> {
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  final TextEditingController _confirmController = TextEditingController();
  bool _loading = false;
  String? _error;
  String? _emailError;
  String? _passwordError;
  String? _confirmError;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final trimmedEmail = _emailController.text.trim();
    final password = _passwordController.text;
    final confirm = _confirmController.text;

    setState(() {
      _emailError =
          trimmedEmail.isEmpty ? 'Bitte E-Mail eingeben.' : null;
      _passwordError =
          password.length < 6 ? 'Mindestens 6 Zeichen erforderlich.' : null;
      _confirmError =
          confirm != password ? 'Passwörter stimmen nicht überein.' : null;
      _error = null;
    });

    if (_emailError != null || _passwordError != null || _confirmError != null) {
      return;
    }

    setState(() => _loading = true);
    final auth = context.read<AuthController>();
    final error = await auth.register(trimmedEmail, password);
    if (!mounted) return;
    if (error != null) {
      setState(() {
        _error = error;
        _loading = false;
      });
      return;
    }
    setState(() => _loading = false);
    context.go('/');
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = CupertinoTheme.of(context).textTheme;
    return CupertinoPageScaffold(
      backgroundColor: CupertinoColors.systemGroupedBackground,
      navigationBar: const CupertinoNavigationBar(
        middle: Text('Registrieren'),
      ),
      child: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Konto anlegen',
                    style: textTheme.navTitleTextStyle,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  LabeledCupertinoField(
                    label: 'E-Mail',
                    controller: _emailController,
                    keyboardType: TextInputType.emailAddress,
                    errorText: _emailError,
                    onChanged: (_) {
                      if (_emailError != null) {
                        setState(() => _emailError = null);
                      }
                    },
                  ),
                  const SizedBox(height: 16),
                  LabeledCupertinoField(
                    label: 'Passwort',
                    controller: _passwordController,
                    obscureText: true,
                    errorText: _passwordError,
                    onChanged: (_) {
                      if (_passwordError != null) {
                        setState(() => _passwordError = null);
                      }
                    },
                  ),
                  const SizedBox(height: 16),
                  LabeledCupertinoField(
                    label: 'Passwort bestätigen',
                    controller: _confirmController,
                    obscureText: true,
                    errorText: _confirmError,
                    onChanged: (_) {
                      if (_confirmError != null) {
                        setState(() => _confirmError = null);
                      }
                    },
                  ),
                  const SizedBox(height: 16),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        _error!,
                        style: const TextStyle(
                          color: CupertinoColors.destructiveRed,
                          fontSize: 13,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  CupertinoButton.filled(
                    onPressed: _loading ? null : _submit,
                    child: _loading
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CupertinoActivityIndicator(),
                          )
                        : const Text('Registrieren'),
                  ),
                  const SizedBox(height: 8),
                  CupertinoButton(
                    onPressed: () => context.go('/login'),
                    child: const Text('Zurück zur Anmeldung'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
