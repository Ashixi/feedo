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
        
        this.search = new SearchModule(this.router, config?.privateKey, config?.usageKey, config?.did);
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

        console.log("[DEBUG] Encrypting and uploading chunks...");
        const CHUNK_SIZE = 5 * 1024 * 1024;
        const size = fileBuffer.byteLength;
        const chunks: Buffer[] = [];
        let offset = 0;
        while (offset < size) {
            const chunk = fileBuffer.subarray(offset, offset + CHUNK_SIZE);
            chunks.push(FeedoCrypto.encryptData(symKey, chunk));
            offset += CHUNK_SIZE;
        }

        const limit = 10;
        const hashes: string[] = new Array(chunks.length);
        let i = 0;
        const workers = new Array(limit).fill(0).map(async () => {
            while (i < chunks.length) {
                const index = i++;
                const chunkFilename = `encrypted_part${index}`;
                // Accessing private method for SDK internal chunk upload
                hashes[index] = await (this.storage as any).uploadSingleChunk(chunks[index], chunkFilename);
            }
        });
        await Promise.all(workers);

        const manifest = {
            type: "feedo_encrypted_manifest",
            filename: 'encrypted_file.bin',
            total_size: size,
            chunk_size: CHUNK_SIZE,
            chunks: hashes
        };

        const manifestString = JSON.stringify(manifest);
        const manifestData = Buffer.from(manifestString, 'utf-8');
        const hashId = await (this.storage as any).uploadSingleChunk(manifestData, 'manifest.json');
        console.log("[DEBUG] uploadPrivateFile finished, hashId:", hashId);

        const encSymKey = FeedoCrypto.encryptSymmetricKeyEcies(targetPubKey, symKey);
        const payloadBytes = Buffer.from(`${hashId}${targetDid}${encSymKey}`, 'utf-8');
        const signature = await wallet.signMessage(payloadBytes);

        console.log("[DEBUG] Calling consensus.grantFileAccess...");
        await this.consensus.grantFileAccess(hashId, targetDid, encSymKey, myPublicKey, signature);
        console.log("[DEBUG] grantFileAccess finished");

        if (indexForSearch && targetDid === myDid) {
            if (size > 30 * 1024 * 1024) {
                console.log("[DEBUG] File > 30MB, skipping search indexing (Vectorization bypass)");
            } else {
                if (metadata.type === "image") {
                    console.log("[DEBUG] Calling search.indexImage...");
                    // Pass the symmetric key so search node can decrypt and vectorize
                    await this.search.indexImage(hashId, metadata, symKey.toString('hex'));
                    console.log("[DEBUG] indexImage finished");
                } else {
                    try {
                        const textContent = fileBuffer.toString('utf-8');
                        console.log("[DEBUG] Calling search.indexPrivateDocument...");
                        await this.search.indexPrivateDocument(hashId, textContent, metadata);
                        console.log("[DEBUG] indexPrivateDocument finished");
                    } catch (e) {
                        // Not text
                    }
                }
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

        const rawData = await this.storage.downloadFile(hashId);
        
        // Check if it's an encrypted manifest
        if (rawData.byteLength < 1024 * 1024) {
            try {
                const text = new TextDecoder().decode(rawData);
                const json = JSON.parse(text);
                if (json.type === 'feedo_encrypted_manifest' && Array.isArray(json.chunks)) {
                    const limit = 10;
                    const decryptedChunks: Buffer[] = new Array(json.chunks.length);
                    let i = 0;
                    const workers = new Array(limit).fill(0).map(async () => {
                        while (i < json.chunks.length) {
                            const index = i++;
                            const encChunkRaw = await (this.storage as any).downloadSingleChunk(json.chunks[index]);
                            const encChunk = Buffer.from(encChunkRaw);
                            decryptedChunks[index] = FeedoCrypto.decryptData(symKey, encChunk);
                        }
                    });
                    await Promise.all(workers);
                    return Buffer.concat(decryptedChunks);
                }
            } catch (e) {
                // Not an encrypted manifest, handle as single encrypted file for backwards compatibility
            }
        }

        const encryptedData = Buffer.from(rawData);
        return FeedoCrypto.decryptData(symKey, encryptedData);
    }
}
