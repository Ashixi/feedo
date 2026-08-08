import axios from 'axios';
import { NodeRouter } from '../router';
import { ethers } from 'ethers';

export class StorageModule {
    constructor(private router: NodeRouter, private privateKey?: string) {}

    private async request(method: string, path: string, data?: any, isMultipart: boolean = false) {
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}${path}`;
        
        const headers: any = {};

        if (this.privateKey) {
            const wallet = new ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:${method}:${path}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }

        try {
            const response = await axios({ method, url, data, headers });
            return response.data;
        } catch (error: any) {
            console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            url = `${baseUrl}${path}`;
            const retryResponse = await axios({ method, url, data, headers });
            return retryResponse.data;
        }
    }

    private async uploadSingleChunk(fileBlobOrBuffer: any, filename: string): Promise<string> {
        let finalData = fileBlobOrBuffer;
        if (typeof Buffer !== 'undefined' && Buffer.isBuffer(fileBlobOrBuffer)) {
            finalData = new Blob([fileBlobOrBuffer as any]);
        } else if (fileBlobOrBuffer instanceof Uint8Array) {
            finalData = new Blob([fileBlobOrBuffer as any]);
        }

        const formData = new FormData();
        formData.append('file', finalData, filename);
        
        let baseUrl = await this.router.getStorageNode();
        let url = `${baseUrl}/upload`;
        
        const headers: any = {};
        if (this.privateKey) {
            const wallet = new ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:POST:/upload:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }

        try {
            const response = await fetch(url, { method: 'POST', headers, body: formData as any });
            if (!response.ok) throw new Error(await response.text());
            return await response.text();
        } catch (error: any) {
            console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            url = `${baseUrl}/upload`;
            const retryResponse = await fetch(url, { method: 'POST', headers, body: formData as any });
            if (!retryResponse.ok) throw new Error(await retryResponse.text());
            return await retryResponse.text();
        }
    }

    async uploadFile(fileBlobOrBuffer: any, filename: string = 'file') {
        let size = 0;
        if (fileBlobOrBuffer.size !== undefined) size = fileBlobOrBuffer.size;
        else if (fileBlobOrBuffer.byteLength !== undefined) size = fileBlobOrBuffer.byteLength;
        else if (fileBlobOrBuffer.length !== undefined) size = fileBlobOrBuffer.length;

        const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB
        
        if (size <= CHUNK_SIZE) {
            return this.uploadSingleChunk(fileBlobOrBuffer, filename);
        }

        // Chunking logic
        const chunks: any[] = [];
        let offset = 0;
        while (offset < size) {
            let chunk;
            if (fileBlobOrBuffer.slice) {
                // Blob or Buffer
                chunk = fileBlobOrBuffer.slice(offset, offset + CHUNK_SIZE);
            } else if (fileBlobOrBuffer.subarray) {
                // Uint8Array
                chunk = fileBlobOrBuffer.subarray(offset, offset + CHUNK_SIZE);
            } else {
                throw new Error("Unsupported file type for chunking");
            }
            chunks.push(chunk);
            offset += CHUNK_SIZE;
        }

        // Upload chunks with promise pool
        const limit = 10;
        const hashes: string[] = new Array(chunks.length);
        let i = 0;
        const workers = new Array(limit).fill(0).map(async () => {
            while (i < chunks.length) {
                const index = i++;
                const chunkFilename = `${filename}.part${index}`;
                hashes[index] = await this.uploadSingleChunk(chunks[index], chunkFilename);
            }
        });
        await Promise.all(workers);

        // Create manifest
        const manifest = {
            type: "feedo_manifest",
            filename: filename,
            total_size: size,
            chunk_size: CHUNK_SIZE,
            chunks: hashes
        };

        const manifestString = JSON.stringify(manifest);
        let manifestData;
        if (typeof Blob !== 'undefined') {
            manifestData = new Blob([manifestString], { type: 'application/json' });
        } else {
            manifestData = Buffer.from(manifestString, 'utf-8');
        }

        return await this.uploadSingleChunk(manifestData, 'manifest.json');
    }

    private async downloadSingleChunk(hash: string): Promise<ArrayBuffer> {
        let baseUrl = await this.router.getStorageNode();
        let path = `/download/${encodeURIComponent(hash)}`;
        let url = `${baseUrl}${path}`;
        
        const headers: any = {};
        if (this.privateKey) {
            const wallet = new ethers.Wallet(this.privateKey);
            const did = `did:feedo:${wallet.address}`;
            const timestamp = Date.now().toString();
            const payload = `FeedoAction:GET:${path}:${timestamp}`;
            const signature = await wallet.signMessage(payload);
            
            headers['X-Feedo-DID'] = did;
            headers['X-Feedo-Timestamp'] = timestamp;
            headers['X-Feedo-Signature'] = signature;
        }
        
        try {
            const response = await axios.get(url, { responseType: 'arraybuffer', headers });
            return response.data;
        } catch (error: any) {
            console.warn(`Download failed on ${baseUrl}, trying new node...`);
            this.router.invalidateStorageNode();
            baseUrl = await this.router.getStorageNode();
            path = `/download/${encodeURIComponent(hash)}`;
            url = `${baseUrl}${path}`;
            const retryResponse = await axios.get(url, { responseType: 'arraybuffer', headers });
            return retryResponse.data;
        }
    }

    async downloadFile(hash: string) {
        const rawData = await this.downloadSingleChunk(hash);
        
        // If it's small, it might be a manifest
        if (rawData.byteLength < 1024 * 1024) { 
            try {
                const text = new TextDecoder().decode(rawData);
                const json = JSON.parse(text);
                if (json.type === 'feedo_manifest' && Array.isArray(json.chunks)) {
                    // Download chunks with promise pool
                    const limit = 10;
                    const chunks: ArrayBuffer[] = new Array(json.chunks.length);
                    let i = 0;
                    const workers = new Array(limit).fill(0).map(async () => {
                        while (i < json.chunks.length) {
                            const index = i++;
                            chunks[index] = await this.downloadSingleChunk(json.chunks[index]);
                        }
                    });
                    await Promise.all(workers);
                    
                    // Concatenate chunks
                    let totalLen = chunks.reduce((acc, c) => acc + c.byteLength, 0);
                    let result = new Uint8Array(totalLen);
                    let offset = 0;
                    for (let c of chunks) {
                        result.set(new Uint8Array(c), offset);
                        offset += c.byteLength;
                    }
                    return result.buffer;
                }
            } catch (e) {
                // Not a manifest or not JSON, fallback to returning raw data
            }
        }
        
        return rawData;
    }

    async ingestJson(payload: any) {
        return this.request('POST', '/api/v1/ingest/post', payload);
    }

    async getRecentFiles() {
        return this.request('GET', '/api/files/recent');
    }
}
