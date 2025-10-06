import 'package:flutter/cupertino.dart';

import '../widgets/section_header.dart';

/// A simple page that lists recent projects.
///
/// In a real application, this data would be fetched from a backend or local
/// database. For now we use a static list of example projects.
class ProjectOverviewPage extends StatelessWidget {
  const ProjectOverviewPage({super.key});

  @override
  Widget build(BuildContext context) {
    final projects = <Map<String, String>>[
      {
        'title': 'Projekt A',
        'description': '3D‐Modell eines Gehäuses',
      },
      {
        'title': 'Projekt B',
        'description': 'CAD‐Konstruktion für eine Halterung',
      },
      {
        'title': 'Projekt C',
        'description': 'Blechbauteil mit Bemaßungen',
      },
    ];
    final theme = CupertinoTheme.of(context);
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: CupertinoColors.systemGroupedBackground,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionHeader(title: 'Projektübersicht'),
          Expanded(
            child: CupertinoScrollbar(
              child: ListView.builder(
                padding:
                    const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                itemCount: projects.length,
                itemBuilder: (context, index) {
                  final project = projects[index];
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: CupertinoColors.systemBackground,
                      borderRadius: BorderRadius.circular(20),
                      boxShadow: const [
                        BoxShadow(
                          color: Color(0x1F000000),
                          offset: Offset(0, 6),
                          blurRadius: 12,
                        ),
                      ],
                    ),
                    child: CupertinoButton(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 18,
                      ),
                      borderRadius: BorderRadius.circular(20),
                      color: CupertinoColors.systemBackground,
                      onPressed: () {
                        // Platzhalter für Projekt-Detailnavigation.
                      },
                      child: Row(
                        children: [
                          Container(
                            width: 44,
                            height: 44,
                            decoration: BoxDecoration(
                              color: theme.primaryColor.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Icon(
                              CupertinoIcons.folder_solid,
                              color: theme.primaryColor,
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  project['title'] ?? '',
                                  style: theme.textTheme.textStyle.copyWith(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  project['description'] ?? '',
                                  style: theme.textTheme.textStyle.copyWith(
                                    color: CupertinoColors.systemGrey,
                                    fontSize: 13,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const Icon(
                            CupertinoIcons.chevron_forward,
                            color: CupertinoColors.systemGrey2,
                          ),
                        ],
                      ),
                    ),
                  ),
                );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}
