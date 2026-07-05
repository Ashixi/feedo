import 'dart:mirrors';
import 'package:dart_nostr/dart_nostr.dart';

void main() {
  final nostr = Nostr.instance;
  final mirror = reflect(nostr);
  for (var entry in mirror.type.declarations.entries) {
    print("Nostr member: ${MirrorSystem.getName(entry.value.simpleName)}");
  }
}
