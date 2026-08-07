import { NodeRouter } from '../router';
export declare class StorageModule {
    private router;
    private privateKey?;
    constructor(router: NodeRouter, privateKey?: string | undefined);
    private request;
    uploadFile(fileBlobOrBuffer: any, filename?: string): Promise<string>;
    downloadFile(hash: string): Promise<any>;
    ingestJson(payload: any): Promise<any>;
    getRecentFiles(): Promise<any>;
}
