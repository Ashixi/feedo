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
import 'screens/user_profile_screen.dart';

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
  String _profileSearchMode = 'name'; // 'name' or 'id'
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
      String urlStr = '$randomNode/query?text=$encodedQuery&limit=50&federated=true';
      if (_selectedItemType != 'all') {
        urlStr += '&item_type=$_selectedItemType';
        if (_selectedItemType == 'profile') {
          urlStr += '&profile_search_by=$_profileSearchMode';
        }
      }
      final url = Uri.parse(urlStr);

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
        Set<String> seenPubkeys = {};
        Set<String> seenVisuals = {};
        for (var item in results) {
          
          final meta = item['metadata'] ?? {};
          if (meta['is_reply'] == true) continue;
          
          // Hide empty posts that failed to load from relays (or are intrinsically empty)
          if (item['item_type'] != 'profile' && (item['text'] == null || item['text'].toString().trim().isEmpty)) {
            continue;
          }
          
          // Item type filter
          if (_selectedItemType != 'all' && item['item_type'] != _selectedItemType) continue;

          // Deduplicate profiles by pubkey and visually identical clones
          if (item['item_type'] == 'profile') {
            final pubkey = item['author_address']?.toString() ?? item['pubkey']?.toString() ?? '';
            
            // Clean up name/about parsing to ensure we don't display raw JSON strings
            String name = meta['name']?.toString() ?? meta['display_name']?.toString() ?? '';
            String about = meta['about']?.toString() ?? '';
            
            if (name.isEmpty && item['text'] != null && item['text'].toString().startsWith('{')) {
               try {
                  final parsed = jsonDecode(item['text']);
                  if (parsed is Map) {
                     name = parsed['name'] ?? parsed['display_name'] ?? '';
                     about = parsed['about'] ?? '';
                  }
               } catch (_) {}
            }
            
            final visualKey = '$name|$about';

            // Pre-populate missing profile data if NostrResolver failed
            item['author_name'] ??= name.isNotEmpty ? name : null;
            item['author_avatar'] ??= meta['picture'];
            
            // Explicitly set the text field to the cleaned about, so we don't render raw JSON later
            item['text'] = about;

            if (pubkey.isNotEmpty) {
              if (seenPubkeys.contains(pubkey)) continue;
              seenPubkeys.add(pubkey);
            }
            if (visualKey.isNotEmpty && visualKey != '|') {
              if (seenVisuals.contains(visualKey)) continue;
              seenVisuals.add(visualKey);
            }
          }

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
        String urlStr = '$randomNode/query?text=$encodedQuery&limit=50&federated=true&offset=$offset';
        if (_selectedItemType != 'all') {
          urlStr += '&item_type=$_selectedItemType';
          if (_selectedItemType == 'profile') {
            urlStr += '&profile_search_by=$_profileSearchMode';
          }
        }
        final url = Uri.parse(urlStr);

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
          
          Set<String> seenPubkeys = {};
          Set<String> seenVisuals = {};
          for (var item in _results) {
            if (item['item_type'] == 'profile') {
              final pubkey = item['author_address']?.toString() ?? item['pubkey']?.toString() ?? '';
              if (pubkey.isNotEmpty) seenPubkeys.add(pubkey);
              final meta = item['metadata'] ?? {};
              final name = meta['name']?.toString() ?? meta['display_name']?.toString() ?? '';
              final about = meta['about']?.toString() ?? '';
              final visualKey = '$name|$about';
              if (visualKey.isNotEmpty && visualKey != '|') seenVisuals.add(visualKey);
            }
          }

          List<dynamic> validResults = [];
          for (var item in results) {
            final meta = item['metadata'] ?? {};
            if (meta['is_reply'] == true) continue;
            
            if (_selectedItemType != 'all' && item['item_type'] != _selectedItemType) continue;

            if (item['item_type'] == 'profile') {
              final pubkey = item['author_address']?.toString() ?? item['pubkey']?.toString() ?? '';
              final name = meta['name']?.toString() ?? meta['display_name']?.toString() ?? '';
              final about = meta['about']?.toString() ?? '';
              final visualKey = '$name|$about';

              // Pre-populate missing profile data if NostrResolver failed
              item['author_name'] ??= name.isNotEmpty ? name : null;
              item['author_avatar'] ??= meta['picture'];
              
              bool skip = false;
              if (pubkey.isNotEmpty) {
                if (seenPubkeys.contains(pubkey)) skip = true;
                seenPubkeys.add(pubkey);
              }
              if (visualKey.isNotEmpty && visualKey != '|') {
                if (seenVisuals.contains(visualKey)) skip = true;
                seenVisuals.add(visualKey);
              }
              
              if (skip) continue;
            }

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
                child: RawAutocomplete<Map<String, dynamic>>(
                  textEditingController: _searchController,
                  focusNode: FocusNode(),
                  optionsBuilder: (TextEditingValue textEditingValue) async {
                    if (textEditingValue.text.trim().length < 2) {
                      return const Iterable<Map<String, dynamic>>.empty();
                    }
                    final randomNode = _apiNodes[Random().nextInt(_apiNodes.length)];
                    final encodedQuery = Uri.encodeComponent(textEditingValue.text.trim());
                    final urlStr = '$randomNode/query?text=$encodedQuery&limit=5&federated=true&item_type=profile';
                    try {
                      final response = await http.get(Uri.parse(urlStr), headers: {'Accept': 'application/json'}).timeout(const Duration(seconds: 3));
                      if (response.statusCode == 200) {
                        final data = jsonDecode(response.body);
                        List<dynamic> results = data['results'] ?? [];
                        return results.cast<Map<String, dynamic>>();
                      }
                    } catch (_) {}
                    return const Iterable<Map<String, dynamic>>.empty();
                  },
                  onSelected: (Map<String, dynamic> item) {
                    final meta = item['metadata'] ?? {};
                    final pubkey = item['author_address'] ?? '';
                    Navigator.push(context, MaterialPageRoute(builder: (context) => UserProfileScreen(
                      pubkey: pubkey,
                      initialName: meta['name'] ?? meta['display_name'],
                      initialAvatar: meta['picture'],
                      initialAbout: meta['about'],
                    )));
                  },
                  fieldViewBuilder: (context, controller, focusNode, onFieldSubmitted) {
                    return TextField(
                      controller: controller,
                      focusNode: focusNode,
                      style: const TextStyle(fontSize: 16, color: Colors.black87),
                      decoration: InputDecoration(
                        hintText: 'Search profiles & posts...',
                        hintStyle: TextStyle(color: Colors.grey[500]),
                        prefixIcon: Padding(
                          padding: const EdgeInsets.only(left: 16.0, right: 8.0),
                          child: Icon(Icons.search, color: Colors.grey[600]),
                        ),
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                        suffixIcon: IconButton(
                          icon: Icon(Icons.arrow_forward_rounded, color: Theme.of(context).colorScheme.primary),
                          onPressed: () {
                            focusNode.unfocus();
                            _performSearch(controller.text);
                          },
                        ),
                      ),
                      onSubmitted: (val) {
                        onFieldSubmitted();
                        _performSearch(val);
                      },
                    );
                  },
                  optionsViewBuilder: (context, onSelected, options) {
                    return Align(
                      alignment: Alignment.topLeft,
                      child: Material(
                        elevation: 4.0,
                        borderRadius: BorderRadius.circular(16),
                        child: Container(
                          width: MediaQuery.of(context).size.width - 32,
                          constraints: const BoxConstraints(maxHeight: 300),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(16),
                          ),
                          child: ListView.builder(
                            padding: const EdgeInsets.symmetric(vertical: 8),
                            shrinkWrap: true,
                            itemCount: options.length,
                            itemBuilder: (context, index) {
                              final item = options.elementAt(index);
                              final meta = item['metadata'] ?? {};
                              final name = meta['name'] ?? meta['display_name'] ?? 'Unknown';
                              final nip05 = meta['nip05'] ?? '';
                              final picture = meta['picture'];
                              return ListTile(
                                leading: CircleAvatar(
                                  backgroundColor: Colors.grey[200],
                                  backgroundImage: picture != null ? NetworkImage(picture) : null,
                                  child: picture == null ? const Icon(Icons.person, color: Colors.grey) : null,
                                ),
                                title: Text(name, style: const TextStyle(fontWeight: FontWeight.bold)),
                                subtitle: nip05.isNotEmpty ? Text(nip05, maxLines: 1, overflow: TextOverflow.ellipsis) : null,
                                onTap: () => onSelected(item),
                              );
                            },
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
            
            // Filter Options
            if (_hasSearched)
              Padding(
                padding: const EdgeInsets.only(top: 16, bottom: 8),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        _buildFilterChip('All', 'all'),
                        const SizedBox(width: 8),
                        _buildFilterChip('Profiles', 'profile'),
                        const SizedBox(width: 8),
                        _buildFilterChip('Posts', 'post'),
                      ],
                    ),
                    if (_selectedItemType == 'profile')
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            _buildSubFilterChip('By Name', 'name'),
                            const SizedBox(width: 8),
                            _buildSubFilterChip('By ID', 'id'),
                          ],
                        ),
                      ),
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

  Widget _buildSubFilterChip(String label, String value) {
    final isSelected = _profileSearchMode == value;
    return GestureDetector(
      onTap: () {
        setState(() {
          _profileSearchMode = value;
          _performSearch(_searchController.text);
        });
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color: isSelected ? Colors.blueAccent.withOpacity(0.15) : Colors.transparent,
          border: Border.all(color: isSelected ? Colors.blueAccent : Colors.grey[300]!),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: isSelected ? Colors.blueAccent : Colors.grey[600],
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
