from typing import List, Optional
from .router import NodeRouter
from .modules.search import SearchModule
from .modules.consensus import ConsensusModule
from .modules.storage import StorageModule

class FeedoClient:
    def __init__(self, search_seeds: Optional[List[str]] = None, consensus_seeds: Optional[List[str]] = None, storage_seeds: Optional[List[str]] = None, private_key: Optional[str] = None):
        self.router = NodeRouter(search_seeds, consensus_seeds, storage_seeds)
        self.private_key = private_key
        
        self.search = SearchModule(self.router, self.private_key)
        self.consensus = ConsensusModule(self.router, self.private_key)
        self.storage = StorageModule(self.router, self.private_key)
