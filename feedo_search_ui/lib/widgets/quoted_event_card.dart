import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:timeago/timeago.dart' as timeago;

import '../utils/constants.dart';
import '../screens/post_screen.dart';
import 'linkified_text.dart';

class QuotedEventCard extends StatefulWidget {
  final String eventId;

  const QuotedEventCard({super.key, required this.eventId});

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
      final url = Uri.parse('${Constants.defaultApiUrl}/posts/resolve/${widget.eventId}');
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
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.grey.shade200),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.grey.shade400),
            ),
            const SizedBox(width: 8),
            Text('Loading quoted event...', style: TextStyle(color: Colors.grey.shade500, fontSize: 14)),
          ],
        ),
      );
    }

    if (_error.isNotEmpty || _postData == null) {
      return Container(
        margin: const EdgeInsets.symmetric(vertical: 8.0),
        padding: const EdgeInsets.all(12.0),
        decoration: BoxDecoration(
          color: Colors.grey.shade50,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.grey.shade200),
        ),
        child: Text(
          _error,
          style: TextStyle(color: Colors.grey.shade600, fontStyle: FontStyle.italic, fontSize: 14),
        ),
      );
    }

    final post = _postData!;
    final authorMetadata = post['metadata']?['author_metadata'] ?? {};
    final String authorName = authorMetadata['display_name'] ?? authorMetadata['name'] ?? 'Unknown User';
    final String? authorAvatar = authorMetadata['picture'];
    final DateTime? date = post['timestamp'] != null ? DateTime.fromMillisecondsSinceEpoch((post['timestamp'] as num).toInt() * 1000) : null;
    final String text = post['text'] ?? '';

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: _openPost,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 8.0),
          padding: const EdgeInsets.all(12.0),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  CircleAvatar(
                    radius: 12,
                    backgroundColor: const Color(0xFFF0F2F5),
                    backgroundImage: (authorAvatar != null && authorAvatar.isNotEmpty) ? NetworkImage(authorAvatar) : null,
                    child: (authorAvatar == null || authorAvatar.isEmpty)
                        ? Icon(Icons.person_rounded, color: Colors.grey.shade400, size: 16)
                        : null,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      authorName,
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: Colors.black87),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  if (date != null)
                    Text(
                      timeago.format(date, locale: 'en_short'),
                      style: TextStyle(color: Colors.grey.shade500, fontSize: 13),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              LinkifiedText(
                text: text,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
