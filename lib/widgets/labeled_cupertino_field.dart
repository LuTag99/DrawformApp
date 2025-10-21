import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../theme/ai_theme.dart';

/// Beschriftetes Eingabefeld im modernen, glasigen Cupertino-Stil mit optionaler
/// Fehlermeldung und Fokus-Highlight.
class LabeledCupertinoField extends StatefulWidget {
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
    this.trailing,
    this.focusNode,
    this.placeholder,
  });

  final String label;
  final TextEditingController controller;
  final bool obscureText;
  final String? errorText;
  final TextInputType keyboardType;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final Widget? trailing;
  final FocusNode? focusNode;
  final String? placeholder;

  @override
  State<LabeledCupertinoField> createState() => _LabeledCupertinoFieldState();
}

class _LabeledCupertinoFieldState extends State<LabeledCupertinoField> {
  late final FocusNode _focusNode =
      widget.focusNode ?? FocusNode(debugLabel: widget.label);
  bool get _ownsFocusNode => widget.focusNode == null;
  bool _hasFocus = false;

  @override
  void initState() {
    super.initState();
    _focusNode.addListener(_handleFocusChange);
  }

  @override
  void dispose() {
    _focusNode.removeListener(_handleFocusChange);
    if (_ownsFocusNode) {
      _focusNode.dispose();
    }
    super.dispose();
  }

  void _handleFocusChange() {
    if (mounted) {
      setState(() {
        _hasFocus = _focusNode.hasFocus;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final cupertinoTheme = CupertinoTheme.of(context);
    final bool hasError =
        widget.errorText != null && widget.errorText!.isNotEmpty;
    final brightness = Theme.of(context).brightness;
    final colorScheme = Theme.of(context).colorScheme;

    final BoxDecoration baseDecoration = AiTheme.glassSurface(
      brightness: brightness,
      borderRadius: BorderRadius.circular(20),
      opacity: hasError
          ? 0.94
          : _hasFocus
              ? 0.88
              : 0.82,
    );

    final Border defaultBorder =
        (baseDecoration.border ?? Border.all(color: Colors.transparent))
            as Border;
    final Color borderColor = hasError
        ? CupertinoColors.destructiveRed
        : _hasFocus
            ? colorScheme.secondary.withValues(alpha: 0.85)
            : defaultBorder.top.color;
    final double borderWidth =
        hasError || _hasFocus ? 1.6 : defaultBorder.top.width;
    final List<BoxShadow>? boxShadow = hasError
        ? [
            BoxShadow(
              color: CupertinoColors.destructiveRed.withValues(alpha: 0.25),
              blurRadius: 30,
              spreadRadius: -12,
              offset: const Offset(0, 18),
            ),
          ]
        : baseDecoration.boxShadow;

    final BoxDecoration decoration = baseDecoration.copyWith(
      border: Border.all(color: borderColor, width: borderWidth),
      boxShadow: boxShadow,
    );

    final TextStyle baseTextStyle = cupertinoTheme.textTheme.textStyle;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.label,
          style: baseTextStyle.copyWith(
            fontWeight: FontWeight.w600,
            letterSpacing: 0.2,
          ),
        ),
        const SizedBox(height: 8),
        AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeInOut,
          decoration: decoration,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: CupertinoTextField(
                  controller: widget.controller,
                  focusNode: _focusNode,
                  keyboardType: widget.keyboardType,
                  obscureText: widget.obscureText,
                  onChanged: widget.onChanged,
                  onSubmitted: widget.onSubmitted,
                  textInputAction: widget.textInputAction,
                  cursorColor: colorScheme.secondary,
                  padding:
                      const EdgeInsets.symmetric(vertical: 12, horizontal: 0),
                  placeholder: widget.placeholder,
                  decoration: const BoxDecoration(),
                  style: baseTextStyle.copyWith(
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                  ),
                  placeholderStyle: baseTextStyle.copyWith(
                    color:
                        baseTextStyle.color?.withValues(alpha: 0.45) ?? Colors.grey,
                    fontSize: 15,
                  ),
                ),
              ),
              if (widget.trailing != null) ...[
                const SizedBox(width: 12),
                SizedBox(
                  height: 44,
                  child: widget.trailing,
                ),
              ],
            ],
          ),
        ),
        if (hasError) ...[
          const SizedBox(height: 6),
          Text(
            widget.errorText!,
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
