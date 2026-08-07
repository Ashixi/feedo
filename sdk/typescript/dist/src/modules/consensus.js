"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.ConsensusModule = void 0;
const axios_1 = __importDefault(require("axios"));
class ConsensusModule {
    router;
    constructor(router) {
        this.router = router;
    }
    async request(method, path, data) {
        let baseUrl = await this.router.getConsensusNode();
        let url = `${baseUrl}${path}`;
        try {
            const response = await (0, axios_1.default)({ method, url, data });
            return response.data;
        }
        catch (error) {
            console.warn(`Consensus request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateConsensusNode();
            baseUrl = await this.router.getConsensusNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await (0, axios_1.default)({ method, url, data });
            return retryResponse.data;
        }
    }
    async resolveName(name) {
        return this.request('GET', `/resolve/${encodeURIComponent(name)}`);
    }
    async resolveCid(cid) {
        return this.request('GET', `/resolve_cid/${encodeURIComponent(cid)}`);
    }
    async getDidBalance(did) {
        return this.request('GET', `/did/${encodeURIComponent(did)}/balance`);
    }
    async registerDid(pubkeyHex, signatureHex) {
        return this.request('POST', '/did/register', { pubkey_hex: pubkeyHex, signature_hex: signatureHex });
    }
    async registerName(name, did, cid, signatureHex) {
        return this.request('POST', '/name/register', { name, did, cid, signature_hex: signatureHex });
    }
    async updateNameCid(name, newCid, signatureHex) {
        return this.request('POST', '/name/update_cid', { name, new_cid: newCid, signature_hex: signatureHex });
    }
    async listGrants() {
        return this.request('GET', '/grants');
    }
}
exports.ConsensusModule = ConsensusModule;
