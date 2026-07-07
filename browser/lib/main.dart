import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:app_links/app_links.dart';
import 'dart:async';
import 'dart:io';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'theme.dart';
import 'core/api_client.dart';
import 'core/local_server.dart';
import 'core/db_helper.dart';
import 'core/adblock_engine.dart';
import 'core/google_scraper.dart';
import 'ui/browser_tab.dart';
import 'ui/onboarding_screen.dart';
import 'ui/search_disambiguation_view.dart';
import 'ui/native_search_results_view.dart';
import 'ui/publish_screen.dart';
import 'ui/start_page_view.dart';

// Import Rust bindings
import 'package:browser/src/rust/frb_generated.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // Initialize sqflite for desktop (Windows/Linux/macOS)
  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
  
  await RustLib.init();
  
  // We skip ProtocolRegistrar and IpfsManager for this MVP to focus on Rust
  runApp(const FeedoBrowserApp());
}

class FeedoBrowserApp extends StatelessWidget {
  const FeedoBrowserApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Feedo Browser',
      theme: AppTheme.lightTheme,
      darkTheme: AppTheme.darkTheme,
      themeMode: ThemeMode.dark,
      home: const OnboardingScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

enum TabState { empty, loading, webview, disambiguation, nativeSearch }

class TabModel {
  String id;
  String displayUrl;
  String? loadUrl;
  String? searchQuery;
  List<Map<String, dynamic>>? searchResults;
  List<Map<String, String>>? googleSearchResults;
  String? feedoSearchError;
  String? ambiguousWeb2Url;
  String? ambiguousFeedoUrl;
  TabState state;
  String? groupId;
  Color? groupColor;

  TabModel({
    required this.id,
    this.displayUrl = '',
    this.loadUrl,
    this.searchQuery,
    this.searchResults,
    this.googleSearchResults,
    this.feedoSearchError,
    this.ambiguousWeb2Url,
    this.ambiguousFeedoUrl,
    this.state = TabState.empty,
    this.groupId,
    this.groupColor,
  });
}

class MainScreen extends StatefulWidget {
  final ApiClient apiClient;
  
  const MainScreen({super.key, required this.apiClient});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  late AppLinks _appLinks;
  StreamSubscription<Uri>? _linkSubscription;

  bool _isInit = false;

  final List<TabModel> _tabs = [];
  int _activeTabIndex = 0;
  bool _showHistoryPanel = false;
  bool _showBookmarksPanel = false;

  final Map<String, TextEditingController> _urlControllers = {};

  @override
  void initState() {
    super.initState();
    _initApp();
  }

  Future<void> _initApp() async {
    try {
      await LocalFeedoServer.start(widget.apiClient);

      try {
        await widget.apiClient.registerDid();
      } catch (e) {
        print("Failed to register DID (maybe consensus node is down): $e");
      }

      _addTab();
      _initAppLinks();
    } catch (e) {
      print("Init error: $e");
    } finally {
      if (mounted) {
        setState(() {
          _isInit = true;
        });
      }
    }
  }

  void _addTab({String url = ''}) {
    final id = DateTime.now().millisecondsSinceEpoch.toString();
    _tabs.add(TabModel(id: id, displayUrl: url));
    _urlControllers[id] = TextEditingController(text: url);
    _activeTabIndex = _tabs.length - 1;

    if (url.isNotEmpty) {
       _handleUrl(url, _activeTabIndex);
    }
    setState(() {});
  }

  void _closeTab(int index) {
    if (_tabs.length == 1) {
      _tabs[0] = TabModel(id: _tabs[0].id, displayUrl: '');
      _urlControllers[_tabs[0].id]!.clear();
      setState(() {});
      return;
    }

    final id = _tabs[index].id;
    _urlControllers.remove(id);
    _tabs.removeAt(index);

    if (_activeTabIndex >= _tabs.length) {
      _activeTabIndex = _tabs.length - 1;
    }
    setState(() {});
  }

