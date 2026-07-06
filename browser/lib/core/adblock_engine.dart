class AdblockEngine {
  static final List<String> _blockedDomains = [
    'google-analytics.com',
    'doubleclick.net',
    'facebook.net',
    'connect.facebook.net',
    'adservice.google.com',
    'googlesyndication.com',
    'amazon-adsystem.com',
    'adnxs.com',
    'taboola.com',
    'outbrain.com',
    'criteo.com',
  ];

  static bool shouldBlock(String url) {
    try {
      final uri = Uri.parse(url);
      final host = uri.host.toLowerCase();
      
      for (final domain in _blockedDomains) {
        if (host == domain || host.endsWith('.$domain')) {
          return true;
        }
      }
    } catch (e) {
      // If parsing fails, do not block to avoid breaking pages
    }
    return false;
  }
}
