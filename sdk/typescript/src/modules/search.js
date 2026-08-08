import axios from 'axios';
import { ethers } from 'ethers';
export class SearchModule {
    router;
    privateKey;
    constructor(router, privateKey) {
        this.router = router;
        this.privateKey = privateKey;
    }
    async request(method, path, data) {
        let baseUrl = await this.router.getSearchNode();
        let url = `${baseUrl}${path}`;
        const headers = {};
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
            // Basic retry logic with a new node on failure
            console.warn(`Search request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateSearchNode();
            baseUrl = await this.router.getSearchNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data, headers });
            return retryResponse.data;
        }
    }
    async search(query, limit = 50, federated = true, itemType = "all", offset = 0, appId) {
        let qs = `text=${encodeURIComponent(query)}&limit=${limit}&federated=${federated}&item_type=${itemType}&offset=${offset}`;
        if (appId)
            qs += `&app_id=${encodeURIComponent(appId)}`;
        return this.request('GET', `/query?${qs}`);
    }
    async getDocuments(limit = 50, offset = 0, itemType = "all", appId) {
        let qs = `limit=${limit}&offset=${offset}&item_type=${itemType}`;
        if (appId)
            qs += `&app_id=${encodeURIComponent(appId)}`;
        return this.request('GET', `/documents?${qs}`);
    }
    async indexPrivateDocument(hashId, plaintext, metadata = {}) {
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
    async indexDocument(content, metadata = {}) {
        // Generate a random hash_id to satisfy the backend requirement
        const hash_id = 'doc_' + Math.random().toString(36).substring(7);
        const item_type = metadata.type || "document";
        // Send 'text: content' because the backend expects the field 'text'
        return this.request('POST', '/index_document', { text: content, metadata, hash_id, item_type });
    }
    async deployProxy(directoryPath, domain) {
        return this.request('POST', '/proxy/publish_feedo', { source_dir: directoryPath, domain });
    }
    async unpin(cid) {
        return this.request('DELETE', `/proxy/unpin_feedo/${cid}`);
    }
    async getStats() {
        return this.request('GET', '/explorer/stats');
    }
}
