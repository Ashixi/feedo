
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'feed_tab.dart';
import 'search_tab.dart';
import 'compose_screen.dart';
import 'utils/feed_filter_config.dart';
import 'chats_tab.dart';
import 'profile_tab.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _currentIndex = 0;
  
  // Filter states
  String _selectedLanguage = 'all';
  DateTime? _selectedSince;
  final TextEditingController _keywordController = TextEditingController();
  final TextEditingController _globalSearchController = TextEditingController();

  List<Widget> get _tabs => [
    const FeedTab(),
    SearchTab(initialQuery: _globalSearchController.text),
    const ChatsTab(),
    const ProfileTab(),
  ];

  @override
  void initState() {
    super.initState();
    _keywordController.text = globalFeedFilter.value.keywords;
    _selectedLanguage = globalFeedFilter.value.language;
    _selectedSince = globalFeedFilter.value.since;
  }

  void _applyFilters() {
    globalFeedFilter.value = FeedFilterConfig(
      keywords: _keywordController.text.trim(),
      language: _selectedLanguage,
      since: _selectedSince,
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth >= 900) {
          return _buildDesktopLayout();
        } else if (constraints.maxWidth >= 600) {
          return _buildTabletLayout();
        } else {
          return _buildMobileLayout();
        }
      },
    );
  }

  Widget _buildTopBar() {
    return Container(
      height: 70,
      padding: const EdgeInsets.symmetric(horizontal: 32),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Colors.grey.withOpacity(0.15), width: 1)),
      ),
      child: Row(
        children: [
          const Icon(Icons.hub_rounded, size: 36, color: Colors.black87),
          const SizedBox(width: 12),
          const Text('Feedo', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900, letterSpacing: -0.5, color: Colors.black87)),
          const Spacer(),
          // Global Search Bar RESTORED logic
          Container(
            width: 450,
            height: 44,
            decoration: BoxDecoration(
              color: const Color(0xFFF3F4F6),
              borderRadius: BorderRadius.circular(22),
            ),
            child: TextField(
              controller: _globalSearchController,
              onSubmitted: (query) {
                if (query.trim().isNotEmpty) {
                  setState(() {
                    _currentIndex = 1; // 1 is Explore/Search
                  });
                }
              },
              decoration: InputDecoration(
                hintText: 'Search the network...',
                hintStyle: TextStyle(color: Colors.grey.shade500, fontSize: 15),
                prefixIcon: Icon(Icons.search_rounded, size: 22, color: Colors.grey.shade600),
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ),
          const Spacer(),
          // Right Side Actions
          const SizedBox(width: 16),
          const CircleAvatar(
            backgroundColor: Color(0xFFF3F4F6),
            radius: 20,
            child: Icon(Icons.person, color: Colors.grey),
          ),
        ],
      ),
    );
  }

  Widget _buildDesktopLayout() {
    return Scaffold(
      backgroundColor: const Color(0xFFFAFAFA),
      body: Column(
        children: [
          _buildTopBar(),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Minimalist Left Sidebar
                SizedBox(
                  width: 240,
                  child: ListView(
                    padding: const EdgeInsets.only(top: 24, left: 16, right: 24),
                    children: [
                      _buildNavItem(Icons.home_filled, Icons.home_outlined, 'For you', 0),
                      _buildNavItem(Icons.chat_bubble_rounded, Icons.chat_bubble_outline, 'Chats', 2),
                      _buildNavItem(Icons.person_rounded, Icons.person_outline, 'Profile', 3),
                      const SizedBox(height: 32),
                      ElevatedButton(
                        onPressed: () => _openCompose(),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.black87,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          elevation: 0,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        child: const Text('New Post', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                      ),
                    ],
                  ),
                ),
                
                // Center Feed area
                Container(
                  width: 650,
                  margin: const EdgeInsets.only(top: 24, bottom: 24),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(color: Colors.grey.withOpacity(0.2), width: 1),
                    boxShadow: [
                      BoxShadow(color: Colors.black.withOpacity(0.02), blurRadius: 10, offset: const Offset(0, 4)),
                    ],
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(24),
                    child: IndexedStack(
                      index: _currentIndex,
                      children: _tabs,
                    ),
                  ),
                ),
                
                // Right Sidebar (Filters panel, hidden when on Search tab)
                SizedBox(
                  width: 320,
                  child: Padding(
                    padding: const EdgeInsets.only(top: 24, left: 24, right: 16),
                    child: _currentIndex == 0 ? _buildFiltersPanel() : const SizedBox(),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTabletLayout() {
    return Scaffold(
      backgroundColor: const Color(0xFFFAFAFA),
      body: Column(
        children: [
          _buildTopBar(),
          Expanded(
            child: Row(
              children: [
                Container(
                  width: 80,
                  color: Colors.transparent,
                  child: Column(
                    children: [
                      const SizedBox(height: 24),
                      _buildIconNavItem(Icons.home_filled, Icons.home_outlined, 0),
                      _buildIconNavItem(Icons.chat_bubble_rounded, Icons.chat_bubble_outline, 2),
                      _buildIconNavItem(Icons.person_rounded, Icons.person_outline, 3),
                    ],
                  ),
                ),
                Expanded(
                  child: Container(
                    margin: const EdgeInsets.only(top: 24, bottom: 24, right: 24),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(color: Colors.grey.withOpacity(0.2), width: 1),
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(24),
                      child: IndexedStack(
                        index: _currentIndex,
                        children: _tabs,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMobileLayout() {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: Text(['For you', 'Explore', 'Chats', 'Profile'][_currentIndex], style: const TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white,
        elevation: 0,
        foregroundColor: Colors.black,
      ),
      body: IndexedStack(
        index: _currentIndex,
        children: _tabs,
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (idx) => setState(() => _currentIndex = idx),
        type: BottomNavigationBarType.fixed,
        selectedItemColor: Colors.black87,
        unselectedItemColor: Colors.grey.shade400,
        showSelectedLabels: false,
        showUnselectedLabels: false,
        backgroundColor: Colors.white,
        elevation: 10,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home_outlined), activeIcon: Icon(Icons.home_filled), label: 'Home'),
          BottomNavigationBarItem(icon: Icon(Icons.search), activeIcon: Icon(Icons.search_rounded), label: 'Explore'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), activeIcon: Icon(Icons.chat_bubble_rounded), label: 'Chats'),
          BottomNavigationBarItem(icon: Icon(Icons.person_outline), activeIcon: Icon(Icons.person_rounded), label: 'Profile'),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _openCompose(),
        backgroundColor: Colors.black87,
        elevation: 2,
        child: const Icon(Icons.add, color: Colors.white),
      ),
    );
  }

  Widget _buildNavItem(IconData activeIcon, IconData inactiveIcon, String title, int index) {
    final isSelected = _currentIndex == index;
    return InkWell(
      onTap: () => setState(() => _currentIndex = index),
      borderRadius: BorderRadius.circular(12),
      hoverColor: Colors.black.withOpacity(0.04),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            Icon(isSelected ? activeIcon : inactiveIcon, size: 26, color: isSelected ? Colors.black87 : Colors.grey.shade600),
            const SizedBox(width: 16),
            Text(title, style: TextStyle(
              fontSize: 17, 
              fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
              color: isSelected ? Colors.black87 : Colors.grey.shade700,
            )),
          ],
        ),
      ),
    );
  }

  Widget _buildIconNavItem(IconData activeIcon, IconData inactiveIcon, int index) {
    final isSelected = _currentIndex == index;
    return InkWell(
      onTap: () => setState(() => _currentIndex = index),
      borderRadius: BorderRadius.circular(12),
      hoverColor: Colors.black.withOpacity(0.04),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 16),
        child: Icon(isSelected ? activeIcon : inactiveIcon, size: 28, color: isSelected ? Colors.black87 : Colors.grey.shade600),
      ),
    );
  }

  Future<void> _selectDate(BuildContext context) async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: _selectedSince ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: const ColorScheme.light(
              primary: Colors.black87,
              onPrimary: Colors.white,
              onSurface: Colors.black87,
            ),
          ),
          child: child!,
        );
      },
    );
    if (picked != null && picked != _selectedSince) {
      setState(() {
        _selectedSince = picked;
      });
    }
  }

  Widget _buildFiltersPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Search Filters', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Colors.black87)),
        const SizedBox(height: 16),
        // Keywords Filter
        TextField(
          controller: _keywordController,
          decoration: InputDecoration(
            filled: true,
            fillColor: Colors.white,
            hintText: 'Keywords / Phrases',
            prefixIcon: Icon(Icons.filter_alt, size: 18, color: Colors.grey.shade600),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade200)),
            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade200)),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          ),
          onSubmitted: (_) => _applyFilters(),
        ),
        const SizedBox(height: 16),
        // Language Filter
        DropdownButtonFormField<String>(
          value: _selectedLanguage,
          decoration: InputDecoration(
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade200)),
            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade200)),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          ),
          items: const [
            DropdownMenuItem(value: 'all', child: Text('All Languages')),
            DropdownMenuItem(value: 'en', child: Text('English')),
            DropdownMenuItem(value: 'uk', child: Text('Ukrainian')),
          ],
          onChanged: (val) {
            if (val != null) setState(() => _selectedLanguage = val);
          },
        ),
        const SizedBox(height: 16),
        // Date Filter
        InkWell(
          onTap: () => _selectDate(context),
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.grey.shade200),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  _selectedSince == null ? 'Any time' : 'Since: ${DateFormat("MMM d, yyyy").format(_selectedSince!)}',
                  style: const TextStyle(fontSize: 15),
                ),
                Icon(Icons.calendar_today, size: 18, color: Colors.grey.shade600),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        // Clear Date Button if date is selected
        if (_selectedSince != null)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: () => setState(() => _selectedSince = null),
              style: TextButton.styleFrom(foregroundColor: Colors.red),
              child: const Text('Clear Date'),
            ),
          ),
        const SizedBox(height: 24),
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton(
            onPressed: _applyFilters,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.black87,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              elevation: 0,
            ),
            child: const Text('Apply Filters', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
          ),
        ),
      ],
    );
  }

  void _openCompose() {
    showDialog(
      context: context,
      builder: (context) => const ComposeScreen(),
    );
  }
}
