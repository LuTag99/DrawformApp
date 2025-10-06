import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../services/auth_service.dart';
import '../../widgets/labeled_cupertino_field.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  bool _loading = false;
  String? _error;
  String? _emailError;
  String? _passwordError;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _emailError =
          _emailController.text.trim().isEmpty ? 'Bitte E-Mail eingeben.' : null;
      _passwordError =
          _passwordController.text.isEmpty ? 'Bitte Passwort eingeben.' : null;
      _error = null;
    });

    if (_emailError != null || _passwordError != null) {
      return;
    }

    setState(() => _loading = true);
    final auth = context.read<AuthController>();
    final error = await auth.login(
      _emailController.text,
      _passwordController.text,
    );
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
        middle: Text('Anmelden'),
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
                    'Willkommen bei Drawform',
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
                        : const Text('Anmelden'),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: CupertinoButton(
                      padding: EdgeInsets.zero,
                      onPressed: () => context.go('/forgot-password'),
                      child: const Text('Passwort vergessen?'),
                    ),
                  ),
                  const SizedBox(height: 8),
                  CupertinoButton(
                    onPressed: () => context.go('/register'),
                    child: const Text('Neues Konto erstellen'),
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
