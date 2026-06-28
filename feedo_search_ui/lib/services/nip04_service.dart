import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:convert/convert.dart';
import 'package:pointycastle/export.dart';
import 'auth_service.dart';

class Nip04Service {
  static final _secp256k1 = ECDomainParameters('secp256k1');

  static Uint8List getSharedSecret(String privateKeyHex, String publicKeyHex) {
    final privKeyInt = BigInt.parse(privateKeyHex, radix: 16);
    final pubKeyPrefix = '02$publicKeyHex';
    final pubKeyBytes = Uint8List.fromList(hex.decode(pubKeyPrefix));
    final q = _secp256k1.curve.decodePoint(pubKeyBytes);

    if (q == null) throw Exception('Invalid public key');

    final p = q * privKeyInt;
    if (p == null || p.isInfinity) throw Exception('Invalid shared secret');

    final secret = p.x!.toBigInteger()!.toRadixString(16).padLeft(64, '0');
    return Uint8List.fromList(hex.decode(secret));
  }

  static Future<String> encrypt(String targetPubKeyHex, String text) async {
    final privateKeyHex = await AuthService.getPrivateKey();
    if (privateKeyHex == null || privateKeyHex.isEmpty) {
      throw Exception('Private key is required for local encryption');
    }

    final sharedSecret = getSharedSecret(privateKeyHex, targetPubKeyHex);
    
    final random = Random.secure();
    final ivBytes = Uint8List.fromList(List<int>.generate(16, (i) => random.nextInt(256)));
    
    final cipher = CBCBlockCipher(AESEngine())
      ..init(true, ParametersWithIV(KeyParameter(sharedSecret), ivBytes));

    final textBytes = utf8.encode(text);
    final padLength = 16 - (textBytes.length % 16);
    final paddedText = Uint8List(textBytes.length + padLength);
    paddedText.setAll(0, textBytes);
    for (int i = 0; i < padLength; i++) {
      paddedText[textBytes.length + i] = padLength;
    }

    final cipherText = Uint8List(paddedText.length);
    for (var i = 0; i < paddedText.length; i += 16) {
      cipher.processBlock(paddedText, i, cipherText, i);
    }

    final cipherTextBase64 = base64Encode(cipherText);
    final ivBase64 = base64Encode(ivBytes);

    return '$cipherTextBase64?iv=$ivBase64';
  }

  static Future<String> decrypt(String senderPubKeyHex, String encryptedText) async {
    final privateKeyHex = await AuthService.getPrivateKey();
    if (privateKeyHex == null || privateKeyHex.isEmpty) {
      throw Exception('Private key is required for local decryption');
    }

    final parts = encryptedText.split('?iv=');
    if (parts.length != 2) return encryptedText;

    try {
      final cipherText = base64Decode(parts[0]);
      final ivBytes = base64Decode(parts[1]);

      final sharedSecret = getSharedSecret(privateKeyHex, senderPubKeyHex);

      final cipher = CBCBlockCipher(AESEngine())
        ..init(false, ParametersWithIV(KeyParameter(sharedSecret), ivBytes));

      final paddedText = Uint8List(cipherText.length);
      for (var i = 0; i < cipherText.length; i += 16) {
        cipher.processBlock(cipherText, i, paddedText, i);
      }

      final padLength = paddedText.last;
      if (padLength < 1 || padLength > 16) {
        throw Exception('Invalid padding');
      }
      
      final textBytes = paddedText.sublist(0, paddedText.length - padLength);
      return utf8.decode(textBytes);
    } catch (e) {
      return '<Encrypted Message>';
    }
  }
}
