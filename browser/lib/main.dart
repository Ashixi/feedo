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
import 'ui/browser_tab.dart';
import 'ui/onboarding_screen.dart';
import 'ui/search_disambiguation_view.dart';
import 'ui/native_search_results_view.dart';
import 'ui/domains_screen.dart';
import 'ui/publish_screen.dart';
import 'ui/start_page_view.dart';
import 'ui/google_search_overlay.dart';

import 'package:browser/src/rust/frb_generated.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
  await RustLib.init();
  runApp(const FeedoBrowserApp());
}

class FeedoBrowserApp extends StatelessWidget {
  const FeedoBrowserApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Feedo Browser', theme: AppTheme.lightTheme, darkTheme: AppTheme.darkTheme,
      themeMode: ThemeMode.dark, home: const OnboardingScreen(), debugShowCheckedModeBanner: false,
    );
  }
}

enum TabState { empty, loading, webview, disambiguation, nativeSearch }

class TabModel {
  String id; String displayUrl; String? loadUrl; String? searchQuery;
  List<Map<String, dynamic>>? searchResults; String? feedoSearchError;
  String? ambiguousWeb2Url; String? ambiguousFeedoUrl; TabState state;
  String? groupId; Color? groupColor;
  TabModel({required this.id, this.displayUrl = '', this.loadUrl, this.searchQuery, this.searchResults, this.feedoSearchError, this.ambiguousWeb2Url, this.ambiguousFeedoUrl, this.state = TabState.empty, this.groupId, this.groupColor});
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
  bool _isGoogleLoggedIn = false;
  final List<TabModel> _tabs = [];
  int _activeTabIndex = 0;
  bool _showHistoryPanel = false;
  bool _showBookmarksPanel = false;
  final Map<String, TextEditingController> _urlControllers = {};
  final Map<String, _NavigationStack> _navStacks = {};

  _NavigationStack _getNavStack(String tabId) {
    if (!_navStacks.containsKey(tabId)) _navStacks[tabId] = _NavigationStack();
    return _navStacks[tabId]!;
  }

  @override
  void initState() { super.initState(); _initApp(); }

  Future<void> _initApp() async {
    try {
      await LocalFeedoServer.start(widget.apiClient);
      try { await widget.apiClient.registerDid(); await widget.apiClient.syncCertificates(); } catch (e) { print("DID/cert error: $e"); }
      _addTab(); _initAppLinks();
    } catch (e) { print("Init error: $e"); }
    finally { if (mounted) setState(() => _isInit = true); }
  }

  void _addTab({String url = ''}) {
    final id = DateTime.now().millisecondsSinceEpoch.toString();
    _tabs.add(TabModel(id: id, displayUrl: url));
    _urlControllers[id] = TextEditingController(text: url);
    _activeTabIndex = _tabs.length - 1;
    if (url.isNotEmpty) _handleUrl(url, _activeTabIndex);
    setState(() {});
  }

  void _closeTab(int index) {
    if (_tabs.length == 1) { _tabs[0] = TabModel(id: _tabs[0].id); _urlControllers[_tabs[0].id]!.clear(); setState(() {}); return; }
    _urlControllers.remove(_tabs[index].id);
    _tabs.removeAt(index);
    if (_activeTabIndex >= _tabs.length) _activeTabIndex = _tabs.length - 1;
    setState(() {});
  }

  void _initAppLinks() {
    _appLinks = AppLinks();
    _linkSubscription = _appLinks.uriLinkStream.listen((uri) { if (uri.scheme == 'feedonet') _addTab(url: uri.toString()); });
  }

  /// Called when Google login completes — marks state and closes login tab.
  void _onGoogleLoginComplete(int tabIndex) {
    setState(() { _isGoogleLoggedIn = true; });
    _closeTab(tabIndex);
    // Ensure we're showing the start page
    if (_tabs.isNotEmpty) {
      _tabs[_activeTabIndex].state = TabState.empty;
      _tabs[_activeTabIndex].loadUrl = null;
      setState(() {});
    }
  }

