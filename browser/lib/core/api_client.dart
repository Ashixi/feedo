import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:browser/src/rust/api/wallet.dart';
import 'package:browser/src/rust/api/server.dart' as rust_server;

import 'dart:math';

class ApiClient {
  static final List<String> gateways = [
    'https://api.feedo.ink',
    'https://api2.feedo.ink'
  ];

  late String baseUrl;
  late String consensusUrl;
  late String searchProxyUrl;
  late String storageNodeUrl;

  final String did;
  final String address;

  ApiClient({required this.did, required this.address}) {
    // Вибираємо випадкову ноду для балансування навантаження
    baseUrl = gateways[Random().nextInt(gateways.length)];
    consensusUrl = '$baseUrl/consensus';
    searchProxyUrl = baseUrl;
    storageNodeUrl = baseUrl;
  }

  Future<bool> registerDid() async {
    final response = await http.post(
      Uri.parse('$consensusUrl/did/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'public_key': address,
      }),
    );
    return response.statusCode == 200;
  }

  Future<bool> registerName(String name) async {
    final message = '$name$did';
    final signature = await signMessage(message: message);

    final response = await http.post(
      Uri.parse('$consensusUrl/name/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'did': did,
        'public_key': address,
        'signature': signature,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['success'] == true;
    }
    return false;
  }

  Future<String?> publishSite(File zipFile) async {
    var request = http.MultipartRequest(
      'POST',
      Uri.parse('$searchProxyUrl/proxy/publish'),
    );
    request.files.add(await http.MultipartFile.fromPath('file', zipFile.path));

    var streamedResponse = await request.send();
    var response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['cid']; // The Pinata IPFS hash
    }
    return null;
  }

  Future<bool> updateCid(String name, String cid) async {
    final message = '$name$cid';
    final signature = await signMessage(message: message);

    final response = await http.post(
      Uri.parse('$consensusUrl/name/update_cid'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'name': name, 'cid': cid, 'signature': signature, 'gateways': ApiClient.gateways}),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['success'] == true;
    }
    return false;
  }

  Future<String?> resolveName(String name) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve/$name'));
    
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data != null && data['cid'] != null) {
        if (data['gateways'] != null) {
          final List<dynamic> gwList = data['gateways'];
          final gateways = gwList.map((e) => e.toString()).toList();
          if (gateways.isNotEmpty) {
            await rust_server.setGateways(gateways: gateways);
          }
        }
        return data['cid'];
      }
    }
    return null;
  }

  Future<String?> resolveCid(String cid) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve_cid/$cid'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data != null) {
        return data.toString();
      }
    }
    return null;
  }

  Future<List<Map<String, dynamic>>> search(String query) async {
    try {
      final encodedQuery = Uri.encodeComponent(query);
      final response = await http.get(Uri.parse('$searchProxyUrl/query?text=$encodedQuery&item_type=website'));
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data != null && data['results'] != null) {
          return List<Map<String, dynamic>>.from(data['results']);
        }
      }
    } catch (e) {
      print('Search error: $e');
    }
    return [];
  }

  Future<String?> publishToFeedoStorage(File zipFile) async {
    final url = '$searchProxyUrl/proxy/publish_feedo';
    print('DEBUG: Sending POST to $url');
    try {
      var request = http.MultipartRequest('POST', Uri.parse(url));
      request.files.add(
        await http.MultipartFile.fromPath('file', zipFile.path),
      );

      var streamedResponse = await request.send();
      var response = await http.Response.fromStream(streamedResponse);

      print(
        'DEBUG: Response status: ${response.statusCode}, body: ${response.body}',
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['cid'];
      }
    } catch (e) {
      print('DEBUG: Publish error: $e');
    }
    return null;
  }

  Future<String?> publishToFeedoStorageBytes(List<int> bytes, String filename) async {
    final url = '$searchProxyUrl/proxy/publish_feedo';
    print('DEBUG: Sending POST to $url with in-memory bytes');
    try {
      var request = http.MultipartRequest('POST', Uri.parse(url));
      request.files.add(
        http.MultipartFile.fromBytes('file', bytes, filename: filename),
      );

      var streamedResponse = await request.send();
      var response = await http.Response.fromStream(streamedResponse);

      print(
        'DEBUG: Response status: ${response.statusCode}, body: ${response.body}',
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['cid'];
      }
    } catch (e) {
      print('DEBUG: Publish error: $e');
    }
    return null;
  }

  Future<bool> unpinSite(String cid, {bool isFeedoStorage = true}) async {
    final url = '$searchProxyUrl/proxy/unpin_feedo/$cid';

    try {
      final response = await http.delete(Uri.parse(url));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  Future<void> saveMyDomain(
    String domain,
    String currentCid,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];

    final Map<String, dynamic> siteInfo = {
      'domain': domain,
      'cid': currentCid,
    };

    domains.removeWhere((d) {
      final map = jsonDecode(d);
      return map['domain'] == domain;
    });

    domains.add(jsonEncode(siteInfo));
    await prefs.setStringList('my_domains', domains);
  }

  Future<List<Map<String, dynamic>>> getMyDomains() async {
    try {
      final response = await http.get(Uri.parse('$consensusUrl/did/$did/names'));
      if (response.statusCode == 200) {
        final List<dynamic> data = jsonDecode(response.body);
        return data.map((e) => e as Map<String, dynamic>).toList();
      }
    } catch (e) {
      print('Error fetching domains: $e');
    }
    return [];
  }

  Future<void> removeMyDomain(String domain) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];
    domains.removeWhere((d) {
      final map = jsonDecode(d);
      return map['domain'] == domain;
    });
    await prefs.setStringList('my_domains', domains);
  }
}
