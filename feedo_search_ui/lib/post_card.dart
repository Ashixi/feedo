import 'package:flutter/material.dart';
import 'package:timeago/timeago.dart' as timeago;
import 'package:url_launcher/url_launcher.dart';

class PostCard extends StatelessWidget {
  final dynamic post;

  const PostCard({super.key, required this.post});

  void _openPost(String hashId) async {
    final url = Uri.parse('https://njump.me/$hashId');
    if (await canLaunchUrl(url)) {
      await launchUrl(url);
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = post;
    final text = item['text'] ?? item['content'] ?? '';
    final authorAddress = item['author_address'] ?? item['pubkey'] ?? 'Unknown';
    final authorName = item['author_name'] ?? authorAddress;
    final authorAvatar = item['author_avatar'];
    final itemType = item['item_type'] ?? 'post';
    final score = item['similarity_score'] ?? item['score'] ?? 0.0;
    final timestamp = item['timestamp'] ?? item['created_at'] ?? 0;
    
    DateTime? date;
    if (timestamp > 0) {
      date = DateTime.fromMillisecondsSinceEpoch(timestamp * 1000);
    }
    
    // Attempt to extract a decent URL if relay_url is present
    String? url;
    if (item['relay_urls'] != null && (item['relay_urls'] as List).isNotEmpty) {
      final relays = List<String>.from(item['relay_urls']);
      final webUrl = relays.firstWhere((r) => r.startsWith('http'), orElse: () => '');
      if (webUrl.isNotEmpty) url = webUrl;
    }
    
    // Nostr njump fallback for Nostr hashes
    final hashId = item['hash_id'] ?? item['id'];
    if (url == null && hashId != null && hashId.toString().length == 64) {
      if (itemType == 'profile') {
         url = 'https://njump.me/p/$authorAddress';
      } else {
         url = 'https://njump.me/$hashId';
      }
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Colors.black12, width: 1)),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: url != null ? () => _openPost(hashId) : null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  CircleAvatar(
                    radius: 20,
                    backgroundColor: Colors.grey[200],
                    backgroundImage: authorAvatar != null ? NetworkImage(authorAvatar) : null,
                    child: authorAvatar == null 
                      ? const Icon(Icons.person, color: Colors.grey)
                      : null,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
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
                        const SizedBox(height: 4),
                        if (text.isNotEmpty)
                          Text(
                            text,
                            style: const TextStyle(
                              color: Colors.black87,
                              fontSize: 15,
                              height: 1.4,
                            ),
                            maxLines: itemType == 'profile' ? 3 : null,
                            overflow: itemType == 'profile' ? TextOverflow.ellipsis : null,
                          ),
                        const SizedBox(height: 12),
                        // Interaction Bar
                        if (itemType != 'profile')
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              _buildInteractionIcon(Icons.chat_bubble_outline, '0'),
                              _buildInteractionIcon(Icons.repeat, '0'),
                              _buildInteractionIcon(Icons.favorite_border, '0'),
                              _buildInteractionIcon(Icons.flash_on, '0'), // Zaps
                              _buildInteractionIcon(Icons.share, ''),
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

  Widget _buildInteractionIcon(IconData icon, String count) {
    return Row(
      children: [
        Icon(icon, size: 18, color: Colors.black54),
        if (count.isNotEmpty) ...[
          const SizedBox(width: 4),
          Text(count, style: const TextStyle(color: Colors.black54, fontSize: 13)),
        ]
      ],
    );
  }
}
