import axios from 'axios';

export interface FeedoNetworkConfig {
    searchSeeds?: string[];
    consensusSeeds?: string[];
    storageSeeds?: string[];
    privateKey?: string;
    usageKey?: string;
    did?: string;
}

const DEFAULT_SEEDS = {
    // Mainnet nodes and local fallback
    search: ["http://95.111.245.68:8000", "http://178.18.253.94:8000", "http://localhost:8000"], 
    consensus: ["http://95.111.245.68:3000", "http://178.18.253.94:3000", "http://localhost:3000"],
    storage: ["http://95.111.245.68:3001", "http://178.18.253.94:3001", "http://localhost:3001"]
};

export class NodeRouter {
    private searchNodes: string[];
    private consensusNodes: string[];
    private storageNodes: string[];

    private activeSearchNode: string | null = null;
    private activeConsensusNode: string | null = null;
    private activeStorageNode: string | null = null;

    constructor(config?: FeedoNetworkConfig) {
        this.searchNodes = config?.searchSeeds || DEFAULT_SEEDS.search;
        this.consensusNodes = config?.consensusSeeds || DEFAULT_SEEDS.consensus;
        this.storageNodes = config?.storageSeeds || DEFAULT_SEEDS.storage;
    }

    private async findFastestNode(nodes: string[], healthEndpoint: string): Promise<string> {
        // Ping all nodes and return the first one that resolves successfully
        const promises = nodes.map(async (node) => {
            const url = `${node}${healthEndpoint}`;
            try {
                await axios.get(url, { timeout: 3000 });
                return node;
            } catch (error) {
                throw new Error(`Node ${node} failed ping`);
            }
        });

        try {
            return await Promise.any(promises);
        } catch (error) {
            console.warn(`All seed nodes failed. Falling back to the first node in the list: ${nodes[0]}`);
            return nodes[0];
        }
    }

    public async getSearchNode(): Promise<string> {
        if (!this.activeSearchNode) {
            this.activeSearchNode = await this.findFastestNode(this.searchNodes, '/explorer/stats');
        }
        return this.activeSearchNode;
    }

    public async getConsensusNode(): Promise<string> {
        if (!this.activeConsensusNode) {
            this.activeConsensusNode = await this.findFastestNode(this.consensusNodes, '/grants');
        }
        return this.activeConsensusNode;
    }

    public async getStorageNode(): Promise<string> {
        if (!this.activeStorageNode) {
            this.activeStorageNode = await this.findFastestNode(this.storageNodes, '/api/files/recent');
        }
        return this.activeStorageNode;
    }

    public invalidateSearchNode() {
        this.activeSearchNode = null;
    }

    public invalidateConsensusNode() {
        this.activeConsensusNode = null;
    }

    public invalidateStorageNode() {
        this.activeStorageNode = null;
    }
}
