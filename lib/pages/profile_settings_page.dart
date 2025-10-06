import 'package:flutter/cupertino.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
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

    if (_currentPasswordController.text.isNotEmpty ||
        _newPasswordController.text.isNotEmpty) {
      if (_currentPasswordController.text.isEmpty ||
          _newPasswordController.text.isEmpty) {
        setState(() {
          _status = 'Bitte aktuelles und neues Passwort ausfüllen.';
          _saving = false;
        });
        return;
      }
      final error = await auth.updatePassword(
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
    final avatarUrl = auth.avatarUrl;
    final theme = CupertinoTheme.of(context);
    return CupertinoScrollbar(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: CupertinoColors.systemBackground,
                borderRadius: BorderRadius.circular(24),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x16000000),
                    offset: Offset(0, 8),
                    blurRadius: 20,
                  ),
                ],
              ),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionHeader(title: 'Profileinstellungen'),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        _AvatarPreview(
                          initials: _initials(auth.email),
                          avatarUrl: avatarUrl,
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: LabeledCupertinoField(
                            label: 'Bild-URL',
                            controller: _avatarController,
                            keyboardType: TextInputType.url,
                            onChanged: (_) {
                              // Sofortiges Update der Vorschau.
                              setState(() {});
                            },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 28),
                    Text(
                      'Passwort ändern',
                      style: theme.textTheme.textStyle
                          .copyWith(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 12),
                    LabeledCupertinoField(
                      label: 'Aktuelles Passwort',
                      controller: _currentPasswordController,
                      obscureText: true,
                    ),
                    const SizedBox(height: 12),
                    LabeledCupertinoField(
                      label: 'Neues Passwort',
                      controller: _newPasswordController,
                      obscureText: true,
                    ),
                    const SizedBox(height: 16),
                    if (_status != null)
                      Text(
                        _status!,
                        style: TextStyle(
                          color: _status == 'Profil aktualisiert.'
                              ? CupertinoColors.activeGreen
                              : CupertinoColors.destructiveRed,
                          fontSize: 13,
                        ),
                      ),
                    const SizedBox(height: 16),
                    Align(
                      alignment: Alignment.centerRight,
                      child: CupertinoButton.filled(
                        onPressed: _saving ? null : _save,
                        child: _saving
                            ? const CupertinoActivityIndicator()
                            : const Text('Speichern'),
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
  final String initials;
  final String? avatarUrl;

  const _AvatarPreview({required this.initials, required this.avatarUrl});

  @override
  Widget build(BuildContext context) {
    final hasImage = avatarUrl != null && avatarUrl!.isNotEmpty;
    final placeholder = Container(
      decoration: BoxDecoration(
        color: CupertinoColors.systemGrey5,
        borderRadius: BorderRadius.circular(44),
      ),
      child: Center(
        child: Text(
          initials,
          style: CupertinoTheme.of(context).textTheme.navTitleTextStyle,
        ),
      ),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(44),
      child: Container(
        width: 88,
        height: 88,
        color: CupertinoColors.systemGrey5,
        child: hasImage
            ? Image.network(
                avatarUrl!,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => placeholder,
              )
            : placeholder,
      ),
    );
  }
}
