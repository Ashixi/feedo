import axios from 'axios';
import { NodeRouter } from '../router';

export class ConsensusModule {
    constructor(private router: NodeRouter, private privateKey?: string) {}

    private async request(method: string, path: string, data?: any) {
        let baseUrl = await this.router.getConsensusNode();
        let url = `${baseUrl}${path}`;
        
        try {
            const response = await axios({ method, url, data });
            return response.data;
        } catch (error: any) {
            console.warn(`Consensus request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateConsensusNode();
            baseUrl = await this.router.getConsensusNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data });
            return retryResponse.data;
        }
    }

    async resolveName(name: string) {
        return this.request('GET', `/resolve/${encodeURIComponent(name)}`);
    }

    async resolveCid(cid: string) {
        return this.request('GET', `/resolve_cid/${encodeURIComponent(cid)}`);
    }

    async getDidBalance(did: string) {
        return this.request('GET', `/did/${encodeURIComponent(did)}/balance`);
    }

    async registerDid(publicKeyHex: string, signature: string) {
        const { ethers } = require('ethers');
        let address = "";
        try {
            // Ethers v6: computeAddress from public key
            address = ethers.computeAddress(publicKeyHex);
        } catch (e) {
            address = publicKeyHex; // fallback
        }
        const did = `did:feedo:${address}`;

        return this.request('POST', '/did/register', {
            did: did,
            public_key: publicKeyHex,
        });
    }

    async registerName(name: string, did: string, cid: string, signatureHex: string) {
        return this.request('POST', '/name/register', { name, did, cid, signature_hex: signatureHex });
    }

    async updateNameCid(name: string, newCid: string, signatureHex: string) {
        return this.request('POST', '/name/update_cid', { name, new_cid: newCid, signature_hex: signatureHex });
    }

    async listGrants() {
        return this.request('GET', '/grants');
    }

    async grantFileAccess(fileHash: string, granteeDid: string, encryptedSymmetricKey: string, publicKey: string, signatureHex: string) {
        return this.request('POST', '/grant/access', {
            file_hash: fileHash,
            grantee_did: granteeDid,
            encrypted_symmetric_key: encryptedSymmetricKey,
            public_key: publicKey,
            signature: signatureHex
        });
    }

    async getFileAccess(fileHash: string, granteeDid: string) {
        return this.request('GET', `/grant/access/${encodeURIComponent(fileHash)}/${encodeURIComponent(granteeDid)}`);
    }
}
