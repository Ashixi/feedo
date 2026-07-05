import 'package:shared_preferences/shared_preferences.dart';

class RelayService {
  static const _keyRelays = 'nostr_relays';
  
  static final List<String> _defaultRelays = [
    'wss://relay.damus.io',
    'wss://relay.primal.net',
    'wss://nos.lol',
  ];

  static Future<List<String>> getRelays() async {
    final prefs = await SharedPreferences.getInstance();
    final relays = prefs.getStringList(_keyRelays);
    if (relays == null || relays.isEmpty) {
      // Save defaults if empty
      await prefs.setStringList(_keyRelays, _defaultRelays);
      return _defaultRelays;
    }
    return relays;
  }

  static Future<void> addRelay(String url) async {
    final prefs = await SharedPreferences.getInstance();
    final relays = await getRelays();
    if (!relays.contains(url)) {
      relays.add(url);
      await prefs.setStringList(_keyRelays, relays);
    }
  }

  static Future<void> removeRelay(String url) async {
    final prefs = await SharedPreferences.getInstance();
    final relays = await getRelays();
    if (relays.contains(url)) {
      relays.remove(url);
      await prefs.setStringList(_keyRelays, relays);
    }
  }
}
