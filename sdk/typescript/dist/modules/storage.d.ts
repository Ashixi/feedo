import { NodeRouter } from '../router';
export declare class StorageModule {
    private router;
    private privateKey?;
    constructor(router: NodeRouter, privateKey?: string | undefined);
    private request;
    private uploadSingleChunk;
    uploadFile(fileBlobOrBuffer: any, filename?: string): Promise<string>;
    private downloadSingleChunk;
    downloadFile(hash: string): Promise<ArrayBuffer>;
    ingestJson(payload: any): Promise<any>;
    getRecentFiles(): Promise<any>;
}
