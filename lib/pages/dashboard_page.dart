import 'package:flutter/cupertino.dart';

import '../widgets/section_header.dart';

/// Dashboard page showing high‑level statistics about projects.
class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = CupertinoTheme.of(context);
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: CupertinoColors.systemGroupedBackground,
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionHeader(title: 'Dashboard'),
            Wrap(
              spacing: 16,
              runSpacing: 16,
              children: const [
                _StatCard(title: 'Anzahl Projekte', value: '3', icon: CupertinoIcons.number_circle),
                _StatCard(title: 'Letzter Export', value: 'vor 2 Tagen', icon: CupertinoIcons.clock),
                _StatCard(title: 'Fehlerquote', value: '0%', icon: CupertinoIcons.check_mark_circled),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;

  const _StatCard({required this.title, required this.value, required this.icon});

  @override
  Widget build(BuildContext context) {
    final theme = CupertinoTheme.of(context);
    return Container(
      width: 220,
      decoration: BoxDecoration(
        color: CupertinoColors.systemBackground,
        borderRadius: BorderRadius.circular(24),
        boxShadow: const [
          BoxShadow(
            color: Color(0x16000000),
            offset: Offset(0, 8),
            blurRadius: 18,
          ),
        ],
        border: Border.all(color: CupertinoColors.separator),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: theme.primaryColor.withOpacity(0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: theme.primaryColor, size: 18),
          ),
          const SizedBox(height: 12),
          Text(
            value,
            style: theme.textTheme.navTitleTextStyle,
          ),
          const SizedBox(height: 6),
          Text(
            title,
            style: theme.textTheme.textStyle.copyWith(
              color: CupertinoColors.systemGrey,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}
