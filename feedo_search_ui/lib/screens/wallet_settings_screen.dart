import 'package:flutter/material.dart';
import '../services/nwc_service.dart';

class WalletSettingsScreen extends StatefulWidget {
  const WalletSettingsScreen({super.key});

  @override
  State<WalletSettingsScreen> createState() => _WalletSettingsScreenState();
}

class _WalletSettingsScreenState extends State<WalletSettingsScreen> {
  final TextEditingController _urlController = TextEditingController();
  bool _isConnected = false;

  @override
  void initState() {
    super.initState();
    _checkStatus();
  }

  Future<void> _checkStatus() async {
    final connected = await NwcService.hasWallet();
    setState(() => _isConnected = connected);
  }

  Future<void> _connect() async {
    final url = _urlController.text.trim();
    if (url.isEmpty || !url.startsWith('nostr+walletconnect://')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid NWC URL')),
      );
      return;
    }
    await NwcService.saveNwcUrl(url);
    _urlController.clear();
    await _checkStatus();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Wallet Connected!')),
      );
    }
  }

  Future<void> _disconnect() async {
    await NwcService.disconnect();
    await _checkStatus();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Wallet Settings')),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Nostr Wallet Connect (NWC)',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              'Link your Lightning Wallet (e.g. Alby, Mutiny) to enable 1-tap Zaps natively in Feedo.',
              style: TextStyle(color: Colors.black54),
            ),
            const SizedBox(height: 24),
            if (_isConnected) ...[
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.green.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.green),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.check_circle, color: Colors.green),
                    SizedBox(width: 12),
                    Text('Wallet Connected', style: TextStyle(color: Colors.green, fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: _disconnect,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.redAccent,
                  foregroundColor: Colors.white,
                ),
                child: const Text('Disconnect Wallet'),
              ),
            ] else ...[
              TextField(
                controller: _urlController,
                decoration: const InputDecoration(
                  labelText: 'NWC Connection URI',
                  hintText: 'nostr+walletconnect://...',
                  border: OutlineInputBorder(),
                ),
                maxLines: 3,
                minLines: 1,
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: _connect,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.purpleAccent,
                  foregroundColor: Colors.white,
                  minimumSize: const Size(double.infinity, 50),
                ),
                child: const Text('Connect Wallet'),
              ),
            ]
          ],
        ),
      ),
    );
  }
}
