import 'dart:convert';
import 'package:http/http.dart' as http;

void main() async {
  final url = Uri.parse('https://api.feedo.ink/feed?limit=20&source_type=nostr');
  final response = await http.get(url);
  final List<dynamic> data = json.decode(response.body);
  
  for (var item in data) {
    print('ID: ${item['id']}');
    print('Lang: ${item['language']}');
    print('Content Preview: ${item['text']}');
    print('---');
  }
}
