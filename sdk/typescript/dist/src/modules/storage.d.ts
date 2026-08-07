import { NodeRouter } from '../router';
export declare class StorageModule {
    private router;
    constructor(router: NodeRouter);
    private request;
    uploadFile(fileBlobOrBuffer: any, filename?: string): Promise<any>;
    downloadFile(hash: string): Promise<any>;
    ingestJson(payload: any): Promise<any>;
    getRecentFiles(): Promise<any>;
}
