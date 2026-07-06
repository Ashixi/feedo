import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:app_links/app_links.dart';
import 'dart:async';

import 'theme.dart';
import 'core/ipfs_manager.dart';
import 'core/api_client.dart';
import 'core/identity_manager.dart';
import 'core/crypto_utils.dart';
import 'core/protocol_registrar.dart';
import 'core/local_server.dart';
import 'ui/browser_tab.dart';
import 'ui/publish_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ProtocolRegistrar.registerWindowsProtocol();
  IpfsManager.startDaemon();
  runApp(const FeedoBrowserApp());
}

class FeedoBrowserApp extends StatelessWidget {
  const FeedoBrowserApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Feedo Browser',
      theme: AppTheme.lightTheme,
      home: const MainScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class TabModel {
  String id;
  String url;
  String? cid;
  bool isLoading;

  TabModel({required this.id, this.url = '', this.cid, this.isLoading = false});
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  late AppLinks _appLinks;
  StreamSubscription<Uri>? _linkSubscription;
  
  late ApiClient _apiClient;
  bool _isInit = false;

  final List<TabModel> _tabs = [];
  int _activeTabIndex = 0;
  
  final Map<String, TextEditingController> _urlControllers = {};

  @override
  void initState() {
    super.initState();
    _initIdentityAndApp();
  }

  Future<void> _initIdentityAndApp() async {
    try {
      final keyPair = await IdentityManager.loadOrGenerateKeyPair();
      _apiClient = ApiClient(keyPair);
      
      await LocalFeedoServer.start(_apiClient);
      
      try {
        await _apiClient.registerDid();
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
    _tabs.add(TabModel(id: id, url: url));
    _urlControllers[id] = TextEditingController(text: url);
    _activeTabIndex = _tabs.length - 1;
    
    if (url.isNotEmpty && url.startsWith('feedonet://')) {
       _handleFeedonetUrl(url, _activeTabIndex);
    }
    setState(() {});
  }

  void _closeTab(int index) {
    if (_tabs.length == 1) {
      _tabs[0] = TabModel(id: _tabs[0].id, url: '');
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

  Future<void> _handleFeedonetUrl(String url, int tabIndex) async {
    final tab = _tabs[tabIndex];
    tab.url = url;
    tab.isLoading = true;
    _urlControllers[tab.id]!.text = url;
    setState(() {});

    try {
      final uri = Uri.parse(url);
      final domain = uri.host; 
      
      final cid = await _apiClient.resolveName(domain);
      
      tab.cid = cid;
      tab.isLoading = false;
    } catch (e) {
      tab.isLoading = false;
      tab.cid = null;
    }
    
    if (mounted) setState(() {});
  }

  void _onSearchSubmit(String query) {
    if (query.isEmpty) return;
    if (!query.startsWith('feedonet://')) {
      query = 'feedonet://$query';
    }
    _handleFeedonetUrl(query, _activeTabIndex);
  }

  void _showPrivateKey() {
    final hexKey = CryptoUtils.getPrivateKeyHex(_apiClient.keyPair.privateKey);
    showDialog(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Your Private Key'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('WARNING: Never share this key. If you lose it, you will lose access to your DID and domains.', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(8),
              color: Colors.grey.shade200,
              child: SelectableText(hexKey, style: const TextStyle(fontFamily: 'monospace')),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: hexKey));
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: const Text('Copied to clipboard')));
              Navigator.pop(c);
            },
            child: const Text('Copy & Close'),
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
      backgroundColor: Colors.white,
      body: Column(
        children: [
          // Custom Tab Bar
          Container(
            color: Colors.grey.shade200,
            height: 48,
            child: Row(
              children: [
                Expanded(
                  child: ListView.builder(
                    scrollDirection: Axis.horizontal,
                    itemCount: _tabs.length,
                    itemBuilder: (context, index) {
                      final tab = _tabs[index];
                      final isActive = index == _activeTabIndex;
                      return GestureDetector(
                        onTap: () => setState(() => _activeTabIndex = index),
                        child: Container(
                          width: 200,
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          decoration: BoxDecoration(
                            color: isActive ? Colors.white : Colors.transparent,
                            borderRadius: const BorderRadius.vertical(top: Radius.circular(8)),
                            border: isActive ? Border.all(color: Colors.grey.shade300) : null,
                          ),
                          margin: const EdgeInsets.only(top: 8, left: 4),
                          child: Row(
                            children: [
                              const Icon(Icons.public, size: 16, color: Colors.grey),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  tab.url.isEmpty ? 'New Tab' : tab.url.replaceFirst('feedonet://', ''),
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
          
          // Address Bar
          Container(
            color: Colors.white,
            padding: const EdgeInsets.all(8),
            child: Row(
              children: [
                IconButton(icon: const Icon(Icons.arrow_back), onPressed: () {}),
                IconButton(icon: const Icon(Icons.arrow_forward), onPressed: () {}),
                IconButton(icon: const Icon(Icons.refresh), onPressed: () {
                   if (activeTab.url.isNotEmpty) _handleFeedonetUrl(activeTab.url, _activeTabIndex);
                }),
                const SizedBox(width: 8),
                Expanded(
                  child: Container(
                    height: 40,
                    decoration: BoxDecoration(
                      color: Colors.grey.shade100,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: TextField(
                      controller: _urlControllers[activeTab.id],
                      decoration: const InputDecoration(
                        hintText: 'Search or type feedonet:// domain',
                        prefixIcon: Icon(Icons.search, size: 20),
                        border: InputBorder.none,
                        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                      ),
                      onSubmitted: _onSearchSubmit,
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                
                // Profile Menu
                PopupMenuButton<String>(
                  icon: const CircleAvatar(
                    backgroundColor: Color(0xFF1A73E8),
                    child: Icon(Icons.person, color: Colors.white, size: 20),
                  ),
                  tooltip: 'Account Menu',
                  onSelected: (value) {
                    if (value == 'publish') {
                      Navigator.push(context, MaterialPageRoute(builder: (_) => PublishScreen(apiClient: _apiClient)));
                    } else if (value == 'key') {
                      _showPrivateKey();
                    }
                  },
                  itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
                    PopupMenuItem<String>(
                      enabled: false,
                      child: Text('DID: ${_apiClient.did.substring(0, 16)}...', style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.black)),
                    ),
                    const PopupMenuDivider(),
                    const PopupMenuItem<String>(
                      value: 'publish',
                      child: ListTile(
                        leading: Icon(Icons.cloud_upload),
                        title: Text('Publish Site'),
                        contentPadding: EdgeInsets.zero,
                      ),
                    ),
                    const PopupMenuItem<String>(
                      value: 'key',
                      child: ListTile(
                        leading: Icon(Icons.vpn_key),
                        title: Text('Show Private Key'),
                        contentPadding: EdgeInsets.zero,
                      ),
                    ),
                  ],
                ),
                const SizedBox(width: 8),
              ],
            ),
          ),
          
          const Divider(height: 1),
          
          // Tab Content
          Expanded(
            child: activeTab.isLoading
                ? const Center(child: CircularProgressIndicator())
                : activeTab.cid != null
                    ? BrowserTab(key: ValueKey(activeTab.id), initialCid: activeTab.cid!)
                    : Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.public, size: 64, color: Colors.grey),
                            const SizedBox(height: 16),
                            const Text("Welcome to Feedo Browser", style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
                            const SizedBox(height: 8),
                            Text("Type a feedonet:// domain to start surfing", style: TextStyle(fontSize: 16, color: Colors.grey.shade600)),
                          ],
                        ),
                      ),
          ),
        ],
      ),
    );
  }
}
