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
        this.search = new search_1.SearchModule(this.router, config?.privateKey, config?.usageKey, config?.did);
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
        console.log("[DEBUG] Encrypting and uploading chunks...");
        const CHUNK_SIZE = 5 * 1024 * 1024;
        const size = fileBuffer.byteLength;
        const chunks = [];
        let offset = 0;
        while (offset < size) {
            const chunk = fileBuffer.subarray(offset, offset + CHUNK_SIZE);
            chunks.push(FeedoCrypto.encryptData(symKey, chunk));
            offset += CHUNK_SIZE;
        }
        const limit = 10;
        const hashes = new Array(chunks.length);
        let i = 0;
        const workers = new Array(limit).fill(0).map(async () => {
            while (i < chunks.length) {
                const index = i++;
                const chunkFilename = `encrypted_part${index}`;
                // Accessing private method for SDK internal chunk upload
                hashes[index] = await this.storage.uploadSingleChunk(chunks[index], chunkFilename);
            }
        });
        await Promise.all(workers);
        const manifest = {
            type: "feedo_encrypted_manifest",
            filename: 'encrypted_file.bin',
            total_size: size,
            chunk_size: CHUNK_SIZE,
            chunks: hashes
        };
        const manifestString = JSON.stringify(manifest);
        const manifestData = Buffer.from(manifestString, 'utf-8');
        const hashId = await this.storage.uploadSingleChunk(manifestData, 'manifest.json');
        console.log("[DEBUG] uploadPrivateFile finished, hashId:", hashId);
        const encSymKey = FeedoCrypto.encryptSymmetricKeyEcies(targetPubKey, symKey);
        const payloadBytes = Buffer.from(`${hashId}${targetDid}${encSymKey}`, 'utf-8');
        const signature = await wallet.signMessage(payloadBytes);
        console.log("[DEBUG] Calling consensus.grantFileAccess...");
        await this.consensus.grantFileAccess(hashId, targetDid, encSymKey, myPublicKey, signature);
        console.log("[DEBUG] grantFileAccess finished");
        if (indexForSearch && targetDid === myDid) {
            if (size > 30 * 1024 * 1024) {
                console.log("[DEBUG] File > 30MB, skipping search indexing (Vectorization bypass)");
            }
            else {
                if (metadata.type === "image") {
                    console.log("[DEBUG] Calling search.indexImage...");
                    // Pass the symmetric key so search node can decrypt and vectorize
                    await this.search.indexImage(hashId, metadata, symKey.toString('hex'));
                    console.log("[DEBUG] indexImage finished");
                }
                else {
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
        const rawData = await this.storage.downloadFile(hashId);
        // Check if it's an encrypted manifest
        if (rawData.byteLength < 1024 * 1024) {
            try {
                const text = new TextDecoder().decode(rawData);
                const json = JSON.parse(text);
                if (json.type === 'feedo_encrypted_manifest' && Array.isArray(json.chunks)) {
                    const limit = 10;
                    const decryptedChunks = new Array(json.chunks.length);
                    let i = 0;
                    const workers = new Array(limit).fill(0).map(async () => {
                        while (i < json.chunks.length) {
                            const index = i++;
                            const encChunkRaw = await this.storage.downloadSingleChunk(json.chunks[index]);
                            const encChunk = Buffer.from(encChunkRaw);
                            decryptedChunks[index] = FeedoCrypto.decryptData(symKey, encChunk);
                        }
                    });
                    await Promise.all(workers);
                    return Buffer.concat(decryptedChunks);
                }
            }
            catch (e) {
                // Not an encrypted manifest, handle as single encrypted file for backwards compatibility
            }
        }
        const encryptedData = Buffer.from(rawData);
        return FeedoCrypto.decryptData(symKey, encryptedData);
    }
}
exports.FeedoClient = FeedoClient;
