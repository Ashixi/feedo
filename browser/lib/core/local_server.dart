import 'package:browser/src/rust/api/server.dart';
import 'api_client.dart';

class LocalFeedoServer {
  static bool _isRunning = false;

  static Future<void> start(ApiClient apiClient) async {
    if (_isRunning) return;

    try {
      await startLocalServer();
      _isRunning = true;
      print('LocalFeedoServer (Rust Engine) started successfully on port 8081');
    } catch (e) {
      print('Failed to start LocalFeedoServer (Rust Engine): $e');
    }
  }

  static int get port => 8081;
}
