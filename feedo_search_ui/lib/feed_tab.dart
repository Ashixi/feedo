import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:timeago/timeago.dart' as timeago;
import 'utils/feed_filter_config.dart';
import 'post_card.dart';
import 'services/auth_service.dart';
import 'nostr_resolver.dart';
import 'feed_layout.dart';
import 'utils/constants.dart';

class FeedTab extends StatefulWidget {
  const FeedTab({super.key});

  @override
  State<FeedTab> createState() => _FeedTabState();
}

class _FeedTabState extends State<FeedTab> {
  List<dynamic> _posts = [];
  int _fetchedCount = 0;
  bool _isLoading = false;
  bool _isLoadingMore = false;
  bool _hasMore = true;
  String? _oldestTimestamp;
  String? _errorMessage;
  final ScrollController _scrollController = ScrollController();
  String? _walletAddress;

  @override
  void initState() {
    super.initState();
    AuthService.getPublicKey().then((val) {
      if (mounted) setState(() => _walletAddress = val);
      _fetchFeed();
    });
    
    globalFeedFilter.addListener(_onFilterChanged);

    _scrollController.addListener(() {
      if (_scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 200) {
        _loadMoreFeed();
      }
    });
  }

  void _onFilterChanged() {
    if (mounted) {
      _fetchFeed();
    }
  }

  @override
  void dispose() {
    globalFeedFilter.removeListener(_onFilterChanged);
    _scrollController.dispose();
    super.dispose();
  }

  String _buildUrl(String base) {
    final filter = globalFeedFilter.value;
    String url = base;
    if (filter.keywords.isNotEmpty) url += '&text=${Uri.encodeComponent(filter.keywords)}';
    if (filter.language != 'all') url += '&language=${filter.language}';
    if (filter.since != null) url += '&since=${filter.since!.millisecondsSinceEpoch ~/ 1000}';
    if (_walletAddress != null) url += '&wallet_address=$_walletAddress';
    // _oldestTimestamp is handled separately
    return url;
  }

