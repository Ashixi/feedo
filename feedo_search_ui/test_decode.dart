import 'package:dart_nostr/dart_nostr.dart';

void main() {
  Nostr.instance.disableLogs();
  try {
    final hex = Nostr.instance.keys.decodePublicKeyToHex("npub18c556t44dpmnpuxex3yurh92mdxps046exm87l0u3y3t7uunau7q0d9k7n");
    print("npub decode: $hex");
  } catch (e) {
    print("npub err: $e");
  }
}
