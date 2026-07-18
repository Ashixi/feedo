import 'package:flutter/material.dart';
import 'dart:io';
import 'dart:convert';
import 'dart:async';
import 'package:file_picker/file_picker.dart';
import 'package:archive/archive.dart';
import '../core/api_client.dart';

/// Returned via Navigator.pop when the user wants to open a domain in a new tab.
class OpenDomainAction {
  final String url;
  OpenDomainAction(this.url);
}

class DomainsScreen extends StatefulWidget {
  final ApiClient apiClient;

  const DomainsScreen({super.key, required this.apiClient});

  @override
  State<DomainsScreen> createState() => _DomainsScreenState();
}

class _DomainsScreenState extends State<DomainsScreen> {
  List<Map<String, dynamic>> _domains = [];
  bool _isLoading = true;
  String? _errorMessage;
  int? _balance;
  File? _selectedZip;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      // Fetch from network first
      final networkDomains = await widget.apiClient.fetchMyDomainsFromNetwork();
      final balance = await widget.apiClient.getBalance();

      // Also merge local cache for domains that may not yet be synced
      final localDomains = await widget.apiClient.getMyDomains();
      final Map<String, Map<String, dynamic>> domainMap = {};

      // Add network domains first (authoritative)
      for (final d in networkDomains) {
        final name = d['domain']?.toString() ?? '';
        if (name.isNotEmpty) {
          domainMap[name] = d;
        }
      }

      // Merge local domains
      for (final d in localDomains) {
        final name = d['domain']?.toString() ?? '';
        if (name.isNotEmpty && !domainMap.containsKey(name)) {
          domainMap[name] = d;
        }
      }

