import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';

class BrowserTab extends StatefulWidget {
  final String url;
  /// Called when the user completes Google login (URL changes away from accounts.google.com).
  final VoidCallback? onLoginComplete;

  const BrowserTab({super.key, required this.url, this.onLoginComplete});

  @override
  State<BrowserTab> createState() => _BrowserTabState();
}

class _BrowserTabState extends State<BrowserTab> {
  final _controller = WebviewController();
  bool _isInitialized = false;
  String _lastUrl = '';
  bool _wasOnLoginPage = false;

  @override
  void initState() {
    super.initState();
    _initWebview();
  }

  Future<void> _initWebview() async {
    await _controller.initialize();
    await _controller.setBackgroundColor(Colors.transparent);

    // Listen for URL changes to detect Google login completion.
    _controller.url.listen((url) {
      if (url.isEmpty || url == _lastUrl) return;
      _lastUrl = url;

      final isOnLoginPage = url.contains('accounts.google.com');
      final isOnGoogleHome = url.contains('google.com') && !isOnLoginPage;

      // Detect: was on login page, now on google.com → login complete!
      if (_wasOnLoginPage && isOnGoogleHome && widget.onLoginComplete != null) {
        widget.onLoginComplete!();
        return;
      }

      // Track whether we're on the login page
      if (isOnLoginPage) {
        _wasOnLoginPage = true;
      }

      // After login, if we land on myaccount.google.com → redirect to google.com home
      if (url.contains('myaccount.google.com')) {
        Future.delayed(const Duration(milliseconds: 500), () {
          _controller.loadUrl('https://www.google.com');
        });
      }
    });

    await _controller.loadUrl(widget.url);
    _lastUrl = widget.url;
    _wasOnLoginPage = widget.url.contains('accounts.google.com');
    if (mounted) {
      setState(() { _isInitialized = true; });
    }
  }

  @override
  void didUpdateWidget(BrowserTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url && _isInitialized) {
      _lastUrl = widget.url;
      _wasOnLoginPage = widget.url.contains('accounts.google.com');
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