// src/router.ts
import axios from "axios";
var DEFAULT_SEEDS = {
  // For local dev, we include localhost ports as well as the mainnet/testnet URLs
  search: ["http://localhost:8000"],
  consensus: ["http://localhost:8080"],
  // Standard Axum port
  storage: ["http://localhost:8081"]
};
var NodeRouter = class {
  searchNodes;
  consensusNodes;
  storageNodes;
  activeSearchNode = null;
  activeConsensusNode = null;
  activeStorageNode = null;
  constructor(config) {
    this.searchNodes = config?.searchSeeds || DEFAULT_SEEDS.search;
    this.consensusNodes = config?.consensusSeeds || DEFAULT_SEEDS.consensus;
    this.storageNodes = config?.storageSeeds || DEFAULT_SEEDS.storage;
  }
  async findFastestNode(nodes, healthEndpoint) {
    const promises = nodes.map(async (node) => {
      const url = `${node}${healthEndpoint}`;
      try {
        await axios.get(url, { timeout: 3e3 });
        return node;
      } catch (error) {
        throw new Error(`Node ${node} failed ping`);
      }
    });
    try {
      return await Promise.any(promises);
    } catch (error) {
      console.warn(`All seed nodes failed. Falling back to the first node in the list: ${nodes[0]}`);
      return nodes[0];
    }
  }
  async getSearchNode() {
    if (!this.activeSearchNode) {
      this.activeSearchNode = await this.findFastestNode(this.searchNodes, "/explorer/stats");
    }
    return this.activeSearchNode;
  }
  async getConsensusNode() {
    if (!this.activeConsensusNode) {
      this.activeConsensusNode = await this.findFastestNode(this.consensusNodes, "/grants");
    }
    return this.activeConsensusNode;
  }
  async getStorageNode() {
    if (!this.activeStorageNode) {
      this.activeStorageNode = await this.findFastestNode(this.storageNodes, "/api/files/recent");
    }
    return this.activeStorageNode;
  }
  invalidateSearchNode() {
    this.activeSearchNode = null;
  }
  invalidateConsensusNode() {
    this.activeConsensusNode = null;
  }
  invalidateStorageNode() {
    this.activeStorageNode = null;
  }
};

// src/modules/search.ts
import axios2 from "axios";
var SearchModule = class {
  constructor(router) {
    this.router = router;
  }
  router;
  async request(method, path, data) {
    let baseUrl = await this.router.getSearchNode();
    let url = `${baseUrl}${path}`;
    try {
      const response = await axios2({ method, url, data });
      return response.data;
    } catch (error) {
      console.warn(`Search request failed on ${baseUrl}, trying to find a new node...`);
      this.router.invalidateSearchNode();
      baseUrl = await this.router.getSearchNode();
      url = `${baseUrl}${path}`;
      const retryResponse = await axios2({ method, url, data });
      return retryResponse.data;
    }
  }
  async query(queryText, limit = 10) {
    return this.request("GET", `/query?q=${encodeURIComponent(queryText)}&limit=${limit}`);
  }
  async indexDocument(content, metadata = {}) {
    return this.request("POST", "/index_document", { content, metadata });
  }
  async deployProxy(directoryPath, domain) {
    return this.request("POST", "/proxy/publish_feedo", { source_dir: directoryPath, domain });
  }
  async unpin(cid) {
    return this.request("DELETE", `/proxy/unpin_feedo/${cid}`);
  }
  async getStats() {
    return this.request("GET", "/explorer/stats");
  }
};

// src/modules/consensus.ts
import axios3 from "axios";
var ConsensusModule = class {
  constructor(router) {
    this.router = router;
  }
  router;
  async request(method, path, data) {
    let baseUrl = await this.router.getConsensusNode();
    let url = `${baseUrl}${path}`;
    try {
      const response = await axios3({ method, url, data });
      return response.data;
    } catch (error) {
      console.warn(`Consensus request failed on ${baseUrl}, trying to find a new node...`);
      this.router.invalidateConsensusNode();
      baseUrl = await this.router.getConsensusNode();
      url = `${baseUrl}${path}`;
      const retryResponse = await axios3({ method, url, data });
      return retryResponse.data;
    }
  }
  async resolveName(name) {
    return this.request("GET", `/resolve/${encodeURIComponent(name)}`);
  }
  async resolveCid(cid) {
    return this.request("GET", `/resolve_cid/${encodeURIComponent(cid)}`);
  }
  async getDidBalance(did) {
    return this.request("GET", `/did/${encodeURIComponent(did)}/balance`);
  }
  async registerDid(pubkeyHex, signatureHex) {
    return this.request("POST", "/did/register", { pubkey_hex: pubkeyHex, signature_hex: signatureHex });
  }
  async registerName(name, did, cid, signatureHex) {
    return this.request("POST", "/name/register", { name, did, cid, signature_hex: signatureHex });
  }
  async updateNameCid(name, newCid, signatureHex) {
    return this.request("POST", "/name/update_cid", { name, new_cid: newCid, signature_hex: signatureHex });
  }
  async listGrants() {
    return this.request("GET", "/grants");
  }
};

// src/modules/storage.ts
import axios4 from "axios";
var StorageModule = class {
  constructor(router) {
    this.router = router;
  }
  router;
  async request(method, path, data, isMultipart = false) {
    let baseUrl = await this.router.getStorageNode();
    let url = `${baseUrl}${path}`;
    const headers = {};
    if (isMultipart) {
      headers["Content-Type"] = "multipart/form-data";
    }
    try {
      const response = await axios4({ method, url, data, headers });
      return response.data;
    } catch (error) {
      console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
      this.router.invalidateStorageNode();
      baseUrl = await this.router.getStorageNode();
      url = `${baseUrl}${path}`;
      const retryResponse = await axios4({ method, url, data, headers });
      return retryResponse.data;
    }
  }
  async uploadFile(fileBlobOrBuffer, filename = "file") {
    const formData = new FormData();
    formData.append("file", fileBlobOrBuffer, filename);
    return this.request("POST", "/upload", formData, true);
  }
  async downloadFile(hash) {
    let baseUrl = await this.router.getStorageNode();
    let url = `${baseUrl}/download/${encodeURIComponent(hash)}`;
    const response = await axios4.get(url, { responseType: "arraybuffer" });
    return response.data;
  }
  async ingestJson(payload) {
    return this.request("POST", "/api/v1/ingest/post", payload);
  }
  async getRecentFiles() {
    return this.request("GET", "/api/files/recent");
  }
};

// src/client.ts
var FeedoClient = class {
  search;
  consensus;
  storage;
  router;
  constructor(config) {
    this.router = new NodeRouter(config);
    this.search = new SearchModule(this.router);
    this.consensus = new ConsensusModule(this.router);
    this.storage = new StorageModule(this.router);
  }
};
export {
  ConsensusModule,
  FeedoClient,
  NodeRouter,
  SearchModule,
  StorageModule
};
