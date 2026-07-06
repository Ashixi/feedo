import 'package:http/http.dart' as http;
import 'package:html/parser.dart' as parser;

class GoogleScraper {
  static Future<List<Map<String, String>>> search(String query) async {
    try {
      final encodedQuery = Uri.encodeComponent(query);
      final url = Uri.parse('https://www.google.com/search?q=$encodedQuery&hl=uk');
      final response = await http.get(
        url,
        headers: {
          'User-Agent':
              'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
        },
      );

      if (response.statusCode == 200) {
        final document = parser.parse(response.body);
        // In Google search, results are typically inside div.g
        final elements = document.querySelectorAll('div.g');
        final List<Map<String, String>> results = [];

        for (var element in elements) {
          final titleElement = element.querySelector('h3');
          final linkElement = element.querySelector('a');
          // Various classes Google uses for snippets
          final snippetElement =
              element.querySelector('div.VwiC3b, div.IsZvec, div.s');

          final title = titleElement?.text ?? '';
          final link = linkElement?.attributes['href'] ?? '';
          final snippet = snippetElement?.text ?? '';

          if (title.isNotEmpty && link.isNotEmpty && link.startsWith('http')) {
            results.add({
              'title': title,
              'link': link,
              'snippet': snippet,
            });
          }
        }
        return results;
      }
    } catch (e) {
      print('Google Scraper Error: $e');
    }
    return [];
  }
}
