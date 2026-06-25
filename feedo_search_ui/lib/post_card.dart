import 'package:flutter/material.dart';
import 'package:timeago/timeago.dart' as timeago;
import 'package:url_launcher/url_launcher.dart';
import 'dart:convert';
import 'services/nostr_publisher.dart';
import 'screens/user_profile_screen.dart';
import 'screens/post_screen.dart';
import 'widgets/linkified_text.dart';

class PostCard extends StatefulWidget {
  final dynamic post;

  const PostCard({super.key, required this.post});

  @override
  State<PostCard> createState() => _PostCardState();
}

class _PostCardState extends State<PostCard> {

  @override
  void initState() {
    super.initState();
  }

  void _openUserProfile() {
    final authorAddress = widget.post['author_address'] ?? widget.post['pubkey'] ?? 'Unknown';
    final authorName = widget.post['author_name'] ?? authorAddress;
    Navigator.of(context).push(MaterialPageRoute(
      builder: (context) => UserProfileScreen(
        pubkey: authorAddress,
        initialName: authorName,
        initialAvatar: widget.post['author_avatar'],
      ),
    ));
  }

  void _openPostScreen() {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (context) => PostScreen(post: widget.post),
    ));
  }

  Future<void> _handleLike() async {
    final postId = widget.post['hash_id'] ?? widget.post['id'];
    final authorPubkey = widget.post['author_address'] ?? widget.post['pubkey'];
    if (postId == null || authorPubkey == null) return;

    if (widget.post['user_liked'] == true) {
      // UNLIKE
      if (widget.post['my_like_id'] == null) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Cannot unlike (ID unknown).')));
        return;
      }
      
      setState(() {
        widget.post['user_liked'] = false;
        widget.post['likes_count'] = (widget.post['likes_count'] ?? 1) - 1;
      });
      
      final deleteId = await NostrPublisher.publishDelete(widget.post['my_like_id']);
      if (deleteId == null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to publish unlike.')));
        setState(() {
          widget.post['user_liked'] = true;
          widget.post['likes_count'] = (widget.post['likes_count'] ?? 0) + 1;
        });
      } else {
        widget.post['my_like_id'] = null; // Cleared
      }
      return;
    }

    // LIKE
    setState(() {
      widget.post['user_liked'] = true;
      widget.post['likes_count'] = (widget.post['likes_count'] ?? 0) + 1;
    });

    final likeId = await NostrPublisher.publishLike(postId, authorPubkey);
    if (likeId == null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to publish like. Are you logged in?')));
      setState(() {
        widget.post['user_liked'] = false;
        widget.post['likes_count'] = (widget.post['likes_count'] ?? 1) - 1;
      });
    } else {
      widget.post['my_like_id'] = likeId;
    }
  }

  Future<void> _handleRepost() async {
    if (widget.post['user_reposted'] == true) return;

    setState(() {
      widget.post['user_reposted'] = true;
      widget.post['reposts_count'] = (widget.post['reposts_count'] ?? 0) + 1;
    });

    final postId = widget.post['hash_id'] ?? widget.post['id'];
    final authorPubkey = widget.post['author_address'] ?? widget.post['pubkey'];
    if (postId == null || authorPubkey == null) return;

    final success = await NostrPublisher.publishRepost(postId, authorPubkey);
    if (success == null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to publish repost.')));
      setState(() {
        widget.post['user_reposted'] = false;
        widget.post['reposts_count'] = (widget.post['reposts_count'] ?? 1) - 1;
      });
    }
  }

  Future<void> _handleComment() async {
    final postId = widget.post['hash_id'] ?? widget.post['id'];
    final authorPubkey = widget.post['author_address'] ?? widget.post['pubkey'];
    if (postId == null || authorPubkey == null) return;

    final textController = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add Comment'),
        content: TextField(
          controller: textController,
          maxLines: 3,
          decoration: const InputDecoration(
            hintText: 'Type your reply...',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, textController.text),
            child: const Text('Reply'),
          ),
        ],
      ),
    );

    if (result != null && result.isNotEmpty) {
      setState(() {
        widget.post['comments_count'] = (widget.post['comments_count'] ?? 0) + 1;
      });
      final success = await NostrPublisher.publishComment(postId, authorPubkey, result);
      if (success == null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to publish comment.')));
        setState(() {
          widget.post['comments_count'] = (widget.post['comments_count'] ?? 1) - 1;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    String text = widget.post['text'] ?? widget.post['content'] ?? '';
    
    // Extract media URLs
    final mediaRegExp = RegExp(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp|mp4|mov|webm)(?:\?\S*)?', caseSensitive: false);
    final mediaUrls = mediaRegExp.allMatches(text).map((m) => m.group(0)!).toList();
    if (text.startsWith('{') && text.contains('"pubkey"') && text.contains('"sig"')) {
      try {
        final parsed = jsonDecode(text);
        if (parsed['content'] != null) {
          text = parsed['content'];
        }
      } catch (_) {}
    }
    final authorAddress = widget.post['author_address'] ?? widget.post['pubkey'] ?? 'Unknown';
    final authorName = widget.post['author_name'] ?? authorAddress;
    final authorAvatar = widget.post['author_avatar'];
    final itemType = widget.post['item_type'] ?? 'post';
    final score = widget.post['similarity_score'] ?? widget.post['score'] ?? 0.0;
    final timestamp = widget.post['timestamp'] ?? widget.post['created_at'] ?? 0;
    
    DateTime? date;
    if (timestamp > 0) {
      date = DateTime.fromMillisecondsSinceEpoch(timestamp * 1000);
    }
    
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Colors.black12, width: 1)),
      ),
      child: Material(
        color: Colors.transparent,
        child: GestureDetector(
          onTap: _openPostScreen,
          onDoubleTap: _handleLike,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  GestureDetector(
                    onTap: _openUserProfile,
                    child: CircleAvatar(
                      radius: 20,
                      backgroundColor: Colors.grey[200],
                      backgroundImage: authorAvatar != null ? NetworkImage(authorAvatar) : null,
                      child: authorAvatar == null 
                        ? const Icon(Icons.person, color: Colors.grey)
                        : null,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        GestureDetector(
                          onTap: _openUserProfile,
                          child: Row(
                            children: [
                              Text(
                                authorName.length > 20 ? '${authorName.substring(0, 16)}...' : authorName,
                                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                              ),
                              const SizedBox(width: 4),
                              Text(
                                '@${authorAddress.length > 12 ? authorAddress.substring(0, 8) : authorAddress}',
                                style: const TextStyle(color: Colors.black54, fontSize: 14),
                              ),
                              const Spacer(),
                              if (date != null && itemType != 'profile')
                                Text(
                                  timeago.format(date, locale: 'en_short'),
                                  style: const TextStyle(color: Colors.black54, fontSize: 14),
                                ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 4),
                        if (text.isNotEmpty)
                          (() {
                            String cleanText = mediaUrls.fold<String>(text, (prev, url) => prev.replaceAll(url, '')).trim();
                            cleanText = cleanText.replaceAll(RegExp(r'\n\s*\n\s*\n+'), '\n\n');
                            
                            return LinkifiedText(
                              text: cleanText,
                              style: const TextStyle(
                                color: Colors.black87,
                                fontSize: 15,
                                height: 1.4,
                              ),
                              maxLines: itemType == 'profile' ? 3 : null,
                              overflow: itemType == 'profile' ? TextOverflow.ellipsis : null,
                            );
                          })(),
                        if (mediaUrls.isNotEmpty) ...[
                          const SizedBox(height: 12),
                          _buildMediaGallery(mediaUrls),
                        ],
                        const SizedBox(height: 12),
                        // Interaction Bar
                        if (itemType != 'profile')
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              _buildInteractionBtn(Icons.chat_bubble_outline, '${widget.post['comments_count'] ?? (widget.post['metrics']?['comments'] ?? 0)}', false, _handleComment),
                              _buildInteractionBtn(Icons.repeat, '${widget.post['reposts_count'] ?? (widget.post['metrics']?['reposts'] ?? 0)}', widget.post['user_reposted'] == true, _handleRepost),
                              _buildInteractionBtn(widget.post['user_liked'] == true ? Icons.favorite : Icons.favorite_border, '${widget.post['likes_count'] ?? (widget.post['metrics']?['likes'] ?? 0)}', widget.post['user_liked'] == true, _handleLike),
                              _buildInteractionBtn(Icons.flash_on, '${widget.post['zaps_count'] ?? (widget.post['metrics']?['tips'] ?? 0)}', (widget.post['zaps_count'] ?? widget.post['metrics']?['tips'] ?? 0) > 0, () {}),
                            ],
                          ),
                        if (score > 0.0)
                          Padding(
                            padding: const EdgeInsets.only(top: 8.0),
                            child: Text(
                              'AI Match: ${(score * 100).toStringAsFixed(1)}%',
                              style: const TextStyle(color: Colors.blueAccent, fontSize: 12, fontWeight: FontWeight.w600),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildInteractionBtn(IconData icon, String count, bool isHighlighted, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Padding(
        padding: const EdgeInsets.all(4.0),
        child: Row(
          children: [
            Icon(icon, size: 18, color: isHighlighted ? Colors.blueAccent : Colors.black54),
            if (count.isNotEmpty) ...[
              const SizedBox(width: 4),
              Text(count, style: TextStyle(
                color: isHighlighted ? Colors.blueAccent : Colors.black54, 
                fontSize: 13,
              )),
            ]
          ],
        ),
      ),
    );
  }

  Widget _buildMediaItem(String url) {
    final lowerUrl = url.toLowerCase();
    final isVideo = lowerUrl.contains('.mp4') || lowerUrl.contains('.mov') || lowerUrl.contains('.webm');
    if (isVideo) {
      return GestureDetector(
        onTap: () async {
          final uri = Uri.parse(url);
          if (await canLaunchUrl(uri)) {
            await launchUrl(uri);
          }
        },
        child: Container(
          color: Colors.black87,
          child: const Center(
            child: Icon(Icons.play_circle_outline, color: Colors.white, size: 64),
          ),
        ),
      );
    } else {
      return Image.network(
        url,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stackTrace) => const SizedBox.shrink(),
      );
    }
  }

  Widget _buildMediaGallery(List<String> urls) {
    if (urls.length == 1) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 400),
          child: SizedBox(
            width: double.infinity,
            child: _buildMediaItem(urls.first),
          ),
        ),
      );
    }
    
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: urls.length == 2 ? 2 : (urls.length == 3 ? 3 : 2),
        crossAxisSpacing: 4,
        mainAxisSpacing: 4,
        childAspectRatio: 1,
      ),
      itemCount: urls.length > 4 ? 4 : urls.length,
      itemBuilder: (context, index) {
        return ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: _buildMediaItem(urls[index]),
        );
      },
    );
  }
}
