"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.FeedoClient = void 0;
const router_1 = require("./router");
const search_1 = require("./modules/search");
const consensus_1 = require("./modules/consensus");
const storage_1 = require("./modules/storage");
class FeedoClient {
    search;
    consensus;
    storage;
    router;
    constructor(config) {
        this.router = new router_1.NodeRouter(config);
        this.search = new search_1.SearchModule(this.router);
        this.consensus = new consensus_1.ConsensusModule(this.router);
        this.storage = new storage_1.StorageModule(this.router);
    }
}
exports.FeedoClient = FeedoClient;
