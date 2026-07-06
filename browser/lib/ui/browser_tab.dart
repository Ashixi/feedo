import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';

import '../core/local_server.dart';

class BrowserTab extends StatefulWidget {
  final String initialCid;
  
  const BrowserTab({super.key, required this.initialCid});

  @override
  State<BrowserTab> createState() => _BrowserTabState();
}

class _BrowserTabState extends State<BrowserTab> {
  final _controller = WebviewController();
  bool _isInitialized = false;

  @override
  void initState() {
    super.initState();
    _initWebview();
  }

  String _buildUrl(String cid) {
    if (cid.startsWith('Qm') || cid.startsWith('bafy')) {
      return 'http://127.0.0.1:8080/ipfs/$cid/';
    } else {
      final p1 = cid.substring(0, 32);
      final p2 = cid.substring(32);
      return 'http://$p1.$p2.localhost:${LocalFeedoServer.port}/';
    }
  }

  Future<void> _initWebview() async {
    await _controller.initialize();
    await _controller.setBackgroundColor(Colors.transparent);
    await _controller.loadUrl(_buildUrl(widget.initialCid));
    if (mounted) {
      setState(() {
        _isInitialized = true;
      });
    }
  }

  @override
  void didUpdateWidget(BrowserTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.initialCid != widget.initialCid && _isInitialized) {
      _controller.loadUrl(_buildUrl(widget.initialCid));
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_isInitialized) {
      return const Center(child: CircularProgressIndicator());
    }
    return Webview(_controller);
  }
}
