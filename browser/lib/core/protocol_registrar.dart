import 'dart:io';

class ProtocolRegistrar {
  static Future<void> registerWindowsProtocol() async {
    if (!Platform.isWindows) return;

    final exePath = Platform.resolvedExecutable;

    try {
      // Create root key
      await Process.run('reg', [
        'add',
        r'HKCU\Software\Classes\feedonet',
        '/ve',
        '/d',
        'URL:feedonet Protocol',
        '/f',
      ]);
      await Process.run('reg', [
        'add',
        r'HKCU\Software\Classes\feedonet',
        '/v',
        'URL Protocol',
        '/d',
        '',
        '/f',
      ]);

      // Create command key
      await Process.run('reg', [
        'add',
        r'HKCU\Software\Classes\feedonet\shell\open\command',
        '/ve',
        '/d',
        '"$exePath" "%1"',
        '/f',
      ]);

      print('Registered feedonet:// protocol successfully.');
    } catch (e) {
      print('Failed to register protocol: $e');
    }
  }
}
