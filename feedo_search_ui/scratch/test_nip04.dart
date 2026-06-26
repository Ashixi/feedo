import 'dart:mirrors';
import 'package:dart_nostr/dart_nostr.dart';

void main() {
  final nostr = Nostr.instance;
  for (var decl in reflect(nostr.keys).type.declarations.values) {
    print("Keys member: ${MirrorSystem.getName(decl.simpleName)}");
  }
}
