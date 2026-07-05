import 'dart:mirrors';
import 'package:dart_nostr/dart_nostr.dart';

void main() {
  final classMirror = reflectClass(NostrEvent);
  for (var entry in classMirror.declarations.entries) {
    var decl = entry.value;
    if (decl is MethodMirror && decl.isConstructor) {
      print("Constructor: ${MirrorSystem.getName(decl.simpleName)}");
    } else if (decl is MethodMirror && decl.isStatic) {
      print("Static method: ${MirrorSystem.getName(decl.simpleName)}");
    }
  }
}
