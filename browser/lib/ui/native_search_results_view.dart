import 'package:flutter/material.dart';

class NativeSearchResultsView extends StatelessWidget {
  final String query;
  final List<Map<String, dynamic>> feedoResults;
  final List<Map<String, String>> googleResults;
  final Function(String) onResultTap;

  const NativeSearchResultsView({
    super.key,
    required this.query,
    required this.feedoResults,
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
      padding: const EdgeInsets.all(24.0),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 24.0),
          child: Text(
            'Search Results for "$query"',
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
          ),
        ),
        
        // FeedoNet Results
        if (feedoResults.isNotEmpty) ...[
          const Padding(
            padding: EdgeInsets.only(bottom: 16.0),
            child: Text(
              'FeedoNet Results',
              style: TextStyle(
                fontSize: 14,
                color: Color(0xFF70757a),
              ),
            ),
          ),
          ...feedoResults.map((result) {
            final metadata = result['metadata'] ?? {};
            final title = metadata['title'] ?? 'Untitled Site';
            final description = metadata['description'] ?? result['text'] ?? '';
            final cid = result['hash_id'] ?? '';
            final score = result['score'] ?? 0.0;
            
            final p1 = cid.length >= 32 ? cid.substring(0, 32) : cid;
            final p2 = cid.length > 32 ? cid.substring(32) : '';
            
            String feedoUrl;
            String displayUrl;
            if (metadata.containsKey('url') && metadata['url'].toString().isNotEmpty) {
              final rawUrl = metadata['url'].toString();
              displayUrl = rawUrl.replaceAll(RegExp(r'^https?://'), '');
              feedoUrl = 'feedonet://$displayUrl';
            } else if (metadata.containsKey('domain') && metadata['domain'].toString().isNotEmpty) {
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
              badge: 'Relevance: ${(score * 100).toStringAsFixed(1)}%',
              onTap: () => onResultTap(feedoUrl),
              isFeedo: true,
            );
          }),
          const SizedBox(height: 32),
        ],

        // Google Results
        if (googleResults.isNotEmpty) ...[
          const Padding(
            padding: EdgeInsets.only(top: 16.0, bottom: 16.0),
            child: Text(
              'Web Results (Google)',
              style: TextStyle(
                fontSize: 14,
                color: Color(0xFF70757a),
              ),
            ),
          ),
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
      ],
    );
  }

  Widget _buildResultCard({
    required String title,
    required String link,
    required String snippet,
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
                  style: const TextStyle(color: Color(0xFF202124), fontSize: 14),
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
            style: const TextStyle(color: Color(0xFF4d5156), fontSize: 14, height: 1.4),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}
