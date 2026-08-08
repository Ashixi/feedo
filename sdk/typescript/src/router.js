import axios from 'axios';
const DEFAULT_SEEDS = {
    // Mainnet nodes and local fallback
    search: ["http://95.111.245.68:8000", "http://178.18.253.94:8000", "http://localhost:8000"],
    consensus: ["http://95.111.245.68:8080", "http://178.18.253.94:8080", "http://localhost:8080"],
    storage: ["http://95.111.245.68:8081", "http://178.18.253.94:8081", "http://localhost:8081"]
};
export class NodeRouter {
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
                await axios.get(url, { timeout: 3000 });
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
