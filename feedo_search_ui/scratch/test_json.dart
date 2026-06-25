import 'dart:convert';
import 'package:http/http.dart' as http;

void main() async {
  final url = Uri.parse('https://api.feedo.ink/feed?limit=5&source_type=nostr');
  final response = await http.get(url);
  final List<dynamic> data = jsonDecode(response.body);
  
  if (data.isNotEmpty) {
    print('KEYS for post 1: ${data[0].keys}');
    print('METADATA for post 1: ${data[0]['metadata']}');
    print('ALL DATA for post 1:');
    print(jsonEncode(data[0]));
  }
}
