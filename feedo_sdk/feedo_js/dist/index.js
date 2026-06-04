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
exports.FeedoClient = void 0;
const secp = __importStar(require("@noble/secp256k1"));
class FeedoClient {
    constructor(privateKeyHex, apiUrl = "http://127.0.0.1:8040") {
        this.privateKeyHex = privateKeyHex.replace("0x", "");
        this.apiUrl = apiUrl;
        this.publicKeyHex = this.uint8ArrayToHex(secp.getPublicKey(this.privateKeyHex, true));
    }
    uint8ArrayToHex(bytes) {
        return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    }
    async sha256(message) {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        return this.uint8ArrayToHex(new Uint8Array(hashBuffer));
    }
    async publish(postData) {
        const hashId = await this.sha256(postData.content + Date.now().toString());
        const contentBlobHash = await this.sha256(postData.content);
        const sigBytes = await secp.sign(hashId, this.privateKeyHex);
        const signature = this.uint8ArrayToHex(sigBytes);
        const payload = {
            author: this.publicKeyHex,
            hash_id: hashId,
            content_blob_hash: contentBlobHash,
            signature: signature,
            title: postData.title,
            text: postData.content,
            source_type: postData.type || "native",
            sequence_number: 1
        };
        const response = await fetch(`${this.apiUrl}/local/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            throw new Error(`Failed to publish: ${response.statusText}`);
        }
        return await response.json();
    }
    async query(text, federated = false) {
        const url = new URL(`${this.apiUrl}/query`);
        url.searchParams.append("text", text);
        if (federated) {
            url.searchParams.append("federated", "true");
        }
        const response = await fetch(url.toString());
        if (!response.ok) {
            throw new Error(`Query failed: ${response.statusText}`);
        }
        return await response.json();
    }
}
exports.FeedoClient = FeedoClient;
