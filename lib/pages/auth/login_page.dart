import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../services/auth_service.dart';
import '../../widgets/ai_background.dart';
import '../../widgets/ai_gradient_button.dart';
import '../../widgets/labeled_cupertino_field.dart';
import '../../theme/ai_theme.dart';

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
    final cupertinoTheme = CupertinoTheme.of(context);
    final brightness = Theme.of(context).brightness;
    final textStyle = cupertinoTheme.textTheme.textStyle;
    final Color linkColor =
        Theme.of(context).colorScheme.secondary.withValues(alpha: 0.95);

    return AiBackground(
      child: CupertinoPageScaffold(
        backgroundColor: Colors.transparent,
        navigationBar: CupertinoNavigationBar(
          backgroundColor: AiTheme.glassSurfaceColor
              .resolveFrom(context)
              .withValues(alpha: 0.85),
          border: null,
          middle: ShaderMask(
            shaderCallback: (Rect bounds) =>
                AiTheme.accentGradient(brightness).createShader(bounds),
            blendMode: BlendMode.srcIn,
            child: const Text(
              'Drawform AI',
              style: TextStyle(
                fontWeight: FontWeight.w600,
                fontSize: 18,
              ),
            ),
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: DecoratedBox(
                  decoration: AiTheme.glassSurface(
                    brightness: brightness,
                    borderRadius: AiTheme.largeRadius,
                    opacity: 0.88,
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                gradient: AiTheme.accentGradient(brightness),
                              ),
                              padding: const EdgeInsets.all(14),
                              child: const Icon(
                                CupertinoIcons.sparkles,
                                color: Colors.white,
                                size: 22,
                              ),
                            ),
                            const SizedBox(width: 16),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Willkommen zurück',
                                    style: textStyle.copyWith(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    'Melde dich an, um deine AI-gestützten Formprozesse zu steuern.',
                                    style: textStyle.copyWith(
                                      fontSize: 14,
                                      height: 1.4,
                                      color: textStyle.color?.withValues(alpha: 0.7),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 28),
                        LabeledCupertinoField(
                          label: 'E-Mail',
                          controller: _emailController,
                          placeholder: 'you@example.com',
                          keyboardType: TextInputType.emailAddress,
                          errorText: _emailError,
                          onChanged: (_) {
                            if (_emailError != null) {
                              setState(() => _emailError = null);
                            }
                          },
                        ),
                        const SizedBox(height: 18),
                        LabeledCupertinoField(
                          label: 'Passwort',
                          controller: _passwordController,
                          placeholder: '••••••••',
                          obscureText: true,
                          errorText: _passwordError,
                          onChanged: (_) {
                            if (_passwordError != null) {
                              setState(() => _passwordError = null);
                            }
                          },
                        ),
                        const SizedBox(height: 18),
                        if (_error != null)
                          Container(
                            margin: const EdgeInsets.only(bottom: 6),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 12,
                            ),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(16),
                              color: CupertinoColors.destructiveRed
                                  .withValues(alpha: 0.12),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  CupertinoIcons.exclamationmark_triangle_fill,
                                  color: CupertinoColors.destructiveRed,
                                  size: 18,
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Text(
                                    _error!,
                                    style: const TextStyle(
                                      color: CupertinoColors.destructiveRed,
                                      fontSize: 13,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        const SizedBox(height: 12),
                        AiGradientButton(
                          label: 'Anmelden',
                          onPressed: _loading ? null : _submit,
                          busy: _loading,
                        ),
                        const SizedBox(height: 12),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            CupertinoButton(
                              padding: EdgeInsets.zero,
                              onPressed: _loading
                                  ? null
                                  : () => context.go('/forgot-password'),
                              child: Text(
                                'Passwort vergessen?',
                                style: textStyle.copyWith(
                                  color: linkColor,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                            ),
                            CupertinoButton(
                              padding: EdgeInsets.zero,
                              onPressed: _loading
                                  ? null
                                  : () => context.go('/register'),
                              child: Text(
                                'Jetzt registrieren',
                                style: textStyle.copyWith(
                                  color: linkColor,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Drawform AI beschleunigt die Erstellung von Fertigungsunterlagen mit Machine-Learning-Assistenz.',
                          style: textStyle.copyWith(
                            fontSize: 13,
                            height: 1.45,
                            color: textStyle.color?.withValues(alpha: 0.6),
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
