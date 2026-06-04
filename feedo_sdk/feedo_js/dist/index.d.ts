export declare class FeedoClient {
    private privateKeyHex;
    private apiUrl;
    private publicKeyHex;
    constructor(privateKeyHex: string, apiUrl?: string);
    private uint8ArrayToHex;
    private sha256;
    publish(postData: {
        title?: string;
        content: string;
        type?: string;
    }): Promise<any>;
    query(text: string, federated?: boolean): Promise<any>;
}
