import 'package:feedo_explorer/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:dio/dio.dart';
import '../../core/api_client.dart';

class NetworkScreen extends ConsumerStatefulWidget {
  const NetworkScreen({super.key});

  @override
  ConsumerState<NetworkScreen> createState() => _NetworkScreenState();
}

class _NetworkScreenState extends ConsumerState<NetworkScreen> {
  Map<String, dynamic>? _summary;
  List<dynamic>? _nodes;
  String? _error;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _fetchSummary();
    });
  }

  Future<void> _fetchSummary() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final dio = ref.read(apiClientProvider);
      final response = await dio.get('/network/summary');
      final nodesResponse = await dio.get('/network/nodes');
      setState(() {
        _summary = response.data;
        _nodes = nodesResponse.data['nodes'];
        _isLoading = false;
      });
    } on DioException catch (e) {
      setState(() {
        _error = e.response?.data?['detail'] ?? e.message ?? "Failed to load network stats";
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
      body: SingleChildScrollView(
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
                      Text(loc.networkTopologyTitle,
                        style: TextStyle(
                          fontSize: isMobile ? 24 : 32, 
                          fontWeight: FontWeight.bold, 
                          letterSpacing: -1
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(loc.networkStatsDesc,
                        style: TextStyle(fontSize: 16, color: Colors.grey.shade400),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  onPressed: _fetchSummary,
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
            else if (_summary != null)
              Column(
                children: [
                  GridView.count(
                    crossAxisCount: isMobile ? 1 : 3,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    crossAxisSpacing: 16,
                    mainAxisSpacing: 16,
                    childAspectRatio: isMobile ? 2.5 : 2.0,
                    children: [
                      _buildMetricCard(
                        loc.totalNodes,
                        _summary!['total_nodes'].toString(),
                        LucideIcons.server,
                        Colors.blue,
                      ),
                      _buildMetricCard(
                        loc.activeSupernodes,
                        _summary!['supernodes'].toString(),
                        LucideIcons.database,
                        Colors.amber,
                      ),
                      _buildMetricCard(
                        loc.networkStatus,
                        _summary!['network_status'] ?? 'Unknown',
                        LucideIcons.activity,
                        _summary!['network_status'] == 'Healthy' ? Colors.green : Colors.orange,
                      ),
                    ],
                  ),
                  const SizedBox(height: 32),
                  Text(loc.kademliaTopology,
                    style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        color: Colors.grey.shade300),
                  ),
                  const SizedBox(height: 16),
                  if (_nodes == null || _nodes!.isEmpty)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(32),
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.surface,
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: Colors.grey.shade800),
                      ),
                      child: Center(
                        child: Column(
                          children: [
                            Icon(LucideIcons.gitMerge,
                                size: 48, color: Colors.grey.shade600),
                            const SizedBox(height: 16),
                            Text(loc.noActivePeers,
                              style: TextStyle(color: Colors.grey.shade500),
                            ),
                          ],
                        ),
                      ),
                    )
                  else
                    Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: _nodes!.map((node) {
                        final isSuper = node['is_supernode'] == true;
                        return Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 12),
                          decoration: BoxDecoration(
                            color: isSuper
                                ? Colors.amber.withOpacity(0.1)
                                : Colors.blue.withOpacity(0.1),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                                color: isSuper
                                    ? Colors.amber.withOpacity(0.3)
                                    : Colors.blue.withOpacity(0.3)),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                isSuper ? LucideIcons.database : LucideIcons.server,
                                color: isSuper ? Colors.amber : Colors.blue,
                                size: 16,
                              ),
                              const SizedBox(width: 8),
                              Text(
                                node['peer_id'].toString().length > 16
                                    ? '${node['peer_id'].toString().substring(0, 16)}...'
                                    : node['peer_id'].toString(),
                                style: TextStyle(
                                  color: Colors.grey.shade300,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                              const SizedBox(width: 12),
                              Container(
                                width: 8,
                                height: 8,
                                decoration: const BoxDecoration(
                                  color: Colors.green,
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ],
                          ),
                        );
                      }).toList(),
                    ),
                ],
              )
          ],
        ),
      ),
    );
  }

  Widget _buildMetricCard(String title, String value, IconData icon, MaterialColor color) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.grey.shade800),
      ),
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: color.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(icon, color: color.shade400, size: 28),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    title,
                    style: TextStyle(fontSize: 14, color: Colors.grey.shade400, fontWeight: FontWeight.w500),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    value,
                    style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: color.shade100),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
