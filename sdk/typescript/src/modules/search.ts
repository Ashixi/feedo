import axios from 'axios';
import { NodeRouter } from '../router';
import { ethers } from 'ethers';

export class SearchModule {
    constructor(
        private router: NodeRouter,
        private privateKey?: string,
        private usageKey?: string,
        private did?: string
    ) {}

    private myDid(): string {
        if (this.did) return this.did;
        const wallet = new ethers.Wallet(this.privateKey!);
        return `did:feedo:${wallet.address}`;
    }

    private async request(method: string, path: string, data?: any) {
        let baseUrl = await this.router.getSearchNode();
        let url = `${baseUrl}${path}`;
        
        const headers: any = {};
        if (this.usageKey && this.did) {
            // Delegated mode: sign with the derived usage key (0xD), declare the owner DID (0xW).
            const wallet = new ethers.Wallet(this.usageKey);
            const timestamp = Date.now().toString();
            const basePath = path.split('?')[0]; // server reconstructs payload using path WITHOUT query string
            const payload = `FeedoAction:${method}:${basePath}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            
            headers['X-Feedo-DID'] = this.did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        } else if (this.privateKey) {
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

    async search(query: string, limit: number = 50, federated: boolean = true, itemType: string = "all", offset: number = 0, appId?: string, searchType: string = "text", imageUrl?: string, namespace?: string) {
        let qs = `text=${encodeURIComponent(query)}&limit=${limit}&federated=${federated}&item_type=${itemType}&offset=${offset}&search_type=${encodeURIComponent(searchType)}`;
        if (appId) qs += `&app_id=${encodeURIComponent(appId)}`;
        if (imageUrl) qs += `&image_url=${encodeURIComponent(imageUrl)}`;
        if (namespace) qs += `&namespace=${encodeURIComponent(namespace)}`;
        return this.request('GET', `/query?${qs}`);
    }

    async getDocuments(limit: number = 50, offset: number = 0, itemType: string = "all", appId?: string, namespace?: string) {
        let qs = `limit=${limit}&offset=${offset}&item_type=${itemType}`;
        if (appId) qs += `&app_id=${encodeURIComponent(appId)}`;
        if (namespace) qs += `&namespace=${encodeURIComponent(namespace)}`;
        return this.request('GET', `/documents?${qs}`);
    }

    async indexPrivateDocument(hashId: string, plaintext: string, metadata: Record<string, any> = {}, namespace?: string) {
        if (!this.privateKey && !this.usageKey) {
            throw new Error("Private key or usage key required to index private documents");
        }
        const myDid = this.myDid();
        
        return this.request('POST', '/index_document', {
            hash_id: hashId,
            text: plaintext,
            item_type: "private_post",
            author: myDid,
            metadata: metadata,
            namespace: namespace || ""
        });
    }

    async indexImage(hashId: string, metadata: Record<string, any> = {}, symmetricKey?: string, namespace?: string) {
        let author = "";
        let itemType = "image";
        
        if (symmetricKey) {
            if (!this.privateKey && !this.usageKey) {
                throw new Error("Private key or usage key required to index private images");
            }
            author = this.myDid();
            itemType = "private_image";
        }
        
        return this.request('POST', '/index_image', {
            hash_id: hashId,
            item_type: itemType,
            author: author,
            metadata: metadata,
            symmetric_key: symmetricKey,
            namespace: namespace || ""
        });
    }

    async indexDocument(content: string, metadata: Record<string, any> = {}, namespace?: string, hashId?: string) {
        // Allow caller to pass a custom hash_id (e.g. for later deletion).
        // If omitted, generate a random one to satisfy the backend requirement.
        const hash_id = hashId || ('doc_' + Math.random().toString(36).substring(7));
        const item_type = metadata.type || "document";
        // Send 'text: content' because the backend expects the field 'text'
        return this.request('POST', '/index_document', { text: content, metadata, hash_id, item_type, namespace: namespace || "" });
    }

    async countByNamespace(namespace: string, federated: boolean = true): Promise<{ count: number }> {
        return this.request('GET', `/count?namespace=${encodeURIComponent(namespace)}&federated=${federated}`);
    }

    async deleteByNamespace(namespace: string): Promise<{ status: string; deleted: number }> {
        return this.request('DELETE', `/namespace/${encodeURIComponent(namespace)}`);
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
