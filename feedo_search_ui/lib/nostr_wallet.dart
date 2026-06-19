import 'dart:js_util';

class NostrWallet {
  static Future<bool> isAvailable() async {
    try {
      var nostr = getProperty(globalThis, 'nostr');
      return nostr != null;
    } catch (e) {
      return false;
    }
  }

  static Future<String?> getPublicKey() async {
    try {
      var nostr = getProperty(globalThis, 'nostr');
      if (nostr == null) return null;
      var promise = callMethod(nostr, 'getPublicKey', []);
      var pubkey = await promiseToFuture(promise);
      return pubkey.toString();
    } catch (e) {
      print('Nostr getPublicKey error: $e');
      return null;
    }
  }

  static Future<Map<String, dynamic>?> signEvent(Map<String, dynamic> event) async {
    try {
      var nostr = getProperty(globalThis, 'nostr');
      if (nostr == null) return null;
      var jsEvent = jsify(event);
      var promise = callMethod(nostr, 'signEvent', [jsEvent]);
      var signedEvent = await promiseToFuture(promise);
      
      // dartify returns a LinkedMap or similar, we cast it to Map
      final dartMap = dartify(signedEvent);
      if (dartMap is Map) {
        return Map<String, dynamic>.from(dartMap);
      }
      return null;
    } catch (e) {
      print('Nostr signEvent error: $e');
      return null;
    }
  }
}
