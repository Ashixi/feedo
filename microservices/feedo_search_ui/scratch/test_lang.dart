import 'dart:convert';
import 'package:http/http.dart' as http;

void main() async {
  final url = Uri.parse('https://api.feedo.ink/feed?limit=200&source_type=nostr');
  final response = await http.get(url);
  final List<dynamic> data = jsonDecode(response.body);
  
  for (var item in data) {
    if (item.containsKey('language') || item.containsKey('lang')) {
      print('Root language: ${item['language']} or ${item['lang']}');
    }
    if (item['metadata'] != null) {
      if (item['metadata'].containsKey('language') || item['metadata'].containsKey('lang')) {
        print('Metadata language: ${item['metadata']['language']} or ${item['metadata']['lang']}');
      }
    }
  }
}
