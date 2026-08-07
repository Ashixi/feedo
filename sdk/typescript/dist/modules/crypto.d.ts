export declare class FeedoCrypto {
    static generateSymmetricKey(): Buffer;
    static encryptData(key: Buffer, data: Buffer): Buffer;
    static decryptData(key: Buffer, encryptedData: Buffer): Buffer;
    /**
     * @param publicKeyHex hex string of secp256k1 public key
     * @param key symmetric key bytes
     * @returns hex string of the ECIES encrypted symmetric key
     */
    static encryptSymmetricKeyEcies(publicKeyHex: string, key: Buffer): string;
    /**
     * @param privateKeyHex hex string of secp256k1 private key
     * @param encryptedKeyHex hex string of the ECIES encrypted symmetric key
     * @returns decrypted symmetric key bytes
     */
    static decryptSymmetricKeyEcies(privateKeyHex: string, encryptedKeyHex: string): Buffer;
}