  void _initAppLinks() {
    _appLinks = AppLinks();
    _linkSubscription = _appLinks.uriLinkStream.listen((uri) {
      if (uri.scheme == 'feedonet') {
        _addTab(url: uri.toString());
      }
    });
  }

  Future<void> _handleUrl(String inputUrl, int tabIndex, {bool isSearch = false, bool forceWeb2 = false}) async {
    final tab = _tabs[tabIndex];
    tab.displayUrl = inputUrl;
    tab.state = TabState.loading;
    _urlControllers[tab.id]!.text = inputUrl;
    setState(() {});
    
    // Add to SQLite History
    DbHelper.addHistory(inputUrl, inputUrl);

    try {
      if (isSearch) {
        tab.searchQuery = inputUrl;
        tab.state = TabState.loading;
        if (mounted) setState(() {});
        
        try {
          final results = await Future.wait([
            widget.apiClient.search(inputUrl),
            GoogleScraper.search(inputUrl)
          ]);
          
          final feedoResData = results[0] as Map<String, dynamic>;
          final feedoRes = List<Map<String, dynamic>>.from(feedoResData['results'] ?? []);
          final feedoError = feedoResData['error'] as String?;

          for (var result in feedoRes) {
            final metadata = result['metadata'] ?? <String, dynamic>{};
            final hasUrl = metadata.containsKey('url') && metadata['url'].toString().isNotEmpty;
            final hasDomain = metadata.containsKey('domain') && metadata['domain'].toString().isNotEmpty;
            
            if (!hasUrl && !hasDomain) {
              final cid = result['hash_id']?.toString() ?? '';
              if (cid.isNotEmpty) {
                final domain = await widget.apiClient.resolveCid(cid);
                if (domain != null && domain.isNotEmpty) {
                  // Make sure metadata is a mutable map
                  final mutableMeta = Map<String, dynamic>.from(metadata as Map);
                  mutableMeta['domain'] = domain;
                  result['metadata'] = mutableMeta;
                }
              }
            }
          }
          
          tab.searchResults = feedoRes;
          tab.feedoSearchError = feedoError;
          tab.googleSearchResults = results[1] as List<Map<String, String>>;
          tab.state = TabState.nativeSearch;
        } catch (e) {
          tab.state = TabState.empty;
        }
      }
      else if (inputUrl.startsWith('feedonet://')) {
        final uri = Uri.parse(inputUrl);
        final cid = await widget.apiClient.resolveName(uri.host);
        
        final p1 = cid!.substring(0, 32);
        final p2 = cid.substring(32);
        tab.loadUrl = 'http://$p1.$p2.localhost:${LocalFeedoServer.port}/';
        tab.state = TabState.webview;
      } 
      else if (inputUrl.startsWith('http://') || inputUrl.startsWith('https://')) {
        tab.loadUrl = inputUrl;
        tab.state = TabState.webview;
      }
      else {
        // Raw domain like consensus.world
        final cid = await widget.apiClient.resolveName(inputUrl);
        
        if (cid != null && !forceWeb2) {
          final p1 = cid.substring(0, 32);
          final p2 = cid.substring(32);
          tab.ambiguousFeedoUrl = 'http://$p1.$p2.localhost:${LocalFeedoServer.port}/';
          tab.ambiguousWeb2Url = 'https://$inputUrl';
          tab.state = TabState.disambiguation;
          tab.searchQuery = inputUrl;
        } else {
          tab.loadUrl = 'https://$inputUrl';
          tab.state = TabState.webview;
        }
      }
    } catch (e) {
      tab.state = TabState.empty;
      tab.loadUrl = null;
    }

    if (mounted) setState(() {});
  }

  void _onSelectGoogle(int tabIndex) {
    final tab = _tabs[tabIndex];
    tab.loadUrl = tab.ambiguousWeb2Url;
    tab.state = TabState.webview;
    setState(() {});
  }
  
  void _onSelectFeedo(int tabIndex) async {
    final tab = _tabs[tabIndex];
    if (tab.ambiguousFeedoUrl != null) {
      tab.loadUrl = tab.ambiguousFeedoUrl;
      tab.state = TabState.webview;
      setState(() {});
    }
  }

