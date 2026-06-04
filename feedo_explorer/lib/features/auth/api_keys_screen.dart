import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import '../../core/wallet_provider.dart';

class WalletIdentityScreen extends ConsumerWidget {
  const WalletIdentityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final wallet = ref.watch(walletProvider);

    return Scaffold(
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(32.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Wallet Identity',
                      style: TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.bold,
                        letterSpacing: -1,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Decentralized access control. Generate a local wallet to sign requests to the Feedo network.',
                      style: TextStyle(
                        fontSize: 16,
                        color: Colors.grey.shade400,
                      ),
                    ),
                  ],
                ),
                if (wallet == null)
                  ElevatedButton.icon(
                    onPressed: () {
                      ref.read(walletProvider.notifier).generateNew();
                    },
                    icon: const Icon(LucideIcons.key),
                    label: const Text('Generate Identity'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.primary,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  )
                else
                  ElevatedButton.icon(
                    onPressed: () {
                      ref.read(walletProvider.notifier).logout();
                    },
                    icon: const Icon(LucideIcons.logOut),
                    label: const Text('Clear Identity'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red.shade600,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  )
              ],
            ),
            const SizedBox(height: 48),
            
            if (wallet == null)
              Center(
                child: Column(
                  children: [
                    Icon(LucideIcons.shieldAlert, size: 64, color: Colors.grey.shade600),
                    const SizedBox(height: 16),
                    Text(
                      'No Identity Found',
                      style: TextStyle(fontSize: 20, color: Colors.grey.shade400, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 8),
                    const Text('You must generate a local wallet to interact with the decentralized API.'),
                  ],
                ),
              )
            else
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(32.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(LucideIcons.checkCircle, color: Colors.teal),
                          SizedBox(width: 12),
                          Text('Identity Active', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.teal)),
                        ],
                      ),
                      const SizedBox(height: 32),
                      const Text('Public Wallet Address (SECP256k1)', style: TextStyle(color: Colors.grey, fontWeight: FontWeight.w500)),
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: Colors.black.withOpacity(0.3),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.grey.shade800),
                        ),
                        child: Text(
                          wallet.walletAddress,
                          style: TextStyle(fontFamily: 'monospace', color: Colors.grey.shade300, fontSize: 16),
                        ),
                      ),
                      const SizedBox(height: 24),
                      const Text('Private Key (Stored Locally)', style: TextStyle(color: Colors.grey, fontWeight: FontWeight.w500)),
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: Colors.black.withOpacity(0.3),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.grey.shade800),
                        ),
                        child: const Row(
                          children: [
                            Icon(LucideIcons.lock, size: 16, color: Colors.redAccent),
                            SizedBox(width: 12),
                            Text(
                              '••••••••••••••••••••••••••••••••••••••••••••••••••••••••',
                              style: TextStyle(fontFamily: 'monospace', color: Colors.redAccent),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 32),
                      const Text(
                        'This identity is used to sign all outgoing HTTP requests using Zero-Trust architecture. It proves you own this wallet address without sending the private key.',
                        style: TextStyle(color: Colors.grey, height: 1.5),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
