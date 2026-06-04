import 'package:elliptic/elliptic.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

class WalletIdentity {
  final PrivateKey privateKey;
  final String walletAddress;

  WalletIdentity({required this.privateKey, required this.walletAddress});

  factory WalletIdentity.generate() {
    var ec = getSecp256k1();
    var priv = ec.generatePrivateKey();
    var pubHex = priv.publicKey.toHex().substring(2); // Remove the '04' prefix to match backend 64-byte uncompressed format
    var walletAddress = "0x" + pubHex;
    return WalletIdentity(privateKey: priv, walletAddress: walletAddress);
  }

  factory WalletIdentity.fromPrivateKeyHex(String hexString) {
    var ec = getSecp256k1();
    var priv = PrivateKey.fromHex(ec, hexString);
    var pubHex = priv.publicKey.toHex().substring(2);
    var walletAddress = "0x" + pubHex;
    return WalletIdentity(privateKey: priv, walletAddress: walletAddress);
  }
}

class WalletNotifier extends Notifier<WalletIdentity?> {
  @override
  WalletIdentity? build() {
    _loadFromStorage();
    return null;
  }

  Future<void> _loadFromStorage() async {
    final prefs = await SharedPreferences.getInstance();
    final hexString = prefs.getString('feedo_wallet_private_key');
    if (hexString != null) {
      try {
        state = WalletIdentity.fromPrivateKeyHex(hexString);
      } catch (e) {
        print("Failed to load wallet: $e");
      }
    }
  }

  Future<void> generateNew() async {
    final identity = WalletIdentity.generate();
    state = identity;
    
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('feedo_wallet_private_key', identity.privateKey.toHex());
  }

  Future<void> logout() async {
    state = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('feedo_wallet_private_key');
  }
}

final walletProvider = NotifierProvider<WalletNotifier, WalletIdentity?>(() {
  return WalletNotifier();
});
