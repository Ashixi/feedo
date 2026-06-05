import 'package:feedo_explorer/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:dio/dio.dart';
import '../../core/api_client.dart';

class IdentitiesScreen extends ConsumerStatefulWidget {
  const IdentitiesScreen({super.key});

  @override
  ConsumerState<IdentitiesScreen> createState() => _IdentitiesScreenState();
}

class _IdentitiesScreenState extends ConsumerState<IdentitiesScreen> {
  List<dynamic> _identities = [];
  String? _error;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _fetchIdentities();
    });
  }

  Future<void> _fetchIdentities() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final dio = ref.read(apiClientProvider);
      final response = await dio.get('/identities');
      setState(() {
        _identities = response.data['identities'] ?? [];
        _isLoading = false;
      });
    } on DioException catch (e) {
      setState(() {
        _error = e.response?.data?['detail'] ?? e.message ?? "Failed to load identities";
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    final isMobile = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: EdgeInsets.all(isMobile ? 16.0 : 32.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(loc.decentralizedIdentities,
                              style: TextStyle(
                                fontSize: isMobile ? 24 : 32, 
                                fontWeight: FontWeight.bold, 
                                letterSpacing: -1
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(loc.activeDidPeersDesc,
                              style: TextStyle(fontSize: 16, color: Colors.grey.shade400),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        onPressed: _fetchIdentities,
                        icon: const Icon(LucideIcons.refreshCcw),
                        tooltip: 'Refresh',
                      )
                    ],
                  ),
                  const SizedBox(height: 32),
                  if (_error != null)
                    Container(
                      padding: const EdgeInsets.all(16),
                      margin: const EdgeInsets.only(bottom: 24),
                      decoration: BoxDecoration(
                        color: Colors.red.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.red.withOpacity(0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(LucideIcons.alertTriangle, color: Colors.red),
                          const SizedBox(width: 12),
                          Expanded(child: Text(_error!, style: const TextStyle(color: Colors.red))),
                        ],
                      ),
                    ),
                  if (_isLoading)
                    const Center(child: CircularProgressIndicator())
                  else if (_identities.isEmpty)
                    Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(LucideIcons.users, size: 64, color: Colors.grey.shade700),
                          const SizedBox(height: 16),
                          Text(loc.noIdentitiesFound, style: TextStyle(color: Colors.grey.shade500)),
                        ],
                      ),
                    )
                  else
                    Card(
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                        side: BorderSide(color: Colors.grey.shade800),
                      ),
                      child: isMobile ? _buildMobileList(loc) : _buildDesktopTable(loc),
                    ),
                ],
              ),
            ),
          )
        ],
      ),
    );
  }

  Widget _buildDesktopTable(AppLocalizations loc) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingTextStyle: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
        columns: [
          DataColumn(label: Text(loc.didColumn)),
          DataColumn(label: Text(loc.reputationColumn)),
          DataColumn(label: Text(loc.statusColumn)),
        ],
        rows: _identities.map((identity) {
          final reputation = (identity['reputation'] ?? 0.0) as double;
          return DataRow(
            cells: [
              DataCell(
                Row(
                  children: [
                    Icon(LucideIcons.fingerprint, size: 16, color: Colors.blue.shade400),
                    const SizedBox(width: 8),
                    Text(
                      identity['did'] ?? 'Unknown',
                      style: const TextStyle(fontFamily: 'monospace'),
                    ),
                  ],
                ),
              ),
              DataCell(
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: reputation >= 0 ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    reputation.toStringAsFixed(2),
                    style: TextStyle(
                      color: reputation >= 0 ? Colors.green.shade400 : Colors.red.shade400,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
              DataCell(
                Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: const BoxDecoration(
                        color: Colors.green,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(loc.active),
                  ],
                ),
              ),
            ],
          );
        }).toList(),
      ),
    );
  }

  Widget _buildMobileList(AppLocalizations loc) {
    return ListView.separated(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: _identities.length,
      separatorBuilder: (context, index) => Divider(color: Colors.grey.shade800, height: 1),
      itemBuilder: (context, index) {
        final identity = _identities[index];
        final reputation = (identity['reputation'] ?? 0.0) as double;
        return ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          leading: Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.blue.withOpacity(0.1),
              shape: BoxShape.circle,
            ),
            child: Icon(LucideIcons.fingerprint, size: 20, color: Colors.blue.shade400),
          ),
          title: Text(
            identity['did'] ?? 'Unknown',
            style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
            overflow: TextOverflow.ellipsis,
          ),
          subtitle: Text(loc.activePeer, style: TextStyle(fontSize: 12, color: Colors.green)),
          trailing: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: reputation >= 0 ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              reputation.toStringAsFixed(1),
              style: TextStyle(
                color: reputation >= 0 ? Colors.green.shade400 : Colors.red.shade400,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        );
      },
    );
  }
}
