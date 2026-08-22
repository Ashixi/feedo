import { FeedoClient } from './src/index';
import { ethers } from 'ethers';

async function runTest() {
    console.log("=== Feedo PROD Client Test ===");

    const usageKey = "0x68a21eb55a6d43d69ed54a5d5938567208d5d3da61d705e9e5b49af4f58f78cf";
    const did = "did:feedo:0xTestAddress";

    const client = new FeedoClient({
        usageKey: usageKey,
        did: did
    });

    try {
        console.log("\n[1] Testing Search Node (POST /query)...");
        const searchResults = await client.search.search("Test");
        console.log("[V] Search returned successfully. Items length:", searchResults?.length || searchResults?.data?.length);

        console.log("\n[2] Testing Consensus Node...");
        const consNode = await (client as any).router.getConsensusNode();
        console.log("[V] Consensus Node elected:", consNode);

        console.log("\n[3] Testing Storage Node...");
        const storeNode = await (client as any).router.getStorageNode();
        console.log("[V] Storage Node elected:", storeNode);

        console.log("\n✅ ALL TESTS PASSED WITH NEW HTTPS ROUTING!");
    } catch (e: any) {
        console.error("Test failed:", e.response?.data || e.message || e);
    }
}

runTest();
