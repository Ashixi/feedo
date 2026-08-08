import axios from 'axios';
import { ethers } from 'ethers';
export class StorageModule {
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
        if (isMultipart) {
            headers['Content-Type'] = 'multipart/form-data';
        }
        if (this.privateKey) {
            const wallet = new ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:${method}:${path}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }
        try {
            const response = await axios({ method, url, data, headers });
            return response.data;
        }
        catch (error) {
            console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data, headers });
            return retryResponse.data;
        }
    }
    async uploadFile(fileBlobOrBuffer, filename = 'file') {
        const formData = new FormData();
        formData.append('file', fileBlobOrBuffer, filename);
        return this.request('POST', '/upload', formData, true);
    }
    async downloadFile(hash) {
        // Returns raw data, which for SDK might be better handled directly or as a buffer
        let baseUrl = await this.router.getStorageNode();
        let path = `/download/${encodeURIComponent(hash)}`;
        let url = `${baseUrl}${path}`;
        const headers = {};
        if (this.privateKey) {
            const wallet = new ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:GET:${path}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }
        const response = await axios.get(url, { responseType: 'arraybuffer', headers });
        return response.data;
    }
    async ingestJson(payload) {
        return this.request('POST', '/api/v1/ingest/post', payload);
    }
    async getRecentFiles() {
        return this.request('GET', '/api/files/recent');
    }
}
