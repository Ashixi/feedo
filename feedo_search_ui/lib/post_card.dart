
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:timeago/timeago.dart' as timeago;
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'services/nostr_publisher.dart';
import 'services/nwc_service.dart';
import 'screens/post_screen.dart';
import 'screens/user_profile_screen.dart';
import 'widgets/linkified_text.dart';
import 'utils/constants.dart';

class PostCard extends StatefulWidget {
  final dynamic post;

  const PostCard({super.key, required this.post});

  @override
  State<PostCard> createState() => _PostCardState();
}

class _PostCardState extends State<PostCard> {
  bool _isHovered = false;
  bool _isLoadingContent = false;

  @override
  void initState() {
    super.initState();
    _checkAndLoadMissingContent();
  }

  Future<void> _checkAndLoadMissingContent() async {
    final String text = widget.post['text'] ?? widget.post['content'] ?? widget.post['about'] ?? '';
    final String? hashId = widget.post['hash_id'];
    final String? sourceType = widget.post['source_type'];
    
    // Only fetch if text is empty and hash_id exists
    if (text.trim().isEmpty && hashId != null) {
      if (!mounted) return;
      setState(() => _isLoadingContent = true);
      
      try {
        if (sourceType == 'nostr') {
           List<String>? relayUrls;
           if (widget.post['relay_urls'] != null) {
             relayUrls = List<String>.from(widget.post['relay_urls']);
           }
           final ev = await NostrPublisher.fetchEventById(hashId, additionalRelays: relayUrls);
           if (mounted && ev != null) {
             setState(() {
               widget.post['text'] = ev['content'];
               
               List<String> extractedMedia = [];
               if (ev['tags'] != null) {
                 for (var tag in ev['tags']) {
                   if (tag is List && tag.isNotEmpty && (tag[0] == 'url' || tag[0] == 'image' || tag[0] == 'imeta')) {
                     if (tag.length > 1) extractedMedia.add(tag[1].toString());
                   }
                 }
               }
               
               final RegExp mediaRegex = RegExp(r'(https?:\/\/[^\s]+\.(?:jpg|jpeg|png|gif|webp|mp4|mov))', caseSensitive: false);
               final matches = mediaRegex.allMatches(ev['content'] ?? '');
               for (final m in matches) {
                 final url = m.group(0);
                 if (url != null && !extractedMedia.contains(url)) extractedMedia.add(url);
               }
               
               if (extractedMedia.isNotEmpty) {
                 widget.post['media'] = extractedMedia;
               }
             });
           }
        } else {
           final url = Uri.parse('${Constants.apiUrl}/posts/$hashId/load_full');
           final response = await http.get(url);
           if (response.statusCode == 200) {
              final data = jsonDecode(response.body);
              if (mounted && data['content'] != null) {
                setState(() {
                  widget.post['text'] = data['content'];
                });
              }
           }
        }
      } catch (_) {
        // ignore errors, just keep it empty
      } finally {
        if (mounted) {
          setState(() => _isLoadingContent = false);
        }
      }
    }
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
        widget.post['my_like_id'] = null;
      }
      return;
    }

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

  Future<void> _handleZap() async {
    final hasWallet = await NwcService.hasWallet();
    if (!hasWallet) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please connect a Lightning Wallet in Settings to Zap!')));
      return;
    }

    final lud16 = widget.post['author_lud16'];
    if (lud16 == null || !lud16.contains('@')) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Author has no Lightning Address (lud16) set up.')));
      return;
    }

    setState(() {
      widget.post['zaps_count'] = (widget.post['zaps_count'] ?? widget.post['metrics']?['tips'] ?? 0) + 1;
    });
    
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Zapping 50 sats...')));

    try {
      final parts = lud16.split('@');
      final url = 'https://${parts[1]}/.well-known/lnurlp/${parts[0]}';
      final response = await http.get(Uri.parse(url));
      if (response.statusCode == 200) {
        final lnurlData = jsonDecode(response.body);
        final callback = lnurlData['callback'];
        final invoiceResponse = await http.get(Uri.parse('$callback?amount=50000'));
        if (invoiceResponse.statusCode == 200) {
          final invoiceData = jsonDecode(invoiceResponse.body);
          final pr = invoiceData['pr'];
          if (pr != null) {
            final success = await NwcService.payInvoice(pr);
            if (success && mounted) {
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Zap successful! ⚡')));
              return;
            }
          }
        }
      }
    } catch (e) {
      print('Zap error: $e');
    }

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to Zap. Please check your wallet connection.')));
      setState(() {
        widget.post['zaps_count'] = (widget.post['zaps_count'] ?? 1) - 1;
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
    final String text = widget.post['text'] ?? widget.post['content'] ?? widget.post['about'] ?? '';
    final String authorAddress = widget.post['author_address'] ?? widget.post['pubkey'] ?? 'Unknown';
    final String authorName = widget.post['author_name'] ?? authorAddress;
    final String? authorAvatar = widget.post['author_avatar'] ?? widget.post['picture'] ?? widget.post['metadata']?['picture'];
    final double score = (widget.post['similarity_score'] ?? widget.post['score'] ?? 0.0).toDouble();
    
    DateTime? date;
    final int timestamp = widget.post['timestamp'] ?? widget.post['created_at'] ?? 0;
    if (timestamp > 0) {
      date = DateTime.fromMillisecondsSinceEpoch(timestamp * 1000);
    } else if (widget.post['published_at'] != null) {
      date = DateTime.tryParse(widget.post['published_at']);
    }

    final itemType = widget.post['item_type'] ?? 'post';
    List<String> mediaUrls = [];
    if (widget.post['media'] != null && widget.post['media'] is List) {
      mediaUrls = List<String>.from(widget.post['media']);
    }
    
    // Threads-style continuous feed container (no individual cards, just flat backgrounds with dividers)
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: Container(
        color: _isHovered ? Colors.grey.shade50 : Colors.white,
        child: InkWell(
          onTap: _openPostScreen,
          child: Padding(
            padding: const EdgeInsets.only(top: 16.0, left: 24.0, right: 24.0, bottom: 8.0),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Avatar column
                Column(
                  children: [
                    MouseRegion(
                      cursor: SystemMouseCursors.click,
                      child: GestureDetector(
                        onTap: _openUserProfile,
                        child: CircleAvatar(
                          radius: 20,
                          backgroundColor: const Color(0xFFF0F2F5),
                          backgroundImage: (authorAvatar != null && authorAvatar.isNotEmpty) ? NetworkImage(authorAvatar) : null,
                          child: (authorAvatar == null || authorAvatar.isEmpty)
                            ? Icon(Icons.person_rounded, color: Colors.grey.shade400, size: 20)
                            : null,
                        ),
                      ),
                    ),
                    // Thread line could go here in the future
                  ],
                ),
                const SizedBox(width: 16),
                
                // Content Column
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Repost Indicator
                      if (widget.post['is_repost'] == true || widget.post['metadata']?['kind'] == 6)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4.0),
                          child: Row(
                            children: [
                              Icon(Icons.repeat_rounded, size: 14, color: Colors.grey.shade500),
                              const SizedBox(width: 4),
                              Text(
                                'Reposted',
                                style: TextStyle(color: Colors.grey.shade500, fontSize: 13, fontWeight: FontWeight.w500),
                              ),
                            ],
                          ),
                        ),
                      // Header
                      MouseRegion(
                        cursor: SystemMouseCursors.click,
                        child: GestureDetector(
                          onTap: _openUserProfile,
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.baseline,
                            textBaseline: TextBaseline.alphabetic,
                            children: [
                              Flexible(
                                child: Text(
                                  authorName,
                                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: Colors.black87),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              const SizedBox(width: 8),
                              if (date != null && itemType != 'profile')
                                Text(
                                  timeago.format(date, locale: 'en_short'),
                                  style: TextStyle(color: Colors.grey.shade500, fontSize: 14),
                                ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 4),
                      
                      // Body Text
                      if (_isLoadingContent)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4.0),
                          child: SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.grey.shade400,
                            ),
                          ),
                        )
                      else if (text.isNotEmpty)
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
                        
                      // Media Gallery
                      if (mediaUrls.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        _buildMediaGallery(mediaUrls),
                      ],
                      
                      // Interaction Bar
                      if (itemType != 'profile') ...[
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            _buildInteractionBtn(Icons.favorite_border_rounded, '${widget.post['likes_count'] ?? widget.post['metrics']?['likes'] ?? ''}', widget.post['user_liked'] == true, _handleLike, hoverColor: Colors.pink.withOpacity(0.1), iconColor: Colors.pink),
                            const SizedBox(width: 16),
                            _buildInteractionBtn(Icons.chat_bubble_outline_rounded, '${widget.post['comments_count'] ?? widget.post['metrics']?['comments'] ?? ''}', false, _handleComment, hoverColor: Colors.blue.withOpacity(0.1), iconColor: Colors.blue),
                            const SizedBox(width: 16),
                            _buildInteractionBtn(Icons.repeat_rounded, '${widget.post['reposts_count'] ?? widget.post['metrics']?['reposts'] ?? ''}', widget.post['user_reposted'] == true, _handleRepost, hoverColor: Colors.green.withOpacity(0.1), iconColor: Colors.green),
                            const Spacer(), // Push zap to the right like a secondary action if needed, or keep it together
                            _buildInteractionBtn(Icons.flash_on_rounded, '${widget.post['zaps_count'] ?? widget.post['metrics']?['tips'] ?? ''}', (widget.post['zaps_count'] ?? widget.post['metrics']?['tips'] ?? 0) > 0, _handleZap, hoverColor: Colors.orange.withOpacity(0.1), iconColor: Colors.orange),
                          ],
                        ),
                      ],
                      
                      // AI Match Score
                      if (score > 0.0)
                        Padding(
                          padding: const EdgeInsets.only(top: 12.0),
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: Colors.purple.shade50,
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.auto_awesome, size: 14, color: Colors.purple.shade600),
                                const SizedBox(width: 4),
                                Text(
                                  'AI Match: ${(score * 100).toStringAsFixed(1)}%',
                                  style: TextStyle(color: Colors.purple.shade700, fontSize: 12, fontWeight: FontWeight.w600),
                                ),
                              ],
                            ),
                          ),
                        ),
                        
                      // Separator for the bottom of the item (Threads style subtle divider)
                      const SizedBox(height: 12),
                      Divider(color: Colors.grey.withOpacity(0.15), height: 1),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildInteractionBtn(IconData icon, String count, bool isHighlighted, VoidCallback onTap, {Color? hoverColor, Color? iconColor}) {
    if (count == '0' || count == 'null') count = '';
    
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        hoverColor: hoverColor,
        splashColor: hoverColor,
        highlightColor: hoverColor,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8.0, vertical: 6.0),
          child: Row(
            children: [
              Icon(icon, size: 20, color: isHighlighted ? iconColor : Colors.grey.shade500),
              if (count.isNotEmpty) ...[
                const SizedBox(width: 6),
                Text(count, style: TextStyle(
                  color: isHighlighted ? iconColor : Colors.grey.shade600, 
                  fontSize: 14,
                  fontWeight: isHighlighted ? FontWeight.w600 : FontWeight.normal,
                )),
              ]
            ],
          ),
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
            child: Icon(Icons.play_circle_fill_rounded, color: Colors.white, size: 48),
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
        child: Container(
          decoration: BoxDecoration(
            border: Border.all(color: Colors.grey.withOpacity(0.1)),
            borderRadius: BorderRadius.circular(12),
          ),
          constraints: const BoxConstraints(maxHeight: 400),
          child: SizedBox(
            width: double.infinity,
            child: _buildMediaItem(urls.first),
          ),
        ),
      );
    }
    
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.withOpacity(0.1)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: GridView.builder(
          padding: EdgeInsets.zero,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: urls.length == 2 ? 2 : (urls.length == 3 ? 3 : 2),
            crossAxisSpacing: 2,
            mainAxisSpacing: 2,
            childAspectRatio: 1,
          ),
          itemCount: urls.length > 4 ? 4 : urls.length,
          itemBuilder: (context, index) {
            return _buildMediaItem(urls[index]);
          },
        ),
      ),
    );
  }
}
