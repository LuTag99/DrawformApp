import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:python_ffi/python_ffi.dart';

import 'pages/auth/forgot_password_page.dart';
import 'pages/auth/login_page.dart';
import 'pages/auth/register_page.dart';
import 'pages/dashboard_page.dart';
import 'pages/export_page.dart';
import 'pages/profile_settings_page.dart';
import 'pages/project_overview_page.dart';
import 'services/auth_service.dart';
import 'theme/ai_theme.dart';
import 'widgets/ai_background.dart';
import 'widgets/ai_gradient_button.dart';

/// Entry point of the Drawform application.
///
/// This application demonstrates how to integrate a Python runtime into a
/// cross‑platform Flutter app. The Python runtime is embedded on desktop
/// platforms via the `python_ffi` package【50642741854547†L191-L194】. For web, you may
/// need to provide an alternative implementation (for example, a remote
/// service that exposes your Python functionality over HTTP). See
/// [PythonService] for details.
Future<void> main() async {
  // Ensure Flutter binding is initialised before calling FFI.
  WidgetsFlutterBinding.ensureInitialized();
  // Initialise the embedded Python runtime. On unsupported platforms (e.g.
  // web) this will throw; catch and ignore so that the app can still start.
  try {
    await PythonFfi.instance.initialize();
  } catch (e) {
    // Running on an unsupported platform (e.g. web) – ignore initialisation.
    debugPrint('Python runtime not available: $e');
  }
  runApp(const MyApp());
}

/// Root widget of the Drawform app.
class MyApp extends StatelessWidget {
  const MyApp({super.key});

  static final AuthController _authController = AuthController();

  static final GoRouter _router = GoRouter(
    initialLocation: '/login',
    refreshListenable: _authController,
    redirect: (context, state) {
      final loggedIn = _authController.isAuthenticated;
      final location = state.location;
      final loggingIn = location == '/login' ||
          location == '/register' ||
          location == '/forgot-password';
      if (!loggedIn && !loggingIn) {
        return '/login';
      }
      if (loggedIn && loggingIn) {
        return state.queryParameters['from'] ?? '/';
      }
      return null;
    },
    routes: <RouteBase>[
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginPage(),
      ),
      GoRoute(
        path: '/register',
        builder: (context, state) => const RegisterPage(),
      ),
      GoRoute(
        path: '/forgot-password',
        builder: (context, state) => const ForgotPasswordPage(),
      ),
      GoRoute(
        path: '/',
        builder: (context, state) => const HomeShell(selectedIndex: 0),
      ),
      GoRoute(
        path: '/dashboard',
        builder: (context, state) => const HomeShell(selectedIndex: 1),
      ),
      GoRoute(
        path: '/export',
        builder: (context, state) => const HomeShell(selectedIndex: 2),
      ),
      GoRoute(
        path: '/profile',
        builder: (context, state) => const HomeShell(selectedIndex: 3),
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    // Der Router hängt am AuthController, daher stellen wir diesen global bereit.
    return ChangeNotifierProvider<AuthController>.value(
      value: _authController,
      child: MaterialApp.router(
        title: 'Drawform AI',
        theme: AiTheme.materialLight(),
        darkTheme: AiTheme.materialDark(),
        themeMode: ThemeMode.system,
        debugShowCheckedModeBanner: false,
        routerConfig: _router,
      ),
    );
  }

}

/// HomeShell bildet das Layout nach iOS-Vorbild: auf Mobilgeräten mit
/// Tab-Navigation, auf großen Displays mit einer Seitenleiste.
class HomeShell extends StatefulWidget {
  final int selectedIndex;

  const HomeShell({super.key, required this.selectedIndex});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  late int _selectedIndex;
  late CupertinoTabController _tabController;

  @override
  void initState() {
    super.initState();
    _selectedIndex = widget.selectedIndex;
    _tabController = CupertinoTabController(initialIndex: _selectedIndex);
  }

  @override
  void didUpdateWidget(HomeShell oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedIndex != widget.selectedIndex) {
      _selectedIndex = widget.selectedIndex;
      _tabController.index = _selectedIndex;
    }
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _handleDestination(int index) {
    if (index == _selectedIndex) {
      return;
    }
    setState(() {
      _selectedIndex = index;
      _tabController.index = index;
    });
    switch (index) {
      case 0:
        context.go('/');
        break;
      case 1:
        context.go('/dashboard');
        break;
      case 2:
        context.go('/export');
        break;
      case 3:
        context.go('/profile');
        break;
    }
  }

