import 'dart:convert';
import 'package:http/http.dart' as http;

class GoogleScraper {
  /// Returns search results using Google Custom Search JSON API.
  /// Falls back to HTML scraping if apiKey/cx are not provided.
  static Future<List<Map<String, dynamic>>> search(
    String query, {
    String? apiKey,
    String? cx,
  }) async {
    // Try Custom Search API first
    if (apiKey != null && apiKey.isNotEmpty && cx != null && cx.isNotEmpty) {
      final results = await _searchViaApi(query, apiKey, cx);
      if (results.isNotEmpty) return results;
    }
    // Fallback: HTML scraping (may be blocked by Google)
    return await _searchViaScraping(query);
  }

  /// Google Custom Search JSON API.
  static Future<List<Map<String, dynamic>>> _searchViaApi(
    String query, String apiKey, String cx,
  ) async {
    try {
      final encodedQuery = Uri.encodeComponent(query);
      final url = Uri.parse(
        'https://www.googleapis.com/customsearch/v1?key=$apiKey&cx=$cx&q=$encodedQuery',
      );
      final response = await http.get(url);
      if (response.statusCode != 200) return [];
      
      final data = jsonDecode(response.body);
      final items = data['items'] as List<dynamic>? ?? [];
      final results = <Map<String, dynamic>>[];
      for (final item in items) {
        results.add({
          'title': item['title']?.toString() ?? '',
          'link': item['link']?.toString() ?? '',
          'url': item['link']?.toString() ?? '',
          'snippet': item['snippet']?.toString() ?? '',
        });
      }
      return results;
    } catch (e) {
      print('Google API error: $e');
      return [];
    }
  }

  /// HTML scraping fallback (may be blocked by Google).
  static Future<List<Map<String, dynamic>>> _searchViaScraping(String query) async {
    // HTML scraping is unreliable — return empty to signal failure cleanly.
    print('Google Scraper: no API key provided, skipping HTML scraping');
    return [];
  }
}