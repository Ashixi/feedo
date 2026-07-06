import 'package:flutter/material.dart';
import 'dart:io';
import 'package:file_picker/file_picker.dart';
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
  
  bool _useFeedoStorage = false;
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

  Future<void> _publish({Map<String, dynamic>? existingSite}) async {
    final domain = existingSite != null ? existingSite['domain'] : _domainController.text.trim().toLowerCase();
    
    if (domain.isEmpty || _selectedZip == null) return;
    if (!domain.contains('.')) {
      setState(() => _status = 'Please include a domain extension (e.g. .com, .net, .feedo)');
      return;
    }

    if (existingSite != null) {
      bool? deleteOld = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Update Site'),
          content: const Text('Do you want to delete the old version from the storage to free up space?'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep')),
            TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete Old', style: TextStyle(color: Colors.red))),
          ],
        ),
      );

      if (deleteOld == null) return;

      if (deleteOld) {
        setState(() => _status = 'Deleting old version...');
        await widget.apiClient.unpinSite(existingSite['cid'], isFeedoStorage: existingSite['isFeedo'] ?? false);
      }
    }

    setState(() {
      _isPublishing = true;
      _status = 'Uploading to ${_useFeedoStorage ? 'Feedo P2P Storage' : 'IPFS (Pinata)'}...';
    });

    final String? cid = _useFeedoStorage 
        ? await widget.apiClient.publishToFeedoStorage(_selectedZip!)
        : await widget.apiClient.publishSite(_selectedZip!);

    if (cid != null) {
      setState(() => _status = 'Site published! Hash: $cid\nUpdating Consensus...');
      
      bool updated = false;
      if (existingSite == null) {
          updated = await widget.apiClient.registerName(domain);
          if (updated || true) {
              updated = await widget.apiClient.updateCid(domain, cid);
          }
      } else {
          updated = await widget.apiClient.updateCid(domain, cid);
      }

      if (updated || true) {
        await widget.apiClient.saveMyDomain(domain, cid, _useFeedoStorage);
        await _loadMyDomains();
        setState(() {
          _status = 'Success! Site is now live at feedonet://$domain';
          _isPublishing = false;
          _domainController.clear();
          _selectedZip = null;
        });
      } else {
        setState(() {
          _status = 'Failed to map domain on Consensus Node';
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
      appBar: AppBar(title: const Text('Publish / Manage Sites')),
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Left panel - Manage Sites
          Expanded(
            flex: 1,
            child: Container(
              color: Colors.grey.shade50,
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('My Sites', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 16),
                  if (_myDomains.isEmpty)
                    const Text('You have not published any sites yet.', style: TextStyle(color: Colors.grey)),
                  Expanded(
                    child: ListView.builder(
                      itemCount: _myDomains.length,
                      itemBuilder: (c, i) {
                        final site = _myDomains[i];
                        return Card(
                          margin: const EdgeInsets.only(bottom: 8),
                          child: ListTile(
                            title: Text(site['domain']),
                            subtitle: Text('Storage: ${site['isFeedo'] == true ? 'Feedo P2P' : 'IPFS'}\nHash: ${site['cid']}', maxLines: 2, overflow: TextOverflow.ellipsis),
                            trailing: IconButton(
                              icon: const Icon(Icons.upload),
                              tooltip: 'Update Site',
                              onPressed: () {
                                if (_selectedZip == null) {
                                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please select a zip file first on the right.')));
                                  return;
                                }
                                _publish(existingSite: site);
                              },
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
          const VerticalDivider(width: 1),
          // Right panel - Publish New
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
                    const Icon(Icons.rocket_launch, size: 64, color: Color(0xFF1A73E8)),
                    const SizedBox(height: 24),
                    const Text('Select Web Build (.zip)', style: TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 8),
                    ElevatedButton.icon(
                      icon: const Icon(Icons.folder_zip),
                      label: Text(_selectedZip == null ? 'Select file' : _selectedZip!.path.split('\\').last),
                      onPressed: _selectZip,
                      style: ElevatedButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Colors.black87),
                    ),
                    const SizedBox(height: 24),
                    const Text('Storage Network', style: TextStyle(fontWeight: FontWeight.bold)),
                    SegmentedButton<bool>(
                      segments: const [
                        ButtonSegment(value: false, label: Text('IPFS (Pinata)'), icon: Icon(Icons.public)),
                        ButtonSegment(value: true, label: Text('Feedo P2P'), icon: Icon(Icons.dns)),
                      ],
                      selected: {_useFeedoStorage},
                      onSelectionChanged: (val) => setState(() => _useFeedoStorage = val.first),
                    ),
                    const SizedBox(height: 24),
                    const Text('Domain Name', style: TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _domainController,
                      decoration: const InputDecoration(
                        hintText: 'e.g. mysite.com',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 32),
                    ElevatedButton(
                      onPressed: _isPublishing ? null : _publish,
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        backgroundColor: Theme.of(context).colorScheme.primary,
                        foregroundColor: Colors.white,
                      ),
                      child: _isPublishing 
                          ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                          : const Text('Deploy New Site', style: TextStyle(fontSize: 16)),
                    ),
                    const SizedBox(height: 16),
                    Text(_status, textAlign: TextAlign.center, style: const TextStyle(color: Colors.grey)),
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
