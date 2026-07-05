import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../services/auth_service.dart';
import '../utils/constants.dart';

class FeedPreferencesScreen extends StatefulWidget {
  const FeedPreferencesScreen({super.key});

  @override
  State<FeedPreferencesScreen> createState() => _FeedPreferencesScreenState();
}

class _FeedPreferencesScreenState extends State<FeedPreferencesScreen> {
  final TextEditingController _tagController = TextEditingController();
  final TextEditingController _languageController = TextEditingController();
  
  List<String> _tags = [];
  List<String> _languages = [];
  bool _isLoading = true;
  bool _isSaving = false;
  String? _myPubkey;

  @override
  void initState() {
    super.initState();
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    _myPubkey = await AuthService.getPublicKey();
    if (_myPubkey != null) {
      try {
        final res = await http.get(Uri.parse('${Constants.apiUrl}/v1/identity/$_myPubkey'));
        if (res.statusCode == 200) {
          final data = jsonDecode(res.body);
          setState(() {
            _tags = List<String>.from(data['preferred_tags'] ?? []);
            _languages = List<String>.from(data['preferred_languages'] ?? []);
          });
        }
      } catch (e) {
        print('Error loading preferences: $e');
      }
    }
    setState(() => _isLoading = false);
  }

  Future<void> _savePreferences() async {
    if (_myPubkey == null) return;
    setState(() => _isSaving = true);
    try {
      await http.put(
        Uri.parse('${Constants.apiUrl}/v1/identity/update/$_myPubkey'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'metadata': {
            'preferred_tags': _tags,
            'preferred_languages': _languages,
          },
          'signature': 'dummy'
        }),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Preferences saved!')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error saving preferences: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  void _addTag(String value) {
    final tag = value.trim().toLowerCase();
    if (tag.isNotEmpty && !_tags.contains(tag)) {
      setState(() {
        _tags.add(tag);
        _tagController.clear();
      });
      _savePreferences();
    }
  }

  void _addLanguage(String value) {
    final lang = value.trim().toLowerCase();
    if (lang.isNotEmpty && !_languages.contains(lang)) {
      setState(() {
        _languages.add(lang);
        _languageController.clear();
      });
      _savePreferences();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('Feed Preferences', style: TextStyle(fontWeight: FontWeight.bold)),
      ),
      body: _isLoading 
        ? const Center(child: CircularProgressIndicator())
        : SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Customize Your Feed',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white),
                ),
                SizedBox(height: 8),
                Text(
                  'Help the algorithm suggest the best posts for you. These settings sync across all your devices.',
                  style: TextStyle(color: Colors.grey[600], fontSize: 14),
                ),
                
                SizedBox(height: 32),
                
                // --- Preferred Tags ---
                const Text('Preferred Topics / Tags', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _tags.map((tag) => Chip(
                    label: Text(tag),
                    onDeleted: () {
                      setState(() => _tags.remove(tag));
                      _savePreferences();
                    },
                    backgroundColor: Colors.blue.withOpacity(0.1),
                    deleteIconColor: Colors.blue,
                  )).toList(),
                ),
                SizedBox(height: 12),
                TextField(
                  controller: _tagController,
                  decoration: InputDecoration(
                    hintText: 'Type a topic and press Enter...',
                    filled: true,
                    fillColor: Colors.grey[100],
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                    suffixIcon: IconButton(
                      icon: Icon(Icons.add_circle, color: Colors.blue),
                      onPressed: () => _addTag(_tagController.text),
                    ),
                  ),
                  onSubmitted: _addTag,
                ),

                SizedBox(height: 32),

                // --- Preferred Languages ---
                const Text('Preferred Languages', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _languages.map((lang) => Chip(
                    label: Text(lang),
                    onDeleted: () {
                      setState(() => _languages.remove(lang));
                      _savePreferences();
                    },
                    backgroundColor: Colors.green.withOpacity(0.1),
                    deleteIconColor: Colors.green,
                  )).toList(),
                ),
                SizedBox(height: 12),
                Autocomplete<String>(
                  optionsBuilder: (TextEditingValue textEditingValue) {
                    if (textEditingValue.text.isEmpty) {
                      return const Iterable<String>.empty();
                    }
                    final knownLangs = [
                      'ukrainian', 'english', 'spanish', 'french', 
                      'german', 'italian', 'polish', 'portuguese', 
                      'japanese', 'chinese', 'korean', 'arabic', 
                      'hindi', 'turkish'
                    ];
                    final query = textEditingValue.text.toLowerCase();
                    final matches = knownLangs.where((lang) => lang.contains(query)).toList();
                    if (matches.isEmpty && query.isNotEmpty) {
                      return [query]; // Allow adding custom if not in list
                    }
                    return matches;
                  },
                  onSelected: (String selection) {
                    _addLanguage(selection);
                  },
                  fieldViewBuilder: (context, controller, focusNode, onFieldSubmitted) {
                    return TextField(
                      controller: controller,
                      focusNode: focusNode,
                      decoration: InputDecoration(
                        hintText: 'Type a language (e.g. ukrainian)...',
                        filled: true,
                        fillColor: Colors.grey[100],
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                        suffixIcon: IconButton(
                          icon: Icon(Icons.add_circle, color: Colors.green),
                          onPressed: () {
                            if (controller.text.isNotEmpty) {
                              _addLanguage(controller.text);
                              controller.clear();
                            }
                          },
                        ),
                      ),
                      onSubmitted: (value) {
                        _addLanguage(value);
                        controller.clear();
                      },
                    );
                  },
                ),
                
                SizedBox(height: 40),
                if (_isSaving)
                   const Center(child: CircularProgressIndicator())
              ],
            ),
          ),
    );
  }
}
