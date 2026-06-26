import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import '../services/auth_service.dart';
import 'package:dart_nostr/dart_nostr.dart';
import '../main_screen.dart'; // We'll need to route to main screen on success

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final TextEditingController _keyController = TextEditingController();
  bool _isLoading = false;

  void _navigateToMain() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (context) => const MainScreen()),
    );
  }

  Future<void> _loginWithExtension() async {
    setState(() => _isLoading = true);
    final success = await AuthService.loginWithExtension();
    setState(() => _isLoading = false);
    
    if (success) {
      _navigateToMain();
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not find Nostr extension. Are you using Alby/nos2x?')),
        );
      }
    }
  }

  Future<void> _loginWithNsec() async {
    final text = _keyController.text.trim();
    if (text.isEmpty) return;
    
    if (!text.startsWith('nsec')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid key format. Must start with nsec')),
      );
      return;
    }

    setState(() => _isLoading = true);
    final success = await AuthService.loginWithNsec(text);
    setState(() => _isLoading = false);

    if (success) {
      _navigateToMain();
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Invalid nsec key')),
        );
      }
    }
  }

  Future<void> _generateNewAccount() async {
    setState(() => _isLoading = true);
    final pubkey = await AuthService.generateNewAccount();
    setState(() => _isLoading = false);
    
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('New account generated! Please backup your key later.')),
      );
      _navigateToMain();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.hub, size: 80, color: Colors.purpleAccent),
                const SizedBox(height: 16),
                const Text(
                  'Welcome to Feedo',
                  style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.black87),
                ),
                const SizedBox(height: 8),
                const Text(
                  'The Unified Semantic Layer for Web4',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 16, color: Colors.black54),
                ),
                const SizedBox(height: 48),
                
                if (kIsWeb) ...[
                  ElevatedButton.icon(
                    onPressed: _isLoading ? null : _loginWithExtension,
                    icon: const Icon(Icons.extension),
                    label: const Text('Login with Browser Extension'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.purpleAccent,
                      foregroundColor: Colors.white,
                      minimumSize: const Size(double.infinity, 50),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(25)),
                    ),
                  ),
                  const SizedBox(height: 24),
                  const Text('OR', style: TextStyle(color: Colors.black54, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 24),
                ],
                
                TextField(
                  controller: _keyController,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: 'Private Key (nsec)',
                    hintText: 'nsec1...',
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
                    prefixIcon: const Icon(Icons.vpn_key),
                  ),
                ),
                const SizedBox(height: 16),
                ElevatedButton(
                  onPressed: _isLoading ? null : _loginWithNsec,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.black87,
                    foregroundColor: Colors.white,
                    minimumSize: const Size(double.infinity, 50),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(25)),
                  ),
                  child: _isLoading 
                    ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(color: Colors.white))
                    : const Text('Login with Key', style: TextStyle(fontSize: 16)),
                ),
                const SizedBox(height: 24),
                TextButton(
                  onPressed: _isLoading ? null : _generateNewAccount,
                  child: const Text('Create New Account', style: TextStyle(color: Colors.purpleAccent, fontSize: 16)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
