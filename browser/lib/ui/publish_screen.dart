import 'package:flutter/material.dart';
import 'dart:io';
import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import 'package:archive/archive.dart';
import '../core/api_client.dart';

class PublishScreen extends StatefulWidget {
  final ApiClient apiClient;

  const PublishScreen({super.key, required this.apiClient});

  @override
  State<PublishScreen> createState() => _PublishScreenState();
}

class _PublishScreenState extends State<PublishScreen> {
  final _domainController = TextEditingController();
  File? _selectedZip;
  bool _isPublishing = false;
  String _status = '';

  List<Map<String, dynamic>> _myDomains = [];

  @override
  void initState() {
    super.initState();
    _loadMyDomains();
  }

  Future<void> _loadMyDomains() async {
    final domains = await widget.apiClient.getMyDomains();
    setState(() {
      _myDomains = domains;
    });
  }

  Future<void> _registerDomain() async {
    final domain = _domainController.text.trim().toLowerCase();
    if (domain.isEmpty) return;
    if (!domain.contains('.')) {
      setState(() => _status = 'Please include a domain extension (e.g. .com, .net, .feedo)');
      return;
    }

    setState(() {
      _isPublishing = true;
      _status = 'Registering domain and generating placeholder...';
    });

    final did = widget.apiClient.did;
    final htmlContent = '''
<!DOCTYPE html>
<html>
<head><title>$domain</title></head>
<body style="font-family: sans-serif; text-align: center; margin-top: 20%; background-color: #f9fafb;">
  <h1 style="color: #111827;">🌐 Домен $domain</h1>
  <p style="color: #4b5563;">Цей домен належить власнику з DID:<br><code style="background: #e5e7eb; padding: 4px 8px; border-radius: 4px; margin-top: 10px; display: inline-block;">$did</code></p>
  <p style="color: #9ca3af; margin-top: 40px;"><em>Powered by Feedo Network</em></p>
</body>
</html>
''';

    final archive = Archive();
    final fileBytes = utf8.encode(htmlContent);
    archive.addFile(ArchiveFile('index.html', fileBytes.length, fileBytes));
    final zipEncoder = ZipEncoder();
    final zipData = zipEncoder.encode(archive);

    final cid = await widget.apiClient.publishToFeedoStorageBytes(zipData, 'site.zip');

    if (cid != null) {
      setState(() => _status = 'Placeholder uploaded! Hash: $cid\nUpdating Consensus...');

      final registered = await widget.apiClient.registerName(domain);
      if (!registered) {
        setState(() {
          _status = 'Failed to register domain name on Consensus Node. Check credits or signature.';
          _isPublishing = false;
        });
        return;
      }
      
      await Future.delayed(const Duration(seconds: 2));
      final updated = await widget.apiClient.updateCid(domain, cid);

      if (updated) {
        await widget.apiClient.saveMyDomain(domain, cid);
        await _loadMyDomains();
        setState(() {
          _status = 'Success! Domain is now yours at feedonet://$domain';
          _isPublishing = false;
          _domainController.clear();
        });
      } else {
        setState(() {
          _status = 'Failed to link CID to domain on Consensus Node';
          _isPublishing = false;
        });
      }
    } else {
      setState(() {
        _status = 'Failed to publish placeholder to Storage';
        _isPublishing = false;
      });
    }
  }

