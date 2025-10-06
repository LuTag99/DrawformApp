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
      final loggingIn = state.subloc == '/login' ||
          state.subloc == '/register' ||
          state.subloc == '/forgot-password';
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
        title: 'Drawform',
        theme: _buildLightTheme(),
        darkTheme: _buildDarkTheme(),
        routerConfig: _router,
      ),
    );
  }

  /// Light theme inspired by Apple's design guidelines.
  ThemeData _buildLightTheme() {
    return ThemeData(
      colorScheme: ColorScheme.light(
        primary: CupertinoColors.activeBlue,
        secondary: CupertinoColors.systemGrey,
        background: CupertinoColors.systemGroupedBackground,
      ),
      useMaterial3: true,
      typography: Typography.material2021(
        platform: TargetPlatform.iOS,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: CupertinoColors.systemGrey6,
        foregroundColor: CupertinoColors.black,
        elevation: 0,
        centerTitle: true,
      ),
      scaffoldBackgroundColor: CupertinoColors.systemGroupedBackground,
      cupertinoOverrideTheme: const CupertinoThemeData(
        brightness: Brightness.light,
        primaryColor: CupertinoColors.activeBlue,
        barBackgroundColor: CupertinoColors.systemGrey6,
      ),
    );
  }

  /// Dark theme inspired by Apple's design guidelines.
  ThemeData _buildDarkTheme() {
    return ThemeData(
      colorScheme: const ColorScheme.dark(
        primary: CupertinoColors.activeBlue,
        secondary: CupertinoColors.systemGrey,
        background: CupertinoColors.systemGrey6,
      ),
      useMaterial3: true,
      typography: Typography.material2021(
        platform: TargetPlatform.iOS,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: CupertinoColors.systemGrey5,
        foregroundColor: CupertinoColors.white,
        elevation: 0,
        centerTitle: true,
      ),
      scaffoldBackgroundColor: CupertinoColors.systemGrey6,
      cupertinoOverrideTheme: const CupertinoThemeData(
        brightness: Brightness.dark,
        primaryColor: CupertinoColors.activeBlue,
        barBackgroundColor: CupertinoColors.systemGrey5,
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
    _tabController = CupertinoTabController(index: _selectedIndex);
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
    return CupertinoTabScaffold(
      controller: _tabController,
      tabBar: CupertinoTabBar(
        currentIndex: _selectedIndex,
        onTap: _handleDestination,
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
          backgroundColor: CupertinoColors.systemGroupedBackground,
          navigationBar: CupertinoNavigationBar(
            middle: Text(_titleForIndex(index)),
            trailing: CupertinoButton(
              padding: EdgeInsets.zero,
              onPressed: () {
                context.read<AuthController>().logout();
                context.go('/login');
              },
              child: const Icon(CupertinoIcons.square_arrow_right),
            ),
          ),
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: _AnimatedSwitcher(
                child: _contentForIndex(index),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildWideLayout(BuildContext context) {
    final auth = context.watch<AuthController>();
    return CupertinoPageScaffold(
      backgroundColor: CupertinoColors.systemGroupedBackground,
      child: Row(
        children: [
          Container(
            width: 260,
            decoration: BoxDecoration(
              color: CupertinoColors.systemGrey5.withOpacity(0.7),
              border: const Border(
                right: BorderSide(color: CupertinoColors.separator),
              ),
            ),
            child: SafeArea(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          auth.email ?? 'Willkommen',
                          style: CupertinoTheme.of(context)
                              .textTheme
                              .navTitleTextStyle,
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Drawform',
                          style: CupertinoTheme.of(context)
                              .textTheme
                              .tabLabelTextStyle
                              .copyWith(color: CupertinoColors.systemGrey),
                        ),
                      ],
                    ),
                  ),
                  const Divider(height: 1, color: CupertinoColors.separator),
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
                  const Divider(height: 1, color: CupertinoColors.separator),
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: CupertinoButton(
                      color: CupertinoColors.destructiveRed,
                      onPressed: () {
                        context.read<AuthController>().logout();
                        context.go('/login');
                      },
                      child: const Text('Abmelden'),
                    ),
                  ),
                ],
              ),
            ),
          ),
          Expanded(
            child: SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(28),
                  child: DecoratedBox(
                    decoration: const BoxDecoration(
                      color: CupertinoColors.systemBackground,
                    ),
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: _AnimatedSwitcher(
                        child: _contentForIndex(_selectedIndex),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
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
    final theme = CupertinoTheme.of(context);
    final color = selected
        ? theme.primaryColor
        : CupertinoColors.label.resolveFrom(context).withOpacity(0.7);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: CupertinoButton(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        color: selected
            ? theme.primaryColor.withOpacity(0.15)
            : CupertinoColors.systemGrey6,
        borderRadius: BorderRadius.circular(16),
        onPressed: onTap,
        child: Row(
          children: [
            Icon(icon, color: color),
            const SizedBox(width: 12),
            Text(
              label,
              style: theme.textTheme.textStyle.copyWith(
                color: color,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ],
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
