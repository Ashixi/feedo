import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:dio/dio.dart';
import '../../core/api_client.dart';
import '../../core/wallet_provider.dart';

class ContentExplorerScreen extends ConsumerStatefulWidget {
  const ContentExplorerScreen({super.key});

  @override
  ConsumerState<ContentExplorerScreen> createState() => _ContentExplorerScreenState();
}

class _ContentExplorerScreenState extends ConsumerState<ContentExplorerScreen> {
  final TextEditingController _searchController = TextEditingController();
  Map<String, dynamic>? _post;
  String? _error;
  bool _isLoading = false;

  Future<void> _search() async {
    final hash = _searchController.text.trim();
    if (hash.isEmpty) return;
    
    final wallet = ref.read(walletProvider);
    if (wallet == null) {
      setState(() => _error = "Please generate a Wallet Identity first.");
      return;
    }

    setState(() {
      _isLoading = true;
      _error = null;
      _post = null;
    });

    try {
      final dio = ref.read(apiClientProvider);
      final response = await dio.get('/posts/by-hash/$hash');
      setState(() {
        _post = response.data;
        _isLoading = false;
      });
    } on DioException catch (e) {
      setState(() {
        _error = e.response?.data?['detail'] ?? "Post not found or network error.";
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      body: SingleChildScrollView(
        padding: EdgeInsets.all(isMobile ? 16.0 : 32.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Content Explorer', style: TextStyle(fontSize: isMobile ? 24 : 32, fontWeight: FontWeight.bold, letterSpacing: -1)),
            const SizedBox(height: 8),
            Text('Search and verify raw posts on the DHT using their cryptographic Hash ID.', style: TextStyle(fontSize: isMobile ? 14 : 16, color: Colors.grey.shade400)),
            const SizedBox(height: 32),
            
            if (isMobile) ...[
              TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: 'Enter Content Hash ID',
                  prefixIcon: const Icon(LucideIcons.search),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  filled: true,
                  fillColor: Colors.black.withOpacity(0.2),
                ),
                onSubmitted: (_) => _search(),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: _isLoading ? null : _search,
                  icon: const Icon(LucideIcons.search),
                  label: const Text('Search'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Theme.of(context).colorScheme.primary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 20),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
            ] else
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _searchController,
                      decoration: InputDecoration(
                        hintText: 'Enter Content Hash ID (e.g., hash_...)',
                        prefixIcon: const Icon(LucideIcons.search),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        filled: true,
                        fillColor: Colors.black.withOpacity(0.2),
                      ),
                      onSubmitted: (_) => _search(),
                    ),
                  ),
                  const SizedBox(width: 16),
                  ElevatedButton.icon(
                    onPressed: _isLoading ? null : _search,
                    icon: const Icon(LucideIcons.search),
                    label: const Text('Search'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.primary,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  )
                ],
              ),
            const SizedBox(height: 32),

            if (_isLoading)
              const Center(child: Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator()))
            else if (_error != null)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: Colors.red.withOpacity(0.1), borderRadius: BorderRadius.circular(8)),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              )
            else if (_post != null)
              Card(
                child: Padding(
                  padding: EdgeInsets.all(isMobile ? 16.0 : 32.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(LucideIcons.fileText, size: isMobile ? 24 : 32, color: Theme.of(context).colorScheme.primary),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Text(
                              _post!['hash_id'] ?? 'Unknown Hash',
                              style: TextStyle(fontSize: isMobile ? 16 : 20, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 32),
                      _buildDetailRow('Author Wallet', _post!['author_address'] ?? 'Unknown', isMobile),
                      const Divider(),
                      _buildDetailRow('Content Type', _post!['content_type'] ?? 'Unknown', isMobile),
                      const Divider(),
                      _buildDetailRow('Timestamp', _post!['published_at'] ?? 'Unknown', isMobile),
                      const Divider(),
                      _buildDetailRow('Signature', _post!['signature'] != null ? 'Present' : 'Missing', isMobile, color: _post!['signature'] != null ? Colors.teal : Colors.red),
                      const Divider(),
                      const SizedBox(height: 16),
                      const Text('Raw Content Payload', style: TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 8),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(color: Colors.black.withOpacity(0.4), borderRadius: BorderRadius.circular(8)),
                        child: Text(
                          _post!['text_content'] ?? 'No text content',
                          style: const TextStyle(fontFamily: 'monospace', color: Colors.greenAccent),
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text('JSON Metadata', style: TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 8),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(color: Colors.black.withOpacity(0.4), borderRadius: BorderRadius.circular(8)),
                        child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: Text(
                            const JsonEncoder.withIndent('  ').convert(_post!),
                            style: TextStyle(fontFamily: 'monospace', color: Colors.grey.shade300, fontSize: 13),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildDetailRow(String label, String value, bool isMobile, {Color? color}) {
    if (isMobile) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: TextStyle(color: Colors.grey.shade400, fontWeight: FontWeight.w500)),
            const SizedBox(height: 4),
            Text(value, style: TextStyle(fontWeight: FontWeight.w600, color: color, fontFamily: 'monospace')),
          ],
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
            child: Text(label, style: TextStyle(color: Colors.grey.shade400, fontWeight: FontWeight.w500)),
          ),
          Expanded(
            child: Text(value, style: TextStyle(fontWeight: FontWeight.w600, color: color, fontFamily: 'monospace')),
          ),
        ],
      ),
    );
  }
}
