import { FeedoNetworkConfig, NodeRouter } from './router';
import { SearchModule } from './modules/search';
import { ConsensusModule } from './modules/consensus';
import { StorageModule } from './modules/storage';

export class FeedoClient {
    public search: SearchModule;
    public consensus: ConsensusModule;
    public storage: StorageModule;
    private router: NodeRouter;

    constructor(config?: FeedoNetworkConfig) {
        this.router = new NodeRouter(config);
        
        this.search = new SearchModule(this.router, config?.privateKey);
        this.consensus = new ConsensusModule(this.router, config?.privateKey);
        this.storage = new StorageModule(this.router, config?.privateKey);
    }
}
