import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
import '../theme/ai_theme.dart';
import '../widgets/ai_gradient_button.dart';
import '../widgets/labeled_cupertino_field.dart';
import '../widgets/section_header.dart';

class ProfileSettingsPage extends StatefulWidget {
  const ProfileSettingsPage({super.key});

  @override
  State<ProfileSettingsPage> createState() => _ProfileSettingsPageState();
}

class _ProfileSettingsPageState extends State<ProfileSettingsPage> {
  final TextEditingController _avatarController = TextEditingController();
  final TextEditingController _currentPasswordController =
      TextEditingController();
  final TextEditingController _newPasswordController = TextEditingController();

  bool _initialised = false;
  bool _saving = false;
  String? _status;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialised) {
      final auth = context.read<AuthController>();
      _avatarController.text = auth.avatarUrl ?? '';
      _initialised = true;
    }
  }

  @override
  void dispose() {
    _avatarController.dispose();
    _currentPasswordController.dispose();
    _newPasswordController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _status = null;
    });

    final auth = context.read<AuthController>();
    auth.updateAvatar(_avatarController.text);

    final bool wantsPasswordChange =
        _currentPasswordController.text.isNotEmpty ||
            _newPasswordController.text.isNotEmpty;
    if (wantsPasswordChange) {
      final bool missingField = _currentPasswordController.text.isEmpty ||
          _newPasswordController.text.isEmpty;
      if (missingField) {
        setState(() {
          _status = 'Bitte aktuelles und neues Passwort ausfüllen.';
          _saving = false;
        });
        return;
      }
      final String? error = await auth.updatePassword(
        currentPassword: _currentPasswordController.text,
        newPassword: _newPasswordController.text,
      );
      if (error != null) {
        setState(() {
          _status = error;
          _saving = false;
        });
        return;
      }
    }

    setState(() {
      _status = 'Profil aktualisiert.';
      _saving = false;
      _currentPasswordController.clear();
      _newPasswordController.clear();
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final brightness = Theme.of(context).brightness;
    final textStyle = CupertinoTheme.of(context).textTheme.textStyle;

    return CupertinoScrollbar(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: DecoratedBox(
              decoration: AiTheme.glassSurface(
                brightness: brightness,
                borderRadius: AiTheme.largeRadius,
                opacity: 0.9,
              ),
              child: Padding(
                padding: const EdgeInsets.all(28),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionHeader(
                      title: 'Profileinstellungen',
                      subtitle:
                          'Personalisieren Sie Ihr AI-Profil und Ihre Sicherheit',
                    ),
                    const SizedBox(height: 12),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _AvatarPreview(
                          initials: _initials(auth.email),
                          avatarUrl: auth.avatarUrl,
                        ),
                        const SizedBox(width: 20),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              LabeledCupertinoField(
                                label: 'Bild-URL',
                                controller: _avatarController,
                                keyboardType: TextInputType.url,
                                placeholder: 'https://example.com/avatar.png',
                                onChanged: (_) => setState(() {}),
                              ),
                              const SizedBox(height: 16),
                              const Wrap(
                                spacing: 10,
                                runSpacing: 10,
                                children: [
                                  _HighlightChip(
                                    icon: CupertinoIcons.sparkles,
                                    label: 'AI-Avatar',
                                  ),
                                  _HighlightChip(
                                    icon: CupertinoIcons.person_crop_circle,
                                    label: 'Sichtbar im Team',
                                  ),
                                  _HighlightChip(
                                    icon: CupertinoIcons.shield_lefthalf_fill,
                                    label: 'Verifiziert',
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 32),
                    Text(
                      'Passwort ändern',
                      style: textStyle.copyWith(
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.2,
                      ),
                    ),
                    const SizedBox(height: 12),
                    LabeledCupertinoField(
                      label: 'Aktuelles Passwort',
                      controller: _currentPasswordController,
                      obscureText: true,
                      placeholder: '••••••••',
                    ),
                    const SizedBox(height: 16),
                    LabeledCupertinoField(
                      label: 'Neues Passwort',
                      controller: _newPasswordController,
                      obscureText: true,
                      placeholder: '••••••••',
                    ),
                    const SizedBox(height: 16),
                    if (_status != null) _StatusBanner(status: _status!),
                    const SizedBox(height: 20),
                    Align(
                      alignment: Alignment.centerRight,
                      child: AiGradientButton(
                        label: 'Speichern',
                        onPressed: _saving ? null : _save,
                        busy: _saving,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  String _initials(String? email) {
    if (email == null || email.isEmpty) {
      return '?';
    }
    final base = email.split('@').first;
    final parts = base.split('.');
    final buffer = StringBuffer();
    if (parts.isNotEmpty && parts[0].isNotEmpty) {
      buffer.write(parts[0][0].toUpperCase());
    }
    if (parts.length > 1 && parts[1].isNotEmpty) {
      buffer.write(parts[1][0].toUpperCase());
    }
    if (buffer.isEmpty) {
      buffer.write(base[0].toUpperCase());
    }
    return buffer.toString();
  }
}

class _AvatarPreview extends StatelessWidget {
  const _AvatarPreview({
    required this.initials,
    required this.avatarUrl,
  });

  final String initials;
  final String? avatarUrl;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final hasImage = avatarUrl != null && avatarUrl!.isNotEmpty;

    final placeholder = Container(
      decoration: BoxDecoration(
        gradient: AiTheme.accentGradient(brightness),
        borderRadius: BorderRadius.circular(48),
      ),
      child: Center(
        child: Text(
          initials,
          style: CupertinoTheme.of(context)
              .textTheme
              .navTitleTextStyle
              .copyWith(color: Colors.white),
        ),
      ),
    );

    return Container(
      width: 96,
      height: 96,
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        gradient: AiTheme.accentGradient(brightness),
        borderRadius: BorderRadius.circular(52),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(48),
        child: Container(
          decoration: BoxDecoration(
            color:
                AiTheme.glassSurfaceColor.resolveFrom(context).withValues(alpha: 0.6),
          ),
          child: hasImage
              ? Image.network(
                  avatarUrl!,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => placeholder,
                )
              : placeholder,
        ),
      ),
    );
  }
}

class _HighlightChip extends StatelessWidget {
  const _HighlightChip({
    required this.icon,
    required this.label,
  });

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        gradient: AiTheme.primaryGradient(brightness),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Colors.white),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusBanner extends StatelessWidget {
  const _StatusBanner({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final bool isSuccess = status == 'Profil aktualisiert.';
    final Color color = isSuccess
        ? CupertinoColors.activeGreen
        : CupertinoColors.destructiveRed;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: color.withValues(alpha: 0.14),
        border: Border.all(color: color.withValues(alpha: 0.28)),
      ),
      child: Row(
        children: [
          Icon(
            isSuccess
                ? CupertinoIcons.check_mark_circled_solid
                : CupertinoIcons.exclamationmark_triangle_fill,
            color: color,
            size: 18,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              status,
              style: TextStyle(
                color: color,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
