import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'services/auth_service.dart';
import 'screens/relay_settings_screen.dart';
import 'screens/edit_profile_screen.dart';
import 'screens/login_screen.dart';
import 'nostr_resolver.dart';
import 'services/relay_service.dart';

class ProfileTab extends StatefulWidget {
  const ProfileTab({super.key});

  @override
  State<ProfileTab> createState() => _ProfileTabState();
}

class _ProfileTabState extends State<ProfileTab> {
  String? _pubkey;
  String _authorName = 'My Nostr Account';
  String? _authorAvatar;

  @override
  void initState() {
    super.initState();
    _loadKey();
  }

  Future<void> _loadKey() async {
    final key = await AuthService.getPublicKey();
    if (key != null) {
      final relays = await RelayService.getRelays();
      final Map<String, dynamic> mockItem = {
        'author_address': key,
        'relay_urls': relays,
        'hash_id': '0000000000000000000000000000000000000000000000000000000000000000',
        'item_type': 'profile',
      };
      await NostrResolver.resolve([mockItem]);
      if (mounted) {
        setState(() {
          _pubkey = key;
          _authorName = mockItem['author_name'] ?? 'My Nostr Account';
          _authorAvatar = mockItem['author_avatar'];
        });
      }
    }
  }

  void _copyToClipboard(String text) {
    Clipboard.setData(ClipboardData(text: text));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Copied to clipboard!')),
    );
  }

  Future<void> _logout() async {
    await AuthService.logout();
    if (mounted) {
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.grey[50],
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // User Card
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 4)),
                  ],
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      radius: 30,
                      backgroundColor: Colors.blueAccent.withOpacity(0.1),
                      backgroundImage: _authorAvatar != null ? NetworkImage(_authorAvatar!) : null,
                      child: _authorAvatar == null ? const Icon(Icons.person, size: 30, color: Colors.blueAccent) : null,
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(_authorName, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.black87)),
                          const SizedBox(height: 4),
                          if (_pubkey != null)
                            GestureDetector(
                              onTap: () => _copyToClipboard(_pubkey!),
                              child: Row(
                                children: [
                                  Text(
                                    '${_pubkey!.substring(0, 8)}...${_pubkey!.substring(_pubkey!.length - 8)}',
                                    style: TextStyle(color: Colors.grey[600], fontSize: 14),
                                  ),
                                  const SizedBox(width: 4),
                                  Icon(Icons.copy, size: 14, color: Colors.grey[400]),
                                ],
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              const Text('Account', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.black54)),
              const SizedBox(height: 8),
              
              _buildSettingsTile(
                icon: Icons.edit_note,
                title: 'Edit Profile',
                subtitle: 'Publish your Name and Avatar to relays',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EditProfileScreen())),
              ),
              
              _buildSettingsTile(
                icon: Icons.key,
                title: 'Show Private Key',
                subtitle: 'Backup your nsec (Do not share this!)',
                onTap: () async {
                  final nsec = await AuthService.getPrivateKey();
                  if (nsec != null && mounted) {
                    showDialog(
                      context: context,
                      builder: (_) => AlertDialog(
                        title: const Text('Your Private Key'),
                        content: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Save this key somewhere safe. If you lose it, you will lose your account forever.', style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold)),
                            const SizedBox(height: 16),
                            SelectableText(nsec, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                          ],
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.of(context).pop(),
                            child: const Text('Close'),
                          ),
                          ElevatedButton(
                            onPressed: () {
                              _copyToClipboard(nsec);
                              Navigator.of(context).pop();
                            },
                            child: const Text('Copy'),
                          )
                        ],
                      )
                    );
                  } else {
                     ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No private key found')));
                  }
                },
              ),

              const SizedBox(height: 24),
              const Text('Network', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.black54)),
              const SizedBox(height: 8),

              _buildSettingsTile(
                icon: Icons.storage,
                title: 'Manage Relays',
                subtitle: 'Choose where your data is stored',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const RelaySettingsScreen())),
              ),

              const SizedBox(height: 40),
              SizedBox(
                width: double.infinity,
                child: TextButton(
                  onPressed: _logout,
                  style: TextButton.styleFrom(foregroundColor: Colors.redAccent, padding: const EdgeInsets.symmetric(vertical: 16)),
                  child: const Text('Log Out', style: TextStyle(fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSettingsTile({required IconData icon, required String title, required String subtitle, required VoidCallback onTap, Widget? trailing}) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey[200]!),
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: ListTile(
          leading: Icon(icon, color: Colors.black87),
          title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600, color: Colors.black87)),
          subtitle: Text(subtitle, style: TextStyle(color: Colors.grey[600], fontSize: 12)),
          trailing: trailing ?? const Icon(Icons.chevron_right, color: Colors.grey),
          onTap: onTap,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
    );
  }
}
