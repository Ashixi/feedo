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
import 'feed_layout.dart';

class SearchTab extends StatefulWidget {
  final String? initialQuery;
  const SearchTab({super.key, this.initialQuery});

  @override
  State<SearchTab> createState() => _SearchTabState();
}

class _SearchTabState extends State<SearchTab> {
  final TextEditingController _searchController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<String> _apiNodes = ['https://api.feedo.ink'];
  bool _hasSearched = false;
  bool _isLoading = false;
  bool _isLoadingMore = false;
  bool _hasMore = true;
  List<dynamic> _results = [];
  int _fetchedCount = 0;
  String _selectedItemType = 'all';
  String? _errorMessage;
  String? _pubkey;
  
  @override
  void initState() {
    super.initState();
    _scrollController.addListener(() {
      if (_scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 200) {
        _loadMoreResults();
      }
    });
    
    if (widget.initialQuery != null && widget.initialQuery!.isNotEmpty) {
      _searchController.text = widget.initialQuery!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _performSearch(widget.initialQuery!);
      });
    }
  }

  @override
  void didUpdateWidget(SearchTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialQuery != oldWidget.initialQuery && widget.initialQuery != null && widget.initialQuery!.isNotEmpty) {
      _searchController.text = widget.initialQuery!;
      _performSearch(widget.initialQuery!);
    }
  }

  @override
  void dispose() {
    _scrollController.dispose();
    _searchController.dispose();
    super.dispose();
  }

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
      _hasMore = true;
    });

    try {
      final randomNode = _apiNodes[Random().nextInt(_apiNodes.length)];
      final encodedQuery = Uri.encodeComponent(query);
      final url = Uri.parse('$randomNode/query?text=$encodedQuery&limit=50&federated=true');

      // Note: Backend GET /query currently doesn't natively support wallet auth signatures.
      // If needed in the future, pass signature via headers.

      final response = await http.get(
        url,
        headers: {'Accept': 'application/json'},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        List<dynamic> results = data['results'] ?? [];
        if (results.isEmpty) {
          _hasMore = false;
        }
        _fetchedCount = results.length;
        
        // Use Stateless Indexer Resolver to fetch missing text and author data from Relays
        await NostrResolver.resolve(results);
        
        // Dynamic Spam Filter: After fetching texts from relays, remove any spam posts
        List<dynamic> validResults = [];
        for (var item in results) {
          
          final meta = item['metadata'] ?? {};
          if (meta['is_reply'] == true) continue;
          
          // Item type filter
          if (_selectedItemType != 'all' && item['item_type'] != _selectedItemType) continue;

          validResults.add(item);
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
          _errorMessage = 'Search failed with status ${response.statusCode}';
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Network error while searching';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadMoreResults() async {
    if (_isLoadingMore || _isLoading || !_hasSearched || _searchController.text.trim().isEmpty || !_hasMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final randomNode = _apiNodes[Random().nextInt(_apiNodes.length)];
      final encodedQuery = Uri.encodeComponent(_searchController.text.trim());
      
      int newlyAdded = 0;
      int maxLoops = 5;

      while (newlyAdded < 5 && maxLoops > 0) {
        maxLoops--;
        final offset = _fetchedCount;
        final url = Uri.parse('$randomNode/query?text=$encodedQuery&limit=50&federated=true&offset=$offset');

        final response = await http.get(url, headers: {'Accept': 'application/json'});

        if (response.statusCode == 200) {
          final data = jsonDecode(response.body);
          List<dynamic> results = data['results'] ?? [];
          if (results.isEmpty) {
            _hasMore = false;
            break;
          }
          
          _fetchedCount += results.length;
          await NostrResolver.resolve(results);
          
          List<dynamic> validResults = [];
          for (var item in results) {
            final meta = item['metadata'] ?? {};
            if (meta['is_reply'] == true) continue;
            
            if (_selectedItemType != 'all' && item['item_type'] != _selectedItemType) continue;

            validResults.add(item);
          }
          
          newlyAdded += validResults.length;
          setState(() {
            _results.addAll(validResults);
          });
        } else {
          break;
        }
      }
    } catch (e) {
    } finally {
      if (mounted) {
        setState(() {
          _isLoadingMore = false;
        });
      }
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
    return Container(
      color: Colors.white,
      child: FeedLayout(
        child: SafeArea(
          child: Column(
            children: [
            const SizedBox(height: 16),
            // Search Bar (Hidden on Desktop/Tablet since it has a global search bar)
            if (MediaQuery.of(context).size.width < 600)
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
                                controller: _scrollController,
                                itemCount: _results.length + 1,
                                itemBuilder: (context, index) {
                                  if (index == _results.length) {
                                    if (_isLoadingMore) {
                                      return const Padding(
                                        padding: EdgeInsets.all(16.0),
                                        child: Center(child: CircularProgressIndicator()),
                                      );
                                    } else if (!_hasMore && _results.isNotEmpty) {
                                      return const Padding(
                                        padding: EdgeInsets.all(32.0),
                                        child: Center(
                                          child: Text(
                                            'No more results',
                                            style: TextStyle(color: Colors.black54),
                                          ),
                                        ),
                                      );
                                    } else {
                                      return const SizedBox(height: 32);
                                    }
                                  }
                                  final item = _results[index];
                                  return PostCard(post: item);
                                },
                              ),
              ),
          ],
        ),
      ),
    ));
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