  Future<void> _handleUrl(String inputUrl, int tabIndex, {bool isSearch = false, bool forceWeb2 = false, bool addToHistory = true, SearchEngine engine = SearchEngine.feedo}) async {
    final tab = _tabs[tabIndex];
    tab.displayUrl = inputUrl;
    tab.state = TabState.loading;
    _urlControllers[tab.id]!.text = inputUrl;
    setState(() {});
    if (addToHistory) _getNavStack(tab.id).push(inputUrl);
    DbHelper.addHistory(inputUrl, inputUrl);

    // Google search → Google WebView
    if (isSearch && engine == SearchEngine.google) {
      final encoded = Uri.encodeComponent(inputUrl);
      tab.loadUrl = 'https://www.google.com/search?q=$encoded';
      tab.state = TabState.webview;
      if (mounted) setState(() {});
      return;
    }

    try {
      if (isSearch) {
        tab.searchQuery = inputUrl; tab.state = TabState.loading; if (mounted) setState(() {});
        try {
          final d = await widget.apiClient.search(inputUrl);
          final r = List<Map<String, dynamic>>.from(d['results'] ?? []);
          final e = d['error'] as String?;
          for (var x in r) {
            final m = x['metadata'] ?? <String, dynamic>{};
            if (!m.containsKey('url') && !m.containsKey('domain')) {
              final c = x['hash_id']?.toString() ?? '';
              if (c.isNotEmpty) { final dm = await widget.apiClient.resolveCid(c); if (dm != null && dm.isNotEmpty) { final meta = Map<String, dynamic>.from(m); meta['domain'] = dm; x['metadata'] = meta; } }
            }
          }
          tab.searchResults = r; tab.feedoSearchError = e; tab.state = TabState.nativeSearch;
        } catch (_) { tab.state = TabState.empty; }
      } else if (inputUrl.startsWith('feedonet://')) {
        final uri = Uri.parse(inputUrl); final cid = await widget.apiClient.resolveName(uri.host);
        if (cid != null && cid.length >= 64) {
          tab.loadUrl = 'http://${cid.substring(0,32)}.${cid.substring(32)}.localhost:${LocalFeedoServer.port}/'; tab.state = TabState.webview;
        } else { tab.state = TabState.empty; tab.loadUrl = null; if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Domain "${uri.host}" not found'))); }
      } else if (inputUrl.startsWith('http://') || inputUrl.startsWith('https://')) {
        tab.loadUrl = inputUrl; tab.state = TabState.webview;
      } else {
        final cid = await widget.apiClient.resolveName(inputUrl);
        if (cid != null && cid.length >= 64 && !forceWeb2) { tab.ambiguousFeedoUrl = 'http://${cid.substring(0,32)}.${cid.substring(32)}.localhost:${LocalFeedoServer.port}/'; tab.ambiguousWeb2Url = 'https://$inputUrl'; tab.state = TabState.disambiguation; tab.searchQuery = inputUrl; }
        else { tab.loadUrl = 'https://$inputUrl'; tab.state = TabState.webview; }
      }
    } catch (_) { tab.state = TabState.empty; tab.loadUrl = null; }
    if (mounted) setState(() {});
  }

  void _onSelectGoogle(int t) { final tab = _tabs[t]; tab.loadUrl = tab.ambiguousWeb2Url; tab.state = TabState.webview; setState(() {}); }
  void _onSelectFeedo(int t) { final tab = _tabs[t]; if (tab.ambiguousFeedoUrl != null) { tab.loadUrl = tab.ambiguousFeedoUrl; tab.state = TabState.webview; setState(() {}); } }

  void _onSearchSubmit(String rawQuery) {
    if (rawQuery.isEmpty) return;
    final q = rawQuery.trim(); final ql = q.toLowerCase();
    if (ql.startsWith('http://') || ql.startsWith('https://') || ql.startsWith('feedonet://')) {
      if (AdblockEngine.shouldBlock(q)) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Blocked!'))); return; }
      _handleUrl(q, _activeTabIndex);
    } else if (ql.contains('.') && !ql.contains(' ')) {
      if (AdblockEngine.shouldBlock('https://$ql')) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Blocked!'))); return; }
      _handleUrl(ql, _activeTabIndex);
    } else { _handleUrl(q, _activeTabIndex, isSearch: true); }
  }

  void _showAccountInfo() {
    showDialog(context: context, builder: (c) => AlertDialog(title: const Text('Account Info'), content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('DID', style: TextStyle(fontWeight: FontWeight.bold)), SelectableText(widget.apiClient.did, style: const TextStyle(fontFamily: 'monospace')),
      const SizedBox(height: 16), const Text('Address', style: TextStyle(fontWeight: FontWeight.bold)), SelectableText(widget.apiClient.address, style: const TextStyle(fontFamily: 'monospace')),
    ]), actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Close'))]));
  }

  @override
  void dispose() { _linkSubscription?.cancel(); for (var c in _urlControllers.values) { c.dispose(); } super.dispose(); }

  @override
  Widget build(BuildContext context) {
    if (!_isInit) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final activeTab = _tabs[_activeTabIndex];

    return Scaffold(
      backgroundColor: Theme.of(context).appBarTheme.backgroundColor,
      body: Column(children: [
        Container(color: Theme.of(context).appBarTheme.backgroundColor, height: 48, child: Row(children: [
          const SizedBox(width: 12), Icon(Icons.public, color: Theme.of(context).colorScheme.primary, size: 24), const SizedBox(width: 12),
          Expanded(child: ListView.builder(scrollDirection: Axis.horizontal, itemCount: _tabs.length, itemBuilder: (context, index) {
            final tab = _tabs[index]; final isActive = index == _activeTabIndex;
            return Column(children: [
              if (tab.groupColor != null) Container(height: 4, width: 200, color: tab.groupColor, margin: const EdgeInsets.only(left: 4)),
              GestureDetector(onTap: () => setState(() => _activeTabIndex = index), onSecondaryTapDown: (details) {
                showMenu(context: context, position: RelativeRect.fromLTRB(details.globalPosition.dx, details.globalPosition.dy, 0, 0), items: [
                  const PopupMenuItem(value: 'red', child: Text('Red Group')), const PopupMenuItem(value: 'blue', child: Text('Blue Group')), const PopupMenuItem(value: 'none', child: Text('Remove from Group')),
                ]).then((value) {
                  if (value == 'red') { setState(() { tab.groupId = 'red'; tab.groupColor = Colors.red; }); }
                  else if (value == 'blue') { setState(() { tab.groupId = 'blue'; tab.groupColor = Colors.blue; }); }
                  else if (value == 'none') { setState(() { tab.groupId = null; tab.groupColor = null; }); }
                });
              },
                child: Container(width: 200, height: tab.groupColor != null ? 36 : 40, padding: const EdgeInsets.symmetric(horizontal: 8),
                  decoration: BoxDecoration(color: isActive ? Theme.of(context).scaffoldBackgroundColor : Colors.transparent, borderRadius: const BorderRadius.vertical(top: Radius.circular(8)), border: isActive ? Border.all(color: Theme.of(context).dividerColor.withOpacity(0.1)) : null),
                  margin: const EdgeInsets.only(top: 8, left: 4),
                  child: Row(children: [Icon(Icons.public, size: 16, color: Theme.of(context).colorScheme.secondary), const SizedBox(width: 8), Expanded(child: Text(tab.displayUrl.isEmpty ? 'New Tab' : tab.displayUrl.replaceFirst('feedonet://', '').replaceFirst('https://', ''), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: isActive ? FontWeight.bold : FontWeight.normal))), IconButton(icon: const Icon(Icons.close, size: 16), onPressed: () => _closeTab(index), padding: EdgeInsets.zero, constraints: const BoxConstraints())])),
              ),
            ]);
          })),
          IconButton(icon: const Icon(Icons.add), onPressed: () => _addTab()),
        ])),
        Expanded(child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _buildSidebar(), if (_showHistoryPanel) _buildHistoryPanel(), if (_showBookmarksPanel) _buildBookmarksPanel(),
          Expanded(child: Column(children: [
            Container(color: Theme.of(context).appBarTheme.backgroundColor, padding: const EdgeInsets.all(8), child: Row(children: [
              IconButton(icon: const Icon(Icons.arrow_back), onPressed: _getNavStack(activeTab.id).canGoBack ? () { final u = _getNavStack(activeTab.id).goBack(); if (u != null) _handleUrl(u, _activeTabIndex, addToHistory: false); } : null),
              IconButton(icon: const Icon(Icons.arrow_forward), onPressed: _getNavStack(activeTab.id).canGoForward ? () { final u = _getNavStack(activeTab.id).goForward(); if (u != null) _handleUrl(u, _activeTabIndex, addToHistory: false); } : null),
              IconButton(icon: const Icon(Icons.refresh), onPressed: () { if (activeTab.displayUrl.isNotEmpty) _handleUrl(activeTab.displayUrl, _activeTabIndex); }),
              const SizedBox(width: 8),
              Expanded(child: Container(height: 40, decoration: BoxDecoration(color: Theme.of(context).inputDecorationTheme.fillColor, borderRadius: BorderRadius.circular(20)),
                child: Row(children: [
                  const SizedBox(width: 16), Icon(Icons.search, size: 20, color: Theme.of(context).colorScheme.secondary), const SizedBox(width: 8),
                  Expanded(child: TextField(controller: _urlControllers[activeTab.id], decoration: const InputDecoration(hintText: 'Search or type URL', border: InputBorder.none), onSubmitted: _onSearchSubmit)),
                  IconButton(icon: Icon(Icons.star_border, color: (activeTab.state == TabState.webview && activeTab.displayUrl.isNotEmpty) ? Colors.grey : Colors.grey.shade300),
                    onPressed: (activeTab.state == TabState.webview && activeTab.displayUrl.isNotEmpty) ? () { DbHelper.addBookmark(activeTab.displayUrl, activeTab.displayUrl); ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Bookmarked!'))); } : null),
                ])),
              ),
              const SizedBox(width: 16),
            ])),
            Expanded(child: Container(decoration: BoxDecoration(color: Theme.of(context).scaffoldBackgroundColor, borderRadius: const BorderRadius.only(topLeft: Radius.circular(8))), clipBehavior: Clip.antiAlias, child: _buildTabContent(activeTab, _activeTabIndex))),
          ])),
        ])),
      ]),
    );
  }

