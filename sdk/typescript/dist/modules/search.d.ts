import { NodeRouter } from '../router';
export declare class SearchModule {
    private router;
    private privateKey?;
    constructor(router: NodeRouter, privateKey?: string | undefined);
    private request;
    search(query: string, limit?: number, federated?: boolean, itemType?: string, offset?: number, appId?: string): Promise<any>;
    getDocuments(limit?: number, offset?: number, itemType?: string, appId?: string): Promise<any>;
    indexPrivateDocument(hashId: string, plaintext: string, metadata?: Record<string, any>): Promise<any>;
    indexDocument(content: string, metadata?: Record<string, any>): Promise<any>;
    deployProxy(directoryPath: string, domain: string): Promise<any>;
    unpin(cid: string): Promise<any>;
    getStats(): Promise<any>;
}
