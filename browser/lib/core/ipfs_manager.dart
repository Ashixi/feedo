import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;
import 'package:archive/archive_io.dart';

class IpfsManager {
  static Process? _ipfsProcess;
  static const String _ipfsVersion = 'v0.27.0';
  static const String _downloadUrl =
      'https://dist.ipfs.tech/kubo/$_ipfsVersion/kubo_${_ipfsVersion}_windows-amd64.zip';

  static Future<void> startDaemon() async {
    final supportDir = await getApplicationSupportDirectory();
    final kuboDir = Directory('${supportDir.path}/kubo');
    final ipfsExe = File('${kuboDir.path}/kubo/ipfs.exe');

    if (!await ipfsExe.exists()) {
      print('Downloading IPFS Kubo...');
      final response = await http.get(Uri.parse(_downloadUrl));
      final zipFile = File('${supportDir.path}/kubo.zip');
      await zipFile.writeAsBytes(response.bodyBytes);

      final bytes = zipFile.readAsBytesSync();
      final archive = ZipDecoder().decodeBytes(bytes);
      extractArchiveToDisk(archive, kuboDir.path);
      await zipFile.delete();
    }

    final ipfsPath = ipfsExe.path;
    final repoDir = Directory('${supportDir.path}/.ipfs');

    if (!await File('${repoDir.path}/config').exists()) {
      await Process.run(
        ipfsPath,
        ['init'],
        environment: {'IPFS_PATH': repoDir.path},
      );
    }

    _ipfsProcess = await Process.start(
      ipfsPath,
      ['daemon', '--routing=dhtclient'],
      environment: {'IPFS_PATH': repoDir.path},
    );
    _ipfsProcess!.stdout.listen(
      (data) => print('IPFS: ${String.fromCharCodes(data)}'),
    );
    _ipfsProcess!.stderr.listen(
      (data) => print('IPFS Error: ${String.fromCharCodes(data)}'),
    );
  }

  static Future<void> stopDaemon() async {
    _ipfsProcess?.kill();
    _ipfsProcess = null;
  }
}
