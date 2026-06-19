import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dart_nostr/dart_nostr.dart';

class AuthService {
  static const _storage = FlutterSecureStorage();
  static const _keyNsec = 'nostr_private_key';

  static Future<void> init() async {
    // Initialize dart_nostr
    Nostr.instance.disableLogs();
  }

  static Future<bool> hasAccount() async {
    final nsec = await _storage.read(key: _keyNsec);
    return nsec != null && nsec.isNotEmpty;
  }

  static Future<String?> getPublicKey() async {
    final nsec = await _storage.read(key: _keyNsec);
    if (nsec == null) return null;
    try {
      final keyPair = NostrKeyPairs(private: nsec);
      return keyPair.public;
    } catch (e) {
      return null;
    }
  }

  static Future<String?> getPrivateKey() async {
    return await _storage.read(key: _keyNsec);
  }

  static Future<String> generateNewAccount() async {
    final keyPair = NostrKeyPairs.generate();
    await _storage.write(key: _keyNsec, value: keyPair.private);
    return keyPair.public;
  }

  static Future<bool> loginWithNsec(String nsec) async {
    try {
      // Validate the key
      final keyPair = NostrKeyPairs(private: nsec);
      await _storage.write(key: _keyNsec, value: keyPair.private);
      return true;
    } catch (e) {
      return false;
    }
  }

  static Future<void> logout() async {
    await _storage.delete(key: _keyNsec);
  }

  static Future<NostrEvent?> signEvent(int kind, String content, List<List<String>> tags) async {
    final nsec = await _storage.read(key: _keyNsec);
    if (nsec == null) return null;

    try {
      final keyPair = NostrKeyPairs(private: nsec);
      
      final event = NostrEvent.fromPartialData(
        kind: kind,
        content: content,
        tags: tags,
        keyPairs: keyPair,
      );
      
      return event;
    } catch (e) {
      print('Failed to sign event: $e');
      return null;
    }
  }
}
