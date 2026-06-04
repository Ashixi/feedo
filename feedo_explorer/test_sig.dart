import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:elliptic/elliptic.dart';
import 'package:ecdsa/ecdsa.dart' as ecdsa;

void main() {
  var ec = getSecp256k1();
  var priv = ec.generatePrivateKey();
  var pubHex = priv.publicKey.toHex().substring(2);
  var walletAddress = "0x" + pubHex;
  var timestamp = "1700000000";
  var dataToSign = "$walletAddress:$timestamp";
  var digest = sha256.convert(utf8.encode(dataToSign)).bytes;
  var signature = ecdsa.signature(priv, digest);
  
  print("Wallet: " + walletAddress);
  print("Sig: " + signature.toCompactHex());
}
