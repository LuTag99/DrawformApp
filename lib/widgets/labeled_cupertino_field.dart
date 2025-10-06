import 'package:flutter/cupertino.dart';

/// Ein beschriftetes Eingabefeld im Cupertino-Stil inkl. optionaler
/// Fehlermeldung.
class LabeledCupertinoField extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final bool obscureText;
  final String? errorText;
  final TextInputType keyboardType;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;

  const LabeledCupertinoField({
    super.key,
    required this.label,
    required this.controller,
    this.obscureText = false,
    this.errorText,
    this.keyboardType = TextInputType.text,
    this.textInputAction,
    this.onChanged,
    this.onSubmitted,
  });

  @override
  Widget build(BuildContext context) {
    final theme = CupertinoTheme.of(context);
    final baseBorder = errorText == null
        ? CupertinoColors.separator
        : CupertinoColors.destructiveRed;
    final borderColor =
        CupertinoDynamicColor.resolve(baseBorder, context);
    final backgroundColor = CupertinoDynamicColor.resolve(
        CupertinoColors.systemBackground, context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: theme.textTheme.textStyle,
        ),
        const SizedBox(height: 6),
        CupertinoTextField(
          controller: controller,
          keyboardType: keyboardType,
          obscureText: obscureText,
          onChanged: onChanged,
          onSubmitted: onSubmitted,
          textInputAction: textInputAction,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: backgroundColor,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: borderColor),
          ),
        ),
        if (errorText != null) ...[
          const SizedBox(height: 4),
          Text(
            errorText!,
            style: const TextStyle(
              color: CupertinoColors.destructiveRed,
              fontSize: 13,
            ),
          ),
        ],
      ],
    );
  }
}
