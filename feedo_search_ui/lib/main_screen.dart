import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'feed_tab.dart';
import 'search_tab.dart';
import 'profile_tab.dart';
import 'chats_tab.dart';
import 'compose_screen.dart';
import 'utils/feed_filter_config.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _currentIndex = 0;

  final List<Widget> _tabs = [
    const FeedTab(),
    const SearchTab(),
    const ChatsTab(),
    const ProfileTab(),
  ];

  final TextEditingController _keywordController = TextEditingController();
  String _selectedLanguage = 'all';
  DateTime? _selectedSince;
  DateTime? _selectedUntil;

  @override
  void initState() {
    super.initState();
    // Initialize filter UI from global state
    _keywordController.text = globalFeedFilter.value.keywords;
    _selectedLanguage = globalFeedFilter.value.language;
    _selectedSince = globalFeedFilter.value.since;
    _selectedUntil = globalFeedFilter.value.until;
  }

  @override
  void dispose() {
    _keywordController.dispose();
    super.dispose();
  }

  void _applyFilters(BuildContext context) {
    globalFeedFilter.value = FeedFilterConfig(
      keywords: _keywordController.text.trim(),
      language: _selectedLanguage,
      since: _selectedSince,
      until: _selectedUntil,
    );
    Navigator.pop(context); // Close the drawer
    
    // Switch to feed tab to see results
    if (_currentIndex != 0) {
      setState(() {
        _currentIndex = 0;
      });
    }
  }

  Future<void> _selectDate(BuildContext context, bool isSince) async {
    final initialDate = isSince ? (_selectedSince ?? DateTime.now()) : (_selectedUntil ?? DateTime.now());
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: initialDate,
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 1)),
    );
    if (picked != null) {
      setState(() {
        if (isSince) {
          _selectedSince = picked;
        } else {
          _selectedUntil = picked;
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(['Feed', 'Search', 'Chats', 'Profile'][_currentIndex], style: const TextStyle(fontWeight: FontWeight.bold)),
        // The Drawer hamburger menu is automatically added here
      ),
      drawer: _buildDrawer(),
      body: IndexedStack(
        index: _currentIndex,
        children: _tabs,
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          showModalBottomSheet(
            context: context,
            isScrollControlled: true,
            backgroundColor: Colors.transparent,
            builder: (context) => const ComposeScreen(),
          );
        },
        icon: const Icon(Icons.edit, color: Colors.white),
        label: const Text('Post', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 4,
      ),
    );
  }

  Widget _buildDrawer() {
    return Drawer(
      child: SafeArea(
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.all(16.0),
              alignment: Alignment.centerLeft,
              child: const Text(
                'Menu',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
              ),
            ),
            const Divider(),
            _buildNavTile(Icons.home, 'Feed', 0),
            _buildNavTile(Icons.search, 'Search', 1),
            _buildNavTile(Icons.forum, 'Chats', 2),
            _buildNavTile(Icons.person, 'Profile', 3),
            
            const Divider(),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Feed Filters', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.black87)),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _keywordController,
                      decoration: InputDecoration(
                        labelText: 'Keywords / Phrases',
                        prefixIcon: const Icon(Icons.search),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        isDense: true,
                      ),
                    ),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                      value: _selectedLanguage,
                      decoration: InputDecoration(
                        labelText: 'Language',
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        isDense: true,
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
                    Row(
                      children: [
                        Expanded(
                          child: InkWell(
                            onTap: () => _selectDate(context, true),
                            child: InputDecorator(
                              decoration: InputDecoration(
                                labelText: 'Since',
                                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                                isDense: true,
                              ),
                              child: Text(
                                _selectedSince != null ? DateFormat('yyyy-MM-dd').format(_selectedSince!) : 'Select Date',
                                style: TextStyle(color: _selectedSince != null ? Colors.black87 : Colors.grey),
                              ),
                            ),
                          ),
                        ),
                        if (_selectedSince != null)
                          IconButton(
                            icon: const Icon(Icons.clear, size: 20),
                            onPressed: () => setState(() => _selectedSince = null),
                          ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: InkWell(
                            onTap: () => _selectDate(context, false),
                            child: InputDecorator(
                              decoration: InputDecoration(
                                labelText: 'Until',
                                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                                isDense: true,
                              ),
                              child: Text(
                                _selectedUntil != null ? DateFormat('yyyy-MM-dd').format(_selectedUntil!) : 'Select Date',
                                style: TextStyle(color: _selectedUntil != null ? Colors.black87 : Colors.grey),
                              ),
                            ),
                          ),
                        ),
                        if (_selectedUntil != null)
                          IconButton(
                            icon: const Icon(Icons.clear, size: 20),
                            onPressed: () => setState(() => _selectedUntil = null),
                          ),
                      ],
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: ElevatedButton(
                        onPressed: () => _applyFilters(context),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Theme.of(context).colorScheme.primary,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        child: const Text('Apply Filters', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNavTile(IconData icon, String title, int index) {
    final isSelected = _currentIndex == index;
    return ListTile(
      leading: Icon(icon, color: isSelected ? Theme.of(context).colorScheme.primary : Colors.grey[700]),
      title: Text(title, style: TextStyle(fontWeight: isSelected ? FontWeight.bold : FontWeight.normal, color: isSelected ? Theme.of(context).colorScheme.primary : Colors.black87)),
      selected: isSelected,
      onTap: () {
        setState(() {
          _currentIndex = index;
        });
        Navigator.pop(context); // Close the drawer
      },
    );
  }
}
