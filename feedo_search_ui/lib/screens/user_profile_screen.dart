import 'chat_screen.dart';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/relay_service.dart';
import '../services/nostr_publisher.dart';
import '../nostr_resolver.dart';
import '../post_card.dart';
import '../feed_layout.dart';
import '../widgets/linkified_text.dart';
import '../utils/bech32.dart';

class UserProfileScreen extends StatefulWidget {
  final String pubkey;
  final String? initialName;
  final String? initialAvatar;
  final String? initialAbout;
  final List<String>? initialRelays;

  const UserProfileScreen({
    super.key, 
    required this.pubkey,
    this.initialName,
    this.initialAvatar,
    this.initialAbout,
    this.initialRelays,
  });

  @override
  State<UserProfileScreen> createState() => _UserProfileScreenState();
}

class _UserProfileScreenState extends State<UserProfileScreen> {
  String? _name;
  String? _avatar;
  String? _about;
  List<Map<String, dynamic>> _posts = [];
  bool _isLoading = true;
  bool _isFollowingLoading = false;
  bool _hasFollowed = false;
  
  final ScrollController _scrollController = ScrollController();
  bool _isLoadingMore = false;
  int? _oldestTimestamp;

  String get _hexPubkey {
    String pk = widget.pubkey;
    if (pk.startsWith('nostr:')) {
      pk = pk.substring(6);
    }
    if (pk.startsWith('npub') || pk.startsWith('nprofile')) {
      try {
        final decoded = Bech32.decodeToHex(pk);
        if (decoded.isNotEmpty) return decoded;
      } catch (_) {}
    }
    return pk;
  }

  @override
  void initState() {
    super.initState();
    _name = widget.initialName;
    _avatar = widget.initialAvatar;
    _about = widget.initialAbout;
    _fetchProfileAndPosts();
    _checkFollowStatus();
    
    _scrollController.addListener(() {
      if (_scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 200) {
        _loadMorePosts();
      }
    });
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _checkFollowStatus() async {
    final pk = _hexPubkey;
    if (pk.isEmpty || pk == 'Unknown') return;
    final following = await NostrPublisher.isFollowing(pk);
    if (mounted) {
      setState(() {
        _hasFollowed = following;
      });
    }
  }

  Future<void> _fetchProfileAndPosts() async {
    final pk = _hexPubkey;
    if (pk.isEmpty || pk == 'Unknown') {
      if (mounted) setState(() => _isLoading = false);
      return;
    }

    final relaySet = (await RelayService.getRelays()).toSet();
    if (widget.initialRelays != null) {
      relaySet.addAll(widget.initialRelays!);
    }
    // Add highly reliable global directory/relay nodes as fallbacks
    relaySet.addAll([
      'wss://purplepag.es',
      'wss://relay.damus.io',
      'wss://nos.lol',
      'wss://relay.nostr.band',
      'wss://relay.primal.net',
      'wss://relay.snort.social',
    ]);
    final relays = relaySet.toList();
    
    // Sub 1: Profile (kind 0)
    // Keep reqId under 64 chars per NIP-01
    final profileReqId = 'p_${pk.substring(0, pk.length > 16 ? 16 : pk.length)}_${DateTime.now().millisecondsSinceEpoch}';
    final profileFilter = {"kinds": [0], "authors": [pk], "limit": 1};
    
    // Sub 2: Posts (kind 1)
    final postsReqId = 'po_${pk.substring(0, pk.length > 16 ? 16 : pk.length)}_${DateTime.now().millisecondsSinceEpoch}';
    final postsFilter = {"kinds": [1], "authors": [pk], "limit": 20};

    final Map<String, dynamic> uniquePosts = {};
    List<WebSocketChannel> channels = [];

    for (var url in relays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        channels.add(channel);
        channel.sink.add(jsonEncode(['REQ', profileReqId, profileFilter]));
        channel.sink.add(jsonEncode(['REQ', postsReqId, postsFilter]));

        channel.stream.listen((msg) {
          try {
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT') {
              final ev = data[2];
              if (data[1] == profileReqId) {
                try {
                  final content = jsonDecode(ev['content']);
                  if (mounted) {
                    setState(() {
                      _name = content['name'] ?? content['display_name'] ?? _name;
                      _avatar = content['picture'] ?? _avatar;
                      _about = content['about'] ?? _about;
                    });
                  }
                } catch (_) {}
              } else if (data[1] == postsReqId) {
                final id = ev['id'];
                if (!uniquePosts.containsKey(id)) {
                  uniquePosts[id] = {
                    'id': id,
                    'hash_id': id,
                    'text': ev['content'],
                    'author_address': ev['pubkey'],
                    'timestamp': ev['created_at'],
                    'item_type': 'post',
                    'relay_urls': relays,
                  };
                  _updatePostsList(uniquePosts);
                }
              }
            }
          } catch (_) {}
        }, onError: (err) {
          print('Error from relay stream: $err');
        });
      } catch (_) {}
    }
    
    // Wait a few seconds to collect profile and posts from all relays
    await Future.delayed(const Duration(seconds: 4));
    
    // Close connections
    for (var ch in channels) {
      try {
        ch.sink.close();
      } catch (_) {}
    }
    
    // Batch resolve all authors and interactions for the posts!
    // Since all posts belong to this user, we can just inject their name/avatar
    for (var post in uniquePosts.values) {
      post['author_name'] = _name ?? post['author_address'];
      post['author_avatar'] = _avatar;
    }
    
    _updatePostsList(uniquePosts);
    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _loadMorePosts() async {
    if (_isLoadingMore || _oldestTimestamp == null) return;
    final pk = _hexPubkey;
    if (pk.isEmpty || pk == 'Unknown') return;
    setState(() => _isLoadingMore = true);

    final relaySet = (await RelayService.getRelays()).toSet();
    if (widget.initialRelays != null) relaySet.addAll(widget.initialRelays!);
    // Add highly reliable global directory/relay nodes as fallbacks
    relaySet.addAll([
      'wss://purplepag.es',
      'wss://relay.damus.io',
      'wss://nos.lol',
      'wss://relay.nostr.band',
      'wss://relay.primal.net',
      'wss://relay.snort.social',
    ]);
    final relays = relaySet.toList();

    final postsReqId = 'more_${pk.substring(0, pk.length > 16 ? 16 : pk.length)}_${DateTime.now().millisecondsSinceEpoch}';
    final postsFilter = {"kinds": [1], "authors": [pk], "limit": 20, "until": _oldestTimestamp};

    final Map<String, dynamic> uniquePosts = { for (var p in _posts) p['id'] as String : p };
    List<WebSocketChannel> channels = [];

    for (var url in relays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        channels.add(channel);
        channel.sink.add(jsonEncode(['REQ', postsReqId, postsFilter]));

        channel.stream.listen((msg) {
          try {
            final data = jsonDecode(msg);
            if (data[0] == 'EVENT' && data[1] == postsReqId) {
              final ev = data[2];
              final id = ev['id'];
              if (!uniquePosts.containsKey(id)) {
                uniquePosts[id] = {
                  'id': id,
                  'hash_id': id,
                  'text': ev['content'],
                  'author_address': ev['pubkey'],
                  'timestamp': ev['created_at'],
                  'item_type': 'post',
                  'relay_urls': relays,
                };
                _updatePostsList(uniquePosts);
              }
            }
          } catch (_) {}
        }, onError: (err) {
          print('Error from load more relay stream: $err');
        });
      } catch (_) {}
    }

    await Future.delayed(const Duration(seconds: 4));
    for (var ch in channels) {
      ch.sink.close();
    }

    for (var post in uniquePosts.values) {
      post['author_name'] = _name ?? post['author_address'];
      post['author_avatar'] = _avatar;
    }

    _updatePostsList(uniquePosts);
    if (mounted) setState(() => _isLoadingMore = false);
  }

  void _updatePostsList(Map<String, dynamic> uniquePosts) {
    var list = uniquePosts.values.toList().cast<Map<String, dynamic>>();
    list.sort((a, b) => (b['timestamp'] as int).compareTo(a['timestamp'] as int));
    
    if (list.isNotEmpty) {
      _oldestTimestamp = list.last['timestamp'] as int;
    }
    
    // Inject current author profile into all posts
    for (var p in list) {
      p['author_name'] = _name ?? p['author_address'];
      p['author_avatar'] = _avatar;
    }

    setState(() {
      _posts = list;
    });
  }

  Future<void> _handleFollow() async {
    setState(() => _isFollowingLoading = true);
    final pk = _hexPubkey;
    if (pk.isEmpty || pk == 'Unknown') return;
    final success = await NostrPublisher.publishFollow(pk);
    if (mounted) {
      if (success != null) {
        setState(() => _hasFollowed = !_hasFollowed);
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(success != null ? (_hasFollowed ? 'Subscribed successfully!' : 'Unsubscribed successfully!') : 'Failed to update subscription. Are you logged in?')),
      );
      setState(() => _isFollowingLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_name ?? 'Profile'),
        actions: [
          IconButton(
            icon: _isFollowingLoading
              ? SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : Icon(_hasFollowed ? Icons.person_remove : Icons.person_add),
            onPressed: _isFollowingLoading ? null : _handleFollow,
          )
        ],
      ),
      body: FeedLayout(
        child: ListView.builder(
          controller: _scrollController,
          itemCount: (_posts.isEmpty && !_isLoading) ? 3 : (_posts.isEmpty && _isLoading ? 3 : _posts.length + 3),
          itemBuilder: (context, index) {
            if (index == 0) return _buildHeader();
            if (index == 1) return const Divider(height: 1);
            
            if (_posts.isEmpty) {
              if (_isLoading) {
                return Padding(
                  padding: EdgeInsets.all(32.0),
                  child: Center(child: CircularProgressIndicator()),
                );
              } else {
                return Padding(
                  padding: const EdgeInsets.all(32.0),
                  child: Center(
                    child: Text('No posts yet.', style: TextStyle(color: Colors.grey[600])),
                  ),
                );
              }
            }
            
            if (index == _posts.length + 2) {
              if (_isLoadingMore) {
                return Padding(
                  padding: EdgeInsets.all(16.0),
                  child: Center(child: CircularProgressIndicator()),
                );
              } else {
                return SizedBox(height: 32);
              }
            }
            
            return PostCard(post: _posts[index - 2]);
          },
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(16.0),
      color: Colors.transparent,
      child: Column(
        children: [
          CircleAvatar(
            radius: 40,
            backgroundImage: _avatar != null ? NetworkImage(_avatar!) : null,
            child: _avatar == null ? Icon(Icons.person, size: 40) : null,
          ),
          SizedBox(height: 12),
          Text(
            _name ?? 'Unknown User',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
          ),
          SizedBox(height: 4),
          Text(
            '@${_hexPubkey.length > 12 ? _hexPubkey.substring(0, 12) : _hexPubkey}...',
            style: TextStyle(color: Colors.grey),
          ),
          if (_about != null && _about!.isNotEmpty) ...[
            SizedBox(height: 12),
            LinkifiedText(
              text: _about!,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 14),
            ),
          ],
          SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton.icon(
                onPressed: _isFollowingLoading ? null : _handleFollow,
                icon: _isFollowingLoading 
                  ? SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : Icon(_hasFollowed ? Icons.person_remove : Icons.person_add),
                label: Text(_isFollowingLoading ? 'Updating...' : (_hasFollowed ? 'Unsubscribe' : 'Subscribe')),
                style: ElevatedButton.styleFrom(
                  backgroundColor: _hasFollowed ? Colors.grey[800] : Colors.black87,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                ),
              ),
              SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: () {
                  Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (context) => ChatScreen(
                        peerPubkey: _hexPubkey,
                        peerName: _name ?? 'Unknown User',
                        peerPicture: _avatar ?? '',
                      ),
                    ),
                  );
                },
                icon: Icon(Icons.chat_bubble_outline),
                label: const Text('Message'),
                style: OutlinedButton.styleFrom(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                  foregroundColor: Colors.white,
                ),
              ),
            ],
          )
        ],
      ),
    );
  }
}




