import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../services/auth_service.dart';
import '../../theme/ai_theme.dart';
import '../../widgets/ai_background.dart';
import '../../widgets/ai_gradient_button.dart';
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

    if (_emailError != null ||
        _passwordError != null ||
        _confirmError != null) {
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
    final cupertinoTheme = CupertinoTheme.of(context);
    final textStyle = cupertinoTheme.textTheme.textStyle;
    final brightness = Theme.of(context).brightness;
    final colorScheme = Theme.of(context).colorScheme;

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
              'Neues Konto',
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
              padding:
                  const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
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
                                CupertinoIcons.person_add_solid,
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
                                    'Konto anlegen',
                                    style: textStyle.copyWith(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    'Erstelle einen Account und profitiere von AI-gestützten Workflows für deine Fertigungsprojekte.',
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
                          placeholder: 'team@drawform.ai',
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
                        LabeledCupertinoField(
                          label: 'Passwort bestätigen',
                          controller: _confirmController,
                          placeholder: '••••••••',
                          obscureText: true,
                          errorText: _confirmError,
                          onChanged: (_) {
                            if (_confirmError != null) {
                              setState(() => _confirmError = null);
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
                                  CupertinoIcons
                                      .exclamationmark_triangle_fill,
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
                          label: 'Registrieren',
                          onPressed: _loading ? null : _submit,
                          busy: _loading,
                        ),
                        const SizedBox(height: 16),
                        CupertinoButton(
                          padding: EdgeInsets.zero,
                          onPressed:
                              _loading ? null : () => context.go('/login'),
                          child: Text(
                            'Zurück zur Anmeldung',
                            style: textStyle.copyWith(
                              color: colorScheme.secondary.withValues(alpha: 0.95),
                              fontWeight: FontWeight.w500,
                            ),
                          ),
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
