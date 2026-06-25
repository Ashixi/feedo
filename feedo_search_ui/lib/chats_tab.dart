import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'services/relay_service.dart';
import 'screens/chat_screen.dart';

class ChatsTab extends StatefulWidget {
  const ChatsTab({super.key});

  @override
  State<ChatsTab> createState() => _ChatsTabState();
}

class _ChatsTabState extends State<ChatsTab> {
  bool _isLoading = true;
  List<Map<String, dynamic>> _channels = [];
  final Map<String, Map<String, dynamic>> _uniqueChannels = {};
  List<String> _subscribedIds = [];

  @override
  void initState() {
    super.initState();
    _loadSubscriptions();
    _fetchChannels();
  }

  Future<void> _loadSubscriptions() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _subscribedIds = prefs.getStringList('subscribed_channels') ?? [];
    });
  }

  Future<void> _toggleSubscription(String channelId) async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      if (_subscribedIds.contains(channelId)) {
        _subscribedIds.remove(channelId);
      } else {
        _subscribedIds.add(channelId);
      }
    });
    await prefs.setStringList('subscribed_channels', _subscribedIds);
  }

  Future<void> _fetchChannels() async {
    setState(() {
      _isLoading = true;
      _uniqueChannels.clear();
      _channels.clear();
    });

    final relays = await RelayService.getRelays();
    final reqId = 'channels_${DateTime.now().millisecondsSinceEpoch}';
    final filter = {"kinds": [40], "limit": 200};
    
    List<WebSocketChannel> channels = [];

    for (var url in relays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        channels.add(channel);
        channel.sink.add(jsonEncode(['REQ', reqId, filter]));

        channel.stream.listen((msg) {
          try {
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == reqId) {
              final ev = data[2];
              final id = ev['id'];
              if (!_uniqueChannels.containsKey(id)) {
                String name = 'Unknown Channel';
                String about = '';
                String picture = '';

                try {
                  final content = jsonDecode(ev['content']);
                  name = content['name'] ?? name;
                  about = content['about'] ?? '';
                  picture = content['picture'] ?? '';
                } catch (_) {}

                _uniqueChannels[id] = {
                  'id': id,
                  'pubkey': ev['pubkey'],
                  'created_at': ev['created_at'],
                  'name': name,
                  'about': about,
                  'picture': picture,
                };
                
                if (mounted) {
                  setState(() {
                    _channels = _uniqueChannels.values.toList();
                    _channels.sort((a, b) => (b['created_at'] as int).compareTo(a['created_at'] as int));
                  });
                }
              }
            }
          } catch (_) {}
        });
      } catch (_) {}
    }

    await Future.delayed(const Duration(seconds: 4));
    for (var ch in channels) {
      ch.sink.close();
    }
    
    if (mounted) {
      setState(() {
        _isLoading = false;
      });
    }
  }

  void _openChat(Map<String, dynamic> channel) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => ChatScreen(
          channelId: channel['id'],
          channelName: channel['name'],
          channelPicture: channel['picture'],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Column(
        children: [
          Container(
            color: Theme.of(context).appBarTheme.backgroundColor ?? Theme.of(context).primaryColor,
            child: const TabBar(
              labelColor: Colors.white,
              unselectedLabelColor: Colors.white70,
              tabs: [
                Tab(text: 'My Chats'),
                Tab(text: 'Discover'),
              ],
            ),
          ),
          Expanded(
            child: TabBarView(
              children: [
                _buildList(onlySubscribed: true),
                _buildList(onlySubscribed: false),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildList({required bool onlySubscribed}) {
    if (_isLoading && _channels.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    final displayChannels = onlySubscribed 
        ? _channels.where((ch) => _subscribedIds.contains(ch['id'])).toList()
        : _channels;

    if (displayChannels.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.forum_outlined, size: 64, color: Colors.grey[400]),
            const SizedBox(height: 16),
            Text(
              onlySubscribed ? 'No subscribed chats.' : 'No active chats found.',
              style: TextStyle(color: Colors.grey[600], fontSize: 16)
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      itemCount: displayChannels.length,
      itemBuilder: (context, index) {
        final ch = displayChannels[index];
        final isSubbed = _subscribedIds.contains(ch['id']);
        
        return ListTile(
          leading: CircleAvatar(
            backgroundColor: Colors.grey[200],
            backgroundImage: ch['picture'].toString().isNotEmpty ? NetworkImage(ch['picture']) : null,
            child: ch['picture'].toString().isEmpty ? const Icon(Icons.tag, color: Colors.grey) : null,
          ),
          title: Text(ch['name'], style: const TextStyle(fontWeight: FontWeight.bold)),
          subtitle: ch['about'].toString().isNotEmpty 
            ? Text(ch['about'], maxLines: 1, overflow: TextOverflow.ellipsis)
            : null,
          trailing: IconButton(
            icon: Icon(
              isSubbed ? Icons.favorite : Icons.favorite_border,
              color: isSubbed ? Colors.red : Colors.grey,
            ),
            onPressed: () => _toggleSubscription(ch['id']),
          ),
          onTap: () => _openChat(ch),
        );
      },
    );
  }
}
