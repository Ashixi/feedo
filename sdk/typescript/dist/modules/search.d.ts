import { NodeRouter } from '../router';
export declare class SearchModule {
    private router;
    private privateKey?;
    constructor(router: NodeRouter, privateKey?: string | undefined);
    private request;
    search(query: string, limit?: number, federated?: boolean, itemType?: string, offset?: number, appId?: string, searchType?: string, imageUrl?: string, namespace?: string): Promise<any>;
    getDocuments(limit?: number, offset?: number, itemType?: string, appId?: string, namespace?: string): Promise<any>;
    indexPrivateDocument(hashId: string, plaintext: string, metadata?: Record<string, any>, namespace?: string): Promise<any>;
    indexImage(hashId: string, metadata?: Record<string, any>, symmetricKey?: string, namespace?: string): Promise<any>;
    indexDocument(content: string, metadata?: Record<string, any>, namespace?: string): Promise<any>;
    countByNamespace(namespace: string, federated?: boolean): Promise<{
        count: number;
    }>;
    deleteByNamespace(namespace: string): Promise<{
        status: string;
        deleted: number;
    }>;
    deployProxy(directoryPath: string, domain: string): Promise<any>;
    unpin(cid: string): Promise<any>;
    getStats(): Promise<any>;
}