  Future<void> _publish({required Map<String, dynamic> existingSite}) async {
    final domain = existingSite['domain'];
    if (_selectedZip == null) return;

    bool? deleteOld = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Update Site'),
        content: const Text(
          'Do you want to delete the old version from the storage to free up space?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text(
              'Delete Old',
              style: TextStyle(color: Colors.red),
            ),
          ),
        ],
      ),
    );

    if (deleteOld == null) return;

    if (deleteOld) {
      setState(() => _status = 'Deleting old version...');
      await widget.apiClient.unpinSite(
        existingSite['cid'],
      );
    }

    setState(() {
      _isPublishing = true;
      _status = 'Uploading to Feedo P2P Storage...';
    });

    final String? cid = await widget.apiClient.publishToFeedoStorage(_selectedZip!);

    if (cid != null) {
      setState(
        () => _status = 'Site published! Hash: $cid\nUpdating Consensus...',
      );

      final updated = await widget.apiClient.updateCid(domain, cid);

      if (updated) {
        await widget.apiClient.saveMyDomain(domain, cid);
        await _loadMyDomains();
        setState(() {
          _status = 'Success! Site is now live at feedonet://$domain';
          _isPublishing = false;
          _selectedZip = null;
        });
      } else {
        setState(() {
          _status = 'Failed to link CID to domain on Consensus Node';
          _isPublishing = false;
        });
      }
    } else {
      setState(() {
        _status = 'Failed to publish to Storage';
        _isPublishing = false;
      });
    }
  }

  Future<void> _selectZip() async {
    FilePickerResult? result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['zip'],
    );

    if (result != null && result.files.single.path != null) {
      setState(() {
        _selectedZip = File(result.files.single.path!);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Domain Management')),
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Left panel - Manage Domains
          Expanded(
            flex: 1,
            child: Container(
              color: Colors.grey.shade50,
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'My Domains',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 16),
                  if (_myDomains.isEmpty)
                    const Text(
                      'You have not registered any domains yet.',
                      style: TextStyle(color: Colors.grey),
                    ),
                  Expanded(
                    child: ListView.builder(
                      itemCount: _myDomains.length,
                      itemBuilder: (c, i) {
                        final site = _myDomains[i];
                        return Card(
                          margin: const EdgeInsets.only(bottom: 8),
                          child: ListTile(
                            title: Text(site['domain']),
                            subtitle: Text(
                              'Storage: Feedo P2P\nHash: ${site['cid']}',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.upload),
                                  tooltip: 'Upload Website',
                                  onPressed: () {
                                    if (_selectedZip == null) {
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        const SnackBar(
                                          content: Text(
                                            'Please select a zip file first on the right.',
                                          ),
                                        ),
                                      );
                                      return;
                                    }
                                    _publish(existingSite: site);
                                  },
                                ),
                                IconButton(
                                  icon: const Icon(Icons.delete_outline, color: Colors.orange),
                                  tooltip: 'Remove from My Domains',
                                  onPressed: () async {
                                    final confirmed = await showDialog<bool>(
                                      context: context,
                                      builder: (c) => AlertDialog(
                                        title: const Text('Remove Site'),
                                        content: Text('Видалити "${site['domain']}" зі списку? Файли в мережі залишаться, лише запис у браузері буде видалено.'),
                                        actions: [
                                          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Скасувати')),
                                          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Видалити', style: TextStyle(color: Colors.orange))),
                                        ],
                                      ),
                                    );
                                    if (confirmed == true) {
                                      await widget.apiClient.removeMyDomain(site['domain']);
                                      await _loadMyDomains();
                                    }
                                  },
                                ),
                                IconButton(
                                  icon: const Icon(Icons.delete_forever, color: Colors.red),
                                  tooltip: 'Delete from Network',
                                  onPressed: () async {
                                    final confirmed = await showDialog<bool>(
                                      context: context,
                                      builder: (c) => AlertDialog(
                                        title: const Text('Delete from Network'),
                                        content: Text('Ти впевнений, що хочеш повністю видалити "${site['domain']}" з мережі? Це призведе до видалення файлів (unpin) та записів у базі пошуку. Дія незворотна!'),
                                        actions: [
                                          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Скасувати')),
                                          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Видалити', style: TextStyle(color: Colors.red))),
                                        ],
                                      ),
                                    );
                                    if (confirmed == true) {
                                      // Call unpin endpoint (Feedo Storage only, no more IPFS)
                                      final success = await widget.apiClient.unpinSite(site['cid']);
                                      if (success) {
                                        // Update consensus node so the domain no longer points to the cached CID
                                        await widget.apiClient.updateCid(site['domain'], 'DELETED');
                                        
                                        await widget.apiClient.removeMyDomain(site['domain']);
                                        await _loadMyDomains();
                                        if (context.mounted) {
                                          ScaffoldMessenger.of(context).showSnackBar(
                                            const SnackBar(content: Text('Сайт успішно видалено з мережі та з твоїх сайтів!')),
                                          );
                                        }
                                      } else {
                                        if (context.mounted) {
                                          ScaffoldMessenger.of(context).showSnackBar(
                                            const SnackBar(content: Text('Помилка при видаленні з мережі!')),
                                          );
                                        }
                                      }
                                    }
                                  },
                                ),
                              ],
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
          // Right panel - Register New
          Expanded(
            flex: 2,
            child: Center(
              child: Container(
                constraints: const BoxConstraints(maxWidth: 400),
                padding: const EdgeInsets.all(32),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Icon(
                      Icons.dns,
                      size: 64,
                      color: Color(0xFF1A73E8),
                    ),
                    const SizedBox(height: 24),
                    const Text(
                      'Register New Domain',
                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 24),
                    const Text(
                      'Domain Name',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _domainController,
                      decoration: const InputDecoration(
                        hintText: 'e.g. ai.feedo',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 32),
                    ElevatedButton(
                      onPressed: _isPublishing ? null : _registerDomain,
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        backgroundColor: Theme.of(context).colorScheme.primary,
                        foregroundColor: Colors.white,
                      ),
                      child: _isPublishing
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                color: Colors.white,
                                strokeWidth: 2,
                              ),
                            )
                          : const Text(
                              'Register Domain',
                              style: TextStyle(fontSize: 16),
                            ),
                    ),
                    const SizedBox(height: 32),
                    const Divider(),
                    const SizedBox(height: 16),
                    const Text(
                      'Upload Website to Existing Domain',
                      style: TextStyle(fontWeight: FontWeight.bold),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      '1. Select a .zip file containing your website.\n2. Click the Upload icon next to your domain in the left panel.',
                      style: TextStyle(color: Colors.grey, fontSize: 12),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton.icon(
                      icon: const Icon(Icons.folder_zip),
                      label: Text(
                        _selectedZip == null
                            ? 'Select .zip file'
                            : _selectedZip!.path.split('\\').last,
                      ),
                      onPressed: _selectZip,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.white,
                        foregroundColor: Colors.black87,
                      ),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      _status,
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.grey),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
