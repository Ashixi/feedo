import 'package:flutter/material.dart';

class NativeSearchResultsView extends StatelessWidget {
  final String query;
  final List<Map<String, dynamic>> feedoResults;
  final String? feedoError;
  final Function(String) onResultTap;

  const NativeSearchResultsView({
    super.key,
    required this.query,
    required this.feedoResults,
    this.feedoError,
    required this.onResultTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (feedoResults.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.search_off, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text(
              'No results found for "$query"',
              style: theme.textTheme.titleMedium?.copyWith(color: Colors.grey),
            ),
          ],
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 48.0, vertical: 24.0),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 24.0),
          child: Text(
            'Search Results for "$query"',
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.bold,
              color: theme.colorScheme.onSurface,
            ),
          ),
        ),
        if (feedoError != null)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 16.0),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.red.withOpacity(0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.red.withOpacity(0.3)),
            ),
            child: Text(
              'Search Node Error: $feedoError',
              style: const TextStyle(color: Colors.red),
            ),
          ),
        if (feedoResults.isEmpty && feedoError == null)
          const Text("No decentralized results found.")
        else
          ...feedoResults.map((result) {
            // --- Google result: flat {title, link, snippet} ---
            if (result.containsKey('link')) {
              final title = result['title']?.toString() ?? '';
              final link = result['link']?.toString() ?? '';
              final snippet = result['snippet']?.toString() ?? '';
              final displayUrl = link
                  .replaceAll(RegExp(r'^https?://'), '')
                  .replaceAll(RegExp(r'/$'), '');
              return _buildResultCard(
                context: context,
                title: title,
                displayUrl: displayUrl,
                snippet: snippet,
                metadata: null,
                duplicates: [],
                onTap: () => onResultTap(link),
              );
            }

            // --- Feedo result: {metadata: {...}, hash_id: ...} ---
            final metadata = result['metadata'] is Map
                ? Map<String, dynamic>.from(result['metadata'] as Map)
                : <String, dynamic>{};
            final cid = result['hash_id']?.toString() ?? '';

            final domain = metadata['domain']?.toString() ?? '';
            final title = (metadata['title']?.toString().isNotEmpty == true)
                ? metadata['title'].toString()
                : (domain.isNotEmpty ? domain : 'Untitled');

            final description = (metadata['description']?.toString().isNotEmpty == true)
                ? metadata['description'].toString()
                : (result['text']?.toString() ?? '');

            String feedoUrl;
            if (domain.isNotEmpty) {
              feedoUrl = 'feedonet://$domain';
            } else if (cid.length >= 64) {
              feedoUrl = 'feedonet://$cid';
            } else {
              feedoUrl = 'feedonet://$cid';
            }

            String displayUrl;
            if (domain.isNotEmpty) {
              displayUrl = domain;
            } else if (metadata.containsKey('url') &&
                metadata['url'].toString().isNotEmpty) {
              final rawUrl = metadata['url'].toString();
              displayUrl = rawUrl.replaceAll(RegExp(r'^https?://'), '');
              if (displayUrl.endsWith('/')) {
                displayUrl = displayUrl.substring(0, displayUrl.length - 1);
              }
            } else if (cid.length >= 64) {
              displayUrl =
                  'feedonet://${cid.substring(0, 8)}...${cid.substring(cid.length - 8)}';
            } else {
              displayUrl = 'feedonet://$cid';
            }

            final duplicatesRaw = result['duplicates'];
            final List<Map<String, dynamic>> duplicates = (duplicatesRaw is List)
                ? duplicatesRaw.cast<Map<String, dynamic>>()
                : [];

            return _buildResultCard(
              context: context,
              title: title,
              displayUrl: displayUrl,
              snippet: description,
              metadata: metadata,
              duplicates: duplicates,
              onTap: () => onResultTap(feedoUrl),
            );
          }),
      ],
    );
  }

  Widget _buildResultCard({
    required BuildContext context,
    required String title,
    required String displayUrl,
    required String snippet,
    Map<String, dynamic>? metadata,
    List<Map<String, dynamic>> duplicates = const [],
    required VoidCallback onTap,
  }) {
    final theme = Theme.of(context);

    final userTags = <String, String>{};
    if (metadata != null) {
      for (final e in metadata.entries) {
        final k = e.key;
        if (k == 'title' || k == 'description' || k == 'url' ||
            k == 'domain' || k == 'hash_id' || k == 'score' ||
            k == 'text') {
          continue;
        }
        userTags[k] = e.value.toString();
      }
    }

    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxWidth: 652),
      margin: const EdgeInsets.only(bottom: 28.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.public, size: 14, color: theme.colorScheme.onSurface.withOpacity(0.45)),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  displayUrl,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.secondary,
                    fontSize: 13,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          InkWell(
            onTap: onTap,
            hoverColor: Colors.transparent,
            child: Text(
              title,
              style: TextStyle(
                fontSize: 20,
                color: theme.colorScheme.primary,
                decoration: TextDecoration.none,
              ),
            ),
          ),
          const SizedBox(height: 6),
          if (snippet.isNotEmpty)
            Text(
              snippet,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurface.withOpacity(0.75),
                fontSize: 14,
                height: 1.45,
              ),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          if (userTags.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8.0,
              runSpacing: 6.0,
              children: userTags.entries
                  .map(
                    (e) => Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: theme.dividerColor.withOpacity(0.5)),
                      ),
                      child: Text(
                        '${e.key}: ${e.value}',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurface.withOpacity(0.55),
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
          ],
          if (duplicates.isNotEmpty) ...[
            const SizedBox(height: 10),
            _DuplicatesSection(duplicates: duplicates, theme: theme),
          ],
        ],
      ),
    );
  }

  String _displayUrlForDuplicate(Map<String, dynamic> dup) {
    final domain = (dup['domain'] ?? '').toString();
    final url = (dup['url'] ?? '').toString();
    final cid = (dup['hash_id'] ?? '').toString();
    if (domain.isNotEmpty) return domain;
    if (url.isNotEmpty) {
      var clean = url.replaceAll(RegExp(r'^https?://'), '');
      if (clean.endsWith('/')) clean = clean.substring(0, clean.length - 1);
      return clean;
    }
    if (cid.length >= 64) {
      return 'feedonet://${cid.substring(0, 8)}...${cid.substring(cid.length - 8)}';
    }
    return 'feedonet://$cid';
  }
}

