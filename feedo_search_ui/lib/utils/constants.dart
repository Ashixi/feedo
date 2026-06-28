import '../services/network_spider.dart';

class Constants {
  // Feedo API Backend Default URL (acts as bootstrap node)
  static const String defaultApiUrl = String.fromEnvironment('API_URL', defaultValue: 'https://api.feedo.ink');
  
  // Dynamic API URL from Network Spider
  static String get apiUrl => NetworkSpider.getRandomNode();
  
  // Instant Indexing endpoint for the Nostr Bridge / Ingester
  // Resolves to the dynamic API_URL + /v1/ingest/post
  static String get ingestUrl => '$apiUrl/v1/ingest/post';
}
