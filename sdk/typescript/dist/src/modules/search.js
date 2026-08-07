"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.SearchModule = void 0;
const axios_1 = __importDefault(require("axios"));
class SearchModule {
    router;
    constructor(router) {
        this.router = router;
    }
    async request(method, path, data) {
        let baseUrl = await this.router.getSearchNode();
        let url = `${baseUrl}${path}`;
        try {
            const response = await (0, axios_1.default)({ method, url, data });
            return response.data;
        }
        catch (error) {
            // Basic retry logic with a new node on failure
            console.warn(`Search request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateSearchNode();
            baseUrl = await this.router.getSearchNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await (0, axios_1.default)({ method, url, data });
            return retryResponse.data;
        }
    }
    async query(queryText, limit = 10) {
        return this.request('GET', `/query?q=${encodeURIComponent(queryText)}&limit=${limit}`);
    }
    async indexDocument(content, metadata = {}) {
        return this.request('POST', '/index_document', { content, metadata });
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
