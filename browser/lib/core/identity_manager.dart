import 'package:shared_preferences/shared_preferences.dart';
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;
import 'crypto_utils.dart';

class IdentityManager {
  static const String _privateKeyKey = 'feedo_private_key';

  static Future<ed.KeyPair> loadOrGenerateKeyPair() async {
    final prefs = await SharedPreferences.getInstance();
    final savedKey = prefs.getString(_privateKeyKey);

    if (savedKey != null && savedKey.isNotEmpty) {
      try {
        return CryptoUtils.keyPairFromPrivateKeyHex(savedKey);
      } catch (e) {
        // Fallback if parsing fails
        return _generateAndSave(prefs);
      }
    } else {
      return _generateAndSave(prefs);
    }
  }

  static Future<ed.KeyPair> _generateAndSave(SharedPreferences prefs) async {
    final keyPair = CryptoUtils.generateKeyPair();
    final hex = CryptoUtils.getPrivateKeyHex(keyPair.privateKey);
    await prefs.setString(_privateKeyKey, hex);
    return keyPair;
  }

  static Future<String?> getSavedPrivateKeyHex() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_privateKeyKey);
  }
}