      if (mounted) {
        setState(() {
          _domains = domainMap.values.toList();
          _balance = balance;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = 'Failed to load domains: $e';
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _registerDomain() async {
    final domainController = TextEditingController();
    // ValueNotifiers гарантують що колбеки завжди читають актуальне значення.
    final selectedZipNotifier = ValueNotifier<File?>(null);
    final statusNotifier = ValueNotifier<String?>(null);

    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setSheetState) {
            return Container(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(ctx).size.height * 0.8,
              ),
              decoration: BoxDecoration(
                color: Theme.of(ctx).scaffoldBackgroundColor,
                borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
              ),
              padding: EdgeInsets.only(
                left: 24,
                right: 24,
                top: 16,
                bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Center(
                      child: Container(
                        width: 40,
                        height: 4,
                        decoration: BoxDecoration(
                          color: Colors.grey.shade400,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    const Text(
                      'Register New Domain',
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Enter a domain name. If you select a ZIP file, it will be uploaded immediately. Otherwise, a placeholder page will be created.',
                      style: TextStyle(color: Colors.grey, fontSize: 13),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 24),
                    TextField(
                      controller: domainController,
                      autofocus: true,
                      decoration: const InputDecoration(
                        labelText: 'Domain Name',
                        hintText: 'e.g. my-site.feedo',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      icon: const Icon(Icons.folder_zip),
                      label: ValueListenableBuilder<File?>(
                        valueListenable: selectedZipNotifier,
                        builder: (_, zip, __) => Text(
                          zip == null
                              ? 'Select .zip file (optional)'
                              : zip.path.split('\\').last,
                        ),
                      ),
                      onPressed: () async {
                        final pickResult = await FilePicker.pickFiles(
                          type: FileType.custom,
                          allowedExtensions: ['zip'],
                        );
                        if (pickResult != null && pickResult.files.single.path != null) {
                          selectedZipNotifier.value = File(pickResult.files.single.path!);
                          setSheetState(() {}); // rebuild
                        }
                      },
                    ),
                    const SizedBox(height: 24),
                    ValueListenableBuilder<String?>(
                      valueListenable: statusNotifier,
                      builder: (_, status, __) {
                        if (status == null) return const SizedBox.shrink();
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Text(
                            status,
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: status.startsWith('Success') ? Colors.green : Colors.orange,
                              fontSize: 13,
                            ),
                          ),
                        );
                      },
                    ),
                    ValueListenableBuilder<String?>(
                      valueListenable: statusNotifier,
                      builder: (_, status, __) {
                        return ElevatedButton(
                          onPressed: status != null
                              ? null
                              : () async {
                                  final domain = domainController.text.trim().toLowerCase();
                                  if (domain.isEmpty) {
                                    statusNotifier.value = 'Please enter a domain name';
                                    setSheetState(() {});
                                    return;
                                  }
                                  if (!domain.contains('.')) {
                                    statusNotifier.value = 'Please include a domain extension';
                                    setSheetState(() {});
                                    return;
                                  }

                                  statusNotifier.value = 'Registering domain...';
                                  setSheetState(() {});

                                  // Upload content (ZIP or placeholder)
                                  String? cid;
                                  final selectedZip = selectedZipNotifier.value;
                                  if (selectedZip != null) {
                                    cid = await widget.apiClient.publishToFeedoStorage(selectedZip);
                                  } else {
                                    // Generate placeholder HTML
                                    final did = widget.apiClient.did;
                                    final htmlContent = '''
<!DOCTYPE html>
<html>
<head><title>$domain</title></head>
<body style="font-family: sans-serif; text-align: center; margin-top: 20%; background-color: #f9fafb;">
  <h1 style="color: #111827;">  Domain $domain</h1>
  <p style="color: #4b5563;">This domain is owned by DID:<br><code style="background: #e5e7eb; padding: 4px 8px; border-radius: 4px; margin-top: 10px; display: inline-block;">$did</code></p>
  <p style="color: #9ca3af; margin-top: 40px;"><em>Powered by Feedo Network</em></p>
</body>
</html>
''';
                                    final archive = Archive();
                                    final fileBytes = utf8.encode(htmlContent);
                                    archive.addFile(ArchiveFile('index.html', fileBytes.length, fileBytes));
                                    final zipEncoder = ZipEncoder();
                                    final zipData = zipEncoder.encode(archive);
                                    cid = await widget.apiClient.publishToFeedoStorageBytes(zipData, 'site.zip');
                                  }

                                  if (cid == null) {
                                    statusNotifier.value = 'Failed to upload to storage';
                                    setSheetState(() {});
                                    return;
                                  }

                                  statusNotifier.value = 'Uploaded! Registering name...';
                                  setSheetState(() {});

                                  final registered = await widget.apiClient.registerName(domain);
                                  if (!registered) {
                                    statusNotifier.value = 'Failed to register domain. Check credits.';
                                    setSheetState(() {});
                                    return;
                                  }

                                  await Future.delayed(const Duration(seconds: 2));
                                  final updated = await widget.apiClient.updateCid(domain, cid);
                                  if (updated) {
                                    await widget.apiClient.saveMyDomain(domain, cid);
                                    statusNotifier.value = 'Success! Domain $domain is now yours.';
                                    setSheetState(() {});
                                    await Future.delayed(const Duration(seconds: 1));
                                    if (ctx.mounted) Navigator.pop(ctx, domain);
                                  } else {
                                    statusNotifier.value = 'Failed to link CID to domain';
                                    setSheetState(() {});
                                  }
                                },
                          style: ElevatedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            backgroundColor: Theme.of(ctx).colorScheme.primary,
                            foregroundColor: Colors.white,
                          ),
                          child: const Text('Register Domain', style: TextStyle(fontSize: 16)),
                        );
                      },
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );

    if (result != null) {
      await _loadData();
    }
  }

  Future<void> _updateSiteZip(Map<String, dynamic> site) async {
    final domain = site['domain']?.toString() ?? '';
    if (domain.isEmpty) return;

    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['zip'],
    );
    if (result == null || result.files.single.path == null) return;

    final zipFile = File(result.files.single.path!);

    // Ask whether to delete old version
    final deleteOld = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Update Site'),
        content: const Text('Delete the old version from storage to free up space?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep')),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Delete Old', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (deleteOld == null) return;

    setState(() => _isLoading = true);

    if (deleteOld) {
      await widget.apiClient.unpinSite(site['cid']?.toString() ?? '');
    }

    final cid = await widget.apiClient.publishToFeedoStorage(zipFile);
    if (cid != null) {
      final updated = await widget.apiClient.updateCid(domain, cid);
      if (updated) {
        await widget.apiClient.saveMyDomain(domain, cid);
      }
    }

    await _loadData();
  }

  Future<void> _deleteDomain(Map<String, dynamic> site) async {
    final domain = site['domain']?.toString() ?? '';
    final cid = site['cid']?.toString() ?? '';

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete from Network'),
        content: Text('Are you sure you want to permanently delete "$domain" from the network? This will unpin files and remove the domain record.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Delete', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    setState(() => _isLoading = true);

    if (cid.isNotEmpty) {
      await widget.apiClient.unpinSite(cid);
      // Mark as deleted on consensus
      await widget.apiClient.updateCid(domain, 'DELETED');
    }
    await widget.apiClient.removeMyDomain(domain);
    await _loadData();
  }

  void _openDomain(String domain) {
    Navigator.pop(context, OpenDomainAction('feedonet://$domain'));
  }

  String _formatDate(dynamic timestamp) {
    if (timestamp == null) return '';
    try {
      final ts = int.tryParse(timestamp.toString()) ?? 0;
      if (ts == 0) return '';
      final dt = DateTime.fromMillisecondsSinceEpoch(ts * 1000);
      return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';
    } catch (_) {
      return '';
    }
  }

  String _shortenCid(String cid) {
    if (cid.length <= 20) return cid;
    return '${cid.substring(0, 12)}...${cid.substring(cid.length - 8)}';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('My Domains'),
        actions: [
          if (_balance != null)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Chip(
                avatar: Icon(Icons.account_balance_wallet, size: 18, color: theme.colorScheme.primary),
                label: Text('${_balance} credits'),
                backgroundColor: theme.colorScheme.surface.withOpacity(0.12),
              ),
            ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _registerDomain,
        icon: const Icon(Icons.add),
        label: const Text('Register Domain'),
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading && _domains.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_errorMessage != null && _domains.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text(_errorMessage!, style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _loadData,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_domains.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.dns, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            const Text(
              'No domains registered yet.',
              style: TextStyle(fontSize: 16, color: Colors.grey),
            ),
            const SizedBox(height: 8),
            const Text(
              'Tap the button below to register your first domain.',
              style: TextStyle(fontSize: 13, color: Colors.grey),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadData,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _domains.length,
        itemBuilder: (context, index) {
          final site = _domains[index];
          return _buildDomainCard(site);
        },
      ),
    );
  }

  Widget _buildDomainCard(Map<String, dynamic> site) {
    final theme = Theme.of(context);
    final domain = site['domain']?.toString() ?? 'unknown';
    final cid = site['cid']?.toString() ?? '';
    final title = site['title']?.toString();
    final description = site['description']?.toString();
    final iconCid = site['icon_cid']?.toString();
    final createdAt = _formatDate(site['created_at']);
    final isDeleted = cid == 'DELETED';

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header: icon + domain name
            Row(
              children: [
                // Favicon or placeholder
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: iconCid != null && iconCid.isNotEmpty
                      ? ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Image.network(
                            '${widget.apiClient.searchProxyUrl}/download/$iconCid',
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => Icon(
                              Icons.public,
                              color: theme.colorScheme.primary,
                              size: 24,
                            ),
                          ),
                        )
                      : Icon(
                          Icons.public,
                          color: theme.colorScheme.primary,
                          size: 24,
                        ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        domain,
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          color: isDeleted ? Colors.red : null,
                          decoration: isDeleted ? TextDecoration.lineThrough : null,
                        ),
                      ),
                      if (isDeleted)
                        const Text(
                          'Deleted from network',
                          style: TextStyle(color: Colors.red, fontSize: 12),
                        ),
                    ],
                  ),
                ),
              ],
            ),
            // Title
            if (title != null && title.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                title,
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: theme.textTheme.bodyLarge?.color,
                ),
              ),
            ],
            // Description
            if (description != null && description.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                description,
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.grey.shade600,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ],
            // CID
            if (cid.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'CID: ${_shortenCid(cid)}',
                style: TextStyle(
                  fontSize: 12,
                  fontFamily: 'monospace',
                  color: Colors.grey.shade500,
                ),
              ),
            ],
            // Created date
            if (createdAt.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                'Created: $createdAt',
                style: TextStyle(fontSize: 12, color: Colors.grey.shade500),
              ),
            ],
            const SizedBox(height: 12),
            // Action buttons
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (cid.isNotEmpty && !isDeleted)
                  TextButton.icon(
                    icon: const Icon(Icons.open_in_browser, size: 18),
                    label: const Text('Open'),
                    onPressed: () => _openDomain(domain),
                  ),
                const SizedBox(width: 4),
                if (!isDeleted)
                  TextButton.icon(
                    icon: const Icon(Icons.upload_file, size: 18),
                    label: const Text('Upload ZIP'),
                    onPressed: () => _updateSiteZip(site),
                  ),
                const SizedBox(width: 4),
                TextButton.icon(
                  icon: Icon(
                    isDeleted ? Icons.delete_forever : Icons.delete_outline,
                    size: 18,
                    color: Colors.red,
                  ),
                  label: Text(
                    'Delete',
                    style: TextStyle(color: Colors.red),
                  ),
                  onPressed: () => _deleteDomain(site),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}