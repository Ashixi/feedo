import 'dart:convert';
import 'package:http/http.dart' as http;

void main() async {
  final url = Uri.parse('https://api.feedo.ink/feed?limit=50&source_type=nostr');
  final response = await http.get(url).timeout(Duration(seconds: 10));
  final List<dynamic> data = jsonDecode(response.body);
  
  for (var item in data) {
    if (item is Map) {
      for (var key in item.keys) {
        if (key.toString().toLowerCase().contains('lang')) {
          print('Found language key in root: $key = ${item[key]}');
        }
      }
      if (item['metadata'] is Map) {
        for (var key in item['metadata'].keys) {
          if (key.toString().toLowerCase().contains('lang')) {
            print('Found language key in metadata: $key = ${item['metadata'][key]}');
          }
        }
      }
    }
  }
}
