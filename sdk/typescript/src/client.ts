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

    async uploadPrivateFile(fileBuffer: Buffer, granteePublicKeyHex?: string, indexForSearch: boolean = true, metadata: Record<string, any> = {}): Promise<string> {
        if (!this.search['privateKey']) {
            throw new Error("Private key required to upload private files");
        }
        const privateKey = this.search['privateKey'];
        const { ethers } = require('ethers');
        const wallet = new ethers.Wallet(privateKey);
        const myDid = `did:feedo:${wallet.address}`;
        const myPublicKey = wallet.signingKey.publicKey;

        const targetPubKey = granteePublicKeyHex || myPublicKey;
        const targetDid = granteePublicKeyHex ? "unknown" : myDid;

        const { FeedoCrypto } = require('./modules/crypto');
        const symKey = FeedoCrypto.generateSymmetricKey();
        const encryptedData = FeedoCrypto.encryptData(symKey, fileBuffer);

        const blob = new Blob([encryptedData]);
        console.log("[DEBUG] Calling storage.uploadFile...");
        const hashId = await this.storage.uploadFile(blob, 'encrypted_file.bin');
        console.log("[DEBUG] uploadFile finished, hashId:", hashId);

        const encSymKey = FeedoCrypto.encryptSymmetricKeyEcies(targetPubKey, symKey);

        const payloadBytes = Buffer.from(`${hashId}${targetDid}${encSymKey}`, 'utf-8');
        const signature = await wallet.signMessage(payloadBytes);

        console.log("[DEBUG] Calling consensus.grantFileAccess...");
        await this.consensus.grantFileAccess(hashId, targetDid, encSymKey, myPublicKey, signature);
        console.log("[DEBUG] grantFileAccess finished");

        if (indexForSearch && targetDid === myDid) {
            try {
                const textContent = fileBuffer.toString('utf-8');
                console.log("[DEBUG] Calling search.indexPrivateDocument...");
                await this.search.indexPrivateDocument(hashId, textContent, metadata);
                console.log("[DEBUG] indexPrivateDocument finished");
            } catch (e) {
                // Not text
            }
        }

        return hashId;
    }

    async downloadPrivateFile(hashId: string): Promise<Buffer> {
        if (!this.search['privateKey']) {
            throw new Error("Private key required to download private files");
        }
        const privateKey = this.search['privateKey'];
        const { ethers } = require('ethers');
        const wallet = new ethers.Wallet(privateKey);
        const myDid = `did:feedo:${wallet.address}`;

        const res = await this.consensus.getFileAccess(hashId, myDid);
        const encSymKey = res.encrypted_symmetric_key;
        if (!encSymKey) {
            throw new Error(`No access granted for ${myDid} to file ${hashId}`);
        }

        const { FeedoCrypto } = require('./modules/crypto');
        const symKey = FeedoCrypto.decryptSymmetricKeyEcies(privateKey, encSymKey);

        const encryptedDataArrayBuffer = await this.storage.downloadFile(hashId);
        const encryptedData = Buffer.from(encryptedDataArrayBuffer);

        return FeedoCrypto.decryptData(symKey, encryptedData);
    }
}
