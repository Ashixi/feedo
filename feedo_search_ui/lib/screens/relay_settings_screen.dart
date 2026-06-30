import 'package:flutter/material.dart';
import '../services/relay_service.dart';

class RelaySettingsScreen extends StatefulWidget {
  const RelaySettingsScreen({super.key});

  @override
  State<RelaySettingsScreen> createState() => _RelaySettingsScreenState();
}

class _RelaySettingsScreenState extends State<RelaySettingsScreen> {
  final TextEditingController _relayController = TextEditingController();
  List<String> _relays = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadRelays();
  }

  Future<void> _loadRelays() async {
    final relays = await RelayService.getRelays();
    setState(() {
      _relays = relays;
      _isLoading = false;
    });
  }

  Future<void> _addRelay() async {
    final url = _relayController.text.trim();
    if (url.isNotEmpty && url.startsWith('wss://')) {
      await RelayService.addRelay(url);
      _relayController.clear();
      _loadRelays();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid URL. Must start with wss://')),
      );
    }
  }

  Future<void> _removeRelay(String url) async {
    await RelayService.removeRelay(url);
    _loadRelays();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('Manage Relays', style: TextStyle(fontWeight: FontWeight.bold)),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Nostr Relays',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
              ),
              SizedBox(height: 8),
              Text(
                'These are the servers where your profile data and posts will be published.',
                style: TextStyle(color: Colors.grey[600], fontSize: 14),
              ),
              SizedBox(height: 24),
              
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _relayController,
                      style: TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'wss://relay.example.com',
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        filled: true,
                        fillColor: Colors.grey[100],
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                      ),
                    ),
                  ),
                  SizedBox(width: 12),
                  ElevatedButton(
                    onPressed: _addRelay,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.white,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 20),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    child: const Text('Add'),
                  ),
                ],
              ),
              
              SizedBox(height: 32),
              
              Expanded(
                child: _isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : ListView.builder(
                        itemCount: _relays.length,
                        itemBuilder: (context, index) {
                          final relay = _relays[index];
                          return Container(
                            margin: const EdgeInsets.only(bottom: 12),
                            decoration: BoxDecoration(
                              color: Colors.grey[50],
                              border: Border.all(color: Colors.grey[200]!),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Material(
                              color: Colors.transparent,
                              borderRadius: BorderRadius.circular(12),
                              child: ListTile(
                                leading: Icon(Icons.storage, color: Colors.grey.shade400),
                                title: Text(relay, style: TextStyle(fontWeight: FontWeight.w500)),
                                trailing: IconButton(
                                  icon: Icon(Icons.delete_outline, color: Colors.redAccent),
                                  onPressed: () => _removeRelay(relay),
                                ),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                              ),
                            ),
                          );
                        },
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
