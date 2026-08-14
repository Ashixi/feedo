export declare class FeedoCrypto {
    static generateSymmetricKey(): Buffer;
    /**
     * Deterministically derive the usage key (0xD) from the wallet key (0xW).
     * usage_sk = HMAC-SHA256(key=wallet_sk, msg="feedo/usage-key/v1") mod n
     * The derived key can sign requests but cannot move funds (USDT stay on 0xW).
     */
    static deriveUsageKey(walletPrivateKeyHex: string): {
        privateKey: string;
        address: string;
    };
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
