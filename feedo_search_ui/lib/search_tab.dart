import 'dart:convert';
import 'dart:math';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import 'package:timeago/timeago.dart' as timeago;

import 'nostr_resolver.dart';
import 'nostr_wallet.dart';
import 'post_card.dart';

class SearchTab extends StatefulWidget {
  const SearchTab({super.key});

  @override
  State<SearchTab> createState() => _SearchTabState();
}

class _SearchTabState extends State<SearchTab> {
  final TextEditingController _searchController = TextEditingController();
  final List<String> _apiNodes = ['https://api.feedo.ink', 'https://api2.feedo.ink'];
  bool _hasSearched = false;
  bool _isLoading = false;
  List<dynamic> _results = [];
  String _selectedItemType = 'all';
  String? _errorMessage;
  String? _pubkey;

  Future<void> _connectWallet() async {
    bool available = await NostrWallet.isAvailable();
    if (!available) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Nostr extension (e.g. Alby) not found!')),
        );
      }
      return;
    }
    String? pubkey = await NostrWallet.getPublicKey();
    if (pubkey != null) {
      setState(() {
        _pubkey = pubkey;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Wallet connected: ${pubkey.substring(0, 8)}...')),
        );
      }
    }
  }

  Future<void> _performSearch(String query) async {
    if (query.trim().isEmpty) return;

    setState(() {
      _hasSearched = true;
      _isLoading = true;
      _errorMessage = null;
      _results = [];
    });

    try {
      final randomNode = _apiNodes[Random().nextInt(_apiNodes.length)];
      final url = Uri.parse('$randomNode/api/v1/semantic/query');
      
      Map<String, dynamic> payload = {
        'text': query,
        'limit': 50,
        'federated': true,
        'source_type': 'nostr',
      };
      
      if (_selectedItemType != 'all') {
        payload['item_type'] = _selectedItemType;
      }

      // If wallet connected, sign the request
      if (_pubkey != null) {
        String nonce = DateTime.now().millisecondsSinceEpoch.toString();
        Map<String, dynamic> eventToSign = {
          "kind": 22222,
          "created_at": (DateTime.now().millisecondsSinceEpoch / 1000).floor(),
          "tags": [["nonce", nonce]],
          "content": "semantic_query:$query:$nonce",
          "pubkey": _pubkey
        };
        
        Map<String, dynamic>? signedEvent = await NostrWallet.signEvent(eventToSign);
        if (signedEvent != null) {
          payload['client_id'] = _pubkey;
          payload['signature'] = signedEvent['sig'];
          payload['nonce'] = nonce;
          payload['auth_event'] = signedEvent;
        } else {
           if (mounted) {
             ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Failed to sign request. Falling back to anonymous mode.')),
            );
           }
        }
      }

      final response = await http.post(
        url,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(payload),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        List<dynamic> results = data['results'] ?? [];
        
        // Use Stateless Indexer Resolver to fetch missing text and author data from Relays
        await NostrResolver.resolve(results);
        
        // Dynamic Spam Filter: After fetching texts from relays, remove any spam posts
        List<dynamic> validResults = [];
        for (var item in results) {
          String t = item['text'] ?? '';
          String cleanText = t.replaceAll(RegExp(r'https?://\S+'), '')
                              .replaceAll(RegExp(r'nostr:\S+'), '')
                              .replaceAll(RegExp(r':\w+:'), '')
                              .trim();
          
          if (item['item_type'] == 'profile' || cleanText.length >= 10) {
            validResults.add(item);
          }
        }
        
        // Take top 20 valid results
        if (validResults.length > 20) {
          validResults = validResults.sublist(0, 20);
        }

        setState(() {
          _results = validResults;
          _isLoading = false;
        });
      } else {
        setState(() {
          _errorMessage = 'Server error: ${response.statusCode}';
          _isLoading = false;
        });
        print('Error: ${response.statusCode}');
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Network error. Please try again.';
        _isLoading = false;
      });
      print('Exception: $e');
    }
  }

  void _openPost(String hashId) async {
    final url = Uri.parse('https://njump.me/$hashId');
    if (await canLaunchUrl(url)) {
      await launchUrl(url);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text('Search', style: TextStyle(fontWeight: FontWeight.bold)),
      ),
      body: SafeArea(
        child: Column(
          children: [
            const SizedBox(height: 16),
            // Search Bar
            Container(
              margin: const EdgeInsets.symmetric(horizontal: 16),
              decoration: BoxDecoration(
                color: Colors.grey[100],
                borderRadius: BorderRadius.circular(30),
              ),
              child: TextField(
                controller: _searchController,
                style: const TextStyle(fontSize: 16, color: Colors.black87),
                decoration: InputDecoration(
                  hintText: 'Search Farcaster & Nostr...',
                  hintStyle: TextStyle(color: Colors.grey[500]),
                  prefixIcon: Padding(
                    padding: const EdgeInsets.only(left: 16.0, right: 8.0),
                    child: Icon(Icons.search, color: Colors.grey[600]),
                  ),
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                  suffixIcon: IconButton(
                    icon: Icon(Icons.arrow_forward_rounded, color: Theme.of(context).colorScheme.primary),
                    onPressed: () => _performSearch(_searchController.text),
                  ),
                ),
                onSubmitted: _performSearch,
              ),
            ),
            
            // Filter Options
            if (_hasSearched)
              Padding(
                padding: const EdgeInsets.only(top: 16, bottom: 8),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _buildFilterChip('All', 'all'),
                    const SizedBox(width: 8),
                    _buildFilterChip('Profiles', 'profile'),
                    const SizedBox(width: 8),
                    _buildFilterChip('Posts', 'post'),
                  ],
                ),
              ),
            
            const SizedBox(height: 16),
            
            // Results Area
            if (_hasSearched)
              Expanded(
                child: _isLoading 
                    ? const Center(child: CircularProgressIndicator())
                    : _errorMessage != null
                        ? Center(
                            child: Text(
                              _errorMessage!, 
                              style: const TextStyle(color: Colors.redAccent, fontSize: 16)
                            )
                          )
                        : _results.isEmpty
                            ? const Center(
                                child: Text(
                                  'No results found.', 
                                  style: TextStyle(color: Colors.black54, fontSize: 16)
                                )
                              )
                            : ListView.builder(
                                itemCount: _results.length,
                                itemBuilder: (context, index) {
                                  final item = _results[index];
                                  return PostCard(post: item);
                                },
                              ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterChip(String label, String value) {
    final isSelected = _selectedItemType == value;
    return GestureDetector(
      onTap: () {
        setState(() {
          _selectedItemType = value;
          _performSearch(_searchController.text);
        });
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? Colors.black87 : Colors.grey[200],
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: isSelected ? Colors.white : Colors.black87,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
