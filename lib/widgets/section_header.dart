import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../theme/ai_theme.dart';

/// Übergeordnete Überschrift mit dezentem AI-Branding.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.subtitle});

  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final cupertinoTheme = CupertinoTheme.of(context);
    final brightness = Theme.of(context).brightness;
    final TextStyle titleStyle = cupertinoTheme.textTheme.navTitleTextStyle
        .copyWith(fontSize: 24, fontWeight: FontWeight.w700);

    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Container(
                height: 26,
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(12),
                  gradient: AiTheme.accentGradient(brightness),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      CupertinoIcons.sparkles,
                      size: 16,
                      color: Colors.white,
                    ),
                    SizedBox(width: 4),
                    Text(
                      'AI',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.4,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              ShaderMask(
                shaderCallback: (Rect bounds) =>
                    AiTheme.accentGradient(brightness).createShader(bounds),
                blendMode: BlendMode.srcIn,
                child: Text(
                  title,
                  style: titleStyle.copyWith(color: Colors.white),
                ),
              ),
            ],
          ),
          if (subtitle != null) ...[
            const SizedBox(height: 8),
            Text(
              subtitle!,
              style: cupertinoTheme.textTheme.textStyle.copyWith(
                color: cupertinoTheme.textTheme.textStyle.color
                    ?.withValues(alpha: 0.65),
                fontSize: 14,
                height: 1.45,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
