import bech32

def bech32_polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d423371, 0x2a1462b3]
    chk = 1
    for i, v in enumerate(values):
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for j in range(5):
            if ((b >> j) & 1):
                chk ^= GEN[j]
        if i < 3:
            print(f"Py chk after {i}: {chk}")
    return chk

def bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def test():
    s = "npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6"
    pos = s.rfind('1')
    hrp = s[:pos]
    data = [bech32.CHARSET.find(x) for x in s[pos+1:]]
    values = bech32_hrp_expand(hrp) + data
    print("Py values:", values[:10])
    print("Py final:", bech32_polymod(values))

test()
