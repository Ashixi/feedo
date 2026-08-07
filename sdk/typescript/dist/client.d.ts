import { FeedoNetworkConfig } from './router';
import { SearchModule } from './modules/search';
import { ConsensusModule } from './modules/consensus';
import { StorageModule } from './modules/storage';
export declare class FeedoClient {
    search: SearchModule;
    consensus: ConsensusModule;
    storage: StorageModule;
    private router;
    constructor(config?: FeedoNetworkConfig);
    uploadPrivateFile(fileBuffer: Buffer, granteePublicKeyHex?: string, indexForSearch?: boolean, metadata?: Record<string, any>): Promise<string>;
    downloadPrivateFile(hashId: string): Promise<Buffer>;
}
