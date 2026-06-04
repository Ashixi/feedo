import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:dio/dio.dart';
import '../../core/api_client.dart';

class ConsensusScreen extends ConsumerStatefulWidget {
  const ConsensusScreen({super.key});

  @override
  ConsumerState<ConsensusScreen> createState() => _ConsensusScreenState();
}

class _ConsensusScreenState extends ConsumerState<ConsensusScreen> {
  List<dynamic> _blocks = [];
  String? _error;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _fetchConsensusHistory();
    });
  }

  Future<void> _fetchConsensusHistory() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final dio = ref.read(apiClientProvider);
      final response = await dio.get('/consensus/history');
      setState(() {
        _blocks = response.data['blocks'] ?? [];
        _isLoading = false;
      });
    } on DioException catch (e) {
      setState(() {
        _error = e.response?.data?['detail'] ?? e.message ?? "Failed to load consensus history";
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
                            Text(
                              'Consensus Logs (PBFT)',
                              style: TextStyle(
                                fontSize: isMobile ? 24 : 32, 
                                fontWeight: FontWeight.bold, 
                                letterSpacing: -1
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'History of confirmed blocks and distributed CRDT operations.',
                              style: TextStyle(fontSize: 16, color: Colors.grey.shade400),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        onPressed: _fetchConsensusHistory,
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
                  else if (_blocks.isEmpty)
                    Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(LucideIcons.history, size: 64, color: Colors.grey.shade700),
                          const SizedBox(height: 16),
                          Text('No consensus logs found yet.', style: TextStyle(color: Colors.grey.shade500)),
                        ],
                      ),
                    )
                  else
                    ListView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: _blocks.length,
                      itemBuilder: (context, index) {
                        final block = _blocks[index];
                        final isCommitted = block['status'] == 'committed';
                        
                        return Card(
                          margin: const EdgeInsets.only(bottom: 12),
                          elevation: 0,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                            side: BorderSide(color: Colors.grey.shade800),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Row(
                                      children: [
                                        Icon(
                                          LucideIcons.box, 
                                          size: 20, 
                                          color: isCommitted ? Colors.green.shade400 : Colors.amber.shade400,
                                        ),
                                        const SizedBox(width: 12),
                                        Text(
                                          'Round #${block['round_id'] ?? 'N/A'}',
                                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                                        ),
                                      ],
                                    ),
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                      decoration: BoxDecoration(
                                        color: isCommitted ? Colors.green.withOpacity(0.1) : Colors.amber.withOpacity(0.1),
                                        borderRadius: BorderRadius.circular(16),
                                      ),
                                      child: Text(
                                        (block['status'] ?? 'Unknown').toUpperCase(),
                                        style: TextStyle(
                                          fontSize: 12,
                                          fontWeight: FontWeight.bold,
                                          color: isCommitted ? Colors.green.shade400 : Colors.amber.shade400,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const Padding(
                                  padding: EdgeInsets.symmetric(vertical: 12),
                                  child: Divider(height: 1, color: Colors.white10),
                                ),
                                Row(
                                  children: [
                                    Icon(LucideIcons.hash, size: 14, color: Colors.grey.shade600),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Text(
                                        block['block_hash'] ?? '0x00000000000000000000',
                                        style: TextStyle(fontFamily: 'monospace', color: Colors.grey.shade400, fontSize: 13),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Row(
                                  children: [
                                    Icon(LucideIcons.clock, size: 14, color: Colors.grey.shade600),
                                    const SizedBox(width: 8),
                                    Text(
                                      block['timestamp'] ?? 'Just now',
                                      style: TextStyle(color: Colors.grey.shade500, fontSize: 12),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
                ],
              ),
            ),
          )
        ],
      ),
    );
  }
}
