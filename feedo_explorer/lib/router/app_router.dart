import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../layout/main_layout.dart';
import '../features/dashboard/dashboard_screen.dart';
import '../features/explorer/content_explorer_screen.dart';
import '../features/explorer/vector_explorer_screen.dart';
import '../features/auth/api_keys_screen.dart';
import '../features/docs/docs_screen.dart';
import '../features/about/about_screen.dart';
import '../features/identities/identities_screen.dart';
import '../features/network/network_screen.dart';
import '../features/consensus/consensus_screen.dart';

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      ShellRoute(
        builder: (context, state, child) {
          return MainLayout(child: child);
        },
        routes: [
          GoRoute(
            path: '/',
            builder: (context, state) => const DashboardScreen(),
          ),
          GoRoute(
            path: '/identities',
            builder: (context, state) => const IdentitiesScreen(),
          ),
          GoRoute(
            path: '/network',
            builder: (context, state) => const NetworkScreen(),
          ),
          GoRoute(
            path: '/consensus',
            builder: (context, state) => const ConsensusScreen(),
          ),
          GoRoute(
            path: '/explorer/content',
            builder: (context, state) => const ContentExplorerScreen(),
          ),
          GoRoute(
            path: '/explorer/vectors',
            builder: (context, state) => const VectorExplorerScreen(),
          ),
          GoRoute(
            path: '/api-keys',
            builder: (context, state) => const WalletIdentityScreen(),
          ),
          GoRoute(
            path: '/docs',
            builder: (context, state) => const DocsScreen(),
          ),
          GoRoute(
            path: '/about',
            builder: (context, state) => const AboutScreen(),
          ),
        ],
      ),
    ],
  );
});
