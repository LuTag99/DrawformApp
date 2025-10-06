import 'package:flutter/cupertino.dart';

/// Kleiner Überschrift-Widget im iOS-Stil, der Abstand und Typografie vereinheitlicht.
class SectionHeader extends StatelessWidget {
  final String title;
  final String? subtitle;

  const SectionHeader({super.key, required this.title, this.subtitle});

  @override
  Widget build(BuildContext context) {
    final theme = CupertinoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: theme.textTheme.navTitleTextStyle,
          ),
          if (subtitle != null) ...[
            const SizedBox(height: 4),
            Text(
              subtitle!,
              style: theme.textTheme.textStyle.copyWith(
                color: CupertinoColors.systemGrey,
                fontSize: 13,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
