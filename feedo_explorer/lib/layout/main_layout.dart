import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:feedo_explorer/l10n/app_localizations.dart';
import '../core/locale_provider.dart';

class MainLayout extends ConsumerWidget {
  final Widget child;
  const MainLayout({super.key, required this.child});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final loc = AppLocalizations.of(context)!;
    
    return LayoutBuilder(
      builder: (context, constraints) {
        final isMobile = constraints.maxWidth < 1000;

        return Scaffold(
          backgroundColor: const Color(0xFF0A0A0A), // Sleek dark background
          appBar: AppBar(
            backgroundColor: const Color(0xFF0A0A0A).withOpacity(0.9),
            elevation: 0,
            title: Row(
              children: [
                Image.asset(
                  'assets/logo.png',
                  height: 32,
                  errorBuilder: (context, error, stackTrace) => Icon(
                    LucideIcons.boxes,
                    color: Theme.of(context).colorScheme.primary,
                    size: 32,
                  ),
                ),
                const SizedBox(width: 12),
                const Text(
                  'Feedo',
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    letterSpacing: -0.5,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
            actions: isMobile
                ? null
                : [
                    _TopNavItem(
                      label: loc.overview,
                      isSelected: GoRouterState.of(context).uri.path == '/',
                      onTap: () => context.go('/'),
                    ),
                    _TopNavItem(
                      label: loc.network,
                      isSelected: GoRouterState.of(context).uri.path == '/network',
                      onTap: () => context.go('/network'),
                    ),
                    _TopNavItem(
                      label: loc.identities,
                      isSelected: GoRouterState.of(context).uri.path == '/identities',
                      onTap: () => context.go('/identities'),
                    ),
                    _TopNavItem(
                      label: loc.consensus,
                      isSelected: GoRouterState.of(context).uri.path == '/consensus',
                      onTap: () => context.go('/consensus'),
                    ),
                    _TopNavItem(
                      label: loc.docs,
                      isSelected: GoRouterState.of(context).uri.path == '/docs',
                      onTap: () => context.go('/docs'),
                    ),
                    const SizedBox(width: 16),
                    _LanguageSwitcher(),
                    const SizedBox(width: 24),
                  ],
          ),
          drawer: isMobile ? _buildMobileDrawer(context, ref) : null,
          body: child,
        );
      },
    );
  }

  Widget _buildMobileDrawer(BuildContext context, WidgetRef ref) {
    final location = GoRouterState.of(context).uri.path;
    final loc = AppLocalizations.of(context)!;

    return Drawer(
      backgroundColor: const Color(0xFF121212),
      child: Column(
        children: [
          DrawerHeader(
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Colors.white10)),
            ),
            child: Row(
              children: [
                Image.asset(
                  'assets/logo.png',
                  height: 32,
                  errorBuilder: (context, error, stackTrace) => Icon(
                    LucideIcons.boxes,
                    color: Theme.of(context).colorScheme.primary,
                    size: 32,
                  ),
                ),
                const SizedBox(width: 12),
                const Text(
                  'Feedo',
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
          ),
          _DrawerItem(
            icon: LucideIcons.layoutDashboard,
            label: loc.overview,
            isSelected: location == '/',
            onTap: () {
              Navigator.pop(context);
              context.go('/');
            },
          ),
          _DrawerItem(
            icon: LucideIcons.network,
            label: loc.networkTopology,
            isSelected: location == '/network',
            onTap: () {
              Navigator.pop(context);
              context.go('/network');
            },
          ),
          _DrawerItem(
            icon: LucideIcons.fingerprint,
            label: loc.identitiesDid,
            isSelected: location == '/identities',
            onTap: () {
              Navigator.pop(context);
              context.go('/identities');
            },
          ),
          _DrawerItem(
            icon: LucideIcons.history,
            label: loc.consensusLogs,
            isSelected: location == '/consensus',
            onTap: () {
              Navigator.pop(context);
              context.go('/consensus');
            },
          ),
          const Divider(color: Colors.white10, height: 32),
          _DrawerItem(
            icon: LucideIcons.bookOpen,
            label: loc.documentation,
            isSelected: location == '/docs',
            onTap: () {
              Navigator.pop(context);
              context.go('/docs');
            },
          ),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Row(
              children: [
                Icon(LucideIcons.globe, color: Colors.white70),
                const SizedBox(width: 16),
                _LanguageSwitcher(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LanguageSwitcher extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider) ?? const Locale('en');
    
    return DropdownButton<String>(
      value: locale.languageCode,
      dropdownColor: const Color(0xFF1E1E1E),
      underline: const SizedBox(),
      icon: const Icon(Icons.arrow_drop_down, color: Colors.white70),
      style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold),
      onChanged: (String? newLanguage) {
        if (newLanguage != null) {
          ref.read(localeProvider.notifier).setLocale(Locale(newLanguage));
        }
      },
      items: const [
        DropdownMenuItem(
          value: 'en',
          child: Text('EN'),
        ),
        DropdownMenuItem(
          value: 'uk',
          child: Text('UK'),
        ),
      ],
    );
  }
}

class _TopNavItem extends StatelessWidget {
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _TopNavItem({
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8.0, vertical: 12),
      child: TextButton(
        onPressed: onTap,
        style: TextButton.styleFrom(
          foregroundColor: isSelected ? Colors.white : Colors.white70,
          backgroundColor: isSelected ? Colors.white.withOpacity(0.1) : Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 15,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
          ),
        ),
      ),
    );
  }
}

class _DrawerItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _DrawerItem({
    required this.icon,
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(
        icon,
        color: isSelected ? Theme.of(context).colorScheme.primary : Colors.white70,
      ),
      title: Text(
        label,
        style: TextStyle(
          color: isSelected ? Colors.white : Colors.white70,
          fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
        ),
      ),
      selected: isSelected,
      selectedTileColor: Colors.white.withOpacity(0.05),
      onTap: onTap,
    );
  }
}
