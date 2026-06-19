import 'package:flutter/material.dart';
import '../services/auth_service.dart';
import '../main_screen.dart';
import '../nostr_wallet.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final TextEditingController _nsecController = TextEditingController();
  bool _isLoading = false;

  void _navigateToHome() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const MainScreen()),
    );
  }

  Future<void> _generateAccount() async {
    setState(() => _isLoading = true);
    await AuthService.generateNewAccount();
    if (mounted) _navigateToHome();
  }

  Future<void> _loginWithNsec() async {
    final nsec = _nsecController.text.trim();
    if (nsec.isEmpty) return;

    setState(() => _isLoading = true);
    final success = await AuthService.loginWithNsec(nsec);
    if (mounted) {
      if (success) {
        _navigateToHome();
      } else {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Invalid private key')),
        );
      }
    }
  }

  Future<void> _loginWithExtension() async {
    bool available = await NostrWallet.isAvailable();
    if (!available) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Nostr extension not found!')),
      );
      return;
    }
    // We don't have nsec, so we just proceed to Home. 
    // In a real app, you might want a global flag indicating extension auth mode.
    _navigateToHome();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white, // Minimalist light theme (or simple dark)
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(Icons.hub, size: 64, color: Colors.black87),
              const SizedBox(height: 24),
              const Text(
                'Join the network.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w900,
                  color: Colors.black87,
                ),
              ),
              const SizedBox(height: 48),
              ElevatedButton(
                onPressed: _isLoading ? null : _generateAccount,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.black87,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(30)),
                ),
                child: _isLoading 
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white))
                    : const Text('Create Account', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  const Expanded(child: Divider()),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16.0),
                    child: Text('or', style: TextStyle(color: Colors.grey[600])),
                  ),
                  const Expanded(child: Divider()),
                ],
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _nsecController,
                obscureText: true,
                style: const TextStyle(color: Colors.black87),
                decoration: InputDecoration(
                  hintText: 'Private Key (nsec)',
                  hintStyle: TextStyle(color: Colors.grey[400]),
                  filled: true,
                  fillColor: Colors.grey[100],
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(30),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                ),
              ),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: _isLoading ? null : _loginWithNsec,
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.black87,
                  side: const BorderSide(color: Colors.black26),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(30)),
                ),
                child: const Text('Log in', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              ),
              const SizedBox(height: 24),
              TextButton(
                onPressed: _loginWithExtension,
                child: const Text('Log in with Browser Extension (Alby)'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
