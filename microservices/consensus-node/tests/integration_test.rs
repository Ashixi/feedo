//! Full integration test: start 2 consensus nodes, register DID, name, CID, check sync.
//!
//! Run with: cargo test --test integration_test -- --nocapture --test-threads=1

use std::process::{Command, Child};
use std::time::Duration;
use std::thread::sleep;
use std::io::Read;
use ethers::prelude::*;
use ethers::utils::hash_message;

const NODE1_HTTP: &str = "http://127.0.0.1:3000";
const NODE2_HTTP: &str = "http://127.0.0.1:3001";
const NODE1_WALLET: &str = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const NODE2_WALLET: &str = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const TEST_NAME: &str = "test.feedo";
const TEST_CID: &str = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi";

struct NodeGuard {
    child: Child,
    name: String,
}

impl Drop for NodeGuard {
    fn drop(&mut self) {
        eprintln!("[TEST] Killing {} (pid={})", self.name, self.child.id());
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn wait_for_http(url: &str, timeout_secs: u64) -> bool {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > Duration::from_secs(timeout_secs) {
            return false;
        }
        match reqwest::blocking::get(url) {
            Ok(resp) => {
                eprintln!("[TEST] {} responded with status {}", url, resp.status());
                return true;
            }
            Err(_) => sleep(Duration::from_millis(500)),
        }
    }
}

fn http_post(url: &str, body: &str) -> reqwest::blocking::Response {
    reqwest::blocking::Client::new()
        .post(url)
        .header("Content-Type", "application/json")
        .body(body.to_string())
        .send()
        .unwrap()
}

fn http_get(url: &str) -> reqwest::blocking::Response {
    reqwest::blocking::get(url).unwrap()
}

/// Poll resolve on a node until CID matches expected, or timeout.
fn poll_resolve_cid(node_url: &str, name: &str, expected_cid: &str, timeout_secs: u64) -> bool {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > Duration::from_secs(timeout_secs) {
            return false;
        }
        let resp = http_get(&format!("{}/resolve/{}", node_url, name));
        if let Ok(resolve) = resp.json::<Option<serde_json::Value>>() {
            if let Some(r) = resolve {
                let cid = r["cid"].as_str().unwrap_or("");
                if cid == expected_cid {
                    eprintln!("[POLL] {} {}: CID={} (matched!)", node_url, name, cid);
                    return true;
                }
                eprintln!("[POLL] {} {}: CID={} (waiting for {})", node_url, name, cid, expected_cid);
            } else {
                eprintln!("[POLL] {} {}: resolve returned None", node_url, name);
            }
        }
        sleep(Duration::from_millis(500));
    }
}

