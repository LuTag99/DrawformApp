import 'dart:ui';

import 'package:flutter/material.dart';

import '../theme/ai_theme.dart';

/// Animated gradient backdrop that gives every screen a cohesive AI feel.
class AiBackground extends StatefulWidget {
  const AiBackground({
    super.key,
    required this.child,
    this.padding,
  });

  final Widget child;
  final EdgeInsetsGeometry? padding;

  @override
  State<AiBackground> createState() => _AiBackgroundState();
}

class _AiBackgroundState extends State<AiBackground>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 26),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        final curve = Curves.easeInOut.transform(_controller.value);
        return DecoratedBox(
          decoration: AiTheme.backgroundDecoration(brightness),
          child: Stack(
            children: [
              _GlowingOrb(
                alignment: Alignment(-1.2 + 0.4 * curve, -1.0),
                size: 420,
                gradient: AiTheme.accentGradient(brightness),
                blurSigma: 180,
              ),
              _GlowingOrb(
                alignment: Alignment(1.0 - 0.3 * curve, 1.1),
                size: 360,
                gradient: AiTheme.primaryGradient(brightness),
                blurSigma: 160,
              ),
              Align(
                alignment: Alignment(0.2, -0.1 + 0.05 * curve),
                child: _TechLinesOverlay(
                  opacity: brightness == Brightness.dark ? 0.12 : 0.08,
                ),
              ),
              Padding(
                padding: widget.padding ?? EdgeInsets.zero,
                child: widget.child,
              ),
            ],
          ),
        );
      },
    );
  }
}

class _GlowingOrb extends StatelessWidget {
  const _GlowingOrb({
    required this.alignment,
    required this.size,
    required this.gradient,
    required this.blurSigma,
  });

  final Alignment alignment;
  final double size;
  final Gradient gradient;
  final double blurSigma;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Align(
        alignment: alignment,
        child: ImageFiltered(
          imageFilter: ImageFilter.blur(sigmaX: blurSigma, sigmaY: blurSigma),
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: gradient,
            ),
          ),
        ),
      ),
    );
  }
}

class _TechLinesOverlay extends StatelessWidget {
  const _TechLinesOverlay({required this.opacity});

  final double opacity;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Opacity(
        opacity: opacity,
        child: CustomPaint(
          size: const Size(360, 360),
          painter: _TechLinesPainter(),
        ),
      ),
    );
  }
}

class _TechLinesPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final Paint paint = Paint()
      ..color = Colors.white
      ..strokeWidth = 1.2
      ..style = PaintingStyle.stroke;

    final Path outerHex = Path()
      ..moveTo(size.width * 0.5, 0)
      ..lineTo(size.width, size.height * 0.25)
      ..lineTo(size.width, size.height * 0.75)
      ..lineTo(size.width * 0.5, size.height)
      ..lineTo(0, size.height * 0.75)
      ..lineTo(0, size.height * 0.25)
      ..close();

    final Path innerHex = Path()
      ..moveTo(size.width * 0.5, size.height * 0.18)
      ..lineTo(size.width * 0.82, size.height * 0.32)
      ..lineTo(size.width * 0.82, size.height * 0.68)
      ..lineTo(size.width * 0.5, size.height * 0.82)
      ..lineTo(size.width * 0.18, size.height * 0.68)
      ..lineTo(size.width * 0.18, size.height * 0.32)
      ..close();

    canvas.drawPath(outerHex, paint);

    paint
      ..color = paint.color.withValues(alpha: 0.6)
      ..strokeWidth = 1.0;
    canvas.drawPath(innerHex, paint);

    final Paint dotPaint = Paint()
      ..color = paint.color.withValues(alpha: 0.5)
      ..style = PaintingStyle.fill;

    final List<Offset> nodes = [
      Offset(size.width * 0.5, size.height * 0.04),
      Offset(size.width * 0.94, size.height * 0.25),
      Offset(size.width * 0.94, size.height * 0.75),
      Offset(size.width * 0.5, size.height * 0.96),
      Offset(size.width * 0.06, size.height * 0.75),
      Offset(size.width * 0.06, size.height * 0.25),
    ];

    for (final Offset node in nodes) {
      canvas.drawCircle(node, 3, dotPaint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