  String _titleForIndex(int index) {
    switch (index) {
      case 0:
        return 'Projekte';
      case 1:
        return 'Dashboard';
      case 2:
        return 'Export';
      case 3:
        return 'Profil';
      default:
        return 'Drawform';
    }
  }

  Widget _contentForIndex(int index) {
    switch (index) {
      case 0:
        return const ProjectOverviewPage(key: ValueKey('projects'));
      case 1:
        return const DashboardPage(key: ValueKey('dashboard'));
      case 2:
        return const ExportPage(key: ValueKey('export'));
      case 3:
        return const ProfileSettingsPage(key: ValueKey('profile'));
      default:
        return const Center(child: Text('Unbekannte Seite'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.of(context).size.width >= 900;
    if (isWide) {
      return _buildWideLayout(context);
    }
    return _buildCupertinoTabs(context);
  }

  Widget _buildCupertinoTabs(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final Color barBackground =
        AiTheme.glassSurfaceColor.resolveFrom(context).withValues(alpha: 0.82);
    final Color activeColor = Theme.of(context).colorScheme.secondary;
    final Color inactiveColor = (CupertinoTheme.of(context)
                .textTheme
                .tabLabelTextStyle
                .color ??
            activeColor)
        .withValues(alpha: 0.6);

    return AiBackground(
      child: CupertinoTabScaffold(
        controller: _tabController,
        tabBar: CupertinoTabBar(
          currentIndex: _selectedIndex,
          onTap: _handleDestination,
          backgroundColor: barBackground,
          activeColor: activeColor,
          inactiveColor: inactiveColor,
          border: const Border(
            top: BorderSide(color: Color(0x1AFFFFFF), width: 0.5),
          ),
          items: const [
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.folder),
              label: 'Projekte',
            ),
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.chart_bar),
              label: 'Dashboard',
            ),
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.square_arrow_down),
              label: 'Export',
            ),
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.person),
              label: 'Profil',
            ),
          ],
        ),
        tabBuilder: (context, index) {
          return CupertinoPageScaffold(
            backgroundColor: Colors.transparent,
            navigationBar: CupertinoNavigationBar(
              backgroundColor: AiTheme.glassSurfaceColor
                  .resolveFrom(context)
                  .withValues(alpha: 0.9),
              border: null,
              middle: ShaderMask(
                shaderCallback: (Rect bounds) =>
                    AiTheme.accentGradient(brightness).createShader(bounds),
                blendMode: BlendMode.srcIn,
                child: Text(
                  _titleForIndex(index),
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 18,
                  ),
                ),
              ),
              trailing: _LogoutButton(
                onPressed: () {
                  context.read<AuthController>().logout();
                  context.go('/login');
                },
              ),
            ),
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
                child: ClipRRect(
                  borderRadius: AiTheme.largeRadius,
                  child: DecoratedBox(
                    decoration: AiTheme.glassSurface(
                      brightness: brightness,
                      borderRadius: AiTheme.largeRadius,
                      opacity: 0.9,
                    ),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 12,
                      ),
                      child: _AnimatedSwitcher(
                        child: _contentForIndex(index),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildWideLayout(BuildContext context) {
    final auth = context.watch<AuthController>();
    final brightness = Theme.of(context).brightness;
    final textStyle = CupertinoTheme.of(context).textTheme.textStyle;

    return AiBackground(
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Row(
            children: [
              SizedBox(
                width: 280,
                child: DecoratedBox(
                  decoration: AiTheme.glassSurface(
                    brightness: brightness,
                    borderRadius: AiTheme.largeRadius,
                    opacity: 0.9,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(24, 28, 24, 18),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ShaderMask(
                              shaderCallback: (Rect bounds) =>
                                  AiTheme.accentGradient(brightness)
                                      .createShader(bounds),
                              blendMode: BlendMode.srcIn,
                              child: const Text(
                                'Drawform AI',
                                style: TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              auth.email ?? 'Willkommen',
                              style: textStyle.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 12),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 12,
                                vertical: 8,
                              ),
                              decoration: BoxDecoration(
                                gradient: AiTheme.primaryGradient(brightness),
                                borderRadius: BorderRadius.circular(16),
                              ),
                              child: const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(
                                    CupertinoIcons.sparkles,
                                    size: 14,
                                    color: Colors.white,
                                  ),
                                  SizedBox(width: 6),
                                  Text(
                                    'AI aktiv',
                                    style: TextStyle(
                                      color: Colors.white,
                                      fontSize: 12,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      Expanded(
                        child: ListView(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          children: [
                            _SideNavButton(
                              label: 'Projekte',
                              icon: CupertinoIcons.folder,
                              selected: _selectedIndex == 0,
                              onTap: () => _handleDestination(0),
                            ),
                            _SideNavButton(
                              label: 'Dashboard',
                              icon: CupertinoIcons.chart_bar,
                              selected: _selectedIndex == 1,
                              onTap: () => _handleDestination(1),
                            ),
                            _SideNavButton(
                              label: 'Export',
                              icon: CupertinoIcons.square_arrow_down,
                              selected: _selectedIndex == 2,
                              onTap: () => _handleDestination(2),
                            ),
                            _SideNavButton(
                              label: 'Profil',
                              icon: CupertinoIcons.person,
                              selected: _selectedIndex == 3,
                              onTap: () => _handleDestination(3),
                            ),
                          ],
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                        child: AiGradientButton(
                          label: 'Abmelden',
                          onPressed: () {
                            context.read<AuthController>().logout();
                            context.go('/login');
                          },
                          leading: const Icon(
                            CupertinoIcons.square_arrow_right,
                            size: 18,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 24),
              Expanded(
                child: ClipRRect(
                  borderRadius: AiTheme.largeRadius,
                  child: DecoratedBox(
                    decoration: AiTheme.glassSurface(
                      brightness: brightness,
                      borderRadius: AiTheme.largeRadius,
                      opacity: 0.92,
                    ),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 20,
                      ),
                      child: _AnimatedSwitcher(
                        child: _contentForIndex(_selectedIndex),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SideNavButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _SideNavButton({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final Color baseColor =
        AiTheme.glassSurfaceColor.resolveFrom(context).withValues(alpha: 0.35);
    final Color textColor = selected
        ? Colors.white
        : CupertinoTheme.of(context)
            .textTheme
            .textStyle
            .color
            ?.withValues(alpha: 0.75) ??
        Colors.white70;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 6),
      child: CupertinoButton(
        padding: EdgeInsets.zero,
        borderRadius: BorderRadius.circular(18),
        onPressed: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeInOut,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          decoration: selected
              ? BoxDecoration(
                  gradient: AiTheme.accentGradient(brightness),
                  borderRadius: BorderRadius.circular(18),
                  boxShadow: AiTheme.elevatedShadow(brightness),
                )
              : BoxDecoration(
                  color: baseColor,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(
                    color: AiTheme.glassSurfaceColor
                        .resolveFrom(context)
                        .withValues(alpha: 0.2),
                  ),
                ),
          child: Row(
            children: [
              Icon(
                icon,
                color: selected ? Colors.white : textColor,
                size: 18,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  label,
                  style: CupertinoTheme.of(context).textTheme.textStyle.copyWith(
                        color: textColor,
                        fontWeight:
                            selected ? FontWeight.w600 : FontWeight.w400,
                        letterSpacing: 0.2,
                      ),
                ),
              ),
              if (selected)
                const Icon(
                  CupertinoIcons.arrow_right,
                  size: 16,
                  color: Colors.white,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _LogoutButton extends StatelessWidget {
  const _LogoutButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return CupertinoButton(
      padding: EdgeInsets.zero,
      onPressed: onPressed,
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: AiTheme.accentGradient(brightness),
          borderRadius: BorderRadius.circular(18),
          boxShadow: AiTheme.elevatedShadow(brightness),
        ),
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Icon(
            CupertinoIcons.square_arrow_right,
            color: Colors.white,
            size: 20,
          ),
        ),
      ),
    );
  }
}

class _AnimatedSwitcher extends StatelessWidget {
  final Widget child;

  const _AnimatedSwitcher({required this.child});

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 250),
      transitionBuilder: (child, animation) => FadeTransition(
        opacity: animation,
        child: child,
      ),
      child: KeyedSubtree(
        key: ValueKey(child.key ?? child.runtimeType),
        child: child,
      ),
    );
  }
}
