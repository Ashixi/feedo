import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/relay_service.dart';
import '../services/nostr_publisher.dart';
import '../services/auth_service.dart';
import '../services/nip04_service.dart';
import '../feed_layout.dart';

class ChatScreen extends StatefulWidget {
  final String peerPubkey;
  final String peerName;
  final String peerPicture;
  final List<String> peerRelays;

  const ChatScreen({
    super.key,
    required this.peerPubkey,
    required this.peerName,
    required this.peerPicture,
    this.peerRelays = const [],
  });

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _msgController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _isLoading = true;
  List<Map<String, dynamic>> _messages = [];
  final Map<String, Map<String, dynamic>> _uniqueMessages = {};
  List<WebSocketChannel> _channels = [];
  String? _myPubkey;

  @override
  void initState() {
    super.initState();
    _initChat();
  }

  @override
  void dispose() {
    for (var ch in _channels) {
      ch.sink.close();
    }
    _msgController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _initChat() async {
    _myPubkey = await AuthService.getPublicKey();
    if (_myPubkey == null || _myPubkey!.isEmpty) return;
    _connectAndFetch();
  }

  Future<void> _connectAndFetch() async {
    final relays = await RelayService.getRelays();
    final globalRelays = ['wss://relay.damus.io', 'wss://nos.lol', 'wss://relay.primal.net', 'wss://relay.nostr.band'];
    final allRelays = {...relays, ...globalRelays, ...widget.peerRelays}.toList();

    final reqId = 'dm_${widget.peerPubkey}_${DateTime.now().millisecondsSinceEpoch}';
    final filters = [
      {"kinds": [4], "authors": [_myPubkey!], "#p": [widget.peerPubkey], "limit": 100},
      {"kinds": [4], "authors": [widget.peerPubkey], "#p": [_myPubkey!], "limit": 100}
    ];

    for (var url in allRelays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        _channels.add(channel);
        channel.sink.add(jsonEncode(['REQ', reqId, ...filters]));

        channel.stream.listen((msg) async {
          try {
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              final id = ev['id'];
              if (!_uniqueMessages.containsKey(id)) {
                // Determine if it's sent or received
                final isSentByMe = ev['pubkey'] == _myPubkey;
                final encryptedContent = ev['content'];
                
                // Add placeholder
                _uniqueMessages[id] = {
                  'id': id,
                  'isSentByMe': isSentByMe,
                  'content': 'Decrypting...',
                  'created_at': ev['created_at'],
                };
                _updateList();

                try {
                  final decrypted = await Nip04Service.decrypt(
                    isSentByMe ? widget.peerPubkey : ev['pubkey'],
                    encryptedContent
                  );
                  _uniqueMessages[id]!['content'] = decrypted;
                  _updateList();
                } catch (e) {
                  _uniqueMessages[id]!['content'] = '<Decryption Failed>';
                  _updateList();
                }
              }
            } else if (data[0] == 'EOSE' && data[1] == reqId) {
               if (mounted) setState(() { _isLoading = false; });
            }
          } catch (_) {}
        });
      } catch (_) {}
    }

    await Future.delayed(const Duration(seconds: 4));
    if (mounted) setState(() { _isLoading = false; });
  }

  void _updateList() {
    if (mounted) {
      setState(() {
        _messages = _uniqueMessages.values.toList();
        _messages.sort((a, b) => (b['created_at'] as int).compareTo(a['created_at'] as int));
      });
    }
  }

  Future<void> _sendMessage() async {
    if (_myPubkey == null) return;
    final text = _msgController.text.trim();
    if (text.isEmpty) return;

    _msgController.clear();
    
    try {
      final encryptedText = await Nip04Service.encrypt(widget.peerPubkey, text);
      final evId = await NostrPublisher.publishDirectMessage(widget.peerPubkey, encryptedText);
      if (evId == null) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to send message')));
      } else {
        // Optimistically add
        final now = (DateTime.now().millisecondsSinceEpoch / 1000).round();
        _uniqueMessages[evId] = {
          'id': evId,
          'isSentByMe': true,
          'content': text,
          'created_at': now,
        };
        _updateList();
        
        // Scroll to bottom
        if (_scrollController.hasClients) {
          _scrollController.animateTo(0.0, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
        }
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            if (widget.peerPicture.isNotEmpty) ...[
              CircleAvatar(
                radius: 16,
                backgroundImage: NetworkImage(widget.peerPicture),
              ),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: Text(widget.peerName, overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 600),
          child: Column(
            children: [
              Expanded(
                child: _isLoading && _messages.isEmpty
                    ? const Center(child: CircularProgressIndicator())
                    : ListView.builder(
                        reverse: true,
                        controller: _scrollController,
                        itemCount: _messages.length,
                        padding: const EdgeInsets.all(16),
                        itemBuilder: (context, index) {
                          final msg = _messages[index];
                          final isSentByMe = msg['isSentByMe'] as bool;
                          
                          return Align(
                            alignment: isSentByMe ? Alignment.centerRight : Alignment.centerLeft,
                            child: Container(
                              margin: EdgeInsets.only(
                                bottom: 8,
                                left: isSentByMe ? 64 : 16,
                                right: isSentByMe ? 16 : 64,
                              ),
                              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                              decoration: BoxDecoration(
                                color: isSentByMe ? Theme.of(context).colorScheme.primary : Colors.grey[200],
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                msg['content'],
                                style: TextStyle(
                                  color: isSentByMe ? Colors.white : Colors.black87,
                                  fontSize: 16,
                                ),
                              ),
                            ),
                          );
                        },
                      ),
              ),
              const Divider(height: 1),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                color: Theme.of(context).scaffoldBackgroundColor,
                child: SafeArea(
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _msgController,
                          decoration: const InputDecoration(
                            hintText: 'Message...',
                            border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(24))),
                            contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                          ),
                          onSubmitted: (_) => _sendMessage(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      CircleAvatar(
                        backgroundColor: Theme.of(context).colorScheme.primary,
                        child: IconButton(
                          icon: const Icon(Icons.send, color: Colors.white),
                          onPressed: _sendMessage,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
