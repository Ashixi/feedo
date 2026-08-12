"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.SearchModule = void 0;
const axios_1 = __importDefault(require("axios"));
const ethers_1 = require("ethers");
class SearchModule {
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
            const wallet = new ethers_1.ethers.Wallet(this.privateKey);
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
            const response = await (0, axios_1.default)({ method, url, data, headers });
            return response.data;
        }
        catch (error) {
            // Basic retry logic with a new node on failure
            console.warn(`Search request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateSearchNode();
            baseUrl = await this.router.getSearchNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await (0, axios_1.default)({ method, url, data, headers });
            return retryResponse.data;
        }
    }
    async search(query, limit = 50, federated = true, itemType = "all", offset = 0, appId, searchType = "text", imageUrl, namespace) {
        let qs = `text=${encodeURIComponent(query)}&limit=${limit}&federated=${federated}&item_type=${itemType}&offset=${offset}&search_type=${encodeURIComponent(searchType)}`;
        if (appId)
            qs += `&app_id=${encodeURIComponent(appId)}`;
        if (imageUrl)
            qs += `&image_url=${encodeURIComponent(imageUrl)}`;
        if (namespace)
            qs += `&namespace=${encodeURIComponent(namespace)}`;
        return this.request('GET', `/query?${qs}`);
    }
    async getDocuments(limit = 50, offset = 0, itemType = "all", appId, namespace) {
        let qs = `limit=${limit}&offset=${offset}&item_type=${itemType}`;
        if (appId)
            qs += `&app_id=${encodeURIComponent(appId)}`;
        if (namespace)
            qs += `&namespace=${encodeURIComponent(namespace)}`;
        return this.request('GET', `/documents?${qs}`);
    }
    async indexPrivateDocument(hashId, plaintext, metadata = {}, namespace) {
        if (!this.privateKey) {
            throw new Error("Private key required to index private documents");
        }
        const wallet = new ethers_1.ethers.Wallet(this.privateKey);
        const myDid = `did:feedo:${wallet.address}`;
        return this.request('POST', '/index_document', {
            hash_id: hashId,
            text: plaintext,
            item_type: "private_post",
            author: myDid,
            metadata: metadata,
            namespace: namespace || ""
        });
    }
    async indexImage(hashId, metadata = {}, symmetricKey, namespace) {
        let author = "";
        let itemType = "image";
        if (symmetricKey) {
            if (!this.privateKey) {
                throw new Error("Private key required to index private images");
            }
            const wallet = new ethers_1.ethers.Wallet(this.privateKey);
            author = `did:feedo:${wallet.address}`;
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
    async indexDocument(content, metadata = {}, namespace, hashId) {
        // Allow caller to pass a custom hash_id (e.g. for later deletion).
        // If omitted, generate a random one to satisfy the backend requirement.
        const hash_id = hashId || ('doc_' + Math.random().toString(36).substring(7));
        const item_type = metadata.type || "document";
        // Send 'text: content' because the backend expects the field 'text'
        return this.request('POST', '/index_document', { text: content, metadata, hash_id, item_type, namespace: namespace || "" });
    }
    async countByNamespace(namespace, federated = true) {
        return this.request('GET', `/count?namespace=${encodeURIComponent(namespace)}&federated=${federated}`);
    }
    async deleteByNamespace(namespace) {
        return this.request('DELETE', `/namespace/${encodeURIComponent(namespace)}`);
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
exports.SearchModule = SearchModule;
