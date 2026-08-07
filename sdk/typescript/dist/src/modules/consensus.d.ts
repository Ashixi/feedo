import { NodeRouter } from '../router';
export declare class ConsensusModule {
    private router;
    constructor(router: NodeRouter);
    private request;
    resolveName(name: string): Promise<any>;
    resolveCid(cid: string): Promise<any>;
    getDidBalance(did: string): Promise<any>;
    registerDid(pubkeyHex: string, signatureHex: string): Promise<any>;
    registerName(name: string, did: string, cid: string, signatureHex: string): Promise<any>;
    updateNameCid(name: string, newCid: string, signatureHex: string): Promise<any>;
    listGrants(): Promise<any>;
}
