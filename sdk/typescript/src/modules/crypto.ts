import { encrypt, decrypt } from 'eciesjs';
import * as crypto from 'crypto';

export class FeedoCrypto {
    static generateSymmetricKey(): Buffer {
        return crypto.randomBytes(32);
    }

    static encryptData(key: Buffer, data: Buffer): Buffer {
        const nonce = crypto.randomBytes(12);
        const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce);
        const ciphertext = Buffer.concat([cipher.update(data), cipher.final()]);
        const tag = cipher.getAuthTag();
        return Buffer.concat([nonce, ciphertext, tag]);
    }

    static decryptData(key: Buffer, encryptedData: Buffer): Buffer {
        if (encryptedData.length < 28) {
            throw new Error("Data is too short to be AES-GCM encrypted");
        }
        const nonce = encryptedData.subarray(0, 12);
        const tag = encryptedData.subarray(encryptedData.length - 16);
        const ciphertext = encryptedData.subarray(12, encryptedData.length - 16);

        const decipher = crypto.createDecipheriv('aes-256-gcm', key, nonce);
        decipher.setAuthTag(tag);
        return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    }

    /**
     * @param publicKeyHex hex string of secp256k1 public key
     * @param key symmetric key bytes
     * @returns hex string of the ECIES encrypted symmetric key
     */
    static encryptSymmetricKeyEcies(publicKeyHex: string, key: Buffer): string {
        const pubKey = publicKeyHex.replace('0x', '');
        const encrypted = encrypt(pubKey, key);
        return Buffer.from(encrypted as any).toString('hex');
    }

    /**
     * @param privateKeyHex hex string of secp256k1 private key
     * @param encryptedKeyHex hex string of the ECIES encrypted symmetric key
     * @returns decrypted symmetric key bytes
     */
    static decryptSymmetricKeyEcies(privateKeyHex: string, encryptedKeyHex: string): Buffer {
        const privKey = privateKeyHex.replace('0x', '');
        const encBytes = Buffer.from(encryptedKeyHex.replace('0x', ''), 'hex');
        const decrypted = decrypt(privKey, encBytes);
        return Buffer.from(decrypted);
    }
}
