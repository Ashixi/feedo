import * as secp from '@noble/secp256k1';

export class FeedoClient {
    private privateKeyHex: string;
    private apiUrl: string;
    private publicKeyHex: string;

    constructor(privateKeyHex: string, apiUrl: string = "http://127.0.0.1:8040") {
        this.privateKeyHex = privateKeyHex.replace("0x", "");
        this.apiUrl = apiUrl;
        this.publicKeyHex = this.uint8ArrayToHex(secp.getPublicKey(this.privateKeyHex, true));
    }

    private uint8ArrayToHex(bytes: Uint8Array): string {
        return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    private async sha256(message: string): Promise<string> {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        return this.uint8ArrayToHex(new Uint8Array(hashBuffer));
    }

    public async publish(postData: { title?: string, content: string, type?: string }) {
        const hashId = await this.sha256(postData.content + Date.now().toString());
        const contentBlobHash = await this.sha256(postData.content);
        
        const sigBytes = await secp.sign(hashId, this.privateKeyHex);
        const signature = this.uint8ArrayToHex(sigBytes);

        const payload = {
            author: this.publicKeyHex,
            hash_id: hashId,
            content_blob_hash: contentBlobHash,
            signature: signature,
            title: postData.title,
            text: postData.content,
            source_type: postData.type || "native",
            sequence_number: 1
        };

        const response = await fetch(`${this.apiUrl}/local/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`Failed to publish: ${response.statusText}`);
        }
        return await response.json();
    }
    
    public async query(text: string, federated: boolean = false) {
        const url = new URL(`${this.apiUrl}/query`);
        url.searchParams.append("text", text);
        if (federated) {
            url.searchParams.append("federated", "true");
        }
        const response = await fetch(url.toString());
        if (!response.ok) {
            throw new Error(`Query failed: ${response.statusText}`);
        }
        return await response.json();
    }
}
