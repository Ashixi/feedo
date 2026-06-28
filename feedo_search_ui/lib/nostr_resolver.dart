import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'services/auth_service.dart';

class NostrResolver {
  /// Resolves the missing text and author data for a list of search results
  /// using their respective relay_urls.
  static Future<void> resolve(List<dynamic> results, {void Function()? onUpdate}) async {
    // Group required post IDs and author pubkeys by relay URL
    Map<String, Set<String>> relayToPostIds = {};
    Map<String, Set<String>> relayToAuthors = {};

    for (var res in results) {
      List<dynamic>? relayUrls = res['relay_urls'];
      if (relayUrls == null && res['metadata'] != null) {
        relayUrls = res['metadata']['relay_urls'];
      }
      
      List<String> relays = [];
      if (relayUrls != null && relayUrls.isNotEmpty) {
        // Use up to 3 relays for redundancy
        relays = List<String>.from(relayUrls).take(3).toList();
      }
      
      // Always include some highly reliable public relays as fallbacks
      if (!relays.contains('wss://relay.damus.io')) relays.add('wss://relay.damus.io');
      if (!relays.contains('wss://nos.lol')) relays.add('wss://nos.lol');
      
      for (String relayUrl in relays) {
        relayToPostIds.putIfAbsent(relayUrl, () => {}).add(res['hash_id']);
        
        // If this is a repost, also fetch the original event!
        if (res['metadata'] != null && res['metadata']['kind'] == 6) {
          var tags = res['metadata']['tags'] as List?;
          if (tags != null) {
            for (var t in tags) {
              if (t is List && t.isNotEmpty && t[0] == 'e' && t.length > 1) {
                relayToPostIds[relayUrl]!.add(t[1]);
              }
            }
          }
        }

        String author = res['author_address'] ?? '';
        // Only add valid Nostr pubkeys (64 char hex) to the profile query
        if (author.isNotEmpty && author.length == 64 && RegExp(r'^[0-9a-fA-F]+$').hasMatch(author)) {
          relayToAuthors.putIfAbsent(relayUrl, () => {}).add(author);
        }
      }
    }

    // Get local user pubkey to track "user_liked" etc
    final myPubkey = await AuthService.getPublicKey();

    // Set to track which interaction event IDs we have already counted
    // so we don't double count if multiple relays return the same like/comment
    Set<String> countedInteractionIds = {};

    // Resolve per relay
    List<Future> futures = [];
    for (var relay in relayToPostIds.keys) {
      futures.add(_fetchFromRelay(
        relay,
        relayToPostIds[relay]!.toList(),
        relayToAuthors[relay]?.toList() ?? [],
        results,
        myPubkey,
        countedInteractionIds,
        onUpdate,
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
    String? myPubkey,
    Set<String> countedInteractionIds,
    void Function()? onUpdate,
  ) async {
    WebSocketChannel? channel;
    try {
      channel = WebSocketChannel.connect(Uri.parse(relayUrl));
      
      String subId = 'req_${DateTime.now().millisecondsSinceEpoch}';
      
      // Request both posts and profiles in one subscription if possible
      List<Map<String, dynamic>> filters = [];
      if (postIds.isNotEmpty) {
        filters.add({'ids': postIds});
        // Fetch social interactions for these posts
        filters.add({'kinds': [1, 6, 7, 9735], '#e': postIds});
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
                bool changed = false;
                for (var res in allResults) {
                  if (res['author_address'] == ev['pubkey']) {
                    res['author_name'] = content['name'] ?? content['display_name'] ?? res['author_name'];
                    res['author_avatar'] = content['picture'];
                    res['author_lud16'] = content['lud16'] ?? content['lud06'];
                    if (res['item_type'] == 'profile') {
                      res['text'] = content['about'] ?? '';
                    }
                    changed = true;
                  }
                }
                if (changed && onUpdate != null) {
                  onUpdate();
                }
              } catch (_) {}
            } 

            // Check if this event is one of the posts we requested the text for
            if (postIds.contains(ev['id'])) {
              bool changed = false;
              for (var res in allResults) {
                // Direct match: this event is the post itself
                if (res['hash_id'] == ev['id']) {
                  String text = ev['content'] ?? '';
                  if (kind == 6 && text.isNotEmpty) {
                    try {
                      var inner = jsonDecode(text);
                      text = inner['content'] ?? '';
                    } catch (_) {}
                  }
                  res['text'] = text;
                  changed = true;
                }
                
                // Repost match: this event is the ORIGINAL event that `res` reposted
                if (res['metadata'] != null && res['metadata']['kind'] == 6) {
                  var tags = res['metadata']['tags'] as List?;
                  if (tags != null) {
                    for (var t in tags) {
                      if (t is List && t.isNotEmpty && t[0] == 'e' && t.length > 1 && t[1] == ev['id']) {
                        res['text'] = ev['content'];
                        // Also grab the original author of the reposted content if we want
                        res['original_author_pubkey'] = ev['pubkey'];
                        res['is_repost_resolved'] = true;
                        changed = true;
                      }
                    }
                  }
                }
              }
              if (changed && onUpdate != null) {
                onUpdate();
              }
            }

            // Check if this event is a social interaction pointing to one of our posts
            if ([1, 6, 7, 9735].contains(kind)) {
              String? eTag;
              for (var t in ev['tags']) {
                if (t is List && t.isNotEmpty && t[0] == 'e' && t.length > 1) {
                  eTag = t[1];
                  break;
                }
              }
              
              if (eTag != null && postIds.contains(eTag)) {
                // Deduplicate interaction events across relays
                if (countedInteractionIds.contains(ev['id'])) continue;
                countedInteractionIds.add(ev['id']);
                
                bool changed = false;
                for (var res in allResults) {
                  if (res['hash_id'] == eTag) {
                    res['metrics'] ??= {};
                    if (kind == 1) { // Reply/Comment
                      res['metrics']['comments'] = (res['metrics']['comments'] ?? 0) + 1;
                    } else if (kind == 6) { // Repost
                      res['metrics']['reposts'] = (res['metrics']['reposts'] ?? 0) + 1;
                    } else if (kind == 7) { // Like
                      res['metrics']['likes'] = (res['metrics']['likes'] ?? 0) + 1;
                      if (ev['pubkey'] == myPubkey) {
                        res['user_liked'] = true;
                      }
                    } else if (kind == 9735) { // Zap/Tip
                      res['metrics']['tips'] = (res['metrics']['tips'] ?? 0) + 1;
                    }
                    changed = true;
                  }
                }
                if (changed && onUpdate != null) {
                  onUpdate();
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

