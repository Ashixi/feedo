import 'dart:convert';
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
    final privateKey = ed.PrivateKey(bytes);
    final publicKey = ed.PublicKey(bytes.sublist(32));
    return ed.KeyPair(privateKey, publicKey);
  }

  static String signMessage(ed.PrivateKey privateKey, String message) {
    final bytes = utf8.encode(message);
    final signature = ed.sign(privateKey, bytes);
    return '0x${HEX.encode(signature)}';
  }
}
