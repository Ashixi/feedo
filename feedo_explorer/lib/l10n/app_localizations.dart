import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_uk.dart';

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale) : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations? of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations);
  }

  static const LocalizationsDelegate<AppLocalizations> delegate = _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates = <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('uk')
  ];

  /// No description provided for @appName.
  ///
  /// In en, this message translates to:
  /// **'Feedo Explorer'**
  String get appName;

  /// No description provided for @overview.
  ///
  /// In en, this message translates to:
  /// **'Overview'**
  String get overview;

  /// No description provided for @network.
  ///
  /// In en, this message translates to:
  /// **'Network'**
  String get network;

  /// No description provided for @identities.
  ///
  /// In en, this message translates to:
  /// **'Identities'**
  String get identities;

  /// No description provided for @consensus.
  ///
  /// In en, this message translates to:
  /// **'Consensus'**
  String get consensus;

  /// No description provided for @docs.
  ///
  /// In en, this message translates to:
  /// **'Docs'**
  String get docs;

  /// No description provided for @networkTopology.
  ///
  /// In en, this message translates to:
  /// **'Network Topology'**
  String get networkTopology;

  /// No description provided for @identitiesDid.
  ///
  /// In en, this message translates to:
  /// **'Identities (DID)'**
  String get identitiesDid;

  /// No description provided for @consensusLogs.
  ///
  /// In en, this message translates to:
  /// **'Consensus Logs'**
  String get consensusLogs;

  /// No description provided for @documentation.
  ///
  /// In en, this message translates to:
  /// **'Documentation'**
  String get documentation;

  /// No description provided for @vectorSearch.
  ///
  /// In en, this message translates to:
  /// **'Vector Search Explorer'**
  String get vectorSearch;

  /// No description provided for @contentExplorer.
  ///
  /// In en, this message translates to:
  /// **'Content Explorer'**
  String get contentExplorer;

  /// No description provided for @heroTitle.
  ///
  /// In en, this message translates to:
  /// **'Feedo. End of the Web2 era.\\nBeginning of the semantic internet.'**
  String get heroTitle;

  /// No description provided for @heroSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Modern internet is broken by monopolies and blind servers. We are rewriting its architecture from scratch. Feedo is a decentralized L1 protocol that turns the fragmented web into a single global knowledge graph. An internet that understands its content.'**
  String get heroSubtitle;

  /// No description provided for @readManifesto.
  ///
  /// In en, this message translates to:
  /// **'Read Manifesto'**
  String get readManifesto;

  /// No description provided for @documentationButton.
  ///
  /// In en, this message translates to:
  /// **'Documentation'**
  String get documentationButton;

  /// No description provided for @deployDapp.
  ///
  /// In en, this message translates to:
  /// **'Deploy dApp'**
  String get deployDapp;

  /// No description provided for @liveNetworkExplorer.
  ///
  /// In en, this message translates to:
  /// **'Live Network Explorer'**
  String get liveNetworkExplorer;

  /// No description provided for @problemTitle.
  ///
  /// In en, this message translates to:
  /// **'The Internet has become a digital graveyard'**
  String get problemTitle;

  /// No description provided for @problemBody.
  ///
  /// In en, this message translates to:
  /// **'The modern Web2 internet is an architectural cripple. It\'s just millions of isolated centralized servers from AWS, Google, and other giants blindly storing gigabytes of raw bytes. They have no idea what lies inside them. Data is fragmented, users don\'t own their content, and search algorithms run on primitive keywords. We decided enough is enough.'**
  String get problemBody;

  /// No description provided for @solutionTitle.
  ///
  /// In en, this message translates to:
  /// **'More than a protocol. A living semantic infrastructure.'**
  String get solutionTitle;

  /// No description provided for @solutionBody.
  ///
  /// In en, this message translates to:
  /// **'Feedo is a next-generation L1 protocol built for the AI and Web3 era. We don\'t just decentralize hosting. We stitch independent nodes into a single, cohesive vector structure.\\n\\nThanks to built-in vector semantics, data inside the Feedo network is automatically structured. Our protocol literally understands the context and meaning of every piece of information. It\'s the world\'s first decentralized database and AI infrastructure merged into one fast organism.'**
  String get solutionBody;

  /// No description provided for @techTitle.
  ///
  /// In en, this message translates to:
  /// **'Under the Hood'**
  String get techTitle;

  /// No description provided for @techBody.
  ///
  /// In en, this message translates to:
  /// **'We don\'t use crutches from the past. Feedo is built on an uncompromising stack to ensure maximum speed, security, and decentralization:'**
  String get techBody;

  /// No description provided for @techRust.
  ///
  /// In en, this message translates to:
  /// **'Written in Rust'**
  String get techRust;

  /// No description provided for @techRustDesc.
  ///
  /// In en, this message translates to:
  /// **'Lightning-fast performance, memory safety, and zero tolerance for failures at the core level.'**
  String get techRustDesc;

  /// No description provided for @techVector.
  ///
  /// In en, this message translates to:
  /// **'Vector Semantics'**
  String get techVector;

  /// No description provided for @techVectorDesc.
  ///
  /// In en, this message translates to:
  /// **'Data is stored as vectors. Allows future AI agents to search for information by meaning, not words.'**
  String get techVectorDesc;

  /// No description provided for @techCrdt.
  ///
  /// In en, this message translates to:
  /// **'CRDT Math'**
  String get techCrdt;

  /// No description provided for @techCrdtDesc.
  ///
  /// In en, this message translates to:
  /// **'No synchronization conflicts. Your data updates instantly across all nodes without middlemen.'**
  String get techCrdtDesc;

  /// No description provided for @techPbft.
  ///
  /// In en, this message translates to:
  /// **'PBFT Consensus'**
  String get techPbft;

  /// No description provided for @techPbftDesc.
  ///
  /// In en, this message translates to:
  /// **'Byzantine fault-tolerant architecture. The network runs even if a portion of nodes is compromised.'**
  String get techPbftDesc;

  /// No description provided for @ecoTitle.
  ///
  /// In en, this message translates to:
  /// **'Build the future, not another CRUD app'**
  String get ecoTitle;

  /// No description provided for @ecoBody.
  ///
  /// In en, this message translates to:
  /// **'Feedo is the foundation. We provide infrastructure to deploy decentralized applications (dApps) that require smart data processing and independence from Big Tech.\\n\\nWhat can be built on Feedo right now:'**
  String get ecoBody;

  /// No description provided for @ecoAiBrowsers.
  ///
  /// In en, this message translates to:
  /// **'AI-Native Browsers'**
  String get ecoAiBrowsers;

  /// No description provided for @ecoAiBrowsersDesc.
  ///
  /// In en, this message translates to:
  /// **'Our team is already developing the world\'s first decentralized browser on top of the Feedo protocol, which will become a window to the new semantic Web.'**
  String get ecoAiBrowsersDesc;

  /// No description provided for @ecoSocial.
  ///
  /// In en, this message translates to:
  /// **'Smart social networks'**
  String get ecoSocial;

  /// No description provided for @ecoSocialDesc.
  ///
  /// In en, this message translates to:
  /// **'Where users truly own their connection graph.'**
  String get ecoSocialDesc;

  /// No description provided for @ecoDb.
  ///
  /// In en, this message translates to:
  /// **'Decentralized knowledge bases'**
  String get ecoDb;

  /// No description provided for @ecoDbDesc.
  ///
  /// In en, this message translates to:
  /// **'Tools for teams that work faster than Notion and don\'t depend on cloud monopolies.'**
  String get ecoDbDesc;

  /// No description provided for @footerTitle.
  ///
  /// In en, this message translates to:
  /// **'Your move.'**
  String get footerTitle;

  /// No description provided for @footerBody.
  ///
  /// In en, this message translates to:
  /// **'The era of blind servers is ending. The industry is moving to the Semantic Web, and we are building its rails.\\n\\nYou can join the core development, spin up your node, deploy your first Feedo-based dApp, or... just silently watch from the sidelines as we change internet history. The choice is yours.'**
  String get footerBody;

  /// No description provided for @getStarted.
  ///
  /// In en, this message translates to:
  /// **'Get started with Feedo ->'**
  String get getStarted;

  /// No description provided for @copyright.
  ///
  /// In en, this message translates to:
  /// **'© 2026 Feedo Protocol. All rights reserved.'**
  String get copyright;

  /// No description provided for @networkTopologyTitle.
  ///
  /// In en, this message translates to:
  /// **'Network Topology'**
  String get networkTopologyTitle;

  /// No description provided for @identitiesDidTitle.
  ///
  /// In en, this message translates to:
  /// **'Identities (DID)'**
  String get identitiesDidTitle;

  /// No description provided for @consensusLogsTitle.
  ///
  /// In en, this message translates to:
  /// **'Consensus Logs'**
  String get consensusLogsTitle;

  /// No description provided for @consensusLogsPbft.
  ///
  /// In en, this message translates to:
  /// **'Consensus Logs (PBFT)'**
  String get consensusLogsPbft;

  /// No description provided for @consensusHistoryDesc.
  ///
  /// In en, this message translates to:
  /// **'History of confirmed blocks and distributed CRDT operations.'**
  String get consensusHistoryDesc;

  /// No description provided for @noConsensusLogs.
  ///
  /// In en, this message translates to:
  /// **'No consensus logs found yet.'**
  String get noConsensusLogs;

  /// No description provided for @networkStatsDesc.
  ///
  /// In en, this message translates to:
  /// **'P2P nodes, Supernodes, and Data Availability Layer stats.'**
  String get networkStatsDesc;

  /// No description provided for @totalNodes.
  ///
  /// In en, this message translates to:
  /// **'Total Nodes'**
  String get totalNodes;

  /// No description provided for @activeSupernodes.
  ///
  /// In en, this message translates to:
  /// **'Active Supernodes'**
  String get activeSupernodes;

  /// No description provided for @networkStatus.
  ///
  /// In en, this message translates to:
  /// **'Network Status'**
  String get networkStatus;

  /// No description provided for @kademliaTopology.
  ///
  /// In en, this message translates to:
  /// **'Kademlia DHT Topology'**
  String get kademliaTopology;

  /// No description provided for @noActivePeers.
  ///
  /// In en, this message translates to:
  /// **'No active peers found in the network.'**
  String get noActivePeers;

  /// No description provided for @contentExplorerTitle.
  ///
  /// In en, this message translates to:
  /// **'Content Explorer'**
  String get contentExplorerTitle;

  /// No description provided for @contentSearchDesc.
  ///
  /// In en, this message translates to:
  /// **'Search and verify raw posts on the DHT using their cryptographic Hash ID.'**
  String get contentSearchDesc;

  /// No description provided for @enterHashId.
  ///
  /// In en, this message translates to:
  /// **'Enter Content Hash ID'**
  String get enterHashId;

  /// No description provided for @searchButton.
  ///
  /// In en, this message translates to:
  /// **'Search'**
  String get searchButton;

  /// No description provided for @enterHashIdPlaceholder.
  ///
  /// In en, this message translates to:
  /// **'Enter Content Hash ID (e.g., hash_...)'**
  String get enterHashIdPlaceholder;

  /// No description provided for @unknownHash.
  ///
  /// In en, this message translates to:
  /// **'Unknown Hash'**
  String get unknownHash;

  /// No description provided for @authorWallet.
  ///
  /// In en, this message translates to:
  /// **'Author Wallet'**
  String get authorWallet;

  /// No description provided for @contentType.
  ///
  /// In en, this message translates to:
  /// **'Content Type'**
  String get contentType;

  /// No description provided for @timestampLabel.
  ///
  /// In en, this message translates to:
  /// **'Timestamp'**
  String get timestampLabel;

  /// No description provided for @signatureLabel.
  ///
  /// In en, this message translates to:
  /// **'Signature'**
  String get signatureLabel;

  /// No description provided for @present.
  ///
  /// In en, this message translates to:
  /// **'Present'**
  String get present;

  /// No description provided for @missing.
  ///
  /// In en, this message translates to:
  /// **'Missing'**
  String get missing;

  /// No description provided for @rawContentPayload.
  ///
  /// In en, this message translates to:
  /// **'Raw Content Payload'**
  String get rawContentPayload;

  /// No description provided for @noTextContent.
  ///
  /// In en, this message translates to:
  /// **'No text content'**
  String get noTextContent;

  /// No description provided for @jsonMetadata.
  ///
  /// In en, this message translates to:
  /// **'JSON Metadata'**
  String get jsonMetadata;

  /// No description provided for @walletIdentityTitle.
  ///
  /// In en, this message translates to:
  /// **'Wallet Identity'**
  String get walletIdentityTitle;

  /// No description provided for @walletIdentityDesc.
  ///
  /// In en, this message translates to:
  /// **'Decentralized access control. Generate a local wallet to sign requests to the Feedo network.'**
  String get walletIdentityDesc;

  /// No description provided for @generateIdentity.
  ///
  /// In en, this message translates to:
  /// **'Generate Identity'**
  String get generateIdentity;

  /// No description provided for @clearIdentity.
  ///
  /// In en, this message translates to:
  /// **'Clear Identity'**
  String get clearIdentity;

  /// No description provided for @noIdentityFound.
  ///
  /// In en, this message translates to:
  /// **'No Identity Found'**
  String get noIdentityFound;

  /// No description provided for @mustGenerateWallet.
  ///
  /// In en, this message translates to:
  /// **'You must generate a local wallet to interact with the decentralized API.'**
  String get mustGenerateWallet;

  /// No description provided for @identityActive.
  ///
  /// In en, this message translates to:
  /// **'Identity Active'**
  String get identityActive;

  /// No description provided for @publicWalletAddress.
  ///
  /// In en, this message translates to:
  /// **'Public Wallet Address (SECP256k1)'**
  String get publicWalletAddress;

  /// No description provided for @privateKeyStoredLocally.
  ///
  /// In en, this message translates to:
  /// **'Private Key (Stored Locally)'**
  String get privateKeyStoredLocally;

  /// No description provided for @identityZeroTrustDesc.
  ///
  /// In en, this message translates to:
  /// **'This identity is used to sign all outgoing HTTP requests using Zero-Trust architecture. It proves you own this wallet address without sending the private key.'**
  String get identityZeroTrustDesc;

  /// No description provided for @feedoDocsTitle.
  ///
  /// In en, this message translates to:
  /// **'Feedo Documentation'**
  String get feedoDocsTitle;

  /// No description provided for @feedoDocsDesc.
  ///
  /// In en, this message translates to:
  /// **'Technical reference for the Feedo Protocol and Semantic Data Grid.'**
  String get feedoDocsDesc;

  /// No description provided for @githubRepo.
  ///
  /// In en, this message translates to:
  /// **'GitHub Repository'**
  String get githubRepo;

  /// No description provided for @decentralizedIdentities.
  ///
  /// In en, this message translates to:
  /// **'Decentralized Identities'**
  String get decentralizedIdentities;

  /// No description provided for @activeDidPeersDesc.
  ///
  /// In en, this message translates to:
  /// **'Active DID peers and their reputation scores on the network.'**
  String get activeDidPeersDesc;

  /// No description provided for @noIdentitiesFound.
  ///
  /// In en, this message translates to:
  /// **'No identities found on the network yet.'**
  String get noIdentitiesFound;

  /// No description provided for @didColumn.
  ///
  /// In en, this message translates to:
  /// **'DID'**
  String get didColumn;

  /// No description provided for @reputationColumn.
  ///
  /// In en, this message translates to:
  /// **'Reputation'**
  String get reputationColumn;

  /// No description provided for @statusColumn.
  ///
  /// In en, this message translates to:
  /// **'Status'**
  String get statusColumn;

  /// No description provided for @activePeer.
  ///
  /// In en, this message translates to:
  /// **'Active Peer'**
  String get activePeer;

  /// No description provided for @active.
  ///
  /// In en, this message translates to:
  /// **'Active'**
  String get active;

  /// No description provided for @vectorSearchExplorer.
  ///
  /// In en, this message translates to:
  /// **'Vector Search Explorer'**
  String get vectorSearchExplorer;

  /// No description provided for @exploreAiVectorsDesc.
  ///
  /// In en, this message translates to:
  /// **'Explore AI embedding vectors for specific posts to understand semantic clustering.'**
  String get exploreAiVectorsDesc;

  /// No description provided for @searchVector.
  ///
  /// In en, this message translates to:
  /// **'Search Vector'**
  String get searchVector;

  /// No description provided for @embeddingRepresentation.
  ///
  /// In en, this message translates to:
  /// **'Embedding Representation'**
  String get embeddingRepresentation;

  /// No description provided for @exposeVectorApiHint.
  ///
  /// In en, this message translates to:
  /// **'Make sure EXPOSE_VECTOR_API=\"true\" is set in your docker-compose.yml to enable this.'**
  String get exposeVectorApiHint;
}

class _AppLocalizationsDelegate extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) => <String>['en', 'uk'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {


  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en': return AppLocalizationsEn();
    case 'uk': return AppLocalizationsUk();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.'
  );
}
