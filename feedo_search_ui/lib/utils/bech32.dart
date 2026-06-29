import 'dart:typed_data';

class Bech32 {
  static const String charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

  static List<int> decode(String str) {
    if (str.length < 8) throw Exception('Too short');
    bool hasLower = false;
    bool hasUpper = false;
    for (int i = 0; i < str.length; i++) {
      int c = str.codeUnitAt(i);
      if (c < 33 || c > 126) throw Exception('Invalid character');
      if (c >= 97 && c <= 122) hasLower = true;
      if (c >= 65 && c <= 90) hasUpper = true;
    }
    if (hasLower && hasUpper) throw Exception('Mixed case');
    str = str.toLowerCase();
    int pos = str.lastIndexOf('1');
    if (pos < 1 || pos + 7 > str.length) throw Exception('No separator character');
    
    List<int> data = [];
    for (int i = pos + 1; i < str.length; i++) {
      int d = charset.indexOf(str[i]);
      if (d == -1) throw Exception('Invalid character in data part');
      data.add(d);
    }
    
    if (!_verifyChecksum(str.substring(0, pos), data)) {
      throw Exception('Invalid checksum');
    }
    return data.sublist(0, data.length - 6);
  }

  static bool _verifyChecksum(String hrp, List<int> data) {
    return _polymod(_expandHrp(hrp) + data) == 1;
  }

  static List<int> _expandHrp(String hrp) {
    List<int> ret = [];
    for (int i = 0; i < hrp.length; i++) {
      ret.add(hrp.codeUnitAt(i) >> 5);
    }
    ret.add(0);
    for (int i = 0; i < hrp.length; i++) {
      ret.add(hrp.codeUnitAt(i) & 31);
    }
    return ret;
  }

  static int _polymod(List<int> values) {
    int chk = 1;
    for (int i = 0; i < values.length; i++) {
      int top = chk >> 25;
      chk = (chk & 0x1ffffff) << 5 ^ values[i];
      for (int j = 0; j < 5; j++) {
        if (((top >> j) & 1) != 0) {
          chk ^= [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d423371, 0x2a1462b3][j];
        }
      }
    }
    return chk;
  }

  static List<int> convertBits(List<int> data, int fromBits, int toBits, bool pad) {
    int acc = 0;
    int bits = 0;
    List<int> ret = [];
    int maxv = (1 << toBits) - 1;
    int maxAcc = (1 << (fromBits + toBits - 1)) - 1;
    for (int i = 0; i < data.length; i++) {
      int value = data[i];
      if (value < 0 || (value >> fromBits) != 0) throw Exception('Invalid value');
      acc = ((acc << fromBits) | value) & maxAcc;
      bits += fromBits;
      while (bits >= toBits) {
        bits -= toBits;
        ret.add((acc >> bits) & maxv);
      }
    }
    if (pad) {
      if (bits > 0) {
        ret.add((acc << (toBits - bits)) & maxv);
      }
    } else if (bits >= fromBits || ((acc << (toBits - bits)) & maxv) != 0) {
      throw Exception('Invalid padding');
    }
    return ret;
  }

  static ({String pubkey, List<String> relays}) decodeProfile(String bech32Str) {
    if (bech32Str.startsWith('nostr:')) {
      bech32Str = bech32Str.substring(6);
    }
    try {
      List<int> data = decode(bech32Str);
      List<int> bytes = convertBits(data, 5, 8, false);
      
      if (bech32Str.startsWith('nprofile')) {
        String pubkey = '';
        List<String> relays = [];
        int i = 0;
        while (i < bytes.length) {
          int t = bytes[i];
          int l = bytes[i+1];
          if (t == 0 && l == 32) {
            pubkey = bytes.sublist(i+2, i+2+32).map((b) => b.toRadixString(16).padLeft(2, '0')).join('');
          } else if (t == 1) {
            try {
              relays.add(String.fromCharCodes(bytes.sublist(i+2, i+2+l)));
            } catch (_) {}
          }
          i += 2 + l;
        }
        return (pubkey: pubkey, relays: relays);
      } else if (bech32Str.startsWith('npub')) {
        return (pubkey: bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join(''), relays: []);
      }
    } catch (e) {}
    return (pubkey: '', relays: []);
  }

  static ({String eventId, List<String> relays}) decodeEvent(String bech32Str) {
    if (bech32Str.startsWith('nostr:')) {
      bech32Str = bech32Str.substring(6);
    }
    try {
      List<int> data = decode(bech32Str);
      List<int> bytes = convertBits(data, 5, 8, false);
      
      if (bech32Str.startsWith('nevent')) {
        String eventId = '';
        List<String> relays = [];
        int i = 0;
        while (i < bytes.length) {
            int t = bytes[i];
            int l = bytes[i+1];
            if (t == 0 && l == 32) {
                eventId = bytes.sublist(i+2, i+2+32).map((b) => b.toRadixString(16).padLeft(2, '0')).join('');
            } else if (t == 1) {
                try {
                    relays.add(String.fromCharCodes(bytes.sublist(i+2, i+2+l)));
                } catch (_) {}
            }
            i += 2 + l;
        }
        return (eventId: eventId, relays: relays);
      } else if (bech32Str.startsWith('note')) {
        return (eventId: bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join(''), relays: []);
      }
    } catch (e) {}
    return (eventId: '', relays: []);
  }

  static String decodeToHex(String bech32Str) {
    return decodeProfile(bech32Str).pubkey;
  }
}
