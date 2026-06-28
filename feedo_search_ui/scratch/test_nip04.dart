import 'package:dart_nostr/dart_nostr.dart';
void main() {
  final keys = NostrKeyPairs.generate();
  final other = NostrKeyPairs.generate();
  try {
    print(Nostr.instance.keys.encrypt(keys.private, other.public, "test"));
  } catch(e) {
    print(e);
  }
}
