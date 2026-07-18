import 'package:flutter/material.dart';

/// Renders Google search results scraped from the hidden WebView.
/// Receives structured data: [{title, link, snippet}].
class GoogleSearchOverlay extends StatelessWidget {
  final List<Map<String, dynamic>> results;
  final String query;
  final VoidCallback onOpenAccount;
  final VoidCallback onOpenGmail;
  final VoidCallback onOpenYoutube;
  final Function(String) onResultTap;

  const GoogleSearchOverlay({
    super.key,
    required this.results,
    required this.query,
    required this.onOpenAccount,
    required this.onOpenGmail,
    required this.onOpenYoutube,
    required this.onResultTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (results.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(height: 60),
            const Icon(Icons.search_off, size: 48, color: Colors.grey),
            const SizedBox(height: 12),
            Text('No results for "$query"', style: theme.textTheme.titleMedium),
            const SizedBox(height: 20),
            // Quick link buttons even when no results
            _buildQuickLinks(context),
          ],
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 16),
      children: [
        // Quick links row
        _buildQuickLinks(context),
        const SizedBox(height: 20),
        // Results
        ...results.map((r) {
          final title = r['title']?.toString() ?? '';
          final link = r['link']?.toString() ?? '';
          final snippet = r['snippet']?.toString() ?? '';
          final displayUrl = link.replaceAll(RegExp(r'^https?://'), '').replaceAll(RegExp(r'/$'), '');
          return _buildResultCard(context, title, displayUrl, snippet, () => onResultTap(link));
        }),
      ],
    );
  }

  Widget _buildQuickLinks(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _quickLinkButton(context, Icons.account_circle, 'Account', onOpenAccount),
        const SizedBox(width: 16),
        _quickLinkButton(context, Icons.mail, 'Gmail', onOpenGmail),
        const SizedBox(width: 16),
        _quickLinkButton(context, Icons.play_circle_fill, 'YouTube', onOpenYoutube),
        const SizedBox(width: 16),
        _quickLinkButton(context, Icons.map, 'Maps', () => onResultTap('https://maps.google.com')),
      ],
    );
  }

  Widget _quickLinkButton(BuildContext context, IconData icon, String label, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        width: 72,
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(
          children: [
            Icon(icon, size: 28, color: Theme.of(context).colorScheme.primary),
            const SizedBox(height: 4),
            Text(label, style: const TextStyle(fontSize: 11)),
          ],
        ),
      ),
    );
  }

  Widget _buildResultCard(BuildContext context, String title, String displayUrl, String snippet, VoidCallback onTap) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxWidth: 652),
      margin: const EdgeInsets.only(bottom: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.public, size: 14, color: theme.colorScheme.onSurface.withOpacity(0.45)),
              const SizedBox(width: 6),
              Flexible(
                child: Text(displayUrl, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.secondary, fontSize: 13), maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ],
          ),
          const SizedBox(height: 4),
          InkWell(
            onTap: onTap,
            child: Text(title, style: TextStyle(fontSize: 18, color: theme.colorScheme.primary, decoration: TextDecoration.none)),
          ),
          const SizedBox(height: 4),
          if (snippet.isNotEmpty)
            Text(snippet, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurface.withOpacity(0.75), fontSize: 14), maxLines: 3, overflow: TextOverflow.ellipsis),
        ],
      ),
    );
  }
}