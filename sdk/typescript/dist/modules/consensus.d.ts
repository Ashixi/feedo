import { NodeRouter } from '../router';
export declare class ConsensusModule {
    private router;
    private privateKey?;
    constructor(router: NodeRouter, privateKey?: string | undefined);
    private request;
    resolveName(name: string): Promise<any>;
    resolveCid(cid: string): Promise<any>;
    getDidBalance(did: string): Promise<any>;
    registerDid(publicKeyHex: string, signature: string): Promise<any>;
    registerName(name: string, did: string, cid: string, signatureHex: string): Promise<any>;
    updateNameCid(name: string, newCid: string, signatureHex: string): Promise<any>;
    listGrants(): Promise<any>;
    grantFileAccess(fileHash: string, granteeDid: string, encryptedSymmetricKey: string, publicKey: string, signatureHex: string): Promise<any>;
    getFileAccess(fileHash: string, granteeDid: string): Promise<any>;
}
