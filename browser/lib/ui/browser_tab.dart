import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';



class BrowserTab extends StatefulWidget {
  final String url;

  const BrowserTab({super.key, required this.url});

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

  Future<void> _initWebview() async {
    await _controller.initialize();
    await _controller.setBackgroundColor(Colors.transparent);
    await _controller.loadUrl(widget.url);
    if (mounted) {
      setState(() {
        _isInitialized = true;
      });
    }
  }

  @override
  void didUpdateWidget(BrowserTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url && _isInitialized) {
      _controller.loadUrl(widget.url);
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
