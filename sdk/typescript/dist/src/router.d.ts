export interface FeedoNetworkConfig {
    searchSeeds?: string[];
    consensusSeeds?: string[];
    storageSeeds?: string[];
}
export declare class NodeRouter {
    private searchNodes;
    private consensusNodes;
    private storageNodes;
    private activeSearchNode;
    private activeConsensusNode;
    private activeStorageNode;
    constructor(config?: FeedoNetworkConfig);
    private findFastestNode;
    getSearchNode(): Promise<string>;
    getConsensusNode(): Promise<string>;
    getStorageNode(): Promise<string>;
    invalidateSearchNode(): void;
    invalidateConsensusNode(): void;
    invalidateStorageNode(): void;
}
