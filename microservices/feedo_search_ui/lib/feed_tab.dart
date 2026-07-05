import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:timeago/timeago.dart' as timeago;
import 'utils/feed_filter_config.dart';
import 'post_card.dart';
import 'services/auth_service.dart';
import 'nostr_resolver.dart';
import 'feed_layout.dart';
import 'utils/constants.dart';
import 'package:shimmer/shimmer.dart';

List<dynamic> _parseJsonList(String jsonStr) {
  return jsonDecode(jsonStr) as List<dynamic>;
}

class FeedTab extends StatefulWidget {
  const FeedTab({super.key});

  @override
  State<FeedTab> createState() => _FeedTabState();
}

class _FeedTabState extends State<FeedTab> {
  List<dynamic> _posts = [];
  final List<dynamic> _prefetchBuffer = [];
  final Set<String> _seenPostIds = {};
  bool _isPrefetching = false;
  static const int _maxBufferSize = 500;
  static const int _chunkSize = 20;

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
      if (_scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 2500) {
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
    return url;
  }

  Future<void> _fetchFeed() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _posts = [];
      _prefetchBuffer.clear();
      _seenPostIds.clear();
      _fetchedCount = 0;
      _hasMore = true;
      _oldestTimestamp = null;
    });

    await _fillBuffer(initialLoad: true);

    if (mounted) {
      setState(() {
        _isLoading = false;
        if (_prefetchBuffer.isNotEmpty) {
          int takeCount = _prefetchBuffer.length < _chunkSize ? _prefetchBuffer.length : _chunkSize;
          _posts.addAll(_prefetchBuffer.sublist(0, takeCount));
          _prefetchBuffer.removeRange(0, takeCount);
        } else if (_errorMessage == null) {
          _hasMore = false;
        }
      });
      // Start background fetch to fill up to 500
      _fillBuffer();
    }
  }

  Future<void> _loadMoreFeed() async {
    if (_isLoadingMore || _isLoading || !_hasMore) return;
    
    if (_prefetchBuffer.isNotEmpty) {
      // Instantly load from buffer
      setState(() {
        int takeCount = _prefetchBuffer.length < _chunkSize ? _prefetchBuffer.length : _chunkSize;
        _posts.addAll(_prefetchBuffer.sublist(0, takeCount));
        _prefetchBuffer.removeRange(0, takeCount);
      });
      // Replenish buffer if it gets low
      if (_prefetchBuffer.length < 100) {
        _fillBuffer();
      }
      return;
    }

    // Buffer is empty, we must wait for network
    setState(() {
      _isLoadingMore = true;
    });

    await _fillBuffer();

    if (mounted) {
      setState(() {
        _isLoadingMore = false;
        if (_prefetchBuffer.isNotEmpty) {
          int takeCount = _prefetchBuffer.length < _chunkSize ? _prefetchBuffer.length : _chunkSize;
          _posts.addAll(_prefetchBuffer.sublist(0, takeCount));
          _prefetchBuffer.removeRange(0, takeCount);
        }
      });
    }
  }

  Future<void> _fillBuffer({bool initialLoad = false}) async {
    if (_isPrefetching || !_hasMore) return;
    _isPrefetching = true;

    try {
      final String apiUrl = Constants.apiUrl;
      
      int loops = 0;
      // Fetch until we have enough in buffer or run out of data
      while (_prefetchBuffer.length < _maxBufferSize && _hasMore && loops < 5) {
        loops++;
        int fetchLimit = 50; // Fetch larger chunks for background
        String urlStr = '$apiUrl/feed?limit=$fetchLimit&source_type=main&offset=$_fetchedCount';
            
        urlStr = _buildUrl(urlStr);
        final url = Uri.parse(urlStr);
        final response = await http.get(url).timeout(const Duration(seconds: 45));

        if (response.statusCode == 200) {
          // Use isolate for parsing large JSON
          final List<dynamic> data = await compute(_parseJsonList, response.body);
          
          if (data.isEmpty) {
            _hasMore = false;
            break;
          }
          
          _oldestTimestamp = data.last['published_at'] ?? _oldestTimestamp;
          _fetchedCount += data.length;
          
          final filter = globalFeedFilter.value;
          
          NostrResolver.resolve(data, onUpdate: () {
            if (mounted) setState(() {});
          });
          
          List<dynamic> validPosts = [];
          for (var item in data) {
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
            
            String postId = (item['hash_id'] ?? item['id']).toString();
            if (!_seenPostIds.contains(postId)) {
              _seenPostIds.add(postId);
              validPosts.add(item);
            }
          }
          
          _prefetchBuffer.addAll(validPosts);
          
          // If we are doing the initial load, stop after one successful fetch to show UI quickly
          if (initialLoad && validPosts.isNotEmpty) {
             break;
          }
        } else {
          if (initialLoad) {
             _errorMessage = 'Failed to load feed: ${response.statusCode}';
          }
          break;
        }
      }
    } catch (e, stack) {
      print('Exception in _fillBuffer: $e');
      if (initialLoad) {
        _errorMessage = 'Error connecting to Feedo Network: $e';
      }
    } finally {
      _isPrefetching = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return _buildBody();
  }

  Widget _buildBody() {
    if (_isLoading && _posts.isEmpty) {
      return FeedLayout(
        child: ListView.builder(
          itemCount: 5,
          itemBuilder: (context, index) => _buildShimmerPost(),
        )
      );
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
                return _buildShimmerPost();
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

  Widget _buildShimmerPost() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
      child: Shimmer.fromColors(
        baseColor: Colors.white.withOpacity(0.05),
        highlightColor: Colors.white.withOpacity(0.15),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 48,
              height: 48,
              decoration: const BoxDecoration(
                color: Colors.white,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: double.infinity,
                    height: 12,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    width: 150,
                    height: 12,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Container(
                    width: double.infinity,
                    height: 150,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                    )
                  ),
                ],
              ),
            )
          ],
        ),
      ),
    );
  }
}
