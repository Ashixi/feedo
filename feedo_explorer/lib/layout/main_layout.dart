import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

class MainLayout extends StatelessWidget {
  final Widget child;
  const MainLayout({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isMobile = constraints.maxWidth < 800;

        if (isMobile) {
          return Scaffold(
            appBar: AppBar(
              title: const Text('Feedo Explorer'),
              backgroundColor: Theme.of(context).colorScheme.surface,
              elevation: 0,
            ),
            drawer: Drawer(
              child: _buildSidebar(context),
            ),
            body: Container(
              color: Theme.of(context).scaffoldBackgroundColor,
              child: child,
            ),
          );
        }

        return Scaffold(
          body: Row(
            children: [
              _buildSidebar(context),
              Expanded(
                child: Container(
                  color: Theme.of(context).scaffoldBackgroundColor,
                  child: child,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSidebar(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;

    return Container(
      width: 260,
      color: Theme.of(context).colorScheme.surface,
      child: Column(
        children: [
          const SizedBox(height: 32),
          // Logo
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                LucideIcons.boxes,
                color: Theme.of(context).colorScheme.primary,
                size: 32,
              ),
              const SizedBox(width: 12),
              const Text(
                'Feedo Explorer',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  letterSpacing: -0.5,
                ),
              ),
            ],
          ),
          const SizedBox(height: 48),

          _NavItem(
            icon: LucideIcons.layoutDashboard,
            label: 'Overview',
            isSelected: location == '/',
            onTap: () => context.go('/'),
          ),
          _NavItem(
            icon: LucideIcons.network,
            label: 'Network Topology',
            isSelected: location == '/network',
            onTap: () => context.go('/network'),
          ),
          _NavItem(
            icon: LucideIcons.fingerprint,
            label: 'Identities (DID)',
            isSelected: location == '/identities',
            onTap: () => context.go('/identities'),
          ),
          _NavItem(
            icon: LucideIcons.history,
            label: 'Consensus Logs',
            isSelected: location == '/consensus',
            onTap: () => context.go('/consensus'),
          ),
          const SizedBox(height: 16),
          const Divider(),
          const SizedBox(height: 16),
          _NavItem(
            icon: LucideIcons.search,
            label: 'Content Data',
            isSelected: location == '/explorer/content',
            onTap: () => context.go('/explorer/content'),
          ),
          _NavItem(
            icon: LucideIcons.database,
            label: 'Vector Space',
            isSelected: location == '/explorer/vectors',
            onTap: () => context.go('/explorer/vectors'),
          ),

          const Spacer(),
          const Divider(),
          const SizedBox(height: 16),

          _NavItem(
            icon: LucideIcons.key,
            label: 'API Keys',
            isSelected: location == '/api-keys',
            onTap: () => context.go('/api-keys'),
          ),
          _NavItem(
            icon: LucideIcons.bookOpen,
            label: 'Documentation',
            isSelected: location == '/docs',
            onTap: () => context.go('/docs'),
          ),
          _NavItem(
            icon: LucideIcons.info,
            label: 'About Project',
            isSelected: location == '/about',
            onTap: () => context.go('/about'),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _NavItem({
    required this.icon,
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          hoverColor: colorScheme.primary.withOpacity(0.1),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              color: isSelected
                  ? colorScheme.primary.withOpacity(0.15)
                  : Colors.transparent,
              border: Border.all(
                color: isSelected
                    ? colorScheme.primary.withOpacity(0.3)
                    : Colors.transparent,
              ),
            ),
            child: Row(
              children: [
                Icon(
                  icon,
                  size: 20,
                  color: isSelected
                      ? colorScheme.primary
                      : Colors.grey.shade400,
                ),
                const SizedBox(width: 12),
                Text(
                  label,
                  style: TextStyle(
                    color: isSelected
                        ? colorScheme.primary
                        : Colors.grey.shade300,
                    fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
