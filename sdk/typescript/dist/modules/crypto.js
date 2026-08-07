"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.FeedoCrypto = void 0;
const eciesjs_1 = require("eciesjs");
const crypto = __importStar(require("crypto"));
class FeedoCrypto {
    static generateSymmetricKey() {
        return crypto.randomBytes(32);
    }
    static encryptData(key, data) {
        const nonce = crypto.randomBytes(12);
        const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce);
        const ciphertext = Buffer.concat([cipher.update(data), cipher.final()]);
        const tag = cipher.getAuthTag();
        return Buffer.concat([nonce, ciphertext, tag]);
    }
    static decryptData(key, encryptedData) {
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
    static encryptSymmetricKeyEcies(publicKeyHex, key) {
        const pubKey = publicKeyHex.replace('0x', '');
        const encrypted = (0, eciesjs_1.encrypt)(pubKey, key);
        return Buffer.from(encrypted).toString('hex');
    }
    /**
     * @param privateKeyHex hex string of secp256k1 private key
     * @param encryptedKeyHex hex string of the ECIES encrypted symmetric key
     * @returns decrypted symmetric key bytes
     */
    static decryptSymmetricKeyEcies(privateKeyHex, encryptedKeyHex) {
        const privKey = privateKeyHex.replace('0x', '');
        const encBytes = Buffer.from(encryptedKeyHex.replace('0x', ''), 'hex');
        const decrypted = (0, eciesjs_1.decrypt)(privKey, encBytes);
        return Buffer.from(decrypted);
    }
}
exports.FeedoCrypto = FeedoCrypto;
