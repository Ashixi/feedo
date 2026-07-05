import 'dart:async';
import 'dart:convert';
import 'package:dart_nostr/dart_nostr.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class NwcService {
  static const _storage = FlutterSecureStorage();
  static const _keyNwcUrl = 'nwc_connection_url';

  static Future<void> saveNwcUrl(String url) async {
    await _storage.write(key: _keyNwcUrl, value: url);
  }

  static Future<String?> getNwcUrl() async {
    return await _storage.read(key: _keyNwcUrl);
  }

  static Future<bool> hasWallet() async {
    final url = await getNwcUrl();
    return url != null && url.isNotEmpty;
  }

  static Future<void> disconnect() async {
    await _storage.delete(key: _keyNwcUrl);
  }

  /// Pays a lightning invoice using NWC (NIP-47)
  static Future<bool> payInvoice(String invoice) async {
    final url = await getNwcUrl();
    if (url == null || url.isEmpty) return false;

    try {
      final uri = Uri.parse(url.replaceFirst('nostr+walletconnect://', 'http://'));
      final targetPubkey = uri.host;
      final relay = uri.queryParameters['relay'];
      final secret = uri.queryParameters['secret'];

      if (relay == null || secret == null) return false;

      // 1. Create the request payload
      final payload = jsonEncode({
        "method": "pay_invoice",
        "params": {
          "invoice": invoice
        }
      });

      // 2. Encrypt payload with the secret key and the target pubkey (NIP-04)
      final keyPair = NostrKeyPairs(private: secret);
      final encrypted = payload; // TODO: Implement NIP-04/NIP-44 encryption!

      // 3. Create the NIP-47 request event (kind 23194)
      final event = NostrEvent.fromPartialData(
        kind: 23194,
        content: encrypted,
        tags: [['p', targetPubkey]],
        keyPairs: keyPair,
      );

      // 4. Send to the specific relay and wait for response
      final channel = WebSocketChannel.connect(Uri.parse(relay));
      final msg = jsonEncode(["EVENT", event.toMap()]);
      channel.sink.add(msg);

      bool success = false;
      final completer = Completer<bool>();

      // Listen for response
      final subscription = channel.stream.listen((message) {
        try {
          final decoded = jsonDecode(message);
          if (decoded[0] == 'EVENT') {
            final ev = decoded[2];
            if (ev['kind'] == 23195 && ev['tags'].any((t) => t[0] == 'e' && t[1] == event.id)) {
              // This is the response to our request
              final responseContent = ev['content']; // TODO: Decrypt
              final respJson = jsonDecode(responseContent);
              if (respJson['error'] == null) {
                success = true;
              } else {
                print("NWC Error: ${respJson['error']}");
              }
              if (!completer.isCompleted) completer.complete(success);
            }
          }
        } catch (e) {
          // ignore
        }
      });

      // Timeout after 10 seconds
      Future.delayed(const Duration(seconds: 10), () {
        if (!completer.isCompleted) completer.complete(false);
      });

      final result = await completer.future;
      subscription.cancel();
      channel.sink.close();
      return result;

    } catch (e) {
      print("NWC PayInvoice Error: $e");
      return false;
    }
  }
}

