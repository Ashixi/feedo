import { NodeRouter } from '../router';
export declare class SearchModule {
    private router;
    constructor(router: NodeRouter);
    private request;
    query(queryText: string, limit?: number): Promise<any>;
    indexDocument(content: string, metadata?: Record<string, any>): Promise<any>;
    deployProxy(directoryPath: string, domain: string): Promise<any>;
    unpin(cid: string): Promise<any>;
    getStats(): Promise<any>;
}
