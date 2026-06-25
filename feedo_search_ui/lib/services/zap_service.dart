import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

class ZapService {
  /// Send a zap by resolving the lud16, fetching an invoice, and launching the wallet.
  static Future<bool> sendZap(String lud16, int amountSats, String comment) async {
    try {
      final parts = lud16.split('@');
      if (parts.length != 2) return false;
      
      final username = parts[0];
      final domain = parts[1];
      
      final lnurlpUrl = Uri.parse('https://$domain/.well-known/lnurlp/$username');
      final res = await http.get(lnurlpUrl).timeout(const Duration(seconds: 10));
      
      if (res.statusCode != 200) return false;
      
      final lnurlData = jsonDecode(res.body);
      final callback = lnurlData['callback'] as String?;
      if (callback == null) return false;
      
      // Amount is in millisatoshis
      final amountMsat = amountSats * 1000;
      
      var callbackUri = Uri.parse(callback);
      var queryParams = Map<String, String>.from(callbackUri.queryParameters);
      queryParams['amount'] = amountMsat.toString();
      if (comment.isNotEmpty) {
        queryParams['comment'] = comment;
      }
      
      callbackUri = callbackUri.replace(queryParameters: queryParams);
      
      final invoiceRes = await http.get(callbackUri).timeout(const Duration(seconds: 10));
      if (invoiceRes.statusCode != 200) return false;
      
      final invoiceData = jsonDecode(invoiceRes.body);
      final pr = invoiceData['pr'] as String?; // bolt11 invoice
      if (pr == null) return false;
      
      // Launch Lightning wallet
      final lightningUri = Uri.parse('lightning:$pr');
      if (await canLaunchUrl(lightningUri)) {
        await launchUrl(lightningUri, mode: LaunchMode.externalApplication);
        return true;
      } else {
        // Fallback or Web PWA handling
        throw pr; // We throw the invoice so UI can catch it and display it
      }
    } catch (e) {
      if (e is String) rethrow; // Rethrow invoice string
      return false;
    }
  }
}
