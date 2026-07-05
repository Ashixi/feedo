import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:timeago/timeago.dart' as timeago;

import '../utils/constants.dart';
import '../screens/post_screen.dart';
import 'linkified_text.dart';

class QuotedEventCard extends StatefulWidget {
  final String eventId;
  final List<String> relays;
  final String author;
  final int depth;

  const QuotedEventCard({super.key, required this.eventId, this.relays = const [], this.author = '', this.depth = 0});

  @override
  State<QuotedEventCard> createState() => _QuotedEventCardState();
}

class _QuotedEventCardState extends State<QuotedEventCard> {
  bool _isLoading = true;
  Map<String, dynamic>? _postData;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _fetchEvent();
  }

  Future<void> _fetchEvent() async {
    try {
      Uri url = Uri.parse('${Constants.defaultApiUrl}/posts/resolve/${widget.eventId}');
      Map<String, dynamic> queryParams = {};
      if (widget.relays.isNotEmpty) {
        queryParams['relay'] = widget.relays;
      }
      if (widget.author.isNotEmpty) {
        queryParams['author'] = widget.author;
      }
      if (queryParams.isNotEmpty) {
        url = url.replace(queryParameters: queryParams);
      }
      final response = await http.get(url, headers: {'Accept': 'application/json'}).timeout(const Duration(seconds: 15));
      
      if (response.statusCode == 200) {
        if (mounted) {
          setState(() {
            _postData = json.decode(response.body);
            _isLoading = false;
          });
        }
      } else {
        if (mounted) {
          setState(() {
            _error = 'Post not found.';
            _isLoading = false;
          });
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Could not load quoted event.';
          _isLoading = false;
        });
      }
    }
  }

  void _openPost() {
    if (_postData == null) return;
    Navigator.of(context).push(MaterialPageRoute(
      builder: (context) => PostScreen(
        post: _postData!,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Container(
        margin: const EdgeInsets.symmetric(vertical: 8.0),
        padding: const EdgeInsets.all(12.0),
        decoration: BoxDecoration(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white.withOpacity(0.08)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.grey.shade500),
            ),
            const SizedBox(width: 8),
            Text('Loading quoted event...', style: TextStyle(color: Colors.grey.shade400, fontSize: 14)),
          ],
        ),
      );
    }

    if (_error.isNotEmpty || _postData == null) {
      return Container(
        margin: const EdgeInsets.symmetric(vertical: 8.0),
        padding: const EdgeInsets.all(12.0),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.05),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white.withOpacity(0.08)),
        ),
        child: Text(
          _error,
          style: TextStyle(color: Colors.grey.shade400, fontStyle: FontStyle.italic, fontSize: 14),
        ),
      );
    }

    final post = _postData!;
    final String authorAddress = post['author_address'] ?? 'Unknown';
    final String authorName = post['display_author'] ?? post['author_name'] ?? post['name'] ?? post['display_name'] ?? authorAddress;
    final String? authorAvatar = post['avatar_url'] ?? post['author_avatar'] ?? post['picture'];
    
    DateTime? date;
    final publishedAt = post['published_at'];
    if (publishedAt is String) {
      date = DateTime.tryParse(publishedAt);
    } else if (publishedAt is int) {
      date = DateTime.fromMillisecondsSinceEpoch(publishedAt * 1000);
    } else {
      final timestamp = post['timestamp'] ?? post['created_at'];
      if (timestamp is int && timestamp > 0) {
        date = DateTime.fromMillisecondsSinceEpoch(timestamp * 1000);
      }
    }
    final String text = post['text'] ?? post['content'] ?? post['about'] ?? '';

    if (widget.depth >= 4) {
      return GestureDetector(
        onTap: _openPost,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4.0),
          padding: const EdgeInsets.all(8.0),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.05),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.white.withOpacity(0.1)),
          ),
          child: Row(
            children: [
              const Icon(Icons.link, color: Colors.blueAccent, size: 16),
              const SizedBox(width: 8),
              const Expanded(
                child: Text(
                  '🔗 Глибока гілка (натисніть щоб відкрити)',
                  style: TextStyle(color: Colors.blueAccent, fontStyle: FontStyle.italic),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      );
    }

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: _openPost,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 8.0),
          padding: widget.depth > 0 ? const EdgeInsets.only(left: 12.0, top: 4.0, bottom: 4.0) : const EdgeInsets.all(12.0),
          decoration: BoxDecoration(
            color: widget.depth > 0 ? Colors.transparent : Colors.white.withOpacity(0.03),
            borderRadius: widget.depth > 0 ? BorderRadius.zero : BorderRadius.circular(12),
            border: widget.depth > 0 
                ? Border(left: BorderSide(color: Colors.grey.shade600, width: 3))
                : Border.all(color: Colors.white.withOpacity(0.1)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  CircleAvatar(
                    radius: 12,
                    backgroundColor: Colors.white.withOpacity(0.1),
                    backgroundImage: (authorAvatar != null && authorAvatar.isNotEmpty) ? NetworkImage(authorAvatar) : null,
                    child: (authorAvatar == null || authorAvatar.isEmpty)
                        ? Icon(Icons.person_rounded, color: Colors.grey.shade400, size: 16)
                        : null,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      authorName,
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: Colors.white),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  if (date != null)
                    Text(
                      timeago.format(date, locale: 'en_short'),
                      style: TextStyle(color: Colors.grey.shade400, fontSize: 13),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              if (text.isNotEmpty)
                LinkifiedText(
                  text: text,
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis,
                  depth: widget.depth,
                ),
            ],
          ),
        ),
      ),
    );
  }
}
