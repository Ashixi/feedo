import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/relay_service.dart';
import '../services/nostr_publisher.dart';

class ChatScreen extends StatefulWidget {
  final String channelId;
  final String channelName;
  final String channelPicture;

  const ChatScreen({
    super.key,
    required this.channelId,
    required this.channelName,
    required this.channelPicture,
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

  @override
  void initState() {
    super.initState();
    _connectAndFetch();
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

  Future<void> _connectAndFetch() async {
    final defaultRelays = await RelayService.getRelays();
    final globalRelays = [
      'wss://relay.damus.io',
      'wss://nos.lol',
      'wss://relay.primal.net',
      'wss://relay.nostr.band'
    ];
    final relays = {...defaultRelays, ...globalRelays}.toList();

    final reqId = 'chat_${widget.channelId}_${DateTime.now().millisecondsSinceEpoch}';
    final filter = {
      "kinds": [42],
      "#e": [widget.channelId],
      "limit": 100
    };

    for (var url in relays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        _channels.add(channel);
        channel.sink.add(jsonEncode(['REQ', reqId, filter]));

        channel.stream.listen((msg) {
          try {
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              final id = ev['id'];
              if (!_uniqueMessages.containsKey(id)) {
                _uniqueMessages[id] = {
                  'id': id,
                  'pubkey': ev['pubkey'],
                  'content': ev['content'],
                  'created_at': ev['created_at'],
                };
                
                if (mounted) {
                  setState(() {
                    _messages = _uniqueMessages.values.toList();
                    _messages.sort((a, b) => (b['created_at'] as int).compareTo(a['created_at'] as int));
                  });
                }
              }
            } else if (data[0] == 'EOSE' && data[1] == reqId) {
               setState(() {
                 _isLoading = false;
               });
            }
          } catch (_) {}
        });
      } catch (_) {}
    }

    // Fallback if no EOSE
    await Future.delayed(const Duration(seconds: 4));
    if (mounted) {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _sendMessage() async {
    final text = _msgController.text.trim();
    if (text.isEmpty) return;

    _msgController.clear();
    
    final evId = await NostrPublisher.publishChatMessage(widget.channelId, text);
    if (evId == null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to send message')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            if (widget.channelPicture.isNotEmpty) ...[
              CircleAvatar(
                radius: 16,
                backgroundImage: NetworkImage(widget.channelPicture),
              ),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: Text(widget.channelName, overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: _isLoading && _messages.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    reverse: true,
                    controller: _scrollController,
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      // Simply layout for now
                      return ListTile(
                        title: Text(msg['content']),
                        subtitle: Text('Author: ${msg['pubkey'].toString().substring(0, 8)}'),
                      );
                    },
                  ),
          ),
          const Divider(height: 1),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            color: Theme.of(context).scaffoldBackgroundColor,
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
        ],
      ),
    );
  }
}