  Future<void> _fetchFeed() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _posts = [];
      _fetchedCount = 0;
      _hasMore = true;
      _oldestTimestamp = null;
    });

    try {
      final String apiUrl = Constants.apiUrl;
      
      int newlyAdded = 0;
      int maxLoops = 5;

      while (newlyAdded < 10 && maxLoops > 0) {
        maxLoops--;
        String urlStr = '$apiUrl/feed?limit=50&source_type=nostr&offset=$_fetchedCount';
            
        urlStr = _buildUrl(urlStr);
        final url = Uri.parse(urlStr);
        final response = await http.get(url).timeout(const Duration(seconds: 45));

        if (response.statusCode == 200) {
          final List<dynamic> data = json.decode(response.body);
          if (data.isEmpty) {
            _hasMore = false;
            break;
          }
          
          _oldestTimestamp = data.last['published_at'] ?? _oldestTimestamp;
          _fetchedCount += data.length;
          
          final filter = globalFeedFilter.value;
          
          // Always await NostrResolver to fully resolve posts before adding them to the feed
          await NostrResolver.resolve(data);
          
          List<dynamic> validPosts = [];
          for (var item in data) {
            String t = item['text'] ?? item['content'] ?? '';
            bool hasMedia = item['media'] != null && item['media'].isNotEmpty;
            
            // Hide empty posts that failed to load from relays (or are intrinsically empty)
            if (item['item_type'] != 'profile' && t.trim().isEmpty && !hasMedia) {
              continue;
            }
            if (filter.language != 'all') {
               String lang = item['language'] ?? item['metadata']?['language'] ?? '';
               if (lang.isNotEmpty && lang != filter.language && lang != 'un' && lang != 'uk') continue;
            }
            
            if (filter.since != null && item['published_at'] != null) {
               try {
                 DateTime pubDate = DateTime.parse(item['published_at']);
                 if (pubDate.isBefore(filter.since!)) continue;
               } catch(_) {}
            }
            
            if (filter.until != null && item['published_at'] != null) {
               try {
                 DateTime pubDate = DateTime.parse(item['published_at']);
                 if (pubDate.isAfter(filter.until!.add(const Duration(days: 1)))) continue;
               } catch(_) {}
            }
            
            validPosts.add(item);
          }
          
          newlyAdded += validPosts.length;
          setState(() {
            _posts.addAll(validPosts);
          });
        } else {
          setState(() {
            if (_posts.isEmpty) _errorMessage = 'Failed to load feed: ${response.statusCode}';
          });
          break;
        }
      }
    } catch (e, stack) {
      print('Exception in _fetchFeed: $e');
      print(stack);
      setState(() {
        if (_posts.isEmpty) _errorMessage = 'Error connecting to Feedo Network: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadMoreFeed() async {
    if (_isLoadingMore || _isLoading || !_hasMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final String apiUrl = Constants.apiUrl;
      
      int newlyAdded = 0;
      int maxLoops = 5;

      while (newlyAdded < 5 && maxLoops > 0) {
        maxLoops--;
        String urlStr = '$apiUrl/feed?limit=50&source_type=nostr&offset=$_fetchedCount';
            
        urlStr = _buildUrl(urlStr);
        final url = Uri.parse(urlStr);
        final response = await http.get(url).timeout(const Duration(seconds: 45));

        if (response.statusCode == 200) {
          final List<dynamic> data = json.decode(response.body);
          if (data.isEmpty) {
            _hasMore = false;
            break;
          }
          
          _oldestTimestamp = data.last['published_at'] ?? _oldestTimestamp;
          _fetchedCount += data.length;
          
          final filter = globalFeedFilter.value;
          
          // Always await NostrResolver to fully resolve posts before adding them to the feed
          await NostrResolver.resolve(data);
          
          List<dynamic> validPosts = [];
          for (var item in data) {
            String t = item['text'] ?? item['content'] ?? '';
            bool hasMedia = item['media'] != null && item['media'].isNotEmpty;
            
            // Hide empty posts that failed to load from relays (or are intrinsically empty)
            if (item['item_type'] != 'profile' && t.trim().isEmpty && !hasMedia) {
              continue;
            }
            if (filter.language != 'all') {
               String lang = item['language'] ?? item['metadata']?['language'] ?? '';
               if (lang.isNotEmpty && lang != filter.language && lang != 'un' && lang != 'uk') continue;
            }
            
            if (filter.since != null && item['published_at'] != null) {
               try {
                 DateTime pubDate = DateTime.parse(item['published_at']);
                 if (pubDate.isBefore(filter.since!)) continue;
               } catch(_) {}
            }
            
            if (filter.until != null && item['published_at'] != null) {
               try {
                 DateTime pubDate = DateTime.parse(item['published_at']);
                 if (pubDate.isAfter(filter.until!.add(const Duration(days: 1)))) continue;
               } catch(_) {}
            }
            
            validPosts.add(item);
          }
          
          newlyAdded += validPosts.length;
          setState(() {
            _posts.addAll(validPosts);
          });
        } else {
          break;
        }
      }
    } catch (_) {
    } finally {
      if (mounted) {
        setState(() {
          _isLoadingMore = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return _buildBody();
  }

  Widget _buildBody() {
    if (_isLoading && _posts.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_errorMessage != null && _posts.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, color: Colors.redAccent, size: 48),
            const SizedBox(height: 16),
            Text(_errorMessage!, style: const TextStyle(color: Colors.black87)),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _fetchFeed,
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.black87,
                foregroundColor: Colors.white,
              ),
              child: const Text('Retry'),
            )
          ],
        ),
      );
    }

    if (_posts.isEmpty) {
      return const Center(
        child: Text('Feed is empty', style: TextStyle(color: Colors.black54, fontSize: 16)),
      );
    }

    return FeedLayout(
      child: RefreshIndicator(
        onRefresh: _fetchFeed,
        child: ListView.builder(
          controller: _scrollController,
          itemCount: _posts.length + 1,
          itemBuilder: (context, index) {
            if (index == _posts.length) {
              if (_isLoadingMore) {
                return const Padding(
                  padding: EdgeInsets.all(16.0),
                  child: Center(child: CircularProgressIndicator()),
                );
              } else if (!_hasMore && _posts.isNotEmpty) {
                return const Padding(
                  padding: EdgeInsets.all(32.0),
                  child: Center(
                    child: Text(
                      'No more posts',
                      style: TextStyle(color: Colors.black54),
                    ),
                  ),
                );
              } else {
                return const SizedBox(height: 32);
              }
            }
            return PostCard(post: _posts[index]);
          },
        ),
      ),
    );
  }
}


