import axios from 'axios';

export interface FeedoNetworkConfig {
    searchSeeds?: string[];
    consensusSeeds?: string[];
    storageSeeds?: string[];
    privateKey?: string;
    usageKey?: string;
    did?: string;
}

const ROUTER_URL = "https://router.feedo.ink";

interface RouterNodeResponse {
    nodes: Array<{
        type: string;
        public_domain?: string;
        internal_http?: string;
    }>;
}

export class NodeRouter {
    private routerUrl: string;

    private activeSearchNode: string | null = null;
    private activeConsensusNode: string | null = null;
    private activeStorageNode: string | null = null;
    
    private cache: Record<string, { nodes: string[], timestamp: number }> = {
        search: { nodes: [], timestamp: 0 },
        consensus: { nodes: [], timestamp: 0 },
        storage: { nodes: [], timestamp: 0 }
    };
    private cacheTtlMs = 5 * 60 * 1000; // 5 minutes

    constructor(config?: FeedoNetworkConfig) {
        // We reuse searchSeeds as the router URL for backward compatibility if provided
        this.routerUrl = config?.searchSeeds?.[0] || ROUTER_URL;
    }
    
    private async getNodesFromRouter(nodeType: string): Promise<string[]> {
        const cached = this.cache[nodeType];
        if (Date.now() - cached.timestamp < this.cacheTtlMs && cached.nodes.length > 0) {
            return cached.nodes;
        }

        try {
            const resp = await axios.get<RouterNodeResponse>(`${this.routerUrl}/discover?type=${nodeType}`, { timeout: 5000 });
            const urls = resp.data.nodes.map(n => n.public_domain || n.internal_http).filter(Boolean) as string[];
            
            if (urls.length > 0) {
                this.cache[nodeType] = { nodes: urls, timestamp: Date.now() };
                return urls;
            }
        } catch (error) {
            console.warn(`Failed to fetch ${nodeType} nodes from router:`, error);
        }
        
        return cached.nodes;
    }

    private async findFastestNode(nodeType: string, healthEndpoint: string): Promise<string> {
        let nodes = await this.getNodesFromRouter(nodeType);
        
        if (nodes.length === 0) {
            const fallbacks: Record<string, string[]> = {
                search: ["https://api.feedo.ink", "http://localhost:8000"],
                consensus: ["https://api.feedo.ink/consensus", "http://localhost:3000"],
                storage: ["https://api.feedo.ink/storage", "http://localhost:3001"]
            };
            nodes = fallbacks[nodeType] || [];
        }

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
            console.warn(`All discovered ${nodeType} nodes failed. Falling back to the first node in the list: ${nodes[0]}`);
            return nodes[0] || "";
        }
    }

    public async getSearchNode(): Promise<string> {
        if (!this.activeSearchNode) {
            this.activeSearchNode = await this.findFastestNode("search", '/explorer/stats');
        }
        return this.activeSearchNode;
    }

    public async getConsensusNode(): Promise<string> {
        if (!this.activeConsensusNode) {
            this.activeConsensusNode = await this.findFastestNode("consensus", '/grants');
        }
        return this.activeConsensusNode;
    }

    public async getStorageNode(): Promise<string> {
        if (!this.activeStorageNode) {
            this.activeStorageNode = await this.findFastestNode("storage", '/api/files/recent');
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
