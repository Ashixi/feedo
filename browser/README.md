# Feedo Browser

Feedo Browser is a native, privacy-first web browser built specifically to seamlessly navigate the decentralized **Feedo Web3 Network**. 

It natively understands `.feedo` domains, completely bypassing traditional DNS and centralized web hosts. It fetches content directly from the decentralized Feedo Storage Network using IPFS-inspired Content Identifiers (CIDs) and verifies ownership via the Feedo Consensus Network.

## Features

- **Native Web3 Resolution**: Type `anyname.feedo` in the URL bar and the browser instantly resolves it via the Feedo Consensus Network.
- **Decentralized Storage Engine**: Pages and assets are fetched directly from decentralized Storage Nodes.
- **Integrated Wallet**: Built-in Feedo Identity wallet for signing transactions, registering domains, and managing your DID.
- **Cross-Platform**: Built with Flutter for a fast, fluid experience on Desktop and Mobile.
- **Rust Core**: Cryptography and peer-to-peer networking logic are powered by a high-performance Rust core via `flutter_rust_bridge`.

## Architecture

- **Frontend UI**: Flutter (Dart)
- **Networking & Crypto**: Rust (`rust_engine`)
- **Bridge**: `flutter_rust_bridge`

## Getting Started

### Prerequisites
- [Flutter SDK](https://flutter.dev/docs/get-started/install) (latest stable)
- [Rust Toolchain](https://rustup.rs/) (cargo, rustc)

### Build & Run
1. Clone the repository.
2. Install dependencies:
   ```bash
   flutter pub get
   ```
3. Generate Rust bindings (if modifying the Rust core):
   ```bash
   flutter_rust_bridge_codegen generate
   ```
4. Run the app:
   ```bash
   flutter run
   ```

## License
MIT
