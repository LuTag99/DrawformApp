import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../services/auth_service.dart';
import '../../theme/ai_theme.dart';
import '../../widgets/ai_background.dart';
import '../../widgets/ai_gradient_button.dart';
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
    final cupertinoTheme = CupertinoTheme.of(context);
    final textStyle = cupertinoTheme.textTheme.textStyle;
    final brightness = Theme.of(context).brightness;

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
              'Passwort zurücksetzen',
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
                constraints: const BoxConstraints(maxWidth: 480),
                child: DecoratedBox(
                  decoration: AiTheme.glassSurface(
                    brightness: brightness,
                    borderRadius: AiTheme.largeRadius,
                    opacity: 0.9,
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(28),
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
                              padding: const EdgeInsets.all(12),
                              child: const Icon(
                                CupertinoIcons.lock_open_fill,
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
                                    'Link anfordern',
                                    style: textStyle.copyWith(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    'Wir senden dir einen sicheren Link, um dein Passwort zurückzusetzen.',
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
                        const SizedBox(height: 24),
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
                        const SizedBox(height: 20),
                        AiGradientButton(
                          label: 'Link senden',
                          onPressed: _loading ? null : _submit,
                          busy: _loading,
                        ),
                        const SizedBox(height: 16),
                        if (_message != null)
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 12,
                            ),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(16),
                              color: CupertinoColors.activeGreen
                                  .withValues(alpha: 0.14),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  CupertinoIcons.check_mark_circled_solid,
                                  color: CupertinoColors.activeGreen,
                                  size: 18,
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Text(
                                    _message!,
                                    style: const TextStyle(
                                      color: CupertinoColors.activeGreen,
                                      fontSize: 13,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        const SizedBox(height: 16),
                        CupertinoButton(
                          padding: EdgeInsets.zero,
                          onPressed: () => context.go('/login'),
                          child: Text(
                            'Zurück zur Anmeldung',
                            style: textStyle.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .secondary
                                  .withValues(alpha: 0.95),
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
