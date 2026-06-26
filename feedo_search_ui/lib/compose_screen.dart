import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'services/auth_service.dart';
import 'services/relay_service.dart';
import 'package:http/http.dart' as http;
import 'utils/constants.dart';

class ComposeScreen extends StatefulWidget {
  const ComposeScreen({super.key});

  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  final TextEditingController _textController = TextEditingController();
  bool _postToNostr = true;
  bool _postToFarcaster = false;
  bool _isPosting = false;

  Future<void> _publishPost() async {
    final content = _textController.text.trim();
    if (content.isEmpty) return;

    if (!_postToNostr && !_postToFarcaster) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select at least one network to publish.')),
      );
      return;
    }

    setState(() => _isPosting = true);

    bool successNostr = true;

    if (_postToNostr) {
      successNostr = await _publishToNostr(content);
    }

    if (_postToFarcaster) {
      // Show warning but don't block closing
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Farcaster publishing is coming soon! Only posted to Nostr.')),
        );
      }
    }

    setState(() => _isPosting = false);

    if (successNostr || _postToFarcaster) {
      if (mounted) {
        Navigator.of(context).pop();
        if (successNostr && !_postToFarcaster) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Post published successfully!')),
          );
        }
      }
    }
  }

  Future<bool> _publishToNostr(String content) async {
    final event = await AuthService.signEvent(1, content, []);
    if (event == null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to sign Nostr event. Do you have an account?')),
        );
      }
      return false;
    }

    // Broadcast to user-selected relays
    int successCount = 0;
    final relays = await RelayService.getRelays();
    
    for (String relayUrl in relays) {
      try {
        final channel = WebSocketChannel.connect(Uri.parse(relayUrl));
        final msg = jsonEncode(["EVENT", event.toMap()]);
        channel.sink.add(msg);
        
        Future.delayed(const Duration(seconds: 2), () {
          channel.sink.close();
        });
        successCount++;
      } catch (e) {
        print("Failed to broadcast to $relayUrl: $e");
      }
    }

    if (successCount > 0) {
      // Instant Indexing: Ping Feedo Backend
      try {
        await http.post(
          Uri.parse(Constants.ingestUrl),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(event.toMap()),
        );
      } catch (e) {
        print("Failed to ping Feedo backend: $e");
      }
    }

    return successCount > 0;
  }

  Future<bool> _publishToFarcaster(String content) async {
    // Farcaster Auth is not yet integrated. Wait for Neynar API key.
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Farcaster publishing is coming soon!')),
      );
    }
    return false; // Return false so dialog doesn't close if they only selected Farcaster
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
        left: 16,
        right: 16,
        top: 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Cancel', style: TextStyle(color: Colors.black54)),
              ),
              ElevatedButton(
                onPressed: _isPosting ? null : _publishPost,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.black87,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                ),
                child: _isPosting 
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Text('Post', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
            ],
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _textController,
            maxLines: 6,
            minLines: 3,
            autofocus: true,
            style: const TextStyle(color: Colors.black87, fontSize: 18),
            decoration: const InputDecoration(
              hintText: "What's happening in Web3?",
              hintStyle: TextStyle(color: Colors.black38),
              border: InputBorder.none,
            ),
          ),
          const Divider(color: Colors.black12),
          const SizedBox(height: 8),
          const Text('Publish to:', style: TextStyle(color: Colors.black87, fontWeight: FontWeight.bold)),
          Row(
            children: [
              FilterChip(
                selected: _postToNostr,
                onSelected: (val) => setState(() => _postToNostr = val),
                label: const Row(
                  children: [
                    Icon(Icons.security, size: 16, color: Colors.purpleAccent),
                    SizedBox(width: 4),
                    Text('Nostr'),
                  ],
                ),
                backgroundColor: Colors.transparent,
                selectedColor: Colors.purpleAccent.withOpacity(0.1),
                checkmarkColor: Colors.purpleAccent,
                labelStyle: TextStyle(color: _postToNostr ? Colors.purpleAccent : Colors.black87),
              ),
            ],
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

