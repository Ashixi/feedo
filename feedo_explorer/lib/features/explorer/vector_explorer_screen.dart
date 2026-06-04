import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:dio/dio.dart';
import '../../core/api_client.dart';
import '../../core/wallet_provider.dart';

class VectorExplorerScreen extends ConsumerStatefulWidget {
  const VectorExplorerScreen({super.key});

  @override
  ConsumerState<VectorExplorerScreen> createState() => _VectorExplorerScreenState();
}

class _VectorExplorerScreenState extends ConsumerState<VectorExplorerScreen> {
  final TextEditingController _searchController = TextEditingController();
  Map<String, dynamic>? _vectorData;
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
      _vectorData = null;
    });

    try {
      final dio = ref.read(apiClientProvider);
      final response = await dio.get('/internal/vector/by_post/$hash');
      setState(() {
        _vectorData = response.data;
        _isLoading = false;
      });
    } on DioException catch (e) {
      setState(() {
        _error = e.response?.data?['detail'] ?? "Vector not found or Vector API disabled.";
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
            Text('Vector Search Explorer', style: TextStyle(fontSize: isMobile ? 24 : 32, fontWeight: FontWeight.bold, letterSpacing: -1)),
            const SizedBox(height: 8),
            Text('Explore AI embedding vectors for specific posts to understand semantic clustering.', style: TextStyle(fontSize: isMobile ? 14 : 16, color: Colors.grey.shade400)),
            const SizedBox(height: 32),
            
            if (isMobile) ...[
              TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: 'Enter Content Hash ID',
                  prefixIcon: const Icon(LucideIcons.binary),
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
                  label: const Text('Search Vector'),
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
                        prefixIcon: const Icon(LucideIcons.binary),
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
                    label: const Text('Search Vector'),
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
            else if (_vectorData != null)
              Card(
                child: Padding(
                  padding: EdgeInsets.all(isMobile ? 16.0 : 32.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(LucideIcons.binary, size: isMobile ? 24 : 32, color: Colors.indigo.shade400),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Text(
                              'Embedding Representation', 
                              style: TextStyle(fontSize: isMobile ? 18 : 20, fontWeight: FontWeight.bold)
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 24),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(color: Colors.black.withOpacity(0.4), borderRadius: BorderRadius.circular(8)),
                        child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: Text(
                            const JsonEncoder.withIndent('  ').convert(_vectorData!),
                            style: TextStyle(fontFamily: 'monospace', color: Colors.blueAccent.shade100, fontSize: 14),
                          ),
                        ),
                      ),
                      const SizedBox(height: 24),
                      const Text('Make sure EXPOSE_VECTOR_API="true" is set in your docker-compose.yml to enable this.', style: TextStyle(color: Colors.grey, fontStyle: FontStyle.italic)),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
