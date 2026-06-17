import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'router/app_router.dart';
import 'theme/app_theme.dart';

import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:feedo_explorer/l10n/app_localizations.dart';
import 'core/locale_provider.dart';

void main() {
  runApp(
    const ProviderScope(
      child: FeedoExplorerApp(),
    ),
  );
}

class FeedoExplorerApp extends ConsumerWidget {
  const FeedoExplorerApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final locale = ref.watch(localeProvider);

    return MaterialApp.router(
      title: 'Feedo Explorer',
      theme: AppTheme.darkTheme,
      routerConfig: router,
      debugShowCheckedModeBanner: false,
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
    );
  }
}
