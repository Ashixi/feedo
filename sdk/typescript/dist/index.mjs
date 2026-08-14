var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
  get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
}) : x)(function(x) {
  if (typeof require !== "undefined") return require.apply(this, arguments);
  throw Error('Dynamic require of "' + x + '" is not supported');
});
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/modules/crypto.ts
var crypto_exports = {};
__export(crypto_exports, {
  FeedoCrypto: () => FeedoCrypto
});
import { encrypt, decrypt } from "eciesjs";
import * as crypto from "crypto";
import { ethers as ethers3 } from "ethers";
var FeedoCrypto;
var init_crypto = __esm({
  "src/modules/crypto.ts"() {
    "use strict";
    FeedoCrypto = class {
      static generateSymmetricKey() {
        return crypto.randomBytes(32);
      }
      /**
       * Deterministically derive the usage key (0xD) from the wallet key (0xW).
       * usage_sk = HMAC-SHA256(key=wallet_sk, msg="feedo/usage-key/v1") mod n
       * The derived key can sign requests but cannot move funds (USDT stay on 0xW).
       */
      static deriveUsageKey(walletPrivateKeyHex) {
        const skBytes = Buffer.from(walletPrivateKeyHex.replace("0x", ""), "hex");
        const digest = crypto.createHmac("sha256", skBytes).update("feedo/usage-key/v1").digest();
        let usageInt = BigInt("0x" + digest.toString("hex"));
        const n = BigInt("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141");
        usageInt = usageInt % n;
        if (usageInt === 0n) usageInt = 1n;
        const usageHex = usageInt.toString(16).padStart(64, "0");
        const wallet = new ethers3.Wallet("0x" + usageHex);
        return { privateKey: "0x" + usageHex, address: wallet.address };
      }
      static encryptData(key, data) {
        const nonce = crypto.randomBytes(12);
        const cipher = crypto.createCipheriv("aes-256-gcm", key, nonce);
        const ciphertext = Buffer.concat([cipher.update(data), cipher.final()]);
        const tag = cipher.getAuthTag();
        return Buffer.concat([nonce, ciphertext, tag]);
      }
      static decryptData(key, encryptedData) {
        if (encryptedData.length < 28) {
          throw new Error("Data is too short to be AES-GCM encrypted");
        }
        const nonce = encryptedData.subarray(0, 12);
        const tag = encryptedData.subarray(encryptedData.length - 16);
        const ciphertext = encryptedData.subarray(12, encryptedData.length - 16);
        const decipher = crypto.createDecipheriv("aes-256-gcm", key, nonce);
        decipher.setAuthTag(tag);
        return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
      }
      /**
       * @param publicKeyHex hex string of secp256k1 public key
       * @param key symmetric key bytes
       * @returns hex string of the ECIES encrypted symmetric key
       */
      static encryptSymmetricKeyEcies(publicKeyHex, key) {
        const pubKey = publicKeyHex.replace("0x", "");
        const encrypted = encrypt(pubKey, key);
        return Buffer.from(encrypted).toString("hex");
      }
      /**
       * @param privateKeyHex hex string of secp256k1 private key
       * @param encryptedKeyHex hex string of the ECIES encrypted symmetric key
       * @returns decrypted symmetric key bytes
       */
      static decryptSymmetricKeyEcies(privateKeyHex, encryptedKeyHex) {
        const privKey = privateKeyHex.replace("0x", "");
        const encBytes = Buffer.from(encryptedKeyHex.replace("0x", ""), "hex");
        const decrypted = decrypt(privKey, encBytes);
        return Buffer.from(decrypted);
      }
    };
  }
});

