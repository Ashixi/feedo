import 'dart:convert';
import 'dart:typed_data';
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;
import 'package:hex/hex.dart';

class CryptoUtils {
  static ed.KeyPair generateKeyPair() {
    return ed.generateKey();
  }

  static String getPublicKeyHex(ed.PublicKey publicKey) {
    return '0x${HEX.encode(publicKey.bytes)}';
  }

  static String getPrivateKeyHex(ed.PrivateKey privateKey) {
    return '0x${HEX.encode(privateKey.bytes)}';
  }

  static ed.KeyPair keyPairFromPrivateKeyHex(String privateKeyHex) {
    final bytes = HEX.decode(privateKeyHex.replaceFirst('0x', ''));
    if (bytes.length == 64) {
      // Full 64-byte private key (seed + public key suffix)
      final privateKey = ed.PrivateKey(bytes);
      final publicKey = ed.public(privateKey);
      return ed.KeyPair(privateKey, publicKey);
    } else if (bytes.length == 32) {
      // 32-byte seed only — derive full key
      final privateKey = ed.newKeyFromSeed(Uint8List.fromList(bytes));
      final publicKey = ed.public(privateKey);
      return ed.KeyPair(privateKey, publicKey);
    } else {
      throw ArgumentError('Invalid private key length: ${bytes.length} bytes (expected 32 or 64)');
    }
  }

  static String signMessage(ed.PrivateKey privateKey, String message) {
    final bytes = utf8.encode(message);
    final signature = ed.sign(privateKey, bytes);
    return '0x${HEX.encode(signature)}';
  }
}
