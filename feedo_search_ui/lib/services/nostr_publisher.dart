import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'auth_service.dart';
import 'relay_service.dart';
import 'package:http/http.dart' as http;
import '../utils/constants.dart';

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

    if (success) {
      try {
        await http.post(
          Uri.parse(Constants.ingestUrl),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(event.toMap()),
        );
      } catch (e) {
        print("Failed to ping Feedo backend for event: $e");
      }
    }

    return success ? event.id : null;
  }

  static Future<String?> publishDirectMessage(String peerPubkey, String encryptedMessage) {
    return publishEvent(
      4,
      encryptedMessage,
      [
        ['p', peerPubkey]
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
  
  static Future<Map<String, dynamic>?> fetchEventById(String eventId, {List<String>? additionalRelays}) async {
    final relays = await RelayService.getRelays();
    if (additionalRelays != null) {
      for (var r in additionalRelays) {
        if (r.isNotEmpty && !relays.contains(r)) relays.add(r);
      }
    }
    
    final globalRelays = [
      'wss://relay.nostr.band',
      'wss://search.nos.today',
      'wss://relay.snort.social',
      'wss://nos.lol',
    ];
    for (var r in globalRelays) {
      if (!relays.contains(r)) relays.add(r);
    }
    
    final filter = {
      "ids": [eventId],
      "limit": 1
    };
    final reqId = 'get_event_${DateTime.now().millisecondsSinceEpoch}';
    final reqStr = jsonEncode(['REQ', reqId, filter]);
    
    Map<String, dynamic>? eventData;
    List<Future<void>> fetchFutures = [];
    
    for (var url in relays) {
      fetchFutures.add(() async {
        if (eventData != null) return;
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          await channel.ready.timeout(const Duration(seconds: 3));
          channel.sink.add(reqStr);
          
          await for (var msg in channel.stream.timeout(const Duration(seconds: 4))) {
            if (eventData != null) {
              channel.sink.close();
              break;
            }
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              eventData = data[2];
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
      await Future.wait(fetchFutures).timeout(const Duration(seconds: 5));
    } catch (_) {}
    
    return eventData;
  }

  static Future<Map<String, dynamic>?> fetchProfile(String pubkey, {List<String>? additionalRelays}) async {
    final relays = await RelayService.getRelays();
    if (additionalRelays != null) {
      for (var r in additionalRelays) {
        if (r.isNotEmpty && !relays.contains(r)) relays.add(r);
      }
    }
    
    final globalRelays = [
      'wss://purplepag.es',
      'wss://relay.damus.io',
      'wss://nos.lol',
      'wss://relay.nostr.band',
    ];
    for (var r in globalRelays) {
      if (!relays.contains(r)) relays.add(r);
    }
    
    final filter = {
      "kinds": [0],
      "authors": [pubkey],
      "limit": 1
    };
    final reqId = 'get_profile_${DateTime.now().millisecondsSinceEpoch}';
    final reqStr = jsonEncode(['REQ', reqId, filter]);
    
    Map<String, dynamic>? profileData;
    List<Future<void>> fetchFutures = [];
    
    for (var url in relays) {
      fetchFutures.add(() async {
        if (profileData != null) return;
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          await channel.ready.timeout(const Duration(seconds: 3));
          channel.sink.add(reqStr);
          
          await for (var msg in channel.stream.timeout(const Duration(seconds: 4))) {
            if (profileData != null) {
              channel.sink.close();
              break;
            }
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              try {
                profileData = jsonDecode(ev['content']);
              } catch (_) {}
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
      await Future.wait(fetchFutures).timeout(const Duration(seconds: 5));
    } catch (_) {}
    
    return profileData;
  }
}

