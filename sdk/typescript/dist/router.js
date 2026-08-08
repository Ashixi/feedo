"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.NodeRouter = void 0;
const axios_1 = __importDefault(require("axios"));
const DEFAULT_SEEDS = {
    // Mainnet nodes and local fallback
    search: ["http://95.111.245.68:8000", "http://178.18.253.94:8000", "http://localhost:8000"],
    consensus: ["http://95.111.245.68:3000", "http://178.18.253.94:3000", "http://localhost:3000"],
    storage: ["http://95.111.245.68:3001", "http://178.18.253.94:3001", "http://localhost:3001"]
};
class NodeRouter {
    searchNodes;
    consensusNodes;
    storageNodes;
    activeSearchNode = null;
    activeConsensusNode = null;
    activeStorageNode = null;
    constructor(config) {
        this.searchNodes = config?.searchSeeds || DEFAULT_SEEDS.search;
        this.consensusNodes = config?.consensusSeeds || DEFAULT_SEEDS.consensus;
        this.storageNodes = config?.storageSeeds || DEFAULT_SEEDS.storage;
    }
    async findFastestNode(nodes, healthEndpoint) {
        // Ping all nodes and return the first one that resolves successfully
        const promises = nodes.map(async (node) => {
            const url = `${node}${healthEndpoint}`;
            try {
                await axios_1.default.get(url, { timeout: 3000 });
                return node;
            }
            catch (error) {
                throw new Error(`Node ${node} failed ping`);
            }
        });
        try {
            return await Promise.any(promises);
        }
        catch (error) {
            console.warn(`All seed nodes failed. Falling back to the first node in the list: ${nodes[0]}`);
            return nodes[0];
        }
    }
    async getSearchNode() {
        if (!this.activeSearchNode) {
            this.activeSearchNode = await this.findFastestNode(this.searchNodes, '/explorer/stats');
        }
        return this.activeSearchNode;
    }
    async getConsensusNode() {
        if (!this.activeConsensusNode) {
            this.activeConsensusNode = await this.findFastestNode(this.consensusNodes, '/grants');
        }
        return this.activeConsensusNode;
    }
    async getStorageNode() {
        if (!this.activeStorageNode) {
            this.activeStorageNode = await this.findFastestNode(this.storageNodes, '/api/files/recent');
        }
        return this.activeStorageNode;
    }
    invalidateSearchNode() {
        this.activeSearchNode = null;
    }
    invalidateConsensusNode() {
        this.activeConsensusNode = null;
    }
    invalidateStorageNode() {
        this.activeStorageNode = null;
    }
}
exports.NodeRouter = NodeRouter;
