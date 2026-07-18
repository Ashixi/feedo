import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:browser/src/rust/api/wallet.dart';
import 'package:browser/src/rust/api/server.dart' as rust_server;
import 'google_scraper.dart';

class ApiClient {
  static final List<String> gateways = [
    'https://api.feedo.ink',
  ];

  late String searchProxyUrl;
  late String consensusUrl;

  final String did;
  final String address;

  ApiClient({required this.did, required this.address}) {
    searchProxyUrl = gateways[Random().nextInt(gateways.length)];
    consensusUrl = '$searchProxyUrl/consensus';
  }

  Future<bool> registerDid() async {
    final response = await http.post(
      Uri.parse('$consensusUrl/did/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'public_key': address}),
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
        'name': name, 'did': did, 'public_key': address, 'signature': signature,
      }),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data['success'] == true) return true;
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
        'name': name, 'cid': cid, 'signature': signature, 'gateways': <String>[],
      }),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data['success'] == true) return true;
    }
    return false;
  }

  Future<String?> resolveName(String name) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve/$name'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data != null && data['cid'] != null) return data['cid'];
    }
    return null;
  }

  Future<Map<String, dynamic>?> resolveNameFull(String name) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve/$name'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data != null) return data as Map<String, dynamic>;
    }
    return null;
  }

  Future<String?> resolveCid(String cid) async {
    final response = await http.get(Uri.parse('$consensusUrl/resolve_cid/$cid'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is String && data.isNotEmpty) return data;
    }
    return null;
  }

  Future<List<Map<String, dynamic>>> fetchMyDomainsFromNetwork() async {
    try {
      final response = await http.get(Uri.parse('$consensusUrl/did/$did/names'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data is List) return data.cast<Map<String, dynamic>>();
      }
    } catch (_) {}
    return [];
  }

  Future<int?> getBalance() async {
    try {
      final response = await http.get(Uri.parse('$consensusUrl/did/$did/balance'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data != null && data['balance_credits'] != null) return data['balance_credits'] as int;
      }
    } catch (_) {}
    return null;
  }

  Future<bool> updateMetadata(String name, {String? title, String? description, String? iconCid}) async {
    final message = '$name${title ?? ''}${description ?? ''}${iconCid ?? ''}';
    final signature = await signMessage(message: message);
    try {
      final body = <String, dynamic>{'name': name, 'public_key': address, 'signature': signature};
      if (title != null) body['title'] = title;
      if (description != null) body['description'] = description;
      if (iconCid != null) body['icon_cid'] = iconCid;
      final response = await http.post(Uri.parse('$consensusUrl/name/update_metadata'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body));
      if (response.statusCode == 200 && jsonDecode(response.body)['success'] == true) return true;
    } catch (_) {}
    return false;
  }

  // ── Search ──

  Future<Map<String, dynamic>> search(String query) async {
    try {
      final encodedQuery = Uri.encodeComponent(query);
      final response = await http.get(Uri.parse('$searchProxyUrl/query?text=$encodedQuery&limit=50&federated=true&item_type=website'));
      if (response.statusCode == 200) return jsonDecode(response.body) as Map<String, dynamic>;
      return {'results': [], 'error': 'Server returned ${response.statusCode}'};
    } catch (e) {
      return {'results': [], 'error': 'Network error: $e'};
    }
  }

  /// Google search — reads API key & CX from SharedPreferences (set during onboarding).
  Future<Map<String, dynamic>> searchGoogle(String query) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final apiKey = prefs.getString('google_api_key') ?? '';
      final cx = prefs.getString('google_cx') ?? '';
      final results = await GoogleScraper.search(query, apiKey: apiKey, cx: cx);
      return {'results': results, 'engine': 'google'};
    } catch (e) {
      return {'results': [], 'error': e.toString(), 'engine': 'google'};
    }
  }

  // ── Publishing ──

  Future<String?> _tryPublishToGateway(String gateway, {File? zipFile, List<int>? bytes, String? filename}) async {
    final url = '$gateway/proxy/publish_feedo';
    try {
      var request = http.MultipartRequest('POST', Uri.parse(url));
      if (zipFile != null) {
        request.files.add(await http.MultipartFile.fromPath('file', zipFile.path, contentType: http.MediaType('application', 'zip')));
      } else if (bytes != null) {
        request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename ?? 'site.zip', contentType: http.MediaType('application', 'zip')));
      } else {
        return null;
      }
      var streamedResponse = await request.send();
      var response = await http.Response.fromStream(streamedResponse);
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final cid = data['cid'];
        if (cid != null) {
          if (gateway != searchProxyUrl) { searchProxyUrl = gateway; consensusUrl = '$gateway/consensus'; }
          return cid;
        }
      }
    } catch (_) {}
    return null;
  }

  Future<String?> publishToFeedoStorage(File zipFile) async {
    for (final gateway in [searchProxyUrl, ...gateways.where((g) => g != searchProxyUrl)]) {
      final cid = await _tryPublishToGateway(gateway, zipFile: zipFile);
      if (cid != null) return cid;
    }
    return null;
  }

  Future<String?> publishToFeedoStorageBytes(List<int> bytes, String filename) async {
    for (final gateway in [searchProxyUrl, ...gateways.where((g) => g != searchProxyUrl)]) {
      final cid = await _tryPublishToGateway(gateway, bytes: bytes, filename: filename);
      if (cid != null) return cid;
    }
    return null;
  }

  Future<bool> unpinSite(String cid) async {
    try {
      final response = await http.delete(Uri.parse('$searchProxyUrl/proxy/unpin_feedo/$cid'));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // ── Local domains (SharedPreferences) ──

  Future<void> saveMyDomain(String domain, String currentCid) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];
    final Map<String, dynamic> siteInfo = {'domain': domain, 'cid': currentCid};
    domains.removeWhere((d) { try { return jsonDecode(d)['domain'] == domain; } catch (_) { return false; } });
    domains.add(jsonEncode(siteInfo));
    await prefs.setStringList('my_domains', domains);
  }

  Future<List<Map<String, dynamic>>> getMyDomains() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return (prefs.getStringList('my_domains') ?? []).map((e) => jsonDecode(e) as Map<String, dynamic>).toList();
    } catch (_) { return []; }
  }

  Future<void> removeMyDomain(String domain) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];
    domains.removeWhere((d) { try { return jsonDecode(d)['domain'] == domain; } catch (_) { return false; } });
    await prefs.setStringList('my_domains', domains);
  }

  Future<void> fetchAndSaveCertificates() async {}
  Future<void> syncCertificates() async {}
}