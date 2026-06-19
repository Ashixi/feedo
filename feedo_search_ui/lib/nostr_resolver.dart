import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

class NostrResolver {
  /// Resolves the missing text and author data for a list of search results
  /// using their respective relay_urls.
  static Future<void> resolve(List<dynamic> results) async {
    // Group required post IDs and author pubkeys by relay URL
    Map<String, Set<String>> relayToPostIds = {};
    Map<String, Set<String>> relayToAuthors = {};

    for (var res in results) {
      if (res['relay_urls'] != null && res['relay_urls'].isNotEmpty) {
        // Use up to 3 relays for redundancy
        List<String> relays = List<String>.from(res['relay_urls']).take(3).toList();
        // Always include some highly reliable public relays as fallbacks
        if (!relays.contains('wss://relay.damus.io')) relays.add('wss://relay.damus.io');
        if (!relays.contains('wss://nos.lol')) relays.add('wss://nos.lol');
        
        for (String relayUrl in relays) {
          relayToPostIds.putIfAbsent(relayUrl, () => {}).add(res['hash_id']);
          
          String author = res['author_address'];
          // Only add valid Nostr pubkeys (64 char hex) to the profile query
          if (author.isNotEmpty && author.length == 64 && RegExp(r'^[0-9a-fA-F]+$').hasMatch(author)) {
            relayToAuthors.putIfAbsent(relayUrl, () => {}).add(author);
          }
        }
      }
    }

    // Resolve per relay
    List<Future> futures = [];
    for (var relay in relayToPostIds.keys) {
      futures.add(_fetchFromRelay(
        relay,
        relayToPostIds[relay]!.toList(),
        relayToAuthors[relay]?.toList() ?? [],
        results,
      ));
    }

    // Wait for all relays to finish (with a timeout)
    await Future.wait(futures).timeout(const Duration(seconds: 4), onTimeout: () => []);
  }

  static Future<void> _fetchFromRelay(
    String relayUrl,
    List<String> postIds,
    List<String> authors,
    List<dynamic> allResults,
  ) async {
    WebSocketChannel? channel;
    try {
      channel = WebSocketChannel.connect(Uri.parse(relayUrl));
      
      String subId = 'req_${DateTime.now().millisecondsSinceEpoch}';
      
      // Request both posts and profiles in one subscription if possible
      List<Map<String, dynamic>> filters = [];
      if (postIds.isNotEmpty) {
        filters.add({'ids': postIds});
      }
      if (authors.isNotEmpty) {
        filters.add({'kinds': [0], 'authors': authors});
      }

      var request = ['REQ', subId, ...filters];
      channel.sink.add(jsonEncode(request));

      await for (var message in channel.stream) {
        try {
          var msg = jsonDecode(message);
          if (msg[0] == 'EOSE' && msg[1] == subId) {
            break; // Finished receiving events for this subscription
          }
          if (msg[0] == 'EVENT' && msg[1] == subId) {
            var ev = msg[2];
            int kind = ev['kind'];
            
            // If it's a profile
            if (kind == 0) {
              try {
                var content = jsonDecode(ev['content']);
                // Update author info in all results
                for (var res in allResults) {
                  if (res['author_address'] == ev['pubkey']) {
                    res['author_name'] = content['name'] ?? content['display_name'] ?? res['author_name'];
                    res['author_avatar'] = content['picture'];
                    if (res['item_type'] == 'profile') {
                      res['text'] = content['about'] ?? '';
                    }
                  }
                }
              } catch (_) {}
            } 
            // If it's a post or other kind
            else {
              for (var res in allResults) {
                if (res['hash_id'] == ev['id']) {
                  res['text'] = ev['content'];
                }
              }
            }
          }
        } catch (_) {}
      }
    } catch (e) {
      // Ignore websocket errors, just skip this relay
    } finally {
      channel?.sink.close();
    }
  }
}
