import { KeyManager } from '../crypto/KeyManager';

export class FeedoClient {
    private keyManager: KeyManager;
    private apiUrl: string;

    constructor(privateKeyHex?: string, apiUrl: string = "http://127.0.0.1:8040") {
        this.keyManager = new KeyManager(privateKeyHex);
        this.apiUrl = apiUrl;
    }

    public getKeyManager(): KeyManager {
        return this.keyManager;
    }

    public async publish(postData: { title?: string, content: string, type?: string }) {
        // Hash the content and metadata
        const timestamp = Math.floor(Date.now() / 1000);
        // We use a simplified hash logic: hash(text_timestamp) to match Python zero-trust
        const textToHash = postData.content + "_" + timestamp.toString();
        const hashId = await KeyManager.hashAsync(textToHash);
        const contentBlobHash = await KeyManager.hashAsync(postData.content);
        
        // Sign the hash
        const signature = this.keyManager.sign(hashId);

        const payload = {
            author: this.keyManager.getWalletAddress(),
            hash_id: hashId,
            content_blob_hash: contentBlobHash,
            signature: signature,
            title: postData.title,
            text: postData.content,
            source_type: postData.type || "native",
            sequence_number: 1,
            timestamp: timestamp
        };

        const response = await fetch(`${this.apiUrl}/local/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            let errorText = response.statusText;
            try {
                const errJson = await response.json();
                if (errJson.detail) errorText = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
            } catch (e) {}
            throw new Error(`Failed to publish: ${errorText}`);
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
