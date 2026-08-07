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
    async uploadFile(fileBlobOrBuffer, filename = 'file') {
        const formData = new FormData();
        formData.append('file', fileBlobOrBuffer, filename);
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
    async downloadFile(hash) {
        // Returns raw data, which for SDK might be better handled directly or as a buffer
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
        const response = await axios_1.default.get(url, { responseType: 'arraybuffer', headers });
        return response.data;
    }
    async ingestJson(payload) {
        return this.request('POST', '/api/v1/ingest/post', payload);
    }
    async getRecentFiles() {
        return this.request('GET', '/api/files/recent');
    }
}
exports.StorageModule = StorageModule;
