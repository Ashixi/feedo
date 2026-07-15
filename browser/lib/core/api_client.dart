import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:browser/src/rust/api/wallet.dart';
import 'package:browser/src/rust/api/server.dart' as rust_server;

class ApiClient {
  static final List<String> gateways = [
    'https://api.feedo.ink',
    'https://api2.feedo.ink'
  ];

  late String searchProxyUrl;
  /// Consensus URL = search-node + /consensus prefix (proxied to consensus-node:3000)
  late String consensusUrl;

  final String did;
  final String address;

  ApiClient({required this.did, required this.address}) {
    searchProxyUrl = gateways[Random().nextInt(gateways.length)];
    consensusUrl = '$searchProxyUrl/consensus';
  }

  // ── DNS / Consensus operations (via search-node proxy → consensus-node:3000) ──

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
    print('[DEBUG] registerName: name=$name did=$did sig=${signature.substring(0, 20)}...');

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

    print('[DEBUG] registerName response: ${response.statusCode} body=${response.body}');

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data['success'] == true) {
        return true;
      } else {
        print('[DEBUG] registerName failed: ${data['error']}');
      }
    }
    return false;
  }

  Future<bool> updateCid(String name, String cid) async {
    final message = '$name$cid';
    final signature = await signMessage(message: message);

    final response = await http.post(
      Uri.parse('$consensusUrl/name/update_cid'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'cid': cid,
        'signature': signature,
        'gateways': <String>[],
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data['success'] == true) {
        return true;
      } else {
        print('[DEBUG] updateCid failed: ${data['error']}');
      }
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

  /// Resolve a name and return the full response (including title, description, icon_cid, etc.)
  Future<Map<String, dynamic>?> resolveNameFull(String name) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve/$name'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data != null) {
        return data as Map<String, dynamic>;
      }
    }
    return null;
  }

  Future<String?> resolveCid(String cid) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve_cid/$cid'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is String && data.isNotEmpty) {
        return data;
      }
    }
    return null;
  }

  /// Fetch all domains registered under this DID from the consensus network.
  /// Returns list of {domain, cid, title, description, icon_cid, created_at, updated_at}
  Future<List<Map<String, dynamic>>> fetchMyDomainsFromNetwork() async {
    try {
      final response = await http.get(Uri.parse('$consensusUrl/did/$did/names'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data is List) {
          return data.cast<Map<String, dynamic>>();
        }
      }
    } catch (e) {
      print('[DEBUG] fetchMyDomainsFromNetwork error: $e');
    }
    return [];
  }

  /// Get the credit balance for this DID.
  Future<int?> getBalance() async {
    try {
      final response = await http.get(Uri.parse('$consensusUrl/did/$did/balance'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data != null && data['balance_credits'] != null) {
          return data['balance_credits'] as int;
        }
      }
    } catch (e) {
      print('[DEBUG] getBalance error: $e');
    }
    return null;
  }

  /// Update metadata (title, description, icon_cid) for a registered name.
  Future<bool> updateMetadata(String name, {String? title, String? description, String? iconCid}) async {
    final message = '$name${title ?? ''}${description ?? ''}${iconCid ?? ''}';
    final signature = await signMessage(message: message);

    try {
      final body = <String, dynamic>{
        'name': name,
        'public_key': address,
        'signature': signature,
      };
      if (title != null) body['title'] = title;
      if (description != null) body['description'] = description;
      if (iconCid != null) body['icon_cid'] = iconCid;

      final response = await http.post(
        Uri.parse('$consensusUrl/name/update_metadata'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['success'] == true) return true;
        print('[DEBUG] updateMetadata failed: ${data['error']}');
      }
    } catch (e) {
      print('[DEBUG] updateMetadata error: $e');
    }
    return false;
  }

  // ── Search operations (via search-node) ──

  Future<Map<String, dynamic>> search(String query) async {
    try {
      final encodedQuery = Uri.encodeComponent(query);
      final response = await http.get(Uri.parse('$searchProxyUrl/query?text=$encodedQuery&limit=50&federated=true&item_type=website'));
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data as Map<String, dynamic>;
      } else {
        return {'results': [], 'error': 'Server returned ${response.statusCode}'};
      }
    } catch (e) {
      print('Search error: $e');
      return {'results': [], 'error': 'Network error: $e'};
    }
  }

  // ── Publishing operations (via search-node → storage-node) ──

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

  Future<bool> unpinSite(String cid) async {
    final url = '$searchProxyUrl/proxy/unpin_feedo/$cid';

    try {
      final response = await http.delete(Uri.parse(url));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  // ── Local domain management (SharedPreferences) ──

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
      try {
        final map = jsonDecode(d);
        return map['domain'] == domain;
      } catch (_) {
        return false;
      }
    });

    domains.add(jsonEncode(siteInfo));
    await prefs.setStringList('my_domains', domains);
  }

  Future<List<Map<String, dynamic>>> getMyDomains() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final List<String> domains = prefs.getStringList('my_domains') ?? [];
      return domains.map((e) => jsonDecode(e) as Map<String, dynamic>).toList();
    } catch (e) {
      print('Error parsing my_domains: $e');
    }
    return [];
  }

  Future<void> removeMyDomain(String domain) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];
    domains.removeWhere((d) {
      try {
        final map = jsonDecode(d);
        return map['domain'] == domain;
      } catch (e) {
        print('Error parsing domain entry during removal: $e');
        return false;
      }
    });
    await prefs.setStringList('my_domains', domains);
  }

  // ── Certificate sync (not yet implemented on consensus node) ──

  Future<void> fetchAndSaveCertificates() async {
    print('DEBUG: fetchAndSaveCertificates skipped — /resolve_cert endpoint not available');
  }

  Future<void> syncCertificates() async {
    print('DEBUG: syncCertificates skipped — /state/sync endpoint not available');
  }
}