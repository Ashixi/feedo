import axios from 'axios';
import { NodeRouter } from '../router';
import { ethers } from 'ethers';

export class SearchModule {
    constructor(private router: NodeRouter, private privateKey?: string) {}

    private async request(method: string, path: string, data?: any) {
        let baseUrl = await this.router.getSearchNode();
        let url = `${baseUrl}${path}`;
        
        const headers: any = {};
        if (this.privateKey) {
            const wallet = new ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const basePath = path.split('?')[0]; // server reconstructs payload using path WITHOUT query string
            const payload = `FeedoAction:${method}:${basePath}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }

        try {
            const response = await axios({ method, url, data, headers });
            return response.data;
        } catch (error: any) {
            // Basic retry logic with a new node on failure
            console.warn(`Search request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateSearchNode();
            baseUrl = await this.router.getSearchNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data, headers });
            return retryResponse.data;
        }
    }

    async search(query: string, limit: number = 50, federated: boolean = true, itemType: string = "all", offset: number = 0, appId?: string) {
        let qs = `text=${encodeURIComponent(query)}&limit=${limit}&federated=${federated}&item_type=${itemType}&offset=${offset}`;
        if (appId) qs += `&app_id=${encodeURIComponent(appId)}`;
        return this.request('GET', `/query?${qs}`);
    }

    async getDocuments(limit: number = 50, offset: number = 0, itemType: string = "all", appId?: string) {
        let qs = `limit=${limit}&offset=${offset}&item_type=${itemType}`;
        if (appId) qs += `&app_id=${encodeURIComponent(appId)}`;
        return this.request('GET', `/documents?${qs}`);
    }

    async indexPrivateDocument(hashId: string, plaintext: string, metadata: Record<string, any> = {}) {
        if (!this.privateKey) {
            throw new Error("Private key required to index private documents");
        }
        const wallet = new ethers.Wallet(this.privateKey);
        const myDid = `did:feedo:${wallet.address}`;
        
        return this.request('POST', '/index_document', {
            hash_id: hashId,
            text: plaintext,
            item_type: "private_post",
            author: myDid,
            metadata: metadata
        });
    }

    async indexDocument(content: string, metadata: Record<string, any> = {}) {
        // Generate a random hash_id to satisfy the backend requirement
        const hash_id = 'doc_' + Math.random().toString(36).substring(7);
        const item_type = metadata.type || "document";
        // Send 'text: content' because the backend expects the field 'text'
        return this.request('POST', '/index_document', { text: content, metadata, hash_id, item_type });
    }

    async deployProxy(directoryPath: string, domain: string) {
        return this.request('POST', '/proxy/publish_feedo', { source_dir: directoryPath, domain });
    }

    async unpin(cid: string) {
        return this.request('DELETE', `/proxy/unpin_feedo/${cid}`);
    }

    async getStats() {
        return this.request('GET', '/explorer/stats');
    }
}
