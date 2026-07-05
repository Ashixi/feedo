import 'dart:math';

class Constants {
  static const String defaultApiUrl = 'https://api.feedo.ink';
  static String get apiUrl => NetworkSpider.getRandomNode();
}

class NetworkSpider {
  static final List<String> _activeNodes = ['https://api.feedo.ink'];
  static final _random = Random();

  static String getRandomNode() {
    if (_activeNodes.isEmpty) return Constants.defaultApiUrl;
    return _activeNodes[_random.nextInt(_activeNodes.length)];
  }
}

void main() {
  print('API URL IS: ${Constants.apiUrl}');
}
