import bech32

def bech32_encode(hrp, data):
    # For nostr note/nevent we need to convert 8-bit to 5-bit
    converted = bech32.convertbits(data, 8, 5, pad=True)
    return bech32.bech32_encode(hrp, converted, bech32.Encoding.BECH32)

import os
# note
event_id = os.urandom(32)
note_str = bech32_encode('note', event_id)

# nevent (TLV: Type 0 is event_id, length 32)
# TLV: 0 (1 byte) + 32 (1 byte) + event_id (32 bytes)
tlv_data = bytes([0, 32]) + event_id
nevent_str = bech32_encode('nevent', tlv_data)

print(f'void main() {{')
print(f'    print(Bech32.decodeEvent("{note_str}"));')
print(f'    print(Bech32.decodeEvent("{nevent_str}"));')
print(f'}}')
