import axios from 'axios';
import { performance } from 'perf_hooks';

// 50 Test Queries to simulate real investor usage
const queries = [
  "decentralized exchange solana", "borrow usdc", "yield farming on ethereum",
  "liquid staking", "nft marketplace", "web3 wallet", "crypto hardware wallet",
  "bitcoin bridge", "optimism rollup", "zk sync layer 2", "buy crypto with fiat",
  "decentralized perpetuals", "crypto lending platform", "best apy stablecoin",
  "dao governance", "web3 gaming", "play to earn", "metaverse land",
  "crypto casino", "web3 social network", "decentralized file storage",
  "ipfs gateway", "ethereum naming service", "buy eth domain",
  "solana meme coins", "arbitrum defi", "base network bridge",
  "polkadot parachains", "cosmos ibc", "restaking eigenlayer",
  "flash loans", "MEV protection", "crypto indices", "algorithmic stablecoin",
  "collateralized debt position", "web3 bug bounty", "smart contract audit",
  "crypto taxation", "crypto payments api", "web3 identity",
  "zero knowledge proofs", "privacy coins", "monero swap",
  "web3 music streaming", "decentralized video platform", "crypto lottery",
  "prediction markets", "token launchpad", "initial dex offering",
  "airdrop checker"
];

const SEARCH_NODE_URL = 'http://localhost:8000/query';

async function runBenchmark() {
  console.log(`Starting benchmark against ${SEARCH_NODE_URL} with ${queries.length} queries...\n`);

  let successCount = 0;
  let totalTime = 0;
  let minTime = Infinity;
  let maxTime = 0;

  for (let i = 0; i < queries.length; i++) {
    const q = queries[i];
    const start = performance.now();
    try {
      await axios.get(SEARCH_NODE_URL, { params: { q } });
      const end = performance.now();
      const duration = end - start;
      
      totalTime += duration;
      if (duration < minTime) minTime = duration;
      if (duration > maxTime) maxTime = duration;
      successCount++;
      
      // Print individual times (formatted)
      process.stdout.write(`[${i+1}/50] "${q}" -> ${duration.toFixed(2)}ms\n`);
    } catch (e) {
      console.error(`[${i+1}/50] "${q}" -> ERROR: ${e.message}`);
    }
  }

  const avgTime = totalTime / successCount;
  
  console.log('\n=============================================');
  console.log('🚀 BENCHMARK RESULTS 🚀');
  console.log('=============================================');
  console.log(`Total Queries Sent:   ${queries.length}`);
  console.log(`Successful Queries:   ${successCount}`);
  console.log(`Average Time:         ${avgTime.toFixed(2)} ms`);
  console.log(`Fastest Query:        ${minTime.toFixed(2)} ms`);
  console.log(`Slowest Query:        ${maxTime.toFixed(2)} ms`);
  console.log(`Est. QPS (Sequential): ${(1000 / avgTime).toFixed(2)} queries per second`);
  console.log('=============================================\n');
}

runBenchmark();
