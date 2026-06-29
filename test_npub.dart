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
    
    int polymod = _polymod(_expandHrp(str.substring(0, pos)) + data);
    print("Polymod: $polymod");
    if (polymod != 1) {
      throw Exception('Invalid checksum');
    }
    return data.sublist(0, data.length - 6);
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
          chk ^= [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3][j];
        }
      }
    }
    return chk;
  }
}

void main() {
    try {
        Bech32.decode("npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6");
    } catch (e) {
        print(e);
    }
}
