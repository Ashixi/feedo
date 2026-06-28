
import 'package:flutter/material.dart';
import 'services/auth_service.dart';
import 'services/relay_service.dart';

class ComposeScreen extends StatefulWidget {
  const ComposeScreen({super.key});

  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  final TextEditingController _textController = TextEditingController();
  bool _postToNostr = true;
  bool _isPosting = false;

  Future<void> _publishPost() async {
    final content = _textController.text.trim();
    if (content.isEmpty) return;

    setState(() => _isPosting = true);

    bool successNostr = true;
    if (_postToNostr) {
      successNostr = await _publishToNostr(content);
    }

    setState(() => _isPosting = false);

    if (successNostr) {
      if (mounted) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Post published successfully!')),
        );
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

    int successCount = 0;
    final relays = await RelayService.getRelays();
    // Dummy publish implementation for UI placeholder
    await Future.delayed(const Duration(milliseconds: 500));
    return true;
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      backgroundColor: Colors.white,
      child: Container(
        width: 600,
        constraints: const BoxConstraints(maxHeight: 450),
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('Create Post', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF1F2937))),
                IconButton(
                  icon: const Icon(Icons.close, color: Colors.grey),
                  onPressed: () => Navigator.of(context).pop(),
                  splashRadius: 20,
                ),
              ],
            ),
            const Divider(),
            const SizedBox(height: 16),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const CircleAvatar(
                  backgroundColor: Color(0xFFF0F2F5),
                  radius: 20,
                  child: Icon(Icons.person, color: Colors.grey),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _textController,
                    maxLines: 8,
                    minLines: 4,
                    autofocus: true,
                    decoration: const InputDecoration(
                      hintText: 'What\'s happening?',
                      border: InputBorder.none,
                      hintStyle: TextStyle(color: Colors.grey, fontSize: 18),
                    ),
                    style: const TextStyle(fontSize: 18, color: Color(0xFF1F2937)),
                  ),
                ),
              ],
            ),
            const Spacer(),
            const Divider(),
            Padding(
              padding: const EdgeInsets.only(top: 16.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      Checkbox(
                        value: _postToNostr,
                        onChanged: (val) => setState(() => _postToNostr = val ?? true),
                        activeColor: const Color(0xFF6366F1),
                      ),
                      const Text('Nostr Network', style: TextStyle(fontWeight: FontWeight.w500)),
                    ],
                  ),
                  ElevatedButton(
                    onPressed: _isPosting ? null : _publishPost,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF6366F1),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                      elevation: 0,
                    ),
                    child: _isPosting
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                        : const Text('Post', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
