import 'dart:convert';
import 'dart:math';
import 'package:http/http.dart' as http;
import '../utils/constants.dart';

class NetworkSpider {
  static final List<String> _activeNodes = [];
  static final _random = Random();
  static bool _isInitialized = false;

  static List<String> get activeNodes {
    if (_activeNodes.isEmpty) {
      return [Constants.defaultApiUrl, 'https://api2.feedo.ink'];
    }
    return List.from(_activeNodes);
  }

  static Future<void> init() async {
    if (_isInitialized) return;
    
    // Always add the default node first
    final defaultUrl = Constants.defaultApiUrl;
    if (!_activeNodes.contains(defaultUrl)) {
      _activeNodes.add(defaultUrl);
    }
    
    // Add secondary node for load balancing
    final secondaryUrl = 'https://api2.feedo.ink';
    if (!_activeNodes.contains(secondaryUrl)) {
      _activeNodes.add(secondaryUrl);
    }
    
    try {
      final response = await http.get(Uri.parse('$defaultUrl/v1/node/peers')).timeout(const Duration(seconds: 10));
      if (response.statusCode == 200) {
        final List<dynamic> peers = json.decode(response.body);
        for (var peer in peers) {
          final url = peer['url'] ?? peer['api_url'];
          if (url != null && url.toString().isNotEmpty) {
            String cleanUrl = url.toString().replaceAll(RegExp(r'/+$'), '');
            if (!_activeNodes.contains(cleanUrl)) {
              _activeNodes.add(cleanUrl);
            }
          }
        }
      }
    } catch (e) {
      print('NetworkSpider failed to fetch peers: $e');
    }
    
    _isInitialized = true;
    print('NetworkSpider initialized with nodes: $_activeNodes');
  }

  static String getRandomNode() {
    if (_activeNodes.isEmpty) return Constants.defaultApiUrl;
    return _activeNodes[_random.nextInt(_activeNodes.length)];
  }
}
