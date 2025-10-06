import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../services/auth_service.dart';
import '../../widgets/labeled_cupertino_field.dart';

class ForgotPasswordPage extends StatefulWidget {
  const ForgotPasswordPage({super.key});

  @override
  State<ForgotPasswordPage> createState() => _ForgotPasswordPageState();
}

class _ForgotPasswordPageState extends State<ForgotPasswordPage> {
  final TextEditingController _emailController = TextEditingController();
  bool _loading = false;
  String? _message;
  String? _emailError;

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final trimmed = _emailController.text.trim();
    setState(() {
      _emailError = trimmed.isEmpty ? 'Bitte E-Mail eingeben.' : null;
      _message = null;
    });
    if (_emailError != null) {
      return;
    }
    setState(() => _loading = true);
    final auth = context.read<AuthController>();
    final message = await auth.resetPassword(trimmed);
    if (!mounted) return;
    setState(() {
      _message = message;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = CupertinoTheme.of(context).textTheme;
    return CupertinoPageScaffold(
      backgroundColor: CupertinoColors.systemGroupedBackground,
      navigationBar: const CupertinoNavigationBar(
        middle: Text('Passwort zurücksetzen'),
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
                    'Wir senden Ihnen einen Link zum Zurücksetzen.',
                    style: textTheme.textStyle,
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
                  CupertinoButton.filled(
                    onPressed: _loading ? null : _submit,
                    child: _loading
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CupertinoActivityIndicator(),
                          )
                        : const Text('Link senden'),
                  ),
                  const SizedBox(height: 16),
                  if (_message != null)
                    Text(
                      _message!,
                      style: const TextStyle(
                        color: CupertinoColors.activeBlue,
                        fontSize: 13,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  const SizedBox(height: 16),
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
