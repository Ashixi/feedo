import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;
import 'package:shared_preferences/shared_preferences.dart';
import 'crypto_utils.dart';

import 'dart:math';

class ApiClient {
  static final List<String> gateways = [
    'https://api2.feedo.ink',
  ];

  late String baseUrl;
  late String consensusUrl;
  late String searchProxyUrl;
  late String storageNodeUrl;

  final ed.KeyPair keyPair;
  late String did;

  ApiClient(this.keyPair) {
    did = 'did:feedo:${CryptoUtils.getPublicKeyHex(keyPair.publicKey).substring(2)}';
    
    // Вибираємо випадкову ноду для балансування навантаження
    baseUrl = gateways[Random().nextInt(gateways.length)];
    consensusUrl = '$baseUrl/consensus';
    searchProxyUrl = '$baseUrl/search';
    storageNodeUrl = '$baseUrl/storage';
  }

  Future<bool> registerDid() async {
    final response = await http.post(
      Uri.parse('$consensusUrl/did/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'public_key': CryptoUtils.getPublicKeyHex(keyPair.publicKey)}),
    );
    return response.statusCode == 200;
  }

  Future<bool> registerName(String name) async {
    final message = '$name$did';
    final signature = CryptoUtils.signMessage(keyPair.privateKey, message);

    final response = await http.post(
      Uri.parse('$consensusUrl/name/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'did': did,
        'public_key': CryptoUtils.getPublicKeyHex(keyPair.publicKey),
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
    var request = http.MultipartRequest('POST', Uri.parse('$searchProxyUrl/proxy/publish'));
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
    final signature = CryptoUtils.signMessage(keyPair.privateKey, message);

    final response = await http.post(
      Uri.parse('$consensusUrl/name/update_cid'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'cid': cid,
        'signature': signature,
      }),
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
        return data['cid'];
      }
    }
    return null;
  }

  Future<String?> publishToFeedoStorage(File zipFile) async {
    final url = '$searchProxyUrl/proxy/publish_feedo';
    print('DEBUG: Sending POST to $url');
    try {
      var request = http.MultipartRequest('POST', Uri.parse(url));
      request.files.add(await http.MultipartFile.fromPath('file', zipFile.path));
      
      var streamedResponse = await request.send();
      var response = await http.Response.fromStream(streamedResponse);
      
      print('DEBUG: Response status: ${response.statusCode}, body: ${response.body}');
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['cid'];
      }
    } catch (e, stackTrace) {
      print('DEBUG: Exception in publishToFeedoStorage: $e');
      print('DEBUG: StackTrace: $stackTrace');
    }
    return null;
  }

  Future<bool> unpinSite(String cid, {bool isFeedoStorage = false}) async {
    final url = isFeedoStorage 
        ? '$storageNodeUrl/delete/$cid' 
        : '$searchProxyUrl/proxy/unpin/$cid';
    
    try {
      final response = await http.delete(Uri.parse(url));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  Future<void> saveMyDomain(String domain, String currentCid, bool isFeedo) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];
    
    final Map<String, dynamic> siteInfo = {
      'domain': domain,
      'cid': currentCid,
      'isFeedo': isFeedo,
    };
    
    domains.removeWhere((d) {
       final map = jsonDecode(d);
       return map['domain'] == domain;
    });
    
    domains.add(jsonEncode(siteInfo));
    await prefs.setStringList('my_domains', domains);
  }

  Future<List<Map<String, dynamic>>> getMyDomains() async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> domains = prefs.getStringList('my_domains') ?? [];
    return domains.map((d) => jsonDecode(d) as Map<String, dynamic>).toList();
  }
}
