import axios from 'axios';
export class ConsensusModule {
    router;
    privateKey;
    constructor(router, privateKey) {
        this.router = router;
        this.privateKey = privateKey;
    }
    async request(method, path, data) {
        let baseUrl = await this.router.getConsensusNode();
        let url = `${baseUrl}${path}`;
        try {
            const response = await axios({ method, url, data });
            return response.data;
        }
        catch (error) {
            console.warn(`Consensus request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateConsensusNode();
            baseUrl = await this.router.getConsensusNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data });
            return retryResponse.data;
        }
    }
    async resolveName(name) {
        return this.request('GET', `/resolve/${encodeURIComponent(name)}`);
    }
    async resolveCid(cid) {
        return this.request('GET', `/resolve_cid/${encodeURIComponent(cid)}`);
    }
    async getDidBalance(did) {
        return this.request('GET', `/did/${encodeURIComponent(did)}/balance`);
    }
    async registerDid(pubkeyHex, signatureHex) {
        return this.request('POST', '/did/register', { pubkey_hex: pubkeyHex, signature_hex: signatureHex });
    }
    async registerName(name, did, cid, signatureHex) {
        return this.request('POST', '/name/register', { name, did, cid, signature_hex: signatureHex });
    }
    async updateNameCid(name, newCid, signatureHex) {
        return this.request('POST', '/name/update_cid', { name, new_cid: newCid, signature_hex: signatureHex });
    }
    async listGrants() {
        return this.request('GET', '/grants');
    }
    async grantFileAccess(fileHash, granteeDid, encryptedSymmetricKey, publicKey, signatureHex) {
        return this.request('POST', '/grant/access', {
            file_hash: fileHash,
            grantee_did: granteeDid,
            encrypted_symmetric_key: encryptedSymmetricKey,
            public_key: publicKey,
            signature: signatureHex
        });
    }
    async getFileAccess(fileHash, granteeDid) {
        return this.request('GET', `/grant/access/${encodeURIComponent(fileHash)}/${encodeURIComponent(granteeDid)}`);
    }
}
