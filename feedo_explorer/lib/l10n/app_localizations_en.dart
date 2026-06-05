import 'app_localizations.dart';

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appName => 'Feedo Explorer';

  @override
  String get overview => 'Overview';

  @override
  String get network => 'Network';

  @override
  String get identities => 'Identities';

  @override
  String get consensus => 'Consensus';

  @override
  String get docs => 'Docs';

  @override
  String get networkTopology => 'Network Topology';

  @override
  String get identitiesDid => 'Identities (DID)';

  @override
  String get consensusLogs => 'Consensus Logs';

  @override
  String get documentation => 'Documentation';

  @override
  String get vectorSearch => 'Vector Search Explorer';

  @override
  String get contentExplorer => 'Content Explorer';

  @override
  String get heroTitle => 'Feedo. End of the Web2 era.\\nBeginning of the semantic internet.';

  @override
  String get heroSubtitle => 'Modern internet is broken by monopolies and blind servers. We are rewriting its architecture from scratch. Feedo is a decentralized L1 protocol that turns the fragmented web into a single global knowledge graph. An internet that understands its content.';

  @override
  String get readManifesto => 'Read Manifesto';

  @override
  String get documentationButton => 'Documentation';

  @override
  String get deployDapp => 'Deploy dApp';

  @override
  String get liveNetworkExplorer => 'Live Network Explorer';

  @override
  String get problemTitle => 'The Internet has become a digital graveyard';

  @override
  String get problemBody => 'The modern Web2 internet is an architectural cripple. It\'s just millions of isolated centralized servers from AWS, Google, and other giants blindly storing gigabytes of raw bytes. They have no idea what lies inside them. Data is fragmented, users don\'t own their content, and search algorithms run on primitive keywords. We decided enough is enough.';

  @override
  String get solutionTitle => 'More than a protocol. A living semantic infrastructure.';

  @override
  String get solutionBody => 'Feedo is a next-generation L1 protocol built for the AI and Web3 era. We don\'t just decentralize hosting. We stitch independent nodes into a single, cohesive vector structure.\\n\\nThanks to built-in vector semantics, data inside the Feedo network is automatically structured. Our protocol literally understands the context and meaning of every piece of information. It\'s the world\'s first decentralized database and AI infrastructure merged into one fast organism.';

  @override
  String get techTitle => 'Under the Hood';

  @override
  String get techBody => 'We don\'t use crutches from the past. Feedo is built on an uncompromising stack to ensure maximum speed, security, and decentralization:';

  @override
  String get techRust => 'Written in Rust';

  @override
  String get techRustDesc => 'Lightning-fast performance, memory safety, and zero tolerance for failures at the core level.';

  @override
  String get techVector => 'Vector Semantics';

  @override
  String get techVectorDesc => 'Data is stored as vectors. Allows future AI agents to search for information by meaning, not words.';

  @override
  String get techCrdt => 'CRDT Math';

  @override
  String get techCrdtDesc => 'No synchronization conflicts. Your data updates instantly across all nodes without middlemen.';

  @override
  String get techPbft => 'PBFT Consensus';

  @override
  String get techPbftDesc => 'Byzantine fault-tolerant architecture. The network runs even if a portion of nodes is compromised.';

  @override
  String get ecoTitle => 'Build the future, not another CRUD app';

  @override
  String get ecoBody => 'Feedo is the foundation. We provide infrastructure to deploy decentralized applications (dApps) that require smart data processing and independence from Big Tech.\\n\\nWhat can be built on Feedo right now:';

  @override
  String get ecoAiBrowsers => 'AI-Native Browsers';

  @override
  String get ecoAiBrowsersDesc => 'Our team is already developing the world\'s first decentralized browser on top of the Feedo protocol, which will become a window to the new semantic Web.';

  @override
  String get ecoSocial => 'Smart social networks';

  @override
  String get ecoSocialDesc => 'Where users truly own their connection graph.';

  @override
  String get ecoDb => 'Decentralized knowledge bases';

  @override
  String get ecoDbDesc => 'Tools for teams that work faster than Notion and don\'t depend on cloud monopolies.';

  @override
  String get footerTitle => 'Your move.';

  @override
  String get footerBody => 'The era of blind servers is ending. The industry is moving to the Semantic Web, and we are building its rails.\\n\\nYou can join the core development, spin up your node, deploy your first Feedo-based dApp, or... just silently watch from the sidelines as we change internet history. The choice is yours.';

  @override
  String get getStarted => 'Get started with Feedo ->';

  @override
  String get copyright => '© 2026 Feedo Protocol. All rights reserved.';

  @override
  String get networkTopologyTitle => 'Network Topology';

  @override
  String get identitiesDidTitle => 'Identities (DID)';

  @override
  String get consensusLogsTitle => 'Consensus Logs';

  @override
  String get consensusLogsPbft => 'Consensus Logs (PBFT)';

  @override
  String get consensusHistoryDesc => 'History of confirmed blocks and distributed CRDT operations.';

  @override
  String get noConsensusLogs => 'No consensus logs found yet.';

  @override
  String get networkStatsDesc => 'P2P nodes, Supernodes, and Data Availability Layer stats.';

  @override
  String get totalNodes => 'Total Nodes';

  @override
  String get activeSupernodes => 'Active Supernodes';

  @override
  String get networkStatus => 'Network Status';

  @override
  String get kademliaTopology => 'Kademlia DHT Topology';

  @override
  String get noActivePeers => 'No active peers found in the network.';

  @override
  String get contentExplorerTitle => 'Content Explorer';

  @override
  String get contentSearchDesc => 'Search and verify raw posts on the DHT using their cryptographic Hash ID.';

  @override
  String get enterHashId => 'Enter Content Hash ID';

  @override
  String get searchButton => 'Search';

  @override
  String get enterHashIdPlaceholder => 'Enter Content Hash ID (e.g., hash_...)';

  @override
  String get unknownHash => 'Unknown Hash';

  @override
  String get authorWallet => 'Author Wallet';

  @override
  String get contentType => 'Content Type';

  @override
  String get timestampLabel => 'Timestamp';

  @override
  String get signatureLabel => 'Signature';

  @override
  String get present => 'Present';

  @override
  String get missing => 'Missing';

  @override
  String get rawContentPayload => 'Raw Content Payload';

  @override
  String get noTextContent => 'No text content';

  @override
  String get jsonMetadata => 'JSON Metadata';

  @override
  String get walletIdentityTitle => 'Wallet Identity';

  @override
  String get walletIdentityDesc => 'Decentralized access control. Generate a local wallet to sign requests to the Feedo network.';

  @override
  String get generateIdentity => 'Generate Identity';

  @override
  String get clearIdentity => 'Clear Identity';

  @override
  String get noIdentityFound => 'No Identity Found';

  @override
  String get mustGenerateWallet => 'You must generate a local wallet to interact with the decentralized API.';

  @override
  String get identityActive => 'Identity Active';

  @override
  String get publicWalletAddress => 'Public Wallet Address (SECP256k1)';

  @override
  String get privateKeyStoredLocally => 'Private Key (Stored Locally)';

  @override
  String get identityZeroTrustDesc => 'This identity is used to sign all outgoing HTTP requests using Zero-Trust architecture. It proves you own this wallet address without sending the private key.';

  @override
  String get feedoDocsTitle => 'Feedo Documentation';

  @override
  String get feedoDocsDesc => 'Technical reference for the Feedo Protocol and Semantic Data Grid.';

  @override
  String get githubRepo => 'GitHub Repository';

  @override
  String get decentralizedIdentities => 'Decentralized Identities';

  @override
  String get activeDidPeersDesc => 'Active DID peers and their reputation scores on the network.';

  @override
  String get noIdentitiesFound => 'No identities found on the network yet.';

  @override
  String get didColumn => 'DID';

  @override
  String get reputationColumn => 'Reputation';

  @override
  String get statusColumn => 'Status';

  @override
  String get activePeer => 'Active Peer';

  @override
  String get active => 'Active';

  @override
  String get vectorSearchExplorer => 'Vector Search Explorer';

  @override
  String get exploreAiVectorsDesc => 'Explore AI embedding vectors for specific posts to understand semantic clustering.';

  @override
  String get searchVector => 'Search Vector';

  @override
  String get embeddingRepresentation => 'Embedding Representation';

  @override
  String get exposeVectorApiHint => 'Make sure EXPOSE_VECTOR_API=\"true\" is set in your docker-compose.yml to enable this.';
}
