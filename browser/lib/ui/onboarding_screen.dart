import 'package:flutter/material.dart';
import 'package:browser/src/rust/api/wallet.dart';
import '../core/api_client.dart';
import '../main.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _passwordController = TextEditingController();
  final _importController = TextEditingController();
  bool _isLoading = false;
  bool _isImporting = false;

  Future<void> _createWallet() async {
    final password = _passwordController.text;
    if (password.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password must be at least 6 characters')),
      );
      return;
    }

    setState(() => _isLoading = true);
    try {
      await generateWallet();
      // Need a stable path for storage
      final dirPath = 'feedo_wallet'; 
      await encryptAndSaveWallet(password: password, dirPath: dirPath);
      
      final did = await getDid();
      final address = await getAddress();
      
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => MainScreen(
            apiClient: ApiClient(did: did, address: address),
          ),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error creating wallet: $e')),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _importWallet() async {
    final pk = _importController.text;
    final password = _passwordController.text;
    
    if (pk.isEmpty || password.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter valid private key and a password (min 6 chars)')),
      );
      return;
    }

    setState(() => _isLoading = true);
    try {
      await importWallet(privateKeyHex: pk);
      final dirPath = 'feedo_wallet';
      await encryptAndSaveWallet(password: password, dirPath: dirPath);

      final did = await getDid();
      final address = await getAddress();
      
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => MainScreen(
            apiClient: ApiClient(did: did, address: address),
          ),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error importing wallet: $e')),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Container(
          width: 400,
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(Icons.public, size: 64, color: Colors.blue),
              const SizedBox(height: 24),
              const Text(
                'Welcome to Feedo',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              const Text(
                'Create a new Web3 identity or import an existing one to get started.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.grey),
              ),
              const SizedBox(height: 32),
              
              if (_isImporting)
                TextField(
                  controller: _importController,
                  decoration: const InputDecoration(
                    labelText: 'Private Key (Hex)',
                    border: OutlineInputBorder(),
                  ),
                ),
              if (_isImporting) const SizedBox(height: 16),
              
              TextField(
                controller: _passwordController,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: _isImporting ? 'New Password to encrypt wallet' : 'Create a Password',
                  border: const OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 24),
              
              if (_isLoading)
                const Center(child: CircularProgressIndicator())
              else ...[
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  onPressed: _isImporting ? _importWallet : _createWallet,
                  child: Text(_isImporting ? 'Import Identity' : 'Create New Identity'),
                ),
                const SizedBox(height: 16),
                TextButton(
                  onPressed: () {
                    setState(() {
                      _isImporting = !_isImporting;
                    });
                  },
                  child: Text(_isImporting ? 'Or create a new identity' : 'Or import existing identity'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
