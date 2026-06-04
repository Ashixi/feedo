import nacl from 'tweetnacl';

export class KeyManager {
    private keyPair: nacl.SignKeyPair;

    constructor(privateKeyHex?: string) {
        if (privateKeyHex) {
            const secretKey = KeyManager.hexToBytes(privateKeyHex.replace("0x", ""));
            // tweetnacl secret keys are 64 bytes (32 byte seed + 32 byte public key)
            // if we are given 32 bytes, we can generate from seed. If 64, fromSecretKey
            if (secretKey.length === 32) {
                this.keyPair = nacl.sign.keyPair.fromSeed(secretKey);
            } else if (secretKey.length === 64) {
                this.keyPair = nacl.sign.keyPair.fromSecretKey(secretKey);
            } else {
                throw new Error("Invalid private key length");
            }
        } else {
            this.keyPair = nacl.sign.keyPair();
        }
    }

    public static hexToBytes(hex: string): Uint8Array {
        if (hex.length % 2 !== 0) throw new Error('Invalid hex string');
        const bytes = new Uint8Array(hex.length / 2);
        for (let i = 0; i < hex.length; i += 2) {
            bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
        }
        return bytes;
    }

    public static bytesToHex(bytes: Uint8Array): string {
        return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    public getPrivateKeyHex(): string {
        return KeyManager.bytesToHex(this.keyPair.secretKey);
    }

    public getPublicKeyHex(): string {
        return KeyManager.bytesToHex(this.keyPair.publicKey);
    }

    public getDid(): string {
        return `did:feedo:${this.getPublicKeyHex()}`;
    }

    public getWalletAddress(): string {
        return this.getPublicKeyHex();
    }

    public sign(messageHashHex: string): string {
        const messageHashBytes = KeyManager.hexToBytes(messageHashHex);
        const signatureBytes = nacl.sign.detached(messageHashBytes, this.keyPair.secretKey);
        return KeyManager.bytesToHex(signatureBytes);
    }

    public static verify(signatureHex: string, messageHashHex: string, publicKeyHex: string): boolean {
        return nacl.sign.detached.verify(
            KeyManager.hexToBytes(messageHashHex),
            KeyManager.hexToBytes(signatureHex),
            KeyManager.hexToBytes(publicKeyHex)
        );
    }
    
    public static async hashAsync(message: string): Promise<string> {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        return KeyManager.bytesToHex(new Uint8Array(hashBuffer));
    }
}
