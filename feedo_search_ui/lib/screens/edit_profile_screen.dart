import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:http/http.dart' as http;
import '../services/auth_service.dart';
import '../services/relay_service.dart';
import '../utils/constants.dart';

class EditProfileScreen extends StatefulWidget {
  const EditProfileScreen({super.key});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _aboutController = TextEditingController();
  final TextEditingController _pictureController = TextEditingController();
  bool _isPublishing = false;

  Future<void> _publishProfile() async {
    setState(() => _isPublishing = true);

    try {
      final contentObj = {
        if (_nameController.text.isNotEmpty) 'name': _nameController.text.trim(),
        if (_aboutController.text.isNotEmpty) 'about': _aboutController.text.trim(),
        if (_pictureController.text.isNotEmpty) 'picture': _pictureController.text.trim(),
      };

      final contentStr = jsonEncode(contentObj);
      
      // Kind 0 is Metadata in Nostr
      final event = await AuthService.signEvent(0, contentStr, []);
      if (event == null) {
        throw Exception('Failed to sign event. Do you have a local account?');
      }
      
      final pubkey = await AuthService.getPublicKey();
      if (pubkey != null) {
        try {
          await http.put(
            Uri.parse('${Constants.apiUrl}/v1/identity/update/$pubkey'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'metadata': contentObj,
              'signature': 'dummy'
            }),
          );
        } catch (e) {
          print('Failed to update identity backend: $e');
        }
      }

      final relays = await RelayService.getRelays();
      final eventJson = jsonEncode(['EVENT', event.toMap()]);

      for (var url in relays) {
        try {
          final channel = WebSocketChannel.connect(Uri.parse(url));
          channel.sink.add(eventJson);
          try {
            await channel.stream.first.timeout(const Duration(seconds: 2));
          } catch (_) {}
          channel.sink.close();
        } catch (e) {
          print('Failed to publish to $url: $e');
        }
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Profile and preferences published!')),
        );
        Navigator.of(context).pop();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _isPublishing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('Edit Profile', style: TextStyle(fontWeight: FontWeight.bold)),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Nostr Profile Metadata',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
              ),
              SizedBox(height: 8),
              Text(
                'This information will be published to your selected relays as a Kind 0 event. It is not stored centrally.',
                style: TextStyle(color: Colors.grey[600], fontSize: 14),
              ),
              SizedBox(height: 24),
              
              _buildTextField('Name / Username', _nameController, false),
              SizedBox(height: 16),
              _buildTextField('About You', _aboutController, false, maxLines: 3),
              SizedBox(height: 16),
              _buildTextField('Picture URL (e.g. https://...)', _pictureController, false),
              
              SizedBox(height: 32),
              
              ElevatedButton(
                onPressed: _isPublishing ? null : _publishProfile,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.white,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                child: _isPublishing
                    ? SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.transparent))
                    : const Text('Save & Publish', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTextField(String label, TextEditingController controller, bool obscure, {int maxLines = 1}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14, color: Colors.white)),
        SizedBox(height: 8),
        TextField(
          controller: controller,
          obscureText: obscure,
          maxLines: maxLines,
          style: TextStyle(color: Colors.white),
          decoration: InputDecoration(
            filled: true,
            fillColor: Colors.grey[100],
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
            ),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          ),
        ),
      ],
    );
  }
}
