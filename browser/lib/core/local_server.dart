import 'dart:io';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as io;
import 'package:http/http.dart' as http;
import 'package:archive/archive.dart';

import 'api_client.dart';

class LocalFeedoServer {
  static HttpServer? _server;
  static int get port => _server?.port ?? 8081;
  
  static final Map<String, Map<String, List<int>>> _cache = {};
  static String? _lastCid;
  
  static Future<void> start(ApiClient apiClient) async {
    if (_server != null) return;
    
    final pipeline = const Pipeline().addHandler((request) => _handleRequest(request, apiClient));
    _server = await io.serve(pipeline, InternetAddress.loopbackIPv4, 8081);
    print('LocalFeedoServer running on localhost:${_server!.port}');
  }
  
  static Future<Response> _handleRequest(Request request, ApiClient apiClient) async {
    final corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': '*',
    };

    if (request.method == 'OPTIONS') {
      return Response.ok('', headers: corsHeaders);
    }

    final host = request.headers['host'] ?? '';
    String cid = '';
    
    if (host.contains('.localhost')) {
      final parts = host.split('.localhost').first.split('.');
      if (parts.length >= 2) {
        cid = parts[0] + parts[1];
      } else {
        cid = parts[0];
      }
    }
    
    if (cid.isEmpty) {
      return Response.notFound('Missing or invalid CID in Host header');
    }

    var filePath = request.url.path;
    if (filePath.isEmpty || filePath == '/') {
      filePath = 'index.html';
    } else if (filePath.startsWith('/')) {
      filePath = filePath.substring(1);
    }
    
    if (!_cache.containsKey(cid)) {
      final success = await _downloadAndExtract(cid, apiClient);
      if (!success) {
        return Response.internalServerError(body: 'Failed to fetch from Feedo P2P Storage');
      }
    }
    
    final siteFiles = _cache[cid]!;
    
    var data = siteFiles[filePath];
    
    if (data == null) {
      for (final key in siteFiles.keys) {
        if (key.endsWith('/$filePath') || key == filePath) {
          data = siteFiles[key];
          break;
        }
      }
    }
    
    // SPA Routing Fallback: If file is not found and it looks like a route (no extension), return index.html
    if (data == null && !filePath.contains('.')) {
      filePath = 'index.html';
      data = siteFiles[filePath];
      if (data == null) {
        for (final key in siteFiles.keys) {
          if (key.endsWith('/index.html') || key == 'index.html') {
            data = siteFiles[key];
            break;
          }
        }
      }
    }
    
    if (data == null) {
      return Response.notFound('File not found in archive');
    }
    
    
    final headers = Map<String, String>.from(corsHeaders);
    headers['content-type'] = _getMimeType(filePath);
    
    return Response.ok(data, headers: headers);
  }
  
  static Future<bool> _downloadAndExtract(String cid, ApiClient apiClient) async {
    try {
      final url = Uri.parse('${apiClient.storageNodeUrl}/download/$cid');
      print('LocalFeedoServer: Downloading ZIP for $cid from $url');
      final response = await http.get(url);
      
      if (response.statusCode != 200) {
        print('LocalFeedoServer: Download failed with status ${response.statusCode}');
        return false;
      }
      
      final archive = ZipDecoder().decodeBytes(response.bodyBytes);
      final siteFiles = <String, List<int>>{};
      
      for (final file in archive) {
        if (file.isFile) {
          siteFiles[file.name] = file.content as List<int>;
        }
      }
      
      _cache[cid] = siteFiles;
      print('LocalFeedoServer: Extracted ${siteFiles.length} files for $cid into RAM. Keys: ${siteFiles.keys.take(5).toList()}...');
      return true;
    } catch (e) {
      print('LocalFeedoServer: Error downloading/extracting: $e');
      return false;
    }
  }
  
  static String _getMimeType(String filename) {
    final ext = filename.split('.').last.toLowerCase();
    switch (ext) {
      case 'html': return 'text/html; charset=utf-8';
      case 'css': return 'text/css; charset=utf-8';
      case 'js': return 'application/javascript; charset=utf-8';
      case 'png': return 'image/png';
      case 'jpg':
      case 'jpeg': return 'image/jpeg';
      case 'gif': return 'image/gif';
      case 'svg': return 'image/svg+xml';
      case 'json': return 'application/json; charset=utf-8';
      case 'ico': return 'image/x-icon';
      case 'txt': return 'text/plain; charset=utf-8';
      default: return 'application/octet-stream';
    }
  }
}