  void _onSearchSubmit(String rawQuery) {
    if (rawQuery.isEmpty) return;
    
    final query = rawQuery.trim();
    final queryLower = query.toLowerCase();

    if (queryLower.startsWith('http://') || queryLower.startsWith('https://') || queryLower.startsWith('feedonet://')) {
      if (AdblockEngine.shouldBlock(query)) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Blocked tracker domain!')));
        return;
      }
      _handleUrl(query, _activeTabIndex);
    } 
    else if (queryLower.contains('.') && !queryLower.contains(' ')) {
      // Treat as domain, could be ambiguous
      _handleUrl(queryLower, _activeTabIndex);
    } 
    else {
      // Pure search
      _handleUrl(query, _activeTabIndex, isSearch: true);
    }
  }

  void _showAccountInfo() {
    showDialog(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Account Info'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('DID', style: TextStyle(fontWeight: FontWeight.bold)),
            SelectableText(widget.apiClient.did, style: const TextStyle(fontFamily: 'monospace')),
            const SizedBox(height: 16),
            const Text('Address', style: TextStyle(fontWeight: FontWeight.bold)),
            SelectableText(widget.apiClient.address, style: const TextStyle(fontFamily: 'monospace')),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _linkSubscription?.cancel();
    for (var c in _urlControllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_isInit) return const Scaffold(body: Center(child: CircularProgressIndicator()));

    final activeTab = _tabs[_activeTabIndex];

    return Scaffold(
      backgroundColor: Theme.of(context).appBarTheme.backgroundColor, // Unified top background
      body: Column(
        children: [
          // 1. TOP TAB BAR (Full Width)
          Container(
            color: Theme.of(context).appBarTheme.backgroundColor,
            height: 48,
            child: Row(
              children: [
                const SizedBox(width: 12),
                Icon(Icons.public, color: Theme.of(context).colorScheme.primary, size: 24), // Feedo Logo moved here
                const SizedBox(width: 12),
                Expanded(
                  child: ListView.builder(
                    scrollDirection: Axis.horizontal,
                    itemCount: _tabs.length,
                    itemBuilder: (context, index) {
                      final tab = _tabs[index];
                      final isActive = index == _activeTabIndex;
                      
                      return Column(
                        children: [
                          if (tab.groupColor != null)
                            Container(
                              height: 4,
                              width: 200,
                              color: tab.groupColor,
                              margin: const EdgeInsets.only(left: 4),
                            ),
                          GestureDetector(
                            onTap: () => setState(() => _activeTabIndex = index),
                            onSecondaryTapDown: (details) {
                               // Simple right-click menu for assigning groups
                               showMenu(
                                 context: context,
                                 position: RelativeRect.fromLTRB(details.globalPosition.dx, details.globalPosition.dy, 0, 0),
                                 items: [
                                   const PopupMenuItem(value: 'red', child: Text('Red Group')),
                                   const PopupMenuItem(value: 'blue', child: Text('Blue Group')),
                                   const PopupMenuItem(value: 'none', child: Text('Remove from Group')),
                                 ]
                               ).then((value) {
                                 if (value == 'red') {
                                   setState(() { tab.groupId = 'red'; tab.groupColor = Colors.red; });
                                 } else if (value == 'blue') {
                                   setState(() { tab.groupId = 'blue'; tab.groupColor = Colors.blue; });
                                 } else if (value == 'none') {
                                   setState(() { tab.groupId = null; tab.groupColor = null; });
                                 }
                               });
                            },
                            child: Container(
                              width: 200,
                              height: tab.groupColor != null ? 36 : 40,
                              padding: const EdgeInsets.symmetric(horizontal: 8),
                              decoration: BoxDecoration(
                                color: isActive ? Theme.of(context).scaffoldBackgroundColor : Colors.transparent,
                                borderRadius: const BorderRadius.vertical(top: Radius.circular(8)),
                                border: isActive ? Border.all(color: Theme.of(context).dividerColor.withOpacity(0.1)) : null,
                              ),
                              margin: const EdgeInsets.only(top: 8, left: 4),
                              child: Row(
                                children: [
                                  Icon(Icons.public, size: 16, color: Theme.of(context).colorScheme.secondary),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      tab.displayUrl.isEmpty ? 'New Tab' : tab.displayUrl.replaceFirst('feedonet://', '').replaceFirst('https://', ''),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(fontWeight: isActive ? FontWeight.bold : FontWeight.normal),
                                    ),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.close, size: 16),
                                    onPressed: () => _closeTab(index),
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.add),
                  onPressed: () => _addTab(),
                ),
              ],
            ),
          ),
          
          // 2. MAIN BROWSER AREA
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _buildSidebar(),
                if (_showHistoryPanel) _buildHistoryPanel(),
                if (_showBookmarksPanel) _buildBookmarksPanel(),
                
                Expanded(
                  child: Column(
                    children: [
                      // Address Bar
                      Container(
                        color: Theme.of(context).appBarTheme.backgroundColor,
            padding: const EdgeInsets.all(8),
            child: Row(
              children: [
                IconButton(icon: const Icon(Icons.arrow_back), onPressed: () {}),
                IconButton(icon: const Icon(Icons.arrow_forward), onPressed: () {}),
                IconButton(icon: const Icon(Icons.refresh), onPressed: () {
                   if (activeTab.displayUrl.isNotEmpty) _handleUrl(activeTab.displayUrl, _activeTabIndex);
                }),
                const SizedBox(width: 8),
                Expanded(
                  child: Container(
                    height: 40,
                    decoration: BoxDecoration(
                      color: Theme.of(context).inputDecorationTheme.fillColor,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Row(
                      children: [
                        const SizedBox(width: 16),
                        Icon(Icons.search, size: 20, color: Theme.of(context).colorScheme.secondary),
                        const SizedBox(width: 8),
                        Expanded(
                          child: TextField(
                            controller: _urlControllers[activeTab.id],
                            decoration: const InputDecoration(
                              hintText: 'Search or type feedonet:// domain',
                              border: InputBorder.none,
                            ),
                            onSubmitted: _onSearchSubmit,
                          ),
                        ),
                        IconButton(
                          icon: Icon(Icons.star_border, color: (activeTab.state == TabState.webview && activeTab.displayUrl.isNotEmpty) ? Colors.grey : Colors.grey.shade300),
                          onPressed: (activeTab.state == TabState.webview && activeTab.displayUrl.isNotEmpty) ? () {
                            DbHelper.addBookmark(activeTab.displayUrl, activeTab.displayUrl);
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Added to Bookmarks!')));
                          } : null,
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(width: 16),
              ],
            ),
          ),

                      // Tab Content with Rounded Corner
                      Expanded(
                        child: Container(
                          decoration: BoxDecoration(
                            color: Theme.of(context).scaffoldBackgroundColor,
                            borderRadius: const BorderRadius.only(topLeft: Radius.circular(8)),
                          ),
                          clipBehavior: Clip.antiAlias,
                          child: _buildTabContent(activeTab, _activeTabIndex),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSidebar() {
    final theme = Theme.of(context);
    
    return Container(
      width: 48,
      color: theme.appBarTheme.backgroundColor,
      child: Column(
        children: [
          const SizedBox(height: 8),
          
          IconButton(
            icon: Icon(Icons.star, color: _showBookmarksPanel ? theme.colorScheme.primary : theme.iconTheme.color),
            tooltip: 'Bookmarks',
            onPressed: () {
              setState(() {
                _showBookmarksPanel = !_showBookmarksPanel;
                _showHistoryPanel = false;
              });
            },
          ),
          IconButton(
            icon: Icon(Icons.history, color: _showHistoryPanel ? theme.colorScheme.primary : theme.iconTheme.color),
            tooltip: 'History',
            onPressed: () {
              setState(() {
                _showHistoryPanel = !_showHistoryPanel;
                _showBookmarksPanel = false;
              });
            },
          ),
          IconButton(
            icon: Icon(Icons.dns, color: theme.iconTheme.color),
            tooltip: 'Domain Management',
            onPressed: () {
               Navigator.push(context, MaterialPageRoute(builder: (context) => PublishScreen(apiClient: widget.apiClient)));
            },
          ),
          
          const Spacer(),
          
          IconButton(
            icon: Icon(Icons.account_balance_wallet, color: theme.iconTheme.color),
            tooltip: 'Wallet / Account',
            onPressed: _showAccountInfo,
          ),
          IconButton(
            icon: const Icon(Icons.delete_forever, color: Colors.redAccent),
            tooltip: 'Clear Storage',
            onPressed: () {
              DbHelper.clearAll().then((_) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Локальне сховище повністю очищено!')));
                setState(() { _tabs.clear(); _addTab(); });
              });
            },
          ),
          const SizedBox(height: 12),
        ],
      ),
    );
  }

  Widget _buildHistoryPanel() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: 300,
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        border: Border(right: BorderSide(color: isDark ? Colors.white12 : Colors.grey.shade300)),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            color: Theme.of(context).appBarTheme.backgroundColor,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('History', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.onSurface)),
                IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _showHistoryPanel = false)),
              ],
            ),
          ),
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: DbHelper.getHistory(),
              builder: (context, snapshot) {
                if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
                final history = snapshot.data!;
                if (history.isEmpty) return const Center(child: Text('No history yet.'));
                return ListView.builder(
                  itemCount: history.length,
                  itemBuilder: (c, i) {
                    final item = history[i];
                    return ListTile(
                      title: Text(item['title'] ?? item['url'] ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Text(item['url'] ?? '', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
                      onTap: () => _handleUrl(item['url'], _activeTabIndex),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBookmarksPanel() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: 300,
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        border: Border(right: BorderSide(color: isDark ? Colors.white12 : Colors.grey.shade300)),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            color: Theme.of(context).appBarTheme.backgroundColor,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Bookmarks', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.onSurface)),
                IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _showBookmarksPanel = false)),
              ],
            ),
          ),
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: DbHelper.getBookmarks(),
              builder: (context, snapshot) {
                if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
                final bookmarks = snapshot.data!;
                if (bookmarks.isEmpty) return const Center(child: Text('No bookmarks yet.'));
                return ListView.builder(
                  itemCount: bookmarks.length,
                  itemBuilder: (c, i) {
                    final item = bookmarks[i];
                    return ListTile(
                      leading: const Icon(Icons.star, color: Colors.orange),
                      title: Text(item['title'] ?? item['url'] ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Text(item['url'] ?? '', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
                      onTap: () => _handleUrl(item['url'], _activeTabIndex),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTabContent(TabModel activeTab, int tabIndex) {
    switch (activeTab.state) {
      case TabState.loading:
        return const Center(child: CircularProgressIndicator());
      
      case TabState.disambiguation:
        return SearchDisambiguationView(
          query: activeTab.searchQuery ?? '',
          onSelectGoogle: () => _onSelectGoogle(tabIndex),
          onSelectFeedo: () => _onSelectFeedo(tabIndex),
        );

      case TabState.nativeSearch:
        return NativeSearchResultsView(
          query: activeTab.searchQuery ?? '',
          feedoResults: activeTab.searchResults ?? [],
          feedoError: activeTab.feedoSearchError,
          googleResults: activeTab.googleSearchResults ?? [],
          onResultTap: (url) => _handleUrl(url, tabIndex),
        );

      case TabState.webview:
        if (activeTab.loadUrl != null) {
          return BrowserTab(key: ValueKey(activeTab.id), url: activeTab.loadUrl!);
        }
        return const Center(child: Text("Error loading URL"));

      case TabState.empty:
      default:
        return _buildEmptyTabState(tabIndex);
    }
  }

  Widget _buildEmptyTabState(int tabIndex) {
    return StartPageView(
      onSearchSubmitted: (query, isSearch) {
        _handleUrl(query, tabIndex, isSearch: isSearch);
      },
    );
  }

}
