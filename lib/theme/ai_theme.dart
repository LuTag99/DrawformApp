import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

/// Centralised theme definition for the application.
///
/// The theme leans into a modern, AI-inspired aesthetic with soft gradients,
/// glassmorphism-inspired surfaces and vibrant accent colours. All screens
/// should reference the helpers in this file to keep styling cohesive.
class AiTheme {
  static const Color _lightPrimary = Color(0xFF4F46E5);
  static const Color _lightSecondary = Color(0xFF0EA5E9);
  static const Color _lightAccent = Color(0xFF38BDF8);
  static const Color _darkPrimary = Color(0xFF818CF8);
  static const Color _darkSecondary = Color(0xFF22D3EE);
  static const Color _darkAccent = Color(0xFFA855F7);

  static const Color _lightBackground = Color(0xFFF4F7FF);
  static const Color _lightSurface = Color(0xFFFFFFFF);
  static const Color _darkBackground = Color(0xFF050B1A);
  static const Color _darkSurface = Color(0xFF0F172A);

  static BorderRadius get largeRadius => BorderRadius.circular(26);
  static BorderRadius get mediumRadius => BorderRadius.circular(20);

  static ThemeData materialLight() =>
      _material(brightness: Brightness.light);

  static ThemeData materialDark() =>
      _material(brightness: Brightness.dark);

