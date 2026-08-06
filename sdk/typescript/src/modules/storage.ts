import axios from 'axios';
import { NodeRouter } from '../router';
import { ethers } from 'ethers';

export class StorageModule {
    constructor(private router: NodeRouter, private privateKey?: string) {}

    private async request(method: string, path: string, data?: any, isMultipart: boolean = false) {
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}${path}`;
        
        const headers: any = {};
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
        } catch (error: any) {
            console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data, headers });
            return retryResponse.data;
        }
    }

    async uploadFile(fileBlobOrBuffer: any, filename: string = 'file') {
        const formData = new FormData();
        formData.append('file', fileBlobOrBuffer, filename);
        return this.request('POST', '/upload', formData, true);
    }

    async downloadFile(hash: string) {
        // Returns raw data, which for SDK might be better handled directly or as a buffer
        let baseUrl = await this.router.getStorageNode();
        let path = `/download/${encodeURIComponent(hash)}`;
        let url = `${baseUrl}${path}`;
        
        const headers: any = {};
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

    async ingestJson(payload: any) {
        return this.request('POST', '/api/v1/ingest/post', payload);
    }

    async getRecentFiles() {
        return this.request('GET', '/api/files/recent');
    }
}