  Widget _buildSidebar() {
    return Container(width: 48, color: Theme.of(context).appBarTheme.backgroundColor, child: Column(children: [
      const SizedBox(height: 8),
      IconButton(icon: Icon(Icons.star, color: _showBookmarksPanel ? Theme.of(context).colorScheme.primary : Theme.of(context).iconTheme.color), tooltip: 'Bookmarks', onPressed: () => setState(() { _showBookmarksPanel = !_showBookmarksPanel; _showHistoryPanel = false; })),
      IconButton(icon: Icon(Icons.history, color: _showHistoryPanel ? Theme.of(context).colorScheme.primary : Theme.of(context).iconTheme.color), tooltip: 'History', onPressed: () => setState(() { _showHistoryPanel = !_showHistoryPanel; _showBookmarksPanel = false; })),
      IconButton(icon: Icon(Icons.dns, color: Theme.of(context).iconTheme.color), tooltip: 'Domain Management', onPressed: () { Navigator.push(context, MaterialPageRoute(builder: (context) => PublishScreen(apiClient: widget.apiClient))); }),
      const Spacer(),
      IconButton(icon: Icon(Icons.account_balance_wallet, color: Theme.of(context).iconTheme.color), tooltip: 'Wallet / Account', onPressed: _showAccountInfo),
      IconButton(icon: const Icon(Icons.delete_forever, color: Colors.redAccent), tooltip: 'Clear Storage', onPressed: () { DbHelper.clearAll().then((_) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Cleared!'))); setState(() { _tabs.clear(); _addTab(); }); }); }),
      const SizedBox(height: 12),
    ]));
  }

  Widget _buildHistoryPanel() {
    return Container(width: 300, decoration: BoxDecoration(color: Theme.of(context).scaffoldBackgroundColor, border: Border(right: BorderSide(color: Theme.of(context).brightness == Brightness.dark ? Colors.white12 : Colors.grey.shade300))), child: Column(children: [
      Container(padding: const EdgeInsets.all(16), color: Theme.of(context).appBarTheme.backgroundColor, child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Text('History', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.onSurface)), IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _showHistoryPanel = false))])),
      Expanded(child: FutureBuilder<List<Map<String, dynamic>>>(future: DbHelper.getHistory(), builder: (context, snapshot) {
        if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
        if (snapshot.data!.isEmpty) return const Center(child: Text('No history yet.'));
        return ListView.builder(itemCount: snapshot.data!.length, itemBuilder: (c, i) { final item = snapshot.data![i]; return ListTile(title: Text(item['title'] ?? item['url'] ?? '', maxLines: 1), subtitle: Text(item['url'] ?? '', maxLines: 1, style: const TextStyle(fontSize: 12)), onTap: () => _handleUrl(item['url'], _activeTabIndex)); });
      })),
    ]));
  }

  Widget _buildBookmarksPanel() {
    return Container(width: 300, decoration: BoxDecoration(color: Theme.of(context).scaffoldBackgroundColor, border: Border(right: BorderSide(color: Theme.of(context).brightness == Brightness.dark ? Colors.white12 : Colors.grey.shade300))), child: Column(children: [
      Container(padding: const EdgeInsets.all(16), color: Theme.of(context).appBarTheme.backgroundColor, child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Text('Bookmarks', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.onSurface)), IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _showBookmarksPanel = false))])),
      Expanded(child: FutureBuilder<List<Map<String, dynamic>>>(future: DbHelper.getBookmarks(), builder: (context, snapshot) {
        if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
        if (snapshot.data!.isEmpty) return const Center(child: Text('No bookmarks yet.'));
        return ListView.builder(itemCount: snapshot.data!.length, itemBuilder: (c, i) { final item = snapshot.data![i]; return ListTile(leading: const Icon(Icons.star, color: Colors.orange), title: Text(item['title'] ?? item['url'] ?? '', maxLines: 1), subtitle: Text(item['url'] ?? '', maxLines: 1, style: const TextStyle(fontSize: 12)), onTap: () => _handleUrl(item['url'], _activeTabIndex)); });
      })),
    ]));
  }

  Widget _buildTabContent(TabModel activeTab, int tabIndex) {
    switch (activeTab.state) {
      case TabState.loading: return const Center(child: CircularProgressIndicator());
      case TabState.disambiguation: return SearchDisambiguationView(query: activeTab.searchQuery ?? '', onSelectGoogle: () => _onSelectGoogle(tabIndex), onSelectFeedo: () => _onSelectFeedo(tabIndex));
      case TabState.nativeSearch: return NativeSearchResultsView(query: activeTab.searchQuery ?? '', feedoResults: activeTab.searchResults ?? [], feedoError: activeTab.feedoSearchError, onResultTap: (url) => _handleUrl(url, tabIndex));
      case TabState.webview:
        if (activeTab.loadUrl == null) return const Center(child: Text("Error loading URL"));
        final isGoogleLogin = activeTab.loadUrl!.contains('accounts.google.com');
        return BrowserTab(
          key: ValueKey(activeTab.id),
          url: activeTab.loadUrl!,
          onLoginComplete: isGoogleLogin ? () => _onGoogleLoginComplete(tabIndex) : null,
        );
      case TabState.empty: return _buildEmptyTabState(tabIndex);
    }
  }

  Widget _buildEmptyTabState(int tabIndex) {
    return StartPageView(
      isGoogleLoggedIn: _isGoogleLoggedIn,
      onSearchSubmitted: (query, isSearch, engine) {
        _handleUrl(query, tabIndex, isSearch: isSearch, engine: engine);
      },
    );
  }
}

class _NavigationStack {
  final List<String> _backStack = []; final List<String> _forwardStack = [];
  void push(String url) { if (_backStack.isNotEmpty && _backStack.last == url) return; _backStack.add(url); _forwardStack.clear(); }
  String? goBack() { if (_backStack.length <= 1) return null; final c = _backStack.removeLast(); _forwardStack.add(c); return _backStack.last; }
  String? goForward() { if (_forwardStack.isEmpty) return null; final n = _forwardStack.removeLast(); _backStack.add(n); return n; }
  bool get canGoBack => _backStack.length > 1; bool get canGoForward => _forwardStack.isNotEmpty;
  void clear() { _backStack.clear(); _forwardStack.clear(); }
}