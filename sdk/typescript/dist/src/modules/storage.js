"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.StorageModule = void 0;
const axios_1 = __importDefault(require("axios"));
class StorageModule {
    router;
    constructor(router) {
        this.router = router;
    }
    async request(method, path, data, isMultipart = false) {
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}${path}`;
        const headers = {};
        if (isMultipart) {
            headers['Content-Type'] = 'multipart/form-data';
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
        return this.request('POST', '/upload', formData, true);
    }
    async downloadFile(hash) {
        // Returns raw data, which for SDK might be better handled directly or as a buffer
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}/download/${encodeURIComponent(hash)}`;
        const response = await axios_1.default.get(url, { responseType: 'arraybuffer' });
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
