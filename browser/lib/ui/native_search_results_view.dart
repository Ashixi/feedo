import 'package:flutter/material.dart';

class NativeSearchResultsView extends StatelessWidget {
  final String query;
  final List<Map<String, dynamic>> feedoResults;
  final String? feedoError;
  final List<Map<String, String>> googleResults;
  final Function(String) onResultTap;

  const NativeSearchResultsView({
    super.key,
    required this.query,
    required this.feedoResults,
    this.feedoError,
    required this.googleResults,
    required this.onResultTap,
  });

  @override
  Widget build(BuildContext context) {
    if (feedoResults.isEmpty && googleResults.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.search_off, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text(
              'No results found for "$query"',
              style: const TextStyle(fontSize: 18, color: Colors.grey),
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
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
          ),
        ),

        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Left Column: FeedoNet Results
            Expanded(
              flex: 3,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(bottom: 16.0),
                    child: Text(
                      'FeedoNet Results',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF70757a),
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
                      final metadata = result['metadata'] ?? {};
                      final title = metadata['title'] ?? 'Untitled Site';
                      final description =
                          metadata['description'] ?? result['text'] ?? '';
                      final cid = result['hash_id'] ?? '';
                      final score = result['score'] ?? 0.0;

                      final p1 = cid.length >= 32 ? cid.substring(0, 32) : cid;
                      final p2 = cid.length > 32 ? cid.substring(32) : '';

                      String feedoUrl;
                      String displayUrl;
                      if (metadata.containsKey('url') &&
                          metadata['url'].toString().isNotEmpty) {
                        final rawUrl = metadata['url'].toString();
                        displayUrl = rawUrl.replaceAll(
                          RegExp(r'^https?://'),
                          '',
                        );
                        feedoUrl = 'feedonet://$displayUrl';
                      } else if (metadata.containsKey('domain') &&
                          metadata['domain'].toString().isNotEmpty) {
                        displayUrl = metadata['domain'].toString();
                        feedoUrl = 'feedonet://$displayUrl';
                      } else {
                        displayUrl = 'feedonet://$p1.$p2';
                        feedoUrl = 'feedonet://$cid';
                      }

                      return _buildResultCard(
                        title: title,
                        link: displayUrl,
                        snippet: description,
                        metadata: metadata,
                        badge:
                            'Relevance: ${(score * 100).toStringAsFixed(1)}%',
                        onTap: () => onResultTap(feedoUrl),
                        isFeedo: true,
                      );
                    }),
                ],
              ),
            ),
            const SizedBox(width: 48),
            // Right Column: Google Results
            Expanded(
              flex: 2,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(bottom: 16.0),
                    child: Text(
                      'Web Results (Google)',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF70757a),
                      ),
                    ),
                  ),
                  if (googleResults.isEmpty)
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: Colors.orange.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: Colors.orange.withOpacity(0.3),
                        ),
                      ),
                      child: const Text(
                        'Google Web Search failed to load or returned 0 results (Scraper blocked by CAPTCHA/Limits).',
                        style: TextStyle(color: Colors.deepOrange),
                      ),
                    )
                  else
                    ...googleResults.map((result) {
                      return _buildResultCard(
                        title: result['title'] ?? '',
                        link: result['link'] ?? '',
                        snippet: result['snippet'] ?? '',
                        onTap: () => onResultTap(result['link'] ?? ''),
                        isFeedo: false,
                      );
                    }),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildResultCard({
    required String title,
    required String link,
    required String snippet,
    Map<String, dynamic>? metadata,
    String? badge,
    required VoidCallback onTap,
    required bool isFeedo,
  }) {
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxWidth: 652),
      margin: const EdgeInsets.only(bottom: 28.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (isFeedo) ...[
                const Icon(Icons.public, size: 16, color: Colors.grey),
                const SizedBox(width: 8),
              ],
              Expanded(
                child: Text(
                  link,
                  style: const TextStyle(
                    color: Color(0xFF202124),
                    fontSize: 14,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          InkWell(
            onTap: onTap,
            hoverColor: Colors.transparent,
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 20,
                color: Color(0xFF1a0dab), // Google Blue
              ),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            snippet,
            style: const TextStyle(
              color: Color(0xFF4d5156),
              fontSize: 14,
              height: 1.4,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          if (isFeedo && metadata != null) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8.0,
              runSpacing: 8.0,
              children: metadata.entries
                  .where(
                    (e) =>
                        e.key != 'title' &&
                        e.key != 'description' &&
                        e.key != 'url' &&
                        e.key != 'domain',
                  )
                  .map(
                    (e) => Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.grey.shade100,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: Colors.grey.shade300),
                      ),
                      child: Text(
                        '${e.key}: ${e.value}',
                        style: TextStyle(
                          fontSize: 11,
                          color: Colors.grey.shade700,
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }
}
