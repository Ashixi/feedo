import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'auth_service.dart';
import 'relay_service.dart';

class NostrPublisher {
  static Future<String?> publishEvent(int kind, String content, List<List<String>> tags) async {
    final event = await AuthService.signEvent(kind, content, tags);
    if (event == null) return null;

    final relays = await RelayService.getRelays();
    final eventJson = jsonEncode(['EVENT', event.toMap()]);
    bool success = false;

    List<Future<void>> futures = [];
    for (var url in relays) {
      futures.add(() async {
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          await channel.ready.timeout(const Duration(seconds: 3));
          channel.sink.add(eventJson);
          // Wait briefly for the connection to send the packet
          await Future.delayed(const Duration(milliseconds: 500));
          channel.sink.close();
          success = true; // If at least one doesn't throw on connect
        } catch (e) {
          print('Failed to publish to $url: $e');
        }
      }());
    }
    
    await Future.wait(futures);
    return success ? event.id : null;
  }

  static Future<String?> publishChatMessage(String channelId, String message) {
    return publishEvent(
      42,
      message,
      [
        ['e', channelId, '', 'root']
      ],
    );
  }

  static Future<String?> publishDelete(String eventId) {
    return publishEvent(
      5,
      '',
      [
        ['e', eventId]
      ],
    );
  }

  static Future<String?> publishLike(String postId, String authorPubkey) {
    return publishEvent(
      7,
      '+',
      [
        ['e', postId],
        ['p', authorPubkey]
      ],
    );
  }

  static Future<String?> publishRepost(String postId, String authorPubkey, {String relayUrl = ''}) {
    return publishEvent(
      6,
      '',
      [
        ['e', postId, relayUrl, 'mention'],
        ['p', authorPubkey]
      ],
    );
  }

  static Future<String?> publishComment(String postId, String authorPubkey, String content) {
    return publishEvent(
      1,
      content,
      [
        ['e', postId, '', 'reply'],
        ['p', authorPubkey]
      ],
    );
  }

  static Future<String?> publishFollow(String targetPubkey) async {
    final myPubkey = await AuthService.getPublicKey();
    if (myPubkey == null) return null;

    final relays = await RelayService.getRelays();
    List<List<String>> currentTags = [];
    bool foundExisting = false;
    
    // Attempt to fetch current kind 3
    final filter = {
      "kinds": [3],
      "authors": [myPubkey],
      "limit": 1
    };
    final reqId = 'get_contacts_${DateTime.now().millisecondsSinceEpoch}';
    final reqStr = jsonEncode(['REQ', reqId, filter]);

    List<Future<void>> fetchFutures = [];
    for (var url in relays) {
      fetchFutures.add(() async {
        if (foundExisting) return;
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          await channel.ready.timeout(const Duration(seconds: 2));
          channel.sink.add(reqStr);
          
          await for (var msg in channel.stream.timeout(const Duration(seconds: 2))) {
            if (foundExisting) {
              channel.sink.close();
              break;
            }
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              final tags = List<List<dynamic>>.from(ev['tags']);
              currentTags = tags.map((t) => List<String>.from(t.map((e) => e.toString()))).toList();
              foundExisting = true;
              channel.sink.close();
              break;
            }
            if (data[0] == 'EOSE' && data[1] == reqId) {
              channel.sink.close();
              break;
            }
          }
        } catch (_) {}
      }());
    }

    try {
      await Future.wait(fetchFutures).timeout(const Duration(seconds: 4));
    } catch (_) {}

    // Append or remove follow
    bool exists = currentTags.any((t) => t.isNotEmpty && t[0] == 'p' && t.length > 1 && t[1] == targetPubkey);
    if (!exists) {
      currentTags.add(['p', targetPubkey]);
    } else {
      currentTags.removeWhere((t) => t.isNotEmpty && t[0] == 'p' && t.length > 1 && t[1] == targetPubkey);
    }

    return publishEvent(3, '', currentTags);
  }

  static Future<bool> isFollowing(String targetPubkey) async {
    final myPubkey = await AuthService.getPublicKey();
    if (myPubkey == null) return false;

    final relays = await RelayService.getRelays();
    bool isSubscribed = false;
    bool foundExisting = false;

    final filter = {
      "kinds": [3],
      "authors": [myPubkey],
      "limit": 1
    };
    final reqId = 'check_follow_${DateTime.now().millisecondsSinceEpoch}';
    final reqStr = jsonEncode(['REQ', reqId, filter]);

    List<Future<void>> fetchFutures = [];
    for (var url in relays) {
      fetchFutures.add(() async {
        if (foundExisting) return;
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          await channel.ready.timeout(const Duration(seconds: 2));
          channel.sink.add(reqStr);
          
          await for (var msg in channel.stream.timeout(const Duration(seconds: 2))) {
            if (foundExisting) {
              channel.sink.close();
              break;
            }
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              final tags = List<List<dynamic>>.from(ev['tags']);
              isSubscribed = tags.any((t) => t.isNotEmpty && t[0] == 'p' && t.length > 1 && t[1] == targetPubkey);
              foundExisting = true;
              channel.sink.close();
              break;
            }
            if (data[0] == 'EOSE' && data[1] == reqId) {
              channel.sink.close();
              break;
            }
          }
        } catch (_) {}
      }());
    }

    try {
      await Future.wait(fetchFutures).timeout(const Duration(seconds: 4));
    } catch (_) {}

    return isSubscribed;
  }
}
