import 'package:flutter/material.dart';

enum SearchEngine { feedo, google }

class StartPageView extends StatefulWidget {
  final Function(String, bool, SearchEngine) onSearchSubmitted;
  final bool isGoogleLoggedIn;

  const StartPageView({
    super.key,
    required this.onSearchSubmitted,
    this.isGoogleLoggedIn = false,
  });

  @override
  State<StartPageView> createState() => _StartPageViewState();
}

class _StartPageViewState extends State<StartPageView> {
  final TextEditingController _searchController = TextEditingController();
  final FocusNode _searchFocus = FocusNode();
  bool _isSearchFocused = false;
  SearchEngine _selectedEngine = SearchEngine.feedo;

  final List<Map<String, dynamic>> _quickLinks = [
    {'title': 'YouTube', 'url': 'https://youtube.com', 'icon': Icons.play_circle_fill, 'color': Colors.red},
    {'title': 'Gemini', 'url': 'https://gemini.google.com', 'icon': Icons.auto_awesome, 'color': Colors.blue},
    {'title': 'Feedo', 'url': 'feedonet://', 'icon': Icons.public, 'color': Colors.green},
    {'title': 'GitHub', 'url': 'https://github.com', 'icon': Icons.code, 'color': Colors.grey.shade400},
    {'title': 'Maps', 'url': 'https://maps.google.com', 'icon': Icons.map, 'color': Colors.orange},
    {'title': 'Gmail', 'url': 'https://gmail.com', 'icon': Icons.mail, 'color': Colors.redAccent},
  ];

  @override
  void initState() {
    super.initState();
    _searchFocus.addListener(() {
      setState(() { _isSearchFocused = _searchFocus.hasFocus; });
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    _searchFocus.dispose();
    super.dispose();
  }

  void _handleSubmit(String value) {
    if (value.trim().isNotEmpty) {
      widget.onSearchSubmitted(value.trim(), !value.contains('.') && !value.contains('://'), _selectedEngine);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final isGoogle = _selectedEngine == SearchEngine.google;
    final titleText = isGoogle ? "Google" : "FeedoNet";
    final bgGradient = isDark
        ? const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF2B2E33), Color(0xFF1E2024)])
        : LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Colors.grey.shade100, Colors.grey.shade300]);

    return Container(
      decoration: BoxDecoration(gradient: bgGradient),
      child: Center(
        child: SingleChildScrollView(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.public, size: 48, color: Theme.of(context).colorScheme.primary),
                  const SizedBox(width: 16),
                  Text(titleText, style: TextStyle(fontSize: 56, fontWeight: FontWeight.w900, letterSpacing: -1.5, color: Theme.of(context).colorScheme.onSurface)),
                ],
              ),
              const SizedBox(height: 48),

              AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: _isSearchFocused ? 680 : 600,
                decoration: BoxDecoration(
                  color: isDark ? const Color(0xFF2D2D2D) : Colors.white,
                  borderRadius: BorderRadius.circular(30),
                  boxShadow: _isSearchFocused
                      ? [BoxShadow(color: Theme.of(context).colorScheme.primary.withOpacity(0.3), blurRadius: 20, spreadRadius: 2)]
                      : [BoxShadow(color: Colors.black.withOpacity(isDark ? 0.3 : 0.05), blurRadius: 10, offset: const Offset(0, 4))],
                  border: Border.all(color: _isSearchFocused ? Theme.of(context).colorScheme.primary : (isDark ? Colors.white12 : Colors.grey.shade300), width: _isSearchFocused ? 2 : 1),
                ),
                child: Row(
                  children: [
                    PopupMenuButton<SearchEngine>(
                      icon: Icon(isGoogle ? Icons.search : Icons.language, size: 22, color: isGoogle ? Colors.blue : Theme.of(context).colorScheme.primary),
                      tooltip: isGoogle ? 'Google' : 'Feedo',
                      onSelected: (e) => setState(() => _selectedEngine = e),
                      itemBuilder: (_) => const [
                        PopupMenuItem(value: SearchEngine.feedo, child: Text('Feedo')),
                        PopupMenuItem(value: SearchEngine.google, child: Text('Google')),
                      ],
                    ),
                    Expanded(
                      child: TextField(
                        controller: _searchController,
                        focusNode: _searchFocus,
                        autofocus: true,
                        style: TextStyle(fontSize: 18, color: Theme.of(context).colorScheme.onSurface),
                        decoration: InputDecoration(
                          hintText: isGoogle ? "Search Google..." : "Search FeedoNet...",
                          hintStyle: TextStyle(color: isDark ? Colors.grey.shade500 : Colors.grey.shade400),
                          border: InputBorder.none, enabledBorder: InputBorder.none, focusedBorder: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
                        ),
                        onChanged: (_) => setState(() {}),
                        onSubmitted: _handleSubmit,
                      ),
                    ),
                    if (isGoogle)
                      IconButton(
                        icon: Icon(widget.isGoogleLoggedIn ? Icons.check_circle : Icons.account_circle, size: 26),
                        color: widget.isGoogleLoggedIn ? Colors.green : Colors.blue,
                        tooltip: widget.isGoogleLoggedIn ? 'Logged into Google' : 'Sign in to Google',
                        onPressed: widget.isGoogleLoggedIn ? null : () => widget.onSearchSubmitted('https://accounts.google.com', false, SearchEngine.google),
                      ),
                    if (_searchController.text.isNotEmpty)
                      IconButton(icon: const Icon(Icons.clear), onPressed: () { _searchController.clear(); setState(() {}); }),
                    const SizedBox(width: 8),
                  ],
                ),
              ),
              const SizedBox(height: 64),

              SizedBox(
                width: 600,
                child: Wrap(
                  spacing: 24, runSpacing: 24, alignment: WrapAlignment.center,
                  children: _quickLinks.map((link) => _QuickLinkItem(
                    title: link['title'], icon: link['icon'], color: link['color'],
                    onTap: () => widget.onSearchSubmitted(link['url'], false, _selectedEngine),
                    isDark: isDark,
                  )).toList(),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _QuickLinkItem extends StatefulWidget {
  final String title; final IconData icon; final Color color; final VoidCallback onTap; final bool isDark;
  const _QuickLinkItem({required this.title, required this.icon, required this.color, required this.onTap, required this.isDark});
  @override
  State<_QuickLinkItem> createState() => _QuickLinkItemState();
}

class _QuickLinkItemState extends State<_QuickLinkItem> {
  bool _isHovered = false;
  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          transform: Matrix4.identity()..scale(_isHovered ? 1.05 : 1.0),
          width: 80,
          child: Column(children: [
            Container(
              width: 64, height: 64,
              decoration: BoxDecoration(
                color: widget.isDark ? const Color(0xFF35363A) : Colors.white,
                borderRadius: BorderRadius.circular(16),
                boxShadow: [BoxShadow(color: Colors.black.withOpacity(widget.isDark ? (_isHovered ? 0.4 : 0.2) : (_isHovered ? 0.1 : 0.05)), blurRadius: _isHovered ? 12 : 6, offset: Offset(0, _isHovered ? 6 : 3))],
                border: Border.all(color: widget.isDark ? Colors.white10 : Colors.transparent),
              ),
              child: Center(child: Icon(widget.icon, size: 32, color: widget.color)),
            ),
            const SizedBox(height: 8),
            Text(widget.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: widget.isDark ? Colors.grey.shade300 : Colors.grey.shade800, fontWeight: _isHovered ? FontWeight.w600 : FontWeight.normal)),
          ]),
        ),
      ),
    );
  }
}