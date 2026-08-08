"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.StorageModule = void 0;
const axios_1 = __importDefault(require("axios"));
const ethers_1 = require("ethers");
class StorageModule {
    router;
    privateKey;
    constructor(router, privateKey) {
        this.router = router;
        this.privateKey = privateKey;
    }
    async request(method, path, data, isMultipart = false) {
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}${path}`;
        const headers = {};
        if (this.privateKey) {
            const wallet = new ethers_1.ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:${method}:${path}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }
        try {
            const response = await (0, axios_1.default)({ method, url, data, headers });
            return response.data;
        }
        catch (error) {
            console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await (0, axios_1.default)({ method, url, data, headers });
            return retryResponse.data;
        }
    }
    async uploadSingleChunk(fileBlobOrBuffer, filename) {
        let finalData = fileBlobOrBuffer;
        if (typeof Buffer !== 'undefined' && Buffer.isBuffer(fileBlobOrBuffer)) {
            finalData = new Blob([fileBlobOrBuffer]);
        }
        else if (fileBlobOrBuffer instanceof Uint8Array) {
            finalData = new Blob([fileBlobOrBuffer]);
        }
        const formData = new FormData();
        formData.append('file', finalData, filename);
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}/upload`;
        const headers = {};
        if (this.privateKey) {
            const wallet = new ethers_1.ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:POST:/upload:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }
        try {
            const response = await fetch(url, { method: 'POST', headers, body: formData });
            if (!response.ok)
                throw new Error(await response.text());
            return await response.text();
        }
        catch (error) {
            console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            url = `${baseUrl}/upload`;
            const retryResponse = await fetch(url, { method: 'POST', headers, body: formData });
            if (!retryResponse.ok)
                throw new Error(await retryResponse.text());
            return await retryResponse.text();
        }
    }
    async uploadFile(fileBlobOrBuffer, filename = 'file') {
        let size = 0;
        if (fileBlobOrBuffer.size !== undefined)
            size = fileBlobOrBuffer.size;
        else if (fileBlobOrBuffer.byteLength !== undefined)
            size = fileBlobOrBuffer.byteLength;
        else if (fileBlobOrBuffer.length !== undefined)
            size = fileBlobOrBuffer.length;
        const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB
        if (size <= CHUNK_SIZE) {
            return this.uploadSingleChunk(fileBlobOrBuffer, filename);
        }
        // Chunking logic
        const chunks = [];
        let offset = 0;
        while (offset < size) {
            let chunk;
            if (fileBlobOrBuffer.slice) {
                // Blob or Buffer
                chunk = fileBlobOrBuffer.slice(offset, offset + CHUNK_SIZE);
            }
            else if (fileBlobOrBuffer.subarray) {
                // Uint8Array
                chunk = fileBlobOrBuffer.subarray(offset, offset + CHUNK_SIZE);
            }
            else {
                throw new Error("Unsupported file type for chunking");
            }
            chunks.push(chunk);
            offset += CHUNK_SIZE;
        }
        // Upload chunks with promise pool
        const limit = 10;
        const hashes = new Array(chunks.length);
        let i = 0;
        const workers = new Array(limit).fill(0).map(async () => {
            while (i < chunks.length) {
                const index = i++;
                const chunkFilename = `${filename}.part${index}`;
                hashes[index] = await this.uploadSingleChunk(chunks[index], chunkFilename);
            }
        });
        await Promise.all(workers);
        // Create manifest
        const manifest = {
            type: "feedo_manifest",
            filename: filename,
            total_size: size,
            chunk_size: CHUNK_SIZE,
            chunks: hashes
        };
        const manifestString = JSON.stringify(manifest);
        let manifestData;
        if (typeof Blob !== 'undefined') {
            manifestData = new Blob([manifestString], { type: 'application/json' });
        }
        else {
            manifestData = Buffer.from(manifestString, 'utf-8');
        }
        return await this.uploadSingleChunk(manifestData, 'manifest.json');
    }
    async downloadSingleChunk(hash) {
        let baseUrl = await this.router.getStorageNode();
        let path = `/download/${encodeURIComponent(hash)}`;
        let url = `${baseUrl}${path}`;
        const headers = {};
        if (this.privateKey) {
            const wallet = new ethers_1.ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:GET:${path}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }
        try {
            const response = await axios_1.default.get(url, { responseType: 'arraybuffer', headers });
            return response.data;
        }
        catch (error) {
            console.warn(`Download failed on ${baseUrl}, trying new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            path = `/download/${encodeURIComponent(hash)}`;
            url = `${baseUrl}${path}`;
            const retryResponse = await axios_1.default.get(url, { responseType: 'arraybuffer', headers });
            return retryResponse.data;
        }
    }
    async downloadFile(hash) {
        const rawData = await this.downloadSingleChunk(hash);
        // If it's small, it might be a manifest
        if (rawData.byteLength < 1024 * 1024) {
            try {
                const text = new TextDecoder().decode(rawData);
                const json = JSON.parse(text);
                if (json.type === 'feedo_manifest' && Array.isArray(json.chunks)) {
                    // Download chunks with promise pool
                    const limit = 10;
                    const chunks = new Array(json.chunks.length);
                    let i = 0;
                    const workers = new Array(limit).fill(0).map(async () => {
                        while (i < json.chunks.length) {
                            const index = i++;
                            chunks[index] = await this.downloadSingleChunk(json.chunks[index]);
                        }
                    });
                    await Promise.all(workers);
                    // Concatenate chunks
                    let totalLen = chunks.reduce((acc, c) => acc + c.byteLength, 0);
                    let result = new Uint8Array(totalLen);
                    let offset = 0;
                    for (let c of chunks) {
                        result.set(new Uint8Array(c), offset);
                        offset += c.byteLength;
                    }
                    return result.buffer;
                }
            }
            catch (e) {
                // Not a manifest or not JSON, fallback to returning raw data
            }
        }
        return rawData;
    }
    async ingestJson(payload) {
        return this.request('POST', '/api/v1/ingest/post', payload);
    }
    async getRecentFiles() {
        return this.request('GET', '/api/files/recent');
    }
}
exports.StorageModule = StorageModule;
