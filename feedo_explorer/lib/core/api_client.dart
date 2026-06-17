import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ecdsa/ecdsa.dart' as ecdsa;
import 'wallet_provider.dart';

import 'package:flutter/foundation.dart';

// Using dynamic baseUrl: relative path for web, absolute for other platforms.
final String _baseUrl = () {
  if (kIsWeb) {
    return 'https://developers.feedo.ink/api/v1';
  }
  return 'http://localhost:8001/api/v1';
}();

final apiClientProvider = Provider<Dio>((ref) {
  final dio = Dio(BaseOptions(baseUrl: _baseUrl));
  final wallet = ref.watch(walletProvider);

  dio.interceptors.add(InterceptorsWrapper(
    onRequest: (options, handler) {
      if (wallet != null) {
        final timestamp = (DateTime.now().millisecondsSinceEpoch ~/ 1000).toString();
        final dataToSign = "${wallet.walletAddress}:$timestamp";
        
        // Backend SECP256k1 verification expects the SHA256 digest to be signed
        final digest = sha256.convert(utf8.encode(dataToSign)).bytes;
        
        final signature = ecdsa.signature(wallet.privateKey, digest);
        
        // Python's ecdsa sign_digest outputs exactly 64 bytes (r and s concatenated)
        final sigHex = signature.toCompactHex();

        options.headers['x-node-wallet'] = wallet.walletAddress;
        options.headers['x-node-timestamp'] = timestamp;
        options.headers['x-node-signature'] = sigHex;
      }
      return handler.next(options);
    }
  ));

  return dio;
});
