import { FeedoClient } from './src/client';
import { ethers } from 'ethers';

async function runTest() {
    console.log("=== Feedo E2E Client Test ===");

    // 1. Generate a random wallet for the test
    const wallet = ethers.Wallet.createRandom();
    console.log("Generated Test Wallet:", wallet.address);

    // 1. Initialize Client pointing to local nodes
    const client = new FeedoClient({
        storageSeeds: ['http://127.0.0.1:3011'],
        consensusSeeds: ['http://127.0.0.1:3012'],
        searchSeeds: ['http://127.0.0.1:8013'],
        privateKey: wallet.privateKey
    });

    try {
        console.log("\n[1] Registering DID on Consensus Node...");
        const did = `did:feedo:${wallet.address}`;
        const signature = await wallet.signMessage(`feedo register ${did}`);
        await client.consensus.registerDid(wallet.signingKey.publicKey, signature);
        console.log("[V] DID Registered!");

        console.log("\n[2] Publishing an encrypted file/post...");
        const textContent = "Hello from Feedo E2E test! This is a secret message.";
        const buffer = Buffer.from(textContent, 'utf-8');
        
        // uploadPrivateFile handles E2EE encryption, Storage upload, Consensus grant, and Search indexing!
        const hashId = await client.uploadPrivateFile(buffer, undefined, true, { app_id: "com.myawesomeapp", type: "text" });
        console.log(`[V] Uploaded successfully! HashID: ${hashId}`);

        console.log("\n[3] Waiting 5 seconds for Search Node indexing...");
        await new Promise(r => setTimeout(r, 5000));

        console.log("\n[4] Searching for the post by app_id...");
        const searchResults = await client.search.search("Hello", 10, true, "all", 0, "com.myawesomeapp");
        console.log("[V] Search Results:", searchResults);

    } catch (e: any) {
        console.error("Test failed:", e.response?.data || e.message);
    }
}

runTest();
