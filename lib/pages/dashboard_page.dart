import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../theme/ai_theme.dart';
import '../widgets/section_header.dart';

/// Dashboard page showing high-level statistics about projects.
class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;

    return CupertinoScrollbar(
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const SectionHeader(
            title: 'Dashboard',
            subtitle: 'Überblick über aktuelle Projekte und Exportentwicklungen',
          ),
          const SizedBox(height: 12),
          const Wrap(
            spacing: 18,
            runSpacing: 18,
            children: [
              _StatCard(
                title: 'Anzahl Projekte',
                value: '3',
                icon: CupertinoIcons.number_circle,
                trendLabel: '+12% im Vergleich zur Vorwoche',
                positiveTrend: true,
              ),
              _StatCard(
                title: 'Letzter Export',
                value: 'vor 2 Tagen',
                icon: CupertinoIcons.clock,
                trendLabel: 'Workflow seit 48 Std. stabil',
                positiveTrend: true,
              ),
              _StatCard(
                title: 'Fehlerquote',
                value: '0%',
                icon: CupertinoIcons.check_mark_circled,
                trendLabel: 'Keine Abweichungen erkannt',
                positiveTrend: true,
              ),
            ],
          ),
          const SizedBox(height: 28),
          SizedBox(
            height: 360,
            child: DecoratedBox(
              decoration: AiTheme.glassSurface(
                brightness: brightness,
                borderRadius: AiTheme.largeRadius,
                opacity: 0.86,
              ),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'AI Insights',
                      style: CupertinoTheme.of(context)
                          .textTheme
                          .navTitleTextStyle
                          .copyWith(fontSize: 20),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      'Die KI erkennt stabile Exportpipelines. Empfohlene Aktion: Automatisierte Qualitätskontrolle aktivieren, um den Output bei gleichbleibender Fehlerquote zu erhöhen.',
                      style: CupertinoTheme.of(context)
                          .textTheme
                          .textStyle
                          .copyWith(
                            fontSize: 14,
                            height: 1.5,
                            color: CupertinoTheme.of(context)
                                .textTheme
                                .textStyle
                                .color
                                ?.withValues(alpha: 0.72),
                          ),
                    ),
                    const SizedBox(height: 20),
                    _InsightChips(brightness: brightness),
                    const SizedBox(height: 20),
                    const Expanded(child: _PlaceholderChart()),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.trendLabel,
    required this.positiveTrend,
  });

  final String title;
  final String value;
  final IconData icon;
  final String trendLabel;
  final bool positiveTrend;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final TextStyle labelStyle = CupertinoTheme.of(context)
        .textTheme
        .textStyle
        .copyWith(
          fontSize: 13,
          height: 1.4,
          color: CupertinoTheme.of(context)
              .textTheme
              .textStyle
              .color
              ?.withValues(alpha: 0.7),
        );

    final gradient = AiTheme.accentGradient(brightness);

    return DecoratedBox(
      decoration: AiTheme.glassSurface(
        brightness: brightness,
        borderRadius: AiTheme.mediumRadius,
        opacity: 0.9,
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              decoration: BoxDecoration(
                gradient: gradient,
                borderRadius: BorderRadius.circular(16),
              ),
              padding: const EdgeInsets.all(14),
              child: Icon(icon, color: Colors.white, size: 22),
            ),
            const SizedBox(height: 18),
            Text(
              value,
              style: CupertinoTheme.of(context)
                  .textTheme
                  .navTitleTextStyle
                  .copyWith(fontSize: 26),
            ),
            const SizedBox(height: 6),
            Text(title, style: labelStyle),
            const SizedBox(height: 16),
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Icon(
                  positiveTrend
                      ? CupertinoIcons.arrow_up_right
                      : CupertinoIcons.arrow_down,
                  size: 16,
                  color: positiveTrend
                      ? CupertinoColors.activeGreen
                      : CupertinoColors.systemRed,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    trendLabel,
                    style: labelStyle.copyWith(
                      color: positiveTrend
                          ? CupertinoColors.activeGreen.withValues(alpha: 0.9)
                          : CupertinoColors.systemRed.withValues(alpha: 0.9),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _InsightChips extends StatelessWidget {
  const _InsightChips({required this.brightness});

  final Brightness brightness;

  @override
  Widget build(BuildContext context) {
    final List<String> chips = [
      'Automatisierung aktiv',
      '3 Projekte in Pipeline',
      '0 Fehler erkannt',
    ];

    return Wrap(
      spacing: 12,
      runSpacing: 10,
      children: chips
          .map(
            (chip) => Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(20),
                gradient: AiTheme.primaryGradient(brightness),
                border: Border.all(
                  color: AiTheme.glassSurfaceColor
                      .resolveFrom(context)
                      .withValues(alpha: 0.3),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    CupertinoIcons.sparkles,
                    size: 14,
                    color: Colors.white,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    chip,
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
          )
          .toList(growable: false),
    );
  }
}

class _PlaceholderChart extends StatelessWidget {
  const _PlaceholderChart();

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return ClipRRect(
      borderRadius: AiTheme.mediumRadius,
      child: DecoratedBox(
        decoration: AiTheme.glassSurface(
          brightness: brightness,
          borderRadius: AiTheme.mediumRadius,
          opacity: 0.65,
        ),
        child: CustomPaint(
          painter: _ChartPainter(
            accentGradient: AiTheme.accentGradient(brightness),
            brightness: brightness,
          ),
        ),
      ),
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter({
    required this.accentGradient,
    required this.brightness,
  });

  final Gradient accentGradient;
  final Brightness brightness;

  @override
  void paint(Canvas canvas, Size size) {
    final Paint gridPaint = Paint()
      ..color = (brightness == Brightness.dark ? Colors.white : Colors.black)
          .withValues(alpha: 0.08)
      ..strokeWidth = 1;

    const int horizontalLines = 4;
    const int verticalLines = 6;

    for (int i = 0; i <= horizontalLines; i++) {
      final double dy = size.height / horizontalLines * i;
      canvas.drawLine(Offset(0, dy), Offset(size.width, dy), gridPaint);
    }
    for (int i = 0; i <= verticalLines; i++) {
      final double dx = size.width / verticalLines * i;
      canvas.drawLine(Offset(dx, 0), Offset(dx, size.height), gridPaint);
    }

    final Path curve = Path()
      ..moveTo(0, size.height * 0.7)
      ..cubicTo(
        size.width * 0.2,
        size.height * 0.4,
        size.width * 0.45,
        size.height * 0.9,
        size.width * 0.65,
        size.height * 0.35,
      )
      ..quadraticBezierTo(
        size.width * 0.85,
        size.height * 0.2,
        size.width,
        size.height * 0.45,
      );

    final Paint curvePaint = Paint()
      ..shader = accentGradient.createShader(
        Rect.fromLTWH(0, 0, size.width, size.height),
      )
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.2
      ..strokeCap = StrokeCap.round;

    canvas.drawPath(curve, curvePaint);

    final Paint glowPaint = Paint()
      ..shader = accentGradient.createShader(
        Rect.fromLTWH(0, 0, size.width, size.height),
      )
      ..style = PaintingStyle.stroke
      ..strokeWidth = 10
      ..strokeCap = StrokeCap.round
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 18);

    canvas.drawPath(curve, glowPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
