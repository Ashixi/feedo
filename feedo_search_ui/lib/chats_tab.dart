import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:http/http.dart' as http;
import 'services/relay_service.dart';
import 'services/auth_service.dart';
import 'screens/chat_screen.dart';
import 'utils/constants.dart';

class ChatsTab extends StatefulWidget {
  const ChatsTab({super.key});

  @override
  State<ChatsTab> createState() => _ChatsTabState();
}

class _ChatsTabState extends State<ChatsTab> {
  bool _isLoading = true;
  String? _myPubkey;
  final Map<String, Map<String, dynamic>> _conversations = {};
  final Map<String, Map<String, dynamic>> _profiles = {};
  List<WebSocketChannel> _channels = [];

  @override
  void initState() {
    super.initState();
    _init();
  }

  @override
  void dispose() {
    for (var ch in _channels) {
      ch.sink.close();
    }
    super.dispose();
  }

  Future<void> _init() async {
    _myPubkey = await AuthService.getPublicKey();
    if (_myPubkey != null) {
      await _fetchSavedChats();
      _fetchConversations();
    } else {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _fetchSavedChats() async {
    try {
      final res = await http.get(Uri.parse('${Constants.apiUrl}/v1/identity/$_myPubkey'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        final List<dynamic> saved = data['saved_chats'] ?? [];
        if (saved.isNotEmpty) {
          if (mounted) {
            setState(() {
              for (var peer in saved) {
                if (peer is String) {
                   _conversations[peer] = {
                     'peerPubkey': peer,
                     'lastMessage': '',
                     'created_at': 0,
                   };
                }
              }
              _isLoading = false;
            });
            _resolveProfiles(_conversations.keys.toList());
          }
        }
      }
    } catch (e) {
      print('Failed to fetch saved chats: $e');
    }
  }

  Future<void> _syncNewChatToBackend(String peerPubkey) async {
    try {
      final res = await http.get(Uri.parse('${Constants.apiUrl}/v1/identity/$_myPubkey'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        List<String> saved = List<String>.from(data['saved_chats'] ?? []);
        if (!saved.contains(peerPubkey)) {
          saved.add(peerPubkey);
          await http.put(
            Uri.parse('${Constants.apiUrl}/v1/identity/update/$_myPubkey'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'metadata': {'saved_chats': saved},
              'signature': 'dummy'
            }),
          );
        }
      }
    } catch (e) {
      print('Failed to sync new chat: $e');
    }
  }

  Future<void> _fetchConversations() async {
    final relays = await RelayService.getRelays();
    final globalRelays = ['wss://relay.damus.io', 'wss://nos.lol', 'wss://relay.primal.net', 'wss://relay.nostr.band'];
    final allRelays = {...relays, ...globalRelays}.toList();

    final reqId = 'dms_${DateTime.now().millisecondsSinceEpoch}';
    final filters = [
      {"kinds": [4], "#p": [_myPubkey!], "limit": 200},
      {"kinds": [4], "authors": [_myPubkey!], "limit": 200}
    ];

    int completedCount = 0;
    final Set<String> pubkeysToResolve = {};

    for (var url in allRelays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        _channels.add(channel);
        channel.sink.add(jsonEncode(['REQ', reqId, ...filters]));

        channel.stream.listen((msg) {
          try {
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              String peerPubkey = '';
              if (ev['pubkey'] == _myPubkey) {
                final pTags = (ev['tags'] as List).where((t) => t[0] == 'p').toList();
                if (pTags.isNotEmpty) peerPubkey = pTags[0][1];
              } else {
                peerPubkey = ev['pubkey'];
              }

              if (peerPubkey.isNotEmpty) {
                if (mounted) {
                  setState(() {
                    bool isNew = !_conversations.containsKey(peerPubkey);
                    if (isNew || _conversations[peerPubkey]!['created_at'] < ev['created_at']) {
                      _conversations[peerPubkey] = {
                        'peerPubkey': peerPubkey,
                        'lastMessage': 'Encrypted Message',
                        'created_at': ev['created_at'],
                      };
                      pubkeysToResolve.add(peerPubkey);
                      if (isNew) {
                         _syncNewChatToBackend(peerPubkey);
                      }
                    }
                  });
                }
              }
            } else if (data[0] == 'EOSE' && data[1] == reqId) {
              completedCount++;
              if (completedCount >= allRelays.length) {
                if (mounted) setState(() => _isLoading = false);
                _resolveProfiles(pubkeysToResolve.toList());
              }
            }
          } catch (_) {}
        });
      } catch (_) {
        completedCount++;
      }
    }

    await Future.delayed(const Duration(seconds: 5));
    if (mounted) {
      setState(() => _isLoading = false);
      _resolveProfiles(pubkeysToResolve.toList());
    }
  }

  Future<void> _resolveProfiles(List<String> pubkeys) async {
    if (pubkeys.isEmpty) return;
    
    final toResolve = pubkeys.where((pk) => !_profiles.containsKey(pk)).toList();
    if (toResolve.isEmpty) return;

    try {
      final response = await http.post(
        Uri.parse('${Constants.apiUrl}/v1/users/resolve_profiles'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({"pubkeys": toResolve}),
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final List<dynamic> data = jsonDecode(response.body);
        if (mounted) {
          setState(() {
            for (var item in data) {
              _profiles[item['pubkey']] = {
                'name': item['name'],
                'picture': item['picture'] ?? '',
                'bio': item['bio'] ?? '',
                'relays': item['relays'] ?? [],
              };
            }
          });
        }
      }
    } catch (_) {}
  }

  void _openChat(String peerPubkey) {
    final profile = _profiles[peerPubkey];
    final relays = (profile?['relays'] as List?)?.cast<String>() ?? [];
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => ChatScreen(
          peerPubkey: peerPubkey,
          peerName: profile?['name'] ?? 'Unknown',
          peerPicture: profile?['picture'] ?? '',
          peerRelays: relays,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      child: _buildContent(),
    );
  }

  Widget _buildContent() {
    if (_myPubkey == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.lock_outline, size: 64, color: Colors.grey[400]),
            const SizedBox(height: 16),
            Text('Please login to see Direct Messages.', style: TextStyle(color: Colors.grey[600], fontSize: 16)),
          ],
        ),
      );
    }

    if (_isLoading && _conversations.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_conversations.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.chat_bubble_outline, size: 64, color: Colors.grey[400]),
            const SizedBox(height: 16),
            Text('No messages found.', style: TextStyle(color: Colors.grey[600], fontSize: 16)),
          ],
        ),
      );
    }

    final sortedConvos = _conversations.values.toList()
      ..sort((a, b) => (b['last_time'] as int).compareTo(a['last_time'] as int));

    return ListView.separated(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: sortedConvos.length,
      separatorBuilder: (context, index) => Divider(height: 1, color: Colors.grey.withOpacity(0.1), indent: 76),
      itemBuilder: (context, index) {
        final convo = sortedConvos[index];
        final peerPubkey = convo['peerPubkey'];
        final profile = _profiles[peerPubkey];
        
        final name = profile?['name'] ?? peerPubkey.substring(0, 8) + '...';
        final picture = profile?['picture'] ?? '';

        return ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
          leading: Container(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))
              ],
            ),
            child: CircleAvatar(
              radius: 24,
              backgroundColor: Colors.grey[100],
              backgroundImage: picture.isNotEmpty ? NetworkImage(picture) : null,
              child: picture.isEmpty ? const Icon(Icons.person, color: Colors.grey) : null,
            ),
          ),
          title: Text(name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.black87)),
          subtitle: const Text('Encrypted Message', style: TextStyle(fontStyle: FontStyle.italic, color: Colors.grey, fontSize: 14)),
          trailing: const Icon(Icons.chevron_right, color: Colors.grey, size: 20),
          onTap: () => _openChat(peerPubkey),
        );
      },
    );
  }
}