  static ThemeData _material({required Brightness brightness}) {
    final bool isDark = brightness == Brightness.dark;
    final Color background =
        isDark ? _darkBackground : _lightBackground;
    final Color surface = isDark ? _darkSurface : _lightSurface;
    final Color primary = isDark ? _darkPrimary : _lightPrimary;
    final Color secondary = isDark ? _darkSecondary : _lightSecondary;
    final Color accent = isDark ? _darkAccent : _lightAccent;
    final Color onBackground =
        isDark ? const Color(0xFFE2E8F0) : const Color(0xFF0F172A);
    final Color onSurface = onBackground;

    final Typography typography =
        Typography.material2021(platform: TargetPlatform.iOS);
    final TextTheme textTheme =
        (isDark ? typography.white : typography.black).apply(
      bodyColor: onSurface,
      displayColor: onSurface,
    );

    final ColorScheme colorScheme = ColorScheme.fromSeed(
      seedColor: primary,
      brightness: brightness,
    ).copyWith(
      primary: primary,
      onPrimary: Colors.white,
      secondary: secondary,
      onSecondary: Colors.white,
      error: const Color(0xFFEF4444),
      onError: Colors.white,
      surface: surface,
      onSurface: onSurface,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      typography: typography,
      textTheme: textTheme,
      scaffoldBackgroundColor: background,
      canvasColor: background,
      visualDensity: VisualDensity.adaptivePlatformDensity,
      appBarTheme: AppBarTheme(
        backgroundColor: surface.withValues(alpha: isDark ? 0.7 : 0.9),
        foregroundColor: onSurface,
        elevation: 0,
        centerTitle: true,
        titleTextStyle: textTheme.titleMedium?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
        ),
      ),
      cardTheme: CardThemeData(
        clipBehavior: Clip.antiAlias,
        color: surface.withValues(alpha: isDark ? 0.82 : 0.92),
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: largeRadius,
          side: BorderSide(
            color: _glassBorder(brightness),
            width: 1,
          ),
        ),
      ),
      iconTheme: IconThemeData(color: accent),
      dividerColor: _glassBorder(brightness),
      cupertinoOverrideTheme: cupertino(brightness),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface.withValues(alpha: isDark ? 0.35 : 0.82),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: _glassBorder(brightness)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: _glassBorder(brightness)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: accent, width: 1.4),
        ),
      ),
    );
  }

  static CupertinoThemeData cupertino(Brightness brightness) {
    final bool isDark = brightness == Brightness.dark;
    final Color primary = isDark ? _darkPrimary : _lightPrimary;
    final Color background =
        isDark ? _darkBackground : _lightBackground;
    final Color surface = isDark ? _darkSurface : _lightSurface;
    final Color onBackground =
        isDark ? const Color(0xFFE2E8F0) : const Color(0xFF0F172A);
    return CupertinoThemeData(
      brightness: brightness,
      primaryColor: primary,
      scaffoldBackgroundColor: background,
      barBackgroundColor: surface.withValues(alpha: isDark ? 0.65 : 0.9),
      textTheme: CupertinoTextThemeData(
        textStyle: TextStyle(
          color: onBackground,
          fontSize: 15,
          letterSpacing: 0.1,
        ),
        navTitleTextStyle: TextStyle(
          color: onBackground,
          fontSize: 20,
          fontWeight: FontWeight.w600,
        ),
        navLargeTitleTextStyle: TextStyle(
          color: onBackground,
          fontSize: 32,
          fontWeight: FontWeight.w700,
        ),
        tabLabelTextStyle: TextStyle(
          color: onBackground.withValues(alpha: 0.82),
          fontSize: 12,
        ),
        actionTextStyle: TextStyle(
          color: primary,
          fontSize: 15,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }

  static CupertinoDynamicColor get glassSurfaceColor =>
      const CupertinoDynamicColor.withBrightness(
        color: Color(0xF2FFFFFF),
        darkColor: Color(0xCC0F172A),
      );

  static LinearGradient primaryGradient(Brightness brightness) =>
      LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: brightness == Brightness.dark
            ? const [
                Color(0xFF111C44),
                Color(0xFF0C3C5D),
                Color(0xFF112240),
              ]
            : const [
                Color(0xFFEFF4FF),
                Color(0xFFE0F2FE),
                Color(0xFFF5F7FF),
              ],
      );

  static LinearGradient accentGradient(Brightness brightness) =>
      LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: brightness == Brightness.dark
            ? const [
                Color(0xFF818CF8),
                Color(0xFF22D3EE),
                Color(0xFFA855F7),
              ]
            : const [
                Color(0xFF4F46E5),
                Color(0xFF0EA5E9),
                Color(0xFF8B5CF6),
              ],
      );

  static BoxDecoration backgroundDecoration(Brightness brightness) =>
      BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: brightness == Brightness.dark
              ? const [
                  Color(0xFF020617),
                  Color(0xFF0F172A),
                  Color(0xFF111827),
                ]
              : const [
                  Color(0xFFF6F7FB),
                  Color(0xFFE8F1FF),
                  Color(0xFFF4FBFF),
                ],
        ),
      );

  static BoxDecoration glassSurface({
    required Brightness brightness,
    BorderRadiusGeometry? borderRadius,
    double opacity = 0.82,
  }) {
    final bool isDark = brightness == Brightness.dark;
    final List<Color> colors = isDark
        ? [
            const Color(0xCC0F172A),
            const Color(0x880F172A),
          ]
        : [
            const Color(0xCCFFFFFF),
            const Color(0x99FFFFFF),
          ];
    return BoxDecoration(
      borderRadius: borderRadius ?? largeRadius,
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: colors
            .map((color) => color.withValues(alpha: opacity))
            .toList(growable: false),
      ),
      border: Border.all(color: _glassBorder(brightness)),
      boxShadow: elevatedShadow(brightness),
    );
  }

  static List<BoxShadow> elevatedShadow(Brightness brightness) => [
        BoxShadow(
          color: brightness == Brightness.dark
              ? Colors.black.withValues(alpha: 0.35)
              : const Color(0xFF4F46E5).withValues(alpha: 0.08),
          blurRadius: 32,
          spreadRadius: -12,
          offset: const Offset(0, 20),
        ),
        BoxShadow(
          color: brightness == Brightness.dark
              ? const Color(0x3322D3EE)
              : const Color(0x334F46E5),
          blurRadius: 24,
          spreadRadius: -10,
          offset: const Offset(0, 10),
        ),
      ];

  static Color _glassBorder(Brightness brightness) =>
      brightness == Brightness.dark
          ? const Color(0x33FFFFFF)
          : const Color(0x190F172A);
}
