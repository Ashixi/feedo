import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../layout/main_layout.dart';
import '../features/dashboard/dashboard_screen.dart';
import '../features/docs/docs_screen.dart';

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
            path: '/docs',
            builder: (context, state) => const DocsScreen(),
          ),

        ],
      ),
    ],
  );
});
