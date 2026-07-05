import 'dart:convert';
import 'package:http/http.dart' as http;

void main() async {
  final url = Uri.parse('https://api.feedo.ink/feed?limit=50&source_type=nostr');
  final response = await http.get(url);
  final List<dynamic> data = json.decode(response.body);
  
  for (var item in data) {
    print('ID: ${item['id']} | Lang: ${item['language']} | Source: ${item['source_type']} | MetaLang: ${item['metadata']?['language']}');
  }
}
