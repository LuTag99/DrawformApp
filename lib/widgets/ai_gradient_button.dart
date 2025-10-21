import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../theme/ai_theme.dart';

/// Gradient-filled primary action button used across the AI-styled screens.
class AiGradientButton extends StatelessWidget {
  const AiGradientButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.leading,
    this.busy = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final Widget? leading;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final bool enabled = onPressed != null && !busy;
    final Gradient gradient = enabled
        ? AiTheme.accentGradient(brightness)
        : LinearGradient(
            colors: [
              Theme.of(context)
                  .colorScheme
                  .surface
                  .withValues(alpha: brightness == Brightness.dark ? 0.4 : 0.55),
              Theme.of(context)
                  .colorScheme
                  .surface
                  .withValues(alpha: brightness == Brightness.dark ? 0.4 : 0.55),
            ],
          );

    return CupertinoButton(
      onPressed: enabled ? onPressed : null,
      padding: EdgeInsets.zero,
      borderRadius: AiTheme.mediumRadius,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 180),
        opacity: enabled ? 1 : 0.6,
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: gradient,
            borderRadius: AiTheme.mediumRadius,
            boxShadow:
                enabled ? AiTheme.elevatedShadow(brightness) : const [],
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              vertical: 16,
              horizontal: 20,
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (busy) ...[
                  const CupertinoActivityIndicator(),
                  const SizedBox(width: 10),
                ] else if (leading != null) ...[
                  leading!,
                  const SizedBox(width: 10),
                ],
                Text(
                  label,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.4,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