// src/router.ts
import axios from "axios";
var DEFAULT_SEEDS = {
  // Mainnet nodes and local fallback
  search: ["http://95.111.245.68:8000", "http://178.18.253.94:8000", "http://localhost:8000"],
  consensus: ["http://95.111.245.68:3000", "http://178.18.253.94:3000", "http://localhost:3000"],
  storage: ["http://95.111.245.68:3001", "http://178.18.253.94:3001", "http://localhost:3001"]
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
import { ethers } from "ethers";
var SearchModule = class {
  constructor(router, privateKey, usageKey, did) {
    this.router = router;
    this.privateKey = privateKey;
    this.usageKey = usageKey;
    this.did = did;
  }
  router;
  privateKey;
  usageKey;
  did;
  myDid() {
    if (this.did) return this.did;
    const wallet = new ethers.Wallet(this.privateKey);
    return `did:feedo:${wallet.address}`;
  }
  async request(method, path, data) {
    let baseUrl = await this.router.getSearchNode();
    let url = `${baseUrl}${path}`;
    const headers = {};
    if (this.usageKey && this.did) {
      const wallet = new ethers.Wallet(this.usageKey);
      const timestamp = Date.now().toString();
      const basePath = path.split("?")[0];
      const payload = `FeedoAction:${method}:${basePath}:${timestamp}`;
      const signature = await wallet.signMessage(payload);
      headers["X-Feedo-DID"] = this.did;
      headers["X-Feedo-Timestamp"] = timestamp;
      headers["X-Feedo-Signature"] = signature;
    } else if (this.privateKey) {
      const wallet = new ethers.Wallet(this.privateKey);
      const did = `did:feedo:${wallet.address}`;
      const timestamp = Date.now().toString();
      const basePath = path.split("?")[0];
      const payload = `FeedoAction:${method}:${basePath}:${timestamp}`;
      const signature = await wallet.signMessage(payload);
      headers["X-Feedo-DID"] = did;
      headers["X-Feedo-Timestamp"] = timestamp;
      headers["X-Feedo-Signature"] = signature;
    }
    try {
      const response = await axios2({ method, url, data, headers });
      return response.data;
    } catch (error) {
      console.warn(`Search request failed on ${baseUrl}, trying to find a new node...`);
      this.router.invalidateSearchNode();
      baseUrl = await this.router.getSearchNode();
      url = `${baseUrl}${path}`;
      const retryResponse = await axios2({ method, url, data, headers });
      return retryResponse.data;
    }
  }
  async search(query, limit = 50, federated = true, itemType = "all", offset = 0, appId, searchType = "text", imageUrl, namespace) {
    let qs = `text=${encodeURIComponent(query)}&limit=${limit}&federated=${federated}&item_type=${itemType}&offset=${offset}&search_type=${encodeURIComponent(searchType)}`;
    if (appId) qs += `&app_id=${encodeURIComponent(appId)}`;
    if (imageUrl) qs += `&image_url=${encodeURIComponent(imageUrl)}`;
    if (namespace) qs += `&namespace=${encodeURIComponent(namespace)}`;
    return this.request("GET", `/query?${qs}`);
  }
  async getDocuments(limit = 50, offset = 0, itemType = "all", appId, namespace) {
    let qs = `limit=${limit}&offset=${offset}&item_type=${itemType}`;
    if (appId) qs += `&app_id=${encodeURIComponent(appId)}`;
    if (namespace) qs += `&namespace=${encodeURIComponent(namespace)}`;
    return this.request("GET", `/documents?${qs}`);
  }
  async indexPrivateDocument(hashId, plaintext, metadata = {}, namespace) {
    if (!this.privateKey && !this.usageKey) {
      throw new Error("Private key or usage key required to index private documents");
    }
    const myDid = this.myDid();
    return this.request("POST", "/index_document", {
      hash_id: hashId,
      text: plaintext,
      item_type: "private_post",
      author: myDid,
      metadata,
      namespace: namespace || ""
    });
  }
  async indexImage(hashId, metadata = {}, symmetricKey, namespace) {
    let author = "";
    let itemType = "image";
    if (symmetricKey) {
      if (!this.privateKey && !this.usageKey) {
        throw new Error("Private key or usage key required to index private images");
      }
      author = this.myDid();
      itemType = "private_image";
    }
    return this.request("POST", "/index_image", {
      hash_id: hashId,
      item_type: itemType,
      author,
      metadata,
      symmetric_key: symmetricKey,
      namespace: namespace || ""
    });
  }
  async indexDocument(content, metadata = {}, namespace, hashId) {
    const hash_id = hashId || "doc_" + Math.random().toString(36).substring(7);
    const item_type = metadata.type || "document";
    return this.request("POST", "/index_document", { text: content, metadata, hash_id, item_type, namespace: namespace || "" });
  }
  async countByNamespace(namespace, federated = true) {
    return this.request("GET", `/count?namespace=${encodeURIComponent(namespace)}&federated=${federated}`);
  }
  async deleteByNamespace(namespace) {
    return this.request("DELETE", `/namespace/${encodeURIComponent(namespace)}`);
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
  constructor(router, privateKey) {
    this.router = router;
    this.privateKey = privateKey;
  }
  router;
  privateKey;
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
  async registerDid(publicKeyHex, signature) {
    const { ethers: ethers4 } = __require("ethers");
    let address = "";
    try {
      address = ethers4.computeAddress(publicKeyHex);
    } catch (e) {
      address = publicKeyHex;
    }
    const did = `did:feedo:${address}`;
    return this.request("POST", "/did/register", {
      did,
      public_key: address,
      signature
    });
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
  async grantFileAccess(fileHash, granteeDid, encryptedSymmetricKey, publicKey, signatureHex) {
    return this.request("POST", "/grant/access", {
      file_hash: fileHash,
      grantee_did: granteeDid,
      encrypted_symmetric_key: encryptedSymmetricKey,
      public_key: publicKey,
      signature: signatureHex
    });
  }
  async getFileAccess(fileHash, granteeDid) {
    return this.request("GET", `/grant/access/${encodeURIComponent(fileHash)}/${encodeURIComponent(granteeDid)}`);
  }
};

// src/modules/storage.ts
import axios4 from "axios";
import { ethers as ethers2 } from "ethers";
var StorageModule = class {
  constructor(router, privateKey) {
    this.router = router;
    this.privateKey = privateKey;
  }
  router;
  privateKey;
  async request(method, path, data, isMultipart = false) {
    let baseUrl = await this.router.getStorageNode();
    let url = `${baseUrl}${path}`;
    const headers = {};
    if (this.privateKey) {
      const wallet = new ethers2.Wallet(this.privateKey);
      const did = `did:feedo:${wallet.address}`;
      const timestamp = Date.now().toString();
      const payload = `FeedoAction:${method}:${path}:${timestamp}`;
      const signature = await wallet.signMessage(payload);
      headers["X-Feedo-DID"] = did;
      headers["X-Feedo-Timestamp"] = timestamp;
      headers["X-Feedo-Signature"] = signature;
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
  async uploadSingleChunk(fileBlobOrBuffer, filename) {
    let finalData = fileBlobOrBuffer;
    if (typeof Buffer !== "undefined" && Buffer.isBuffer(fileBlobOrBuffer)) {
      finalData = new Blob([fileBlobOrBuffer]);
    } else if (fileBlobOrBuffer instanceof Uint8Array) {
      finalData = new Blob([fileBlobOrBuffer]);
    }
    const formData = new FormData();
    formData.append("file", finalData, filename);
    let baseUrl = await this.router.getStorageNode();
    let url = `${baseUrl}/upload`;
    const headers = {};
    if (this.privateKey) {
      const wallet = new ethers2.Wallet(this.privateKey);
      const did = `did:feedo:${wallet.address}`;
      const timestamp = Date.now().toString();
      const payload = `FeedoAction:POST:/upload:${timestamp}`;
      const signature = await wallet.signMessage(payload);
      headers["X-Feedo-DID"] = did;
      headers["X-Feedo-Timestamp"] = timestamp;
      headers["X-Feedo-Signature"] = signature;
    }
    try {
      const response = await fetch(url, { method: "POST", headers, body: formData });
      if (!response.ok) throw new Error(await response.text());
      return await response.text();
    } catch (error) {
      console.warn(`Storage request failed on ${baseUrl}, trying to find a new node...`);
      this.router.invalidateStorageNode();
      baseUrl = await this.router.getStorageNode();
      url = `${baseUrl}/upload`;
      const retryResponse = await fetch(url, { method: "POST", headers, body: formData });
      if (!retryResponse.ok) throw new Error(await retryResponse.text());
      return await retryResponse.text();
    }
  }
  async uploadFile(fileBlobOrBuffer, filename = "file") {
    let size = 0;
    if (fileBlobOrBuffer.size !== void 0) size = fileBlobOrBuffer.size;
    else if (fileBlobOrBuffer.byteLength !== void 0) size = fileBlobOrBuffer.byteLength;
    else if (fileBlobOrBuffer.length !== void 0) size = fileBlobOrBuffer.length;
    const CHUNK_SIZE = 5 * 1024 * 1024;
    if (size <= CHUNK_SIZE) {
      return this.uploadSingleChunk(fileBlobOrBuffer, filename);
    }
    const chunks = [];
    let offset = 0;
    while (offset < size) {
      let chunk;
      if (fileBlobOrBuffer.slice) {
        chunk = fileBlobOrBuffer.slice(offset, offset + CHUNK_SIZE);
      } else if (fileBlobOrBuffer.subarray) {
        chunk = fileBlobOrBuffer.subarray(offset, offset + CHUNK_SIZE);
      } else {
        throw new Error("Unsupported file type for chunking");
      }
      chunks.push(chunk);
      offset += CHUNK_SIZE;
    }
    const limit = 10;
    const hashes = new Array(chunks.length);
    let i = 0;
    const workers = new Array(limit).fill(0).map(async () => {
      while (i < chunks.length) {
        const index = i++;
        const chunkFilename = `${filename}.part${index}`;
        hashes[index] = await this.uploadSingleChunk(chunks[index], chunkFilename);
      }
    });
    await Promise.all(workers);
    const manifest = {
      type: "feedo_manifest",
      filename,
      total_size: size,
      chunk_size: CHUNK_SIZE,
      chunks: hashes
    };
    const manifestString = JSON.stringify(manifest);
    let manifestData;
    if (typeof Blob !== "undefined") {
      manifestData = new Blob([manifestString], { type: "application/json" });
    } else {
      manifestData = Buffer.from(manifestString, "utf-8");
    }
    return await this.uploadSingleChunk(manifestData, "manifest.json");
  }
  async downloadSingleChunk(hash) {
    let baseUrl = await this.router.getStorageNode();
    let path = `/download/${encodeURIComponent(hash)}`;
    let url = `${baseUrl}${path}`;
    const headers = {};
    if (this.privateKey) {
      const wallet = new ethers2.Wallet(this.privateKey);
      const did = `did:feedo:${wallet.address}`;
      const timestamp = Date.now().toString();
      const payload = `FeedoAction:GET:${path}:${timestamp}`;
      const signature = await wallet.signMessage(payload);
      headers["X-Feedo-DID"] = did;
      headers["X-Feedo-Timestamp"] = timestamp;
      headers["X-Feedo-Signature"] = signature;
    }
    try {
      const response = await axios4.get(url, { responseType: "arraybuffer", headers });
      return response.data;
    } catch (error) {
      console.warn(`Download failed on ${baseUrl}, trying new node...`);
      this.router.invalidateStorageNode();
      baseUrl = await this.router.getStorageNode();
      path = `/download/${encodeURIComponent(hash)}`;
      url = `${baseUrl}${path}`;
      const retryResponse = await axios4.get(url, { responseType: "arraybuffer", headers });
      return retryResponse.data;
    }
  }
  async downloadFile(hash) {
    const rawData = await this.downloadSingleChunk(hash);
    if (rawData.byteLength < 1024 * 1024) {
      try {
        const text = new TextDecoder().decode(rawData);
        const json = JSON.parse(text);
        if (json.type === "feedo_manifest" && Array.isArray(json.chunks)) {
          const limit = 10;
          const chunks = new Array(json.chunks.length);
          let i = 0;
          const workers = new Array(limit).fill(0).map(async () => {
            while (i < json.chunks.length) {
              const index = i++;
              chunks[index] = await this.downloadSingleChunk(json.chunks[index]);
            }
          });
          await Promise.all(workers);
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
      }
    }
    return rawData;
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
    this.search = new SearchModule(this.router, config?.privateKey, config?.usageKey, config?.did);
    this.consensus = new ConsensusModule(this.router, config?.privateKey);
    this.storage = new StorageModule(this.router, config?.privateKey);
  }
  async uploadPrivateFile(fileBuffer, granteePublicKeyHex, indexForSearch = true, metadata = {}) {
    if (!this.search["privateKey"]) {
      throw new Error("Private key required to upload private files");
    }
    const privateKey = this.search["privateKey"];
    const { ethers: ethers4 } = __require("ethers");
    const wallet = new ethers4.Wallet(privateKey);
    const myDid = `did:feedo:${wallet.address}`;
    const myPublicKey = wallet.signingKey.publicKey;
    const targetPubKey = granteePublicKeyHex || myPublicKey;
    const targetDid = granteePublicKeyHex ? "unknown" : myDid;
    const { FeedoCrypto: FeedoCrypto2 } = (init_crypto(), __toCommonJS(crypto_exports));
    const symKey = FeedoCrypto2.generateSymmetricKey();
    console.log("[DEBUG] Encrypting and uploading chunks...");
    const CHUNK_SIZE = 5 * 1024 * 1024;
    const size = fileBuffer.byteLength;
    const chunks = [];
    let offset = 0;
    while (offset < size) {
      const chunk = fileBuffer.subarray(offset, offset + CHUNK_SIZE);
      chunks.push(FeedoCrypto2.encryptData(symKey, chunk));
      offset += CHUNK_SIZE;
    }
    const limit = 10;
    const hashes = new Array(chunks.length);
    let i = 0;
    const workers = new Array(limit).fill(0).map(async () => {
      while (i < chunks.length) {
        const index = i++;
        const chunkFilename = `encrypted_part${index}`;
        hashes[index] = await this.storage.uploadSingleChunk(chunks[index], chunkFilename);
      }
    });
    await Promise.all(workers);
    const manifest = {
      type: "feedo_encrypted_manifest",
      filename: "encrypted_file.bin",
      total_size: size,
      chunk_size: CHUNK_SIZE,
      chunks: hashes
    };
    const manifestString = JSON.stringify(manifest);
    const manifestData = Buffer.from(manifestString, "utf-8");
    const hashId = await this.storage.uploadSingleChunk(manifestData, "manifest.json");
    console.log("[DEBUG] uploadPrivateFile finished, hashId:", hashId);
    const encSymKey = FeedoCrypto2.encryptSymmetricKeyEcies(targetPubKey, symKey);
    const payloadBytes = Buffer.from(`${hashId}${targetDid}${encSymKey}`, "utf-8");
    const signature = await wallet.signMessage(payloadBytes);
    console.log("[DEBUG] Calling consensus.grantFileAccess...");
    await this.consensus.grantFileAccess(hashId, targetDid, encSymKey, myPublicKey, signature);
    console.log("[DEBUG] grantFileAccess finished");
    if (indexForSearch && targetDid === myDid) {
      if (size > 30 * 1024 * 1024) {
        console.log("[DEBUG] File > 30MB, skipping search indexing (Vectorization bypass)");
      } else {
        if (metadata.type === "image") {
          console.log("[DEBUG] Calling search.indexImage...");
          await this.search.indexImage(hashId, metadata, symKey.toString("hex"));
          console.log("[DEBUG] indexImage finished");
        } else {
          try {
            const textContent = fileBuffer.toString("utf-8");
            console.log("[DEBUG] Calling search.indexPrivateDocument...");
            await this.search.indexPrivateDocument(hashId, textContent, metadata);
            console.log("[DEBUG] indexPrivateDocument finished");
          } catch (e) {
          }
        }
      }
    }
    return hashId;
  }
  async downloadPrivateFile(hashId) {
    if (!this.search["privateKey"]) {
      throw new Error("Private key required to download private files");
    }
    const privateKey = this.search["privateKey"];
    const { ethers: ethers4 } = __require("ethers");
    const wallet = new ethers4.Wallet(privateKey);
    const myDid = `did:feedo:${wallet.address}`;
    const res = await this.consensus.getFileAccess(hashId, myDid);
    const encSymKey = res.encrypted_symmetric_key;
    if (!encSymKey) {
      throw new Error(`No access granted for ${myDid} to file ${hashId}`);
    }
    const { FeedoCrypto: FeedoCrypto2 } = (init_crypto(), __toCommonJS(crypto_exports));
    const symKey = FeedoCrypto2.decryptSymmetricKeyEcies(privateKey, encSymKey);
    const rawData = await this.storage.downloadFile(hashId);
    if (rawData.byteLength < 1024 * 1024) {
      try {
        const text = new TextDecoder().decode(rawData);
        const json = JSON.parse(text);
        if (json.type === "feedo_encrypted_manifest" && Array.isArray(json.chunks)) {
          const limit = 10;
          const decryptedChunks = new Array(json.chunks.length);
          let i = 0;
          const workers = new Array(limit).fill(0).map(async () => {
            while (i < json.chunks.length) {
              const index = i++;
              const encChunkRaw = await this.storage.downloadSingleChunk(json.chunks[index]);
              const encChunk = Buffer.from(encChunkRaw);
              decryptedChunks[index] = FeedoCrypto2.decryptData(symKey, encChunk);
            }
          });
          await Promise.all(workers);
          return Buffer.concat(decryptedChunks);
        }
      } catch (e) {
      }
    }
    const encryptedData = Buffer.from(rawData);
    return FeedoCrypto2.decryptData(symKey, encryptedData);
  }
};

// src/index.ts
init_crypto();
export {
  ConsensusModule,
  FeedoClient,
  FeedoCrypto,
  NodeRouter,
  SearchModule,
  StorageModule
};