class _DuplicatesSection extends StatefulWidget {
  final List<Map<String, dynamic>> duplicates;
  final ThemeData theme;
  const _DuplicatesSection({required this.duplicates, required this.theme});
  @override
  State<_DuplicatesSection> createState() => _DuplicatesSectionState();
}

class _DuplicatesSectionState extends State<_DuplicatesSection> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final count = widget.duplicates.length;
    final label = count == 1
        ? '1 duplicate (same content, different source)'
        : '$count duplicates (same content, different sources)';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => setState(() => _expanded = !_expanded),
          borderRadius: BorderRadius.circular(6),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 2),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(_expanded ? Icons.expand_less : Icons.expand_more, size: 18, color: widget.theme.colorScheme.primary.withOpacity(0.7)),
                const SizedBox(width: 4),
                Icon(Icons.content_copy, size: 14, color: widget.theme.colorScheme.onSurface.withOpacity(0.4)),
                const SizedBox(width: 6),
                Text(label, style: widget.theme.textTheme.bodySmall?.copyWith(color: widget.theme.colorScheme.onSurface.withOpacity(0.55), fontSize: 12)),
              ],
            ),
          ),
        ),
        if (_expanded) ...[
          const SizedBox(height: 4),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: widget.theme.colorScheme.surfaceContainerHighest.withOpacity(0.4),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: widget.theme.dividerColor.withOpacity(0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: widget.duplicates.map((dup) {
                final idx = widget.duplicates.indexOf(dup);
                final displayUrl = _displayUrlForDuplicateStatic(dup);
                return Padding(
                  padding: EdgeInsets.only(top: idx == 0 ? 0 : 8, bottom: idx == widget.duplicates.length - 1 ? 0 : 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.link, size: 14, color: widget.theme.colorScheme.secondary.withOpacity(0.6)),
                      const SizedBox(width: 6),
                      Expanded(child: Text(displayUrl, style: widget.theme.textTheme.bodySmall?.copyWith(color: widget.theme.colorScheme.secondary.withOpacity(0.7), fontSize: 12), maxLines: 1, overflow: TextOverflow.ellipsis)),
                    ],
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ],
    );
  }

  static String _displayUrlForDuplicateStatic(Map<String, dynamic> dup) {
    final domain = (dup['domain'] ?? '').toString();
    final url = (dup['url'] ?? '').toString();
    final cid = (dup['hash_id'] ?? '').toString();
    if (domain.isNotEmpty) return domain;
    if (url.isNotEmpty) {
      var clean = url.replaceAll(RegExp(r'^https?://'), '');
      if (clean.endsWith('/')) clean = clean.substring(0, clean.length - 1);
      return clean;
    }
    if (cid.length >= 64) {
      return 'feedonet://${cid.substring(0, 8)}...${cid.substring(cid.length - 8)}';
    }
    return 'feedonet://$cid';
  }
}