import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/relay_service.dart';
import '../nostr_resolver.dart';
import '../post_card.dart';
import '../feed_layout.dart';

class PostScreen extends StatefulWidget {
  final Map<String, dynamic> post;

  const PostScreen({super.key, required this.post});

  @override
  State<PostScreen> createState() => _PostScreenState();
}

class _PostScreenState extends State<PostScreen> {
  List<Map<String, dynamic>> _comments = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchComments();
  }

  Future<void> _fetchComments() async {
    final relays = await RelayService.getRelays();
    
    // Add the post's original relays to ensure we find its comments
    List<dynamic>? postRelays = widget.post['relay_urls'];
    if (postRelays == null && widget.post['metadata'] != null) {
      postRelays = widget.post['metadata']['relay_urls'];
    }
    if (postRelays != null) {
      for (var r in postRelays) {
        if (!relays.contains(r)) relays.add(r.toString());
      }
    }

    final postId = widget.post['hash_id'] ?? widget.post['id'];
    
    if (postId == null) {
      if (mounted) setState(() => _isLoading = false);
      return;
    }

    // Keep reqId under 64 chars per NIP-01
    final reqId = 'c_${postId.substring(0, 16)}_${DateTime.now().millisecondsSinceEpoch}';
    final filter = {
      "kinds": [1],
      "#e": [postId],
      "limit": 50
    };

    final Map<String, dynamic> uniqueComments = {};
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
              
              if (!uniqueComments.containsKey(id)) {
                uniqueComments[id] = {
                  'id': id,
                  'hash_id': id,
                  'text': ev['content'],
                  'author_address': ev['pubkey'],
                  'timestamp': ev['created_at'],
                  'item_type': 'post',
                };
                _updateCommentsList(uniqueComments);
              }
            }
          } catch (_) {}
        });
      } catch (_) {}
    }
    
    // Wait a few seconds to collect comments from all relays
    await Future.delayed(const Duration(seconds: 4));
    
    // Close connections
    for (var ch in channels) {
      ch.sink.close();
    }
    
    // Update the main post's comment count to match exactly what we fetched
    if (mounted) {
      setState(() {
        widget.post['comments_count'] = uniqueComments.length;
      });
    }
    
    // Fetch profiles for all unique comment authors in one bulk request
    final Set<String> authors = uniqueComments.values.map((c) => c['author_address'] as String).toSet();
    if (authors.isNotEmpty && mounted) {
      final profileReqId = 'p_${DateTime.now().millisecondsSinceEpoch}';
      final profileFilter = {"kinds": [0], "authors": authors.toList()};
      
      for (var url in relays) {
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          channel.sink.add(jsonEncode(['REQ', profileReqId, profileFilter]));
          
          channel.stream.listen((msg) {
            try {
              final data = jsonDecode(msg);
              if (data[0] == 'EVENT' && data[1] == profileReqId) {
                final ev = data[2];
                final content = jsonDecode(ev['content']);
                bool changed = false;
                
                for (var comment in uniqueComments.values) {
                  if (comment['author_address'] == ev['pubkey'] && comment['author_avatar'] == null) {
                    comment['author_name'] = content['name'] ?? content['display_name'];
                    comment['author_avatar'] = content['picture'];
                    changed = true;
                  }
                }
                if (changed) _updateCommentsList(uniqueComments);
              }
            } catch (_) {}
          });
          
          // Keep profile sockets open longer to ensure we get all profiles
          Future.delayed(const Duration(seconds: 4), () => channel.sink.close());
        } catch (_) {}
      }
    }
    
    if (mounted) setState(() => _isLoading = false);
  }

  void _updateCommentsList(Map<String, dynamic> uniqueComments) {
    if (!mounted) return;
    final list = uniqueComments.values.toList().cast<Map<String, dynamic>>();
    // Sort oldest first for comments, or newest first? Let's do oldest first so it reads like a thread
    list.sort((a, b) => (a['timestamp'] as int).compareTo(b['timestamp'] as int));

    setState(() {
      _comments = list;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Post'),
      ),
      body: FeedLayout(
        child: Column(
          children: [
          // The main post
          PostCard(post: widget.post),
          const Divider(height: 1, thickness: 2),
          
          // Comments header
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            alignment: Alignment.centerLeft,
            color: Colors.grey[100],
            child: Text(
              'Comments',
              style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey[700]),
            ),
          ),
          
          // The comments list
          Expanded(
            child: _isLoading && _comments.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : _comments.isEmpty
                    ? Center(
                        child: Text(
                          'No comments yet.',
                          style: TextStyle(color: Colors.grey[600]),
                        ),
                      )
                    : ListView.builder(
                        itemCount: _comments.length,
                        itemBuilder: (context, index) {
                          return PostCard(post: _comments[index]);
                        },
                      ),
          )
        ],
      ),
    ),
    );
  }
}
