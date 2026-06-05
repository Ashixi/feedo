import 'package:feedo_explorer/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import '../../core/wallet_provider.dart';

class WalletIdentityScreen extends ConsumerWidget {
  const WalletIdentityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final loc = AppLocalizations.of(context)!;
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
                    Text(loc.walletIdentityTitle,
                      style: TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.bold,
                        letterSpacing: -1,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(loc.walletIdentityDesc,
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
                    label: Text(loc.generateIdentity),
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
                    label: Text(loc.clearIdentity),
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
                    Text(loc.noIdentityFound,
                      style: TextStyle(fontSize: 20, color: Colors.grey.shade400, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 8),
                    Text(loc.mustGenerateWallet),
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
                      Row(
                        children: [
                          Icon(LucideIcons.checkCircle, color: Colors.teal),
                          SizedBox(width: 12),
                          Text(loc.identityActive, style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.teal)),
                        ],
                      ),
                      const SizedBox(height: 32),
                      Text(loc.publicWalletAddress, style: TextStyle(color: Colors.grey, fontWeight: FontWeight.w500)),
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
                      Text(loc.privateKeyStoredLocally, style: TextStyle(color: Colors.grey, fontWeight: FontWeight.w500)),
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
                      Text(loc.identityZeroTrustDesc,
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
