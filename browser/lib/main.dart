import 'package:flutter/material.dart';
import 'dart:io';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'package:browser/src/rust/frb_generated.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
  // Initialize Rust engine
  await RustLib.init();
  runApp(const FeedoBrowserEngineStub());
}

class FeedoBrowserEngineStub extends StatelessWidget {
  const FeedoBrowserEngineStub({super.key});
  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      title: 'Feedo Engine',
      home: Scaffold(
        body: Center(child: Text('Engine initialized. UI removed.')),
      ),
    );
  }
}