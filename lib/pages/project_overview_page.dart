import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../theme/ai_theme.dart';
import '../widgets/section_header.dart';

/// A simple page that lists recent projects with AI-styled cards.
class ProjectOverviewPage extends StatelessWidget {
  const ProjectOverviewPage({super.key});

  @override
  Widget build(BuildContext context) {
    final projects = <Map<String, String>>[
      {
        'title': 'Projekt A',
        'description': '3D-Modell eines Gehäuses',
        'status': 'In Analyse',
      },
      {
        'title': 'Projekt B',
        'description': 'CAD-Konstruktion für eine Halterung',
        'status': 'Freigegeben',
      },
      {
        'title': 'Projekt C',
        'description': 'Blechbauteil mit Bemaßungen',
        'status': 'In Freigabe',
      },
    ];

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionHeader(
            title: 'Projektübersicht',
            subtitle: 'Aktuelle Konstruktionen und ihr AI-bewerteter Status',
          ),
          Expanded(
            child: CupertinoScrollbar(
              child: ListView.separated(
                padding: const EdgeInsets.only(top: 6, bottom: 16),
                itemCount: projects.length,
                separatorBuilder: (_, __) => const SizedBox(height: 14),
                itemBuilder: (context, index) {
                  final project = projects[index];
                  return _ProjectTile(
                    title: project['title'] ?? '',
                    description: project['description'] ?? '',
                    status: project['status'] ?? '',
                    accentIndex: index,
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

class _ProjectTile extends StatelessWidget {
  const _ProjectTile({
    required this.title,
    required this.description,
    required this.status,
    required this.accentIndex,
  });

  final String title;
  final String description;
  final String status;
  final int accentIndex;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final textTheme = CupertinoTheme.of(context).textTheme;
    final gradients = [
      AiTheme.accentGradient(brightness),
      AiTheme.primaryGradient(brightness),
      AiTheme.accentGradient(brightness),
    ];

    final Gradient chipGradient = gradients[accentIndex % gradients.length];

    return DecoratedBox(
      decoration: AiTheme.glassSurface(
        brightness: brightness,
        borderRadius: AiTheme.largeRadius,
        opacity: 0.88,
      ),
      child: CupertinoButton(
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 20),
        borderRadius: AiTheme.largeRadius,
        onPressed: () {
          // Platzhalter für Projekt-Detailnavigation.
        },
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                gradient: chipGradient,
                borderRadius: BorderRadius.circular(18),
              ),
              child: const Icon(
                CupertinoIcons.folder_solid,
                color: Colors.white,
                size: 22,
              ),
            ),
            const SizedBox(width: 18),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          style: textTheme.textStyle.copyWith(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(
                          gradient: chipGradient,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Row(
                          children: [
                            const Icon(
                              CupertinoIcons.waveform_path,
                              size: 14,
                              color: Colors.white,
                            ),
                            const SizedBox(width: 6),
                            Text(
                              status,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 12,
                                fontWeight: FontWeight.w500,
                                letterSpacing: 0.2,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    description,
                    style: textTheme.textStyle.copyWith(
                      color: textTheme.textStyle.color?.withValues(alpha: 0.7),
                      fontSize: 13,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Row(
                        children: [
                          Icon(
                            CupertinoIcons.sparkles,
                            size: 16,
                            color: Theme.of(context)
                                .colorScheme
                                .secondary
                                .withValues(alpha: 0.9),
                          ),
                          const SizedBox(width: 6),
                          Text(
                            'AI Score 92%',
                            style: textTheme.textStyle.copyWith(
                              fontSize: 12,
                              color: textTheme.textStyle.color
                                  ?.withValues(alpha: 0.65),
                            ),
                          ),
                        ],
                      ),
                      const Icon(
                        CupertinoIcons.chevron_forward,
                        size: 18,
                        color: CupertinoColors.systemGrey2,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