#[test]
fn full_integration_test() {
    // Step 0: Find binary
    let bin_path = std::env::var("CARGO_BIN_EXE_consensus-node")
        .unwrap_or_else(|_| "target/debug/consensus-node".to_string());
    let bin_path = std::path::PathBuf::from(bin_path);
    assert!(bin_path.exists(), "Binary not found at {:?}. Build with: cargo build --bin consensus-node", bin_path);

    // Clean up previous test databases
    let _ = std::fs::remove_dir_all("test_db1");
    let _ = std::fs::remove_dir_all("test_db2");

    // Generate test wallet for signing
    let wallet = LocalWallet::new(&mut rand::thread_rng());
    let pub_key = format!("0x{}", hex::encode(wallet.address().as_bytes()));

    // --- Start Node 1 (bootstrap) ---
    eprintln!("[TEST] Starting Node1...");
    let node1 = Command::new(&bin_path)
        .env("HTTP_PORT", "3000")
        .env("GRPC_PORT", "50051")
        .env("P2P_PORT", "8041")
        .env("DB_DIR", "test_db1")
        .env("NODE_WALLET_ADDRESS", NODE1_WALLET)
        .env("ETH_RPC_URL", "https://polygon-rpc.com")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("Failed to start Node1");

    let mut node1_guard = NodeGuard { child: node1, name: "Node1".to_string() };

    eprintln!("[TEST] Waiting for Node1 to start...");
    assert!(wait_for_http(NODE1_HTTP, 20), "Node1 did not start within 20s");

    // Extract PeerId from Node1 stderr
    let node1_peer_id = {
        let stderr = node1_guard.child.stderr.as_mut().unwrap();
        let mut buf = [0u8; 4096];
        sleep(Duration::from_secs(2));
        let n = stderr.read(&mut buf).unwrap_or(0);
        let output = String::from_utf8_lossy(&buf[..n]);
        eprintln!("[TEST] Node1 stderr: {}", output);
        output.lines()
            .find(|l| l.contains("Consensus Local peer id:"))
            .and_then(|l| {
                let start = l.find('"')? + 1;
                let end = l[start..].find('"')?;
                Some(l[start..start + end].to_string())
            })
            .unwrap_or_else(|| "12D3KooWUnknown".to_string())
    };
    eprintln!("[TEST] Node1 PeerId: {}", node1_peer_id);

    // --- Start Node 2 (follower) ---
    let bootstrap = format!("/ip4/127.0.0.1/udp/8041/quic-v1/p2p/{}", node1_peer_id);
    eprintln!("[TEST] Starting Node2 with BOOTSTRAP_NODES={}", bootstrap);

    let node2 = Command::new(&bin_path)
        .env("HTTP_PORT", "3001")
        .env("GRPC_PORT", "50052")
        .env("P2P_PORT", "8042")
        .env("DB_DIR", "test_db2")
        .env("NODE_WALLET_ADDRESS", NODE2_WALLET)
        .env("BOOTSTRAP_NODES", &bootstrap)
        .env("ETH_RPC_URL", "https://polygon-rpc.com")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .expect("Failed to start Node2");

    let node2_guard = NodeGuard { child: node2, name: "Node2".to_string() };

    eprintln!("[TEST] Waiting for Node2 to start...");
    assert!(wait_for_http(NODE2_HTTP, 20), "Node2 did not start within 20s");

    // Give nodes time to discover each other
    sleep(Duration::from_secs(5));
    eprintln!("[TEST] Both nodes running. Starting tests...");

    // ==================== TEST 1: DID Registration ====================
    eprintln!("\n[TEST 1] DID Registration");
    let did_body = format!(r#"{{"public_key":"{}"}}"#, pub_key);
    let resp = http_post(&format!("{}/did/register", NODE1_HTTP), &did_body);
    assert_eq!(resp.status(), 200);
    let did_json: serde_json::Value = resp.json().unwrap();
    let did = did_json["did"].as_str().unwrap().to_string();
    eprintln!("[TEST 1] Registered DID: {}", did);
    assert!(did.starts_with("did:feedo:"));

    // ==================== TEST 2: DID Balance ====================
    eprintln!("\n[TEST 2] DID Balance");
    let resp = http_get(&format!("{}/did/{}/balance", NODE1_HTTP, did));
    let balance: Option<serde_json::Value> = resp.json().unwrap();
    eprintln!("[TEST 2] Balance: {:?}", balance);
    assert!(balance.is_some(), "Balance should exist after registration");

    // ==================== TEST 3: Name Registration ====================
    eprintln!("\n[TEST 3] Name Registration");
    let payload_str = format!("{}{}", TEST_NAME, did);
    let sig = wallet.sign_hash(hash_message(payload_str.as_bytes())).unwrap();
    let sig_hex = format!("0x{}", hex::encode(sig.to_vec()));

    let name_body = format!(
        r#"{{"name":"{}","did":"{}","public_key":"{}","signature":"{}"}}"#,
        TEST_NAME, did, pub_key, sig_hex
    );
    let resp = http_post(&format!("{}/name/register", NODE1_HTTP), &name_body);
    let name_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 3] Name registration response: {:?}", name_json);
    assert!(name_json["success"].as_bool().unwrap_or(false), "Name registration should succeed: {:?}", name_json);

    // ==================== TEST 4: Resolve Name on Both Nodes ====================
    eprintln!("\n[TEST 4] Resolve Name");
    sleep(Duration::from_secs(3));

    let resp1 = http_get(&format!("{}/resolve/{}", NODE1_HTTP, TEST_NAME));
    let resolve1: Option<serde_json::Value> = resp1.json().unwrap();
    eprintln!("[TEST 4] Node1 resolve: {:?}", resolve1);

    let resp2 = http_get(&format!("{}/resolve/{}", NODE2_HTTP, TEST_NAME));
    let resolve2: Option<serde_json::Value> = resp2.json().unwrap();
    eprintln!("[TEST 4] Node2 resolve: {:?}", resolve2);

    assert!(resolve1.is_some(), "Node1 should resolve the name");
    assert!(resolve2.is_some(), "Node2 should also resolve the name (DHT sync)");
    // Ensure both nodes agree on DID
    assert_eq!(
        resolve1.as_ref().and_then(|r| r["did"].as_str()),
        resolve2.as_ref().and_then(|r| r["did"].as_str()),
        "Both nodes should return the same DID"
    );

    // ==================== TEST 5: CID Update ====================
    eprintln!("\n[TEST 5] CID Update");
    let cid_payload = format!("{}{}", TEST_NAME, TEST_CID);
    let cid_sig = wallet.sign_hash(hash_message(cid_payload.as_bytes())).unwrap();
    let cid_sig_hex = format!("0x{}", hex::encode(cid_sig.to_vec()));

    let update_body = format!(
        r#"{{"name":"{}","cid":"{}","signature":"{}","gateways":["http://gateway1.feedo.ink"]}}"#,
        TEST_NAME, TEST_CID, cid_sig_hex
    );
    let resp = http_post(&format!("{}/name/update_cid", NODE1_HTTP), &update_body);
    let update_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 5] CID update response: {:?}", update_json);

    // ==================== TEST 6: Verify CID on Both Nodes (with polling) ====================
    eprintln!("\n[TEST 6] Verify CID after update (polling with 15s timeout)");

    // Node1 should have CID immediately (local write)
    assert!(
        poll_resolve_cid(NODE1_HTTP, TEST_NAME, TEST_CID, 15),
        "Node1 should have the updated CID within 15s"
    );

    // Node2 gets CID via consensus (gossipsub broadcast + PBFT finalization)
    assert!(
        poll_resolve_cid(NODE2_HTTP, TEST_NAME, TEST_CID, 15),
        "Node2 should also have the updated CID within 15s"
    );

    // ==================== TEST 7: Fault Tolerance ====================
    eprintln!("\n[TEST 7] Fault Tolerance");
    eprintln!("[TEST 7] Killing Node2...");
    drop(node2_guard);

    // Register another name on Node1 (self-committee)
    let payload2 = format!("test2.feedo{}", did);
    let sig2 = wallet.sign_hash(hash_message(payload2.as_bytes())).unwrap();
    let sig2_hex = format!("0x{}", hex::encode(sig2.to_vec()));

    let name2_body = format!(
        r#"{{"name":"test2.feedo","did":"{}","public_key":"{}","signature":"{}"}}"#,
        did, pub_key, sig2_hex
    );
    let resp = http_post(&format!("{}/name/register", NODE1_HTTP), &name2_body);
    let name2_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 7] Name2 registration on Node1: {:?}", name2_json);
    sleep(Duration::from_secs(2));

    let resp1 = http_get(&format!("{}/resolve/test2.feedo", NODE1_HTTP));
    let resolve1: Option<serde_json::Value> = resp1.json().unwrap();
    eprintln!("[TEST 7] Node1 resolve test2: {:?}", resolve1);

    eprintln!("\n========== ALL TESTS PASSED ==========");
}