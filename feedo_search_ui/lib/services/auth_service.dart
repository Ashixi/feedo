import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dart_nostr/dart_nostr.dart';
import 'package:flutter/foundation.dart';
import '../nostr_wallet.dart';

enum AuthMethod { none, nsec, extension }

class AuthService {
  static const _storage = FlutterSecureStorage();
  static const _keyNsec = 'nostr_private_key';
  static const _keyAuthMethod = 'nostr_auth_method';
  
  static AuthMethod _currentMethod = AuthMethod.none;
  static String? _extensionPubkey;

  static Future<void> init() async {
    Nostr.instance.disableLogs();
    final methodStr = await _storage.read(key: _keyAuthMethod);
    if (methodStr == 'nsec') {
      _currentMethod = AuthMethod.nsec;
    } else if (methodStr == 'extension') {
      _currentMethod = AuthMethod.extension;
      if (kIsWeb) {
        _extensionPubkey = await NostrWallet.getPublicKey();
      }
    }
  }

  static Future<bool> hasAccount() async {
    if (_currentMethod == AuthMethod.nsec) {
      final nsec = await _storage.read(key: _keyNsec);
      return nsec != null && nsec.isNotEmpty;
    } else if (_currentMethod == AuthMethod.extension) {
      return _extensionPubkey != null;
    }
    return false;
  }

  static Future<String?> getPublicKey() async {
    if (_currentMethod == AuthMethod.nsec) {
      final nsec = await _storage.read(key: _keyNsec);
      if (nsec == null) return null;
      try {
        final keyPair = NostrKeyPairs(private: nsec);
        return keyPair.public;
      } catch (e) {
        return null;
      }
    } else if (_currentMethod == AuthMethod.extension) {
      return _extensionPubkey;
    }
    return null;
  }

  static Future<String> generateNewAccount() async {
    final keyPair = NostrKeyPairs.generate();
    await _storage.write(key: _keyNsec, value: keyPair.private);
    await _storage.write(key: _keyAuthMethod, value: 'nsec');
    _currentMethod = AuthMethod.nsec;
    return keyPair.public;
  }

  static Future<bool> loginWithNsec(String nsec) async {
    try {
      final keyPair = NostrKeyPairs(private: nsec);
      await _storage.write(key: _keyNsec, value: keyPair.private);
      await _storage.write(key: _keyAuthMethod, value: 'nsec');
      _currentMethod = AuthMethod.nsec;
      return true;
    } catch (e) {
      return false;
    }
  }

  static Future<bool> loginWithExtension() async {
    if (!kIsWeb) return false;
    final isAvailable = await NostrWallet.isAvailable();
    if (!isAvailable) return false;
    
    final pubkey = await NostrWallet.getPublicKey();
    if (pubkey != null) {
      _extensionPubkey = pubkey;
      await _storage.write(key: _keyAuthMethod, value: 'extension');
      _currentMethod = AuthMethod.extension;
      return true;
    }
    return false;
  }

  static Future<String?> getPrivateKey() async { return await _storage.read(key: _keyNsec); }

  static Future<void> logout() async {
    await _storage.delete(key: _keyNsec);
    await _storage.delete(key: _keyAuthMethod);
    _currentMethod = AuthMethod.none;
    _extensionPubkey = null;
  }

  static Future<NostrEvent?> signEvent(int kind, String content, List<List<String>> tags) async {
    if (_currentMethod == AuthMethod.nsec) {
      final nsec = await _storage.read(key: _keyNsec);
      if (nsec == null) return null;
      try {
        final keyPair = NostrKeyPairs(private: nsec);
        return NostrEvent.fromPartialData(
          kind: kind,
          content: content,
          tags: tags,
          keyPairs: keyPair,
        );
      } catch (e) {
        return null;
      }
    } else if (_currentMethod == AuthMethod.extension && kIsWeb) {
      try {
        final pubkey = await getPublicKey();
        if (pubkey == null) return null;
        
        final partialEvent = {
          'kind': kind,
          'created_at': DateTime.now().millisecondsSinceEpoch ~/ 1000,
          'tags': tags,
          'content': content,
          'pubkey': pubkey,
        };
        
        final signedMap = await NostrWallet.signEvent(partialEvent);
        if (signedMap != null) {
          return NostrEvent.deserialized(jsonEncode(signedMap));
        }
      } catch (e) {
        print('Extension sign error: $e');
      }
    }
    return null;
  }
}



