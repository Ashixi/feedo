"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.FeedoClient = void 0;
const router_1 = require("./router");
const search_1 = require("./modules/search");
const consensus_1 = require("./modules/consensus");
const storage_1 = require("./modules/storage");
class FeedoClient {
    search;
    consensus;
    storage;
    router;
    constructor(config) {
        this.router = new router_1.NodeRouter(config);
        this.search = new search_1.SearchModule(this.router, config?.privateKey);
        this.consensus = new consensus_1.ConsensusModule(this.router, config?.privateKey);
        this.storage = new storage_1.StorageModule(this.router, config?.privateKey);
    }
    async uploadPrivateFile(fileBuffer, granteePublicKeyHex, indexForSearch = true, metadata = {}) {
        if (!this.search['privateKey']) {
            throw new Error("Private key required to upload private files");
        }
        const privateKey = this.search['privateKey'];
        const { ethers } = require('ethers');
        const wallet = new ethers.Wallet(privateKey);
        const myDid = `did:feedo:${wallet.address}`;
        const myPublicKey = wallet.signingKey.publicKey;
        const targetPubKey = granteePublicKeyHex || myPublicKey;
        const targetDid = granteePublicKeyHex ? "unknown" : myDid;
        const { FeedoCrypto } = require('./modules/crypto');
        const symKey = FeedoCrypto.generateSymmetricKey();
        const encryptedData = FeedoCrypto.encryptData(symKey, fileBuffer);
        const blob = new Blob([encryptedData]);
        console.log("[DEBUG] Calling storage.uploadFile...");
        const hashId = await this.storage.uploadFile(blob, 'encrypted_file.bin');
        console.log("[DEBUG] uploadFile finished, hashId:", hashId);
        const encSymKey = FeedoCrypto.encryptSymmetricKeyEcies(targetPubKey, symKey);
        const payloadBytes = Buffer.from(`${hashId}${targetDid}${encSymKey}`, 'utf-8');
        const signature = await wallet.signMessage(payloadBytes);
        console.log("[DEBUG] Calling consensus.grantFileAccess...");
        await this.consensus.grantFileAccess(hashId, targetDid, encSymKey, myPublicKey, signature);
        console.log("[DEBUG] grantFileAccess finished");
        if (indexForSearch && targetDid === myDid) {
            try {
                const textContent = fileBuffer.toString('utf-8');
                console.log("[DEBUG] Calling search.indexPrivateDocument...");
                await this.search.indexPrivateDocument(hashId, textContent, metadata);
                console.log("[DEBUG] indexPrivateDocument finished");
            }
            catch (e) {
                // Not text
            }
        }
        return hashId;
    }
    async downloadPrivateFile(hashId) {
        if (!this.search['privateKey']) {
            throw new Error("Private key required to download private files");
        }
        const privateKey = this.search['privateKey'];
        const { ethers } = require('ethers');
        const wallet = new ethers.Wallet(privateKey);
        const myDid = `did:feedo:${wallet.address}`;
        const res = await this.consensus.getFileAccess(hashId, myDid);
        const encSymKey = res.encrypted_symmetric_key;
        if (!encSymKey) {
            throw new Error(`No access granted for ${myDid} to file ${hashId}`);
        }
        const { FeedoCrypto } = require('./modules/crypto');
        const symKey = FeedoCrypto.decryptSymmetricKeyEcies(privateKey, encSymKey);
        const encryptedDataArrayBuffer = await this.storage.downloadFile(hashId);
        const encryptedData = Buffer.from(encryptedDataArrayBuffer);
        return FeedoCrypto.decryptData(symKey, encryptedData);
    }
}
exports.FeedoClient = FeedoClient;
