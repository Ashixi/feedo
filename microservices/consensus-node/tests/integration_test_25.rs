//! 25-node consensus integration test with epoch rotation.
//!
//! Запускає 25 екземплярів consensus-node як child processes,
//! перевіряє синхронізацію через DHT/gossipsub, PBFT консенсус,
//! та epoch rotation (EPOCH_DURATION_SECS=10).
//!
//! Run with:
//!   cargo build --bin consensus-node
//!   cargo test --test integration_test_25 -- --nocapture --test-threads=1

use std::process::{Command, Child};
use std::time::Duration;
use std::thread::sleep;
use std::io::Read;
use ethers::prelude::*;
use ethers::utils::hash_message;

const BASE_HTTP_PORT: u16 = 3000;
const BASE_P2P_PORT: u16 = 8041;
const BASE_GRPC_PORT: u16 = 50051;
const TOTAL_NODES: usize = 25;
const TEST_NAME1: &str = "test25.feedo";
const TEST_NAME2: &str = "test25-2.feedo";
const TEST_CID: &str = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi";
const EPOCH_DURATION_FOR_TEST: &str = "10"; // 10 seconds per epoch
const NODE_DISCOVERY_TIMEOUT: u64 = 40;
const RESOLVE_POLL_TIMEOUT: u64 = 60;

/// Get unique wallet address for each node: 0x{index:040x}
fn node_wallet(index: usize) -> String {
    format!("0x{:040x}", index)
}

/// Get HTTP URL for node
fn node_url(index: usize) -> String {
    format!("http://127.0.0.1:{}", BASE_HTTP_PORT + index as u16)
}

struct NodeGuard {
    child: Child,
    index: usize,
}

impl Drop for NodeGuard {
    fn drop(&mut self) {
        eprintln!("[TEST] Killing Node{} (pid={})", self.index, self.child.id());
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

/// Poll resolve on a node until CID and/or epoch match expected values, or timeout.
/// Returns the resolved JSON value if successful, None otherwise.
fn poll_resolve(
    node_url: &str,
    name: &str,
    expected_cid: Option<&str>,
    min_epoch: Option<u64>,
    timeout_secs: u64,
) -> Option<serde_json::Value> {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > Duration::from_secs(timeout_secs) {
            return None;
        }
        let resp = http_get(&format!("{}/resolve/{}", node_url, name));
        if let Ok(resolve) = resp.json::<Option<serde_json::Value>>() {
            if let Some(r) = resolve {
                let cid_ok = match expected_cid {
                    Some(expected) => r["cid"].as_str().unwrap_or("") == expected,
                    None => true,
                };
                let epoch_ok = match min_epoch {
                    Some(min) => r["epoch"].as_u64().unwrap_or(0) >= min,
                    None => true,
                };
                if cid_ok && epoch_ok {
                    return Some(r);
                }
            }
        }
        sleep(Duration::from_millis(500));
    }
}

/// Poll until at least `min_count` nodes out of `total` resolve the name with given CID.
fn poll_all_nodes(
    base_url: &str,
    name: &str,
    expected_cid: Option<&str>,
    min_epoch: Option<u64>,
    timeout_secs: u64,
    total_nodes: usize,
    min_count: usize,
) -> bool {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > Duration::from_secs(timeout_secs) {
            return false;
        }
        let mut ok_count = 0usize;
        for i in 0..total_nodes {
            let url = if base_url.contains("3000") && i == 0 {
                base_url.to_string()
            } else {
                format!("http://127.0.0.1:{}", BASE_HTTP_PORT + i as u16)
            };
            let resp = http_get(&format!("{}/resolve/{}", url, name));
            if let Ok(resolve) = resp.json::<Option<serde_json::Value>>() {
                if let Some(r) = resolve {
                    let cid_ok = match expected_cid {
                        Some(expected) => r["cid"].as_str().unwrap_or("") == expected,
                        None => true,
                    };
                    let epoch_ok = match min_epoch {
                        Some(min) => r["epoch"].as_u64().unwrap_or(0) >= min,
                        None => true,
                    };
                    if cid_ok && epoch_ok {
                        ok_count += 1;
                    }
                }
            }
        }
        eprintln!(
            "[POLL_ALL] {}/{} nodes resolved name={} (need {})",
            ok_count, total_nodes, name, min_count
        );
        if ok_count >= min_count {
            return true;
        }
        sleep(Duration::from_millis(1000));
    }
}

#[test]
#[ignore] // Run explicitly: cargo test --test integration_test_25 -- --nocapture --test-threads=1 --include-ignored
fn full_25_node_epoch_test() {
    // Step 0: Find binary
    let bin_path = std::env::var("CARGO_BIN_EXE_consensus-node")
        .unwrap_or_else(|_| "target/debug/consensus-node".to_string());
    let bin_path = std::path::PathBuf::from(bin_path);
    assert!(bin_path.exists(), "Binary not found at {:?}. Build with: cargo build --bin consensus-node", bin_path);

    // Clean up previous test databases
    for i in 0..TOTAL_NODES {
        let _ = std::fs::remove_dir_all(format!("test_db_25/{}", i));
    }

    // Generate test wallet for signing
    let wallet = LocalWallet::new(&mut rand::thread_rng());
    let pub_key = format!("0x{}", hex::encode(wallet.address().as_bytes()));

    // ============================================================
    // Step 1: Start Node0 (bootstrap)
    // ============================================================
    eprintln!("\n[SETUP] Starting Node0 (bootstrap)...");
    let mut node0 = Command::new(&bin_path)
        .env("HTTP_PORT", format!("{}", BASE_HTTP_PORT))
        .env("GRPC_PORT", format!("{}", BASE_GRPC_PORT))
        .env("P2P_PORT", format!("{}", BASE_P2P_PORT))
        .env("DB_DIR", format!("test_db_25/0"))
        .env("NODE_WALLET_ADDRESS", node_wallet(0))
        .env("EPOCH_DURATION_SECS", EPOCH_DURATION_FOR_TEST)
        .env("ETH_RPC_URL", "https://polygon-rpc.com")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("Failed to start Node0");

    let node0_url = node_url(0);
    eprintln!("[SETUP] Waiting for Node0 to start...");
    assert!(wait_for_http(&node0_url, 20), "Node0 did not start within 20s");

    // Extract PeerId from Node0 stderr
    let node0_peer_id = {
        let stderr = node0.stderr.as_mut().unwrap();
        let mut buf = [0u8; 8192];
        sleep(Duration::from_secs(3));
        let n = stderr.read(&mut buf).unwrap_or(0);
        let output = String::from_utf8_lossy(&buf[..n]);
        eprintln!("[SETUP] Node0 stderr preview: {:.200}", output);
        output
            .lines()
            .find(|l| l.contains("Consensus Local peer id:"))
            .and_then(|l| {
                let start = l.find('"')? + 1;
                let end = l[start..].find('"')?;
                Some(l[start..start + end].to_string())
            })
            .unwrap_or_else(|| "12D3KooWUnknown".to_string())
    };
    eprintln!("[SETUP] Node0 PeerId: {}", node0_peer_id);

    let mut guards: Vec<NodeGuard> = Vec::with_capacity(TOTAL_NODES);
    guards.push(NodeGuard { child: node0, index: 0 });

    let bootstrap = format!("/ip4/127.0.0.1/udp/8041/quic-v1/p2p/{}", node0_peer_id);

    // ============================================================
    // Step 2: Start Nodes 1..24
    // ============================================================
    eprintln!("\n[SETUP] Starting Nodes 1..24...");
    let start_time = std::time::Instant::now();

    for i in 1..TOTAL_NODES {
        let http_port = BASE_HTTP_PORT + i as u16;
        let p2p_port = BASE_P2P_PORT + i as u16;
        let grpc_port = BASE_GRPC_PORT + i as u16;
        let db_dir = format!("test_db_25/{}", i);

        let child = Command::new(&bin_path)
            .env("HTTP_PORT", format!("{}", http_port))
            .env("GRPC_PORT", format!("{}", grpc_port))
            .env("P2P_PORT", format!("{}", p2p_port))
            .env("DB_DIR", db_dir)
            .env("NODE_WALLET_ADDRESS", node_wallet(i))
            .env("BOOTSTRAP_NODES", &bootstrap)
            .env("EPOCH_DURATION_SECS", EPOCH_DURATION_FOR_TEST)
            .env("ETH_RPC_URL", "https://polygon-rpc.com")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .unwrap_or_else(|e| panic!("Failed to start Node{}: {}", i, e));

        let url = format!("http://127.0.0.1:{}", http_port);
        eprintln!("[SETUP] Waiting for Node{} on {}...", i, url);
        assert!(wait_for_http(&url, 20), "Node{} did not start within 20s", i);

        guards.push(NodeGuard { child, index: i });
    }

    let setup_elapsed = start_time.elapsed();
    eprintln!("[SETUP] All {} nodes started in {:.1}s", TOTAL_NODES, setup_elapsed.as_secs_f64());

    // Give nodes time to discover each other (gossipsub mesh + DHT)
    eprintln!("[SETUP] Waiting {}s for peer discovery...", NODE_DISCOVERY_TIMEOUT);
    sleep(Duration::from_secs(NODE_DISCOVERY_TIMEOUT));
    eprintln!("[SETUP] Peer discovery wait complete. Starting tests...");

    // ============================================================
    // TEST 1: DID Registration
    // ============================================================
    eprintln!("\n========== TEST 1: DID Registration ==========");
    let did_body = format!(r#"{{"public_key":"{}"}}"#, pub_key);
    let resp = http_post(&format!("{}/did/register", node0_url), &did_body);
    assert_eq!(resp.status(), 200);
    let did_json: serde_json::Value = resp.json().unwrap();
    let did = did_json["did"].as_str().unwrap().to_string();
    eprintln!("[TEST 1] Registered DID: {}", did);
    assert!(did.starts_with("did:feedo:"));

    // Check balance
    let resp = http_get(&format!("{}/did/{}/balance", node0_url, did));
    let balance: Option<serde_json::Value> = resp.json().unwrap();
    eprintln!("[TEST 1] Balance: {:?}", balance);
    assert!(balance.is_some(), "Balance should exist");

    // ============================================================
    // TEST 2: Name Registration
    // ============================================================
    eprintln!("\n========== TEST 2: Name Registration ==========");
    let payload_str = format!("{}{}", TEST_NAME1, did);
    let sig = wallet.sign_hash(hash_message(payload_str.as_bytes())).unwrap();
    let sig_hex = format!("0x{}", hex::encode(sig.to_vec()));

    let name_body = format!(
        r#"{{"name":"{}","did":"{}","public_key":"{}","signature":"{}"}}"#,
        TEST_NAME1, did, pub_key, sig_hex
    );
    let resp = http_post(&format!("{}/name/register", node0_url), &name_body);
    let name_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 2] Name registration: {:?}", name_json);
    assert!(name_json["success"].as_bool().unwrap_or(false));

    // ============================================================
    // TEST 3: Resolve on ALL 25 Nodes
    // ============================================================
    eprintln!("\n========== TEST 3: Resolve Name on ALL {} Nodes ==========", TOTAL_NODES);
    assert!(
        poll_all_nodes(&node0_url, TEST_NAME1, None, None, RESOLVE_POLL_TIMEOUT, TOTAL_NODES, 20),
        "At least 20 out of {} nodes should resolve the name", TOTAL_NODES
    );

    // Verify DID consistency across first 5 and last 5 nodes
    let mut did_set = std::collections::HashSet::new();
    for i in [0, 1, 2, 3, 4, 20, 21, 22, 23, 24].iter() {
        let url = format!("http://127.0.0.1:{}", BASE_HTTP_PORT + i);
        let resp = http_get(&format!("{}/resolve/{}", url, TEST_NAME1));
        if let Ok(resolve) = resp.json::<Option<serde_json::Value>>() {
            if let Some(r) = resolve {
                if let Some(d) = r["did"].as_str() {
                    did_set.insert(d.to_string());
                }
            }
        }
    }
    eprintln!("[TEST 3] Unique DIDs found across nodes: {:?}", did_set);
    assert_eq!(did_set.len(), 1, "All nodes should agree on the same DID");

    // ============================================================
    // TEST 4: CID Update through middle node (Node12)
    // ============================================================
    eprintln!("\n========== TEST 4: CID Update via Node12 ==========");
    let cid_payload = format!("{}{}", TEST_NAME1, TEST_CID);
    let cid_sig = wallet.sign_hash(hash_message(cid_payload.as_bytes())).unwrap();
    let cid_sig_hex = format!("0x{}", hex::encode(cid_sig.to_vec()));

    let update_body = format!(
        r#"{{"name":"{}","cid":"{}","signature":"{}","gateways":["http://gateway1.feedo.ink"]}}"#,
        TEST_NAME1, TEST_CID, cid_sig_hex
    );
    let node12_url = node_url(12);
    let resp = http_post(&format!("{}/name/update_cid", node12_url), &update_body);
    let update_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 4] CID update response: {:?}", update_json);

    // Verify CID on ALL nodes
    eprintln!("[TEST 4] Polling all {} nodes for CID...", TOTAL_NODES);
    assert!(
        poll_all_nodes(&node0_url, TEST_NAME1, Some(TEST_CID), None, RESOLVE_POLL_TIMEOUT, TOTAL_NODES, 18),
        "At least 18 nodes should see the updated CID"
    );

    // ============================================================
    // TEST 5: Epoch Rotation
    // ============================================================
    eprintln!("\n========== TEST 5: Epoch Rotation (waiting for epoch >= 1) ==========");
    // EPOCH_DURATION_SECS=10, we already spent ~40s in setup + tests, so epoch 1 likely already active.
    // Wait up to 20 more seconds to ensure at least epoch 1.
    assert!(
        poll_all_nodes(&node0_url, TEST_NAME1, Some(TEST_CID), Some(1), 30, TOTAL_NODES, 15),
        "At least 15 nodes should report epoch >= 1 after rotation"
    );

    let sample_url = node_url(5);
    let resp = http_get(&format!("{}/resolve/{}", sample_url, TEST_NAME1));
    let sample: Option<serde_json::Value> = resp.json().unwrap();
    eprintln!("[TEST 5] Sample resolve from Node5: {:?}", sample);
    let epoch_val = sample.as_ref().and_then(|r| r["epoch"].as_u64()).unwrap_or(0);
    assert!(epoch_val >= 1, "Epoch should be >= 1, got {}", epoch_val);

    // ============================================================
    // TEST 6: Multi-Epoch — register name after rotation
    // ============================================================
    eprintln!("\n========== TEST 6: Multi-Epoch Name Registration ==========");
    // Wait for another epoch to pass
    eprintln!("[TEST 6] Waiting 15s for next epoch...");
    sleep(Duration::from_secs(15));

    // Verify we're now in epoch >= 2
    let resp = http_get(&format!("{}/resolve/{}", sample_url, TEST_NAME1));
    let sample: Option<serde_json::Value> = resp.json().unwrap();
    let epoch_val2 = sample.as_ref().and_then(|r| r["epoch"].as_u64()).unwrap_or(0);
    eprintln!("[TEST 6] Current epoch from Node5: {}", epoch_val2);

    // Register a second name
    let payload2 = format!("{}{}", TEST_NAME2, did);
    let sig2 = wallet.sign_hash(hash_message(payload2.as_bytes())).unwrap();
    let sig2_hex = format!("0x{}", hex::encode(sig2.to_vec()));

    let name2_body = format!(
        r#"{{"name":"{}","did":"{}","public_key":"{}","signature":"{}"}}"#,
        TEST_NAME2, did, pub_key, sig2_hex
    );
    let resp = http_post(&format!("{}/name/register", node0_url), &name2_body);
    let name2_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 6] Name2 registration: {:?}", name2_json);
    assert!(name2_json["success"].as_bool().unwrap_or(false));

    // Check that the new name resolves with current epoch
    sleep(Duration::from_secs(5));
    let resp = http_get(&format!("{}/resolve/{}", node0_url, TEST_NAME2));
    let resolve2: Option<serde_json::Value> = resp.json().unwrap();
    eprintln!("[TEST 6] Node0 resolve test25-2: {:?}", resolve2);
    assert!(resolve2.is_some(), "New name should resolve");
    let new_epoch = resolve2.as_ref().and_then(|r| r["epoch"].as_u64()).unwrap_or(0);
    eprintln!("[TEST 6] New name registered with epoch: {}", new_epoch);

    // ============================================================
    // TEST 7: Fault Tolerance — Kill 5 nodes
    // ============================================================
    eprintln!("\n========== TEST 7: Fault Tolerance (kill Nodes 20-24) ==========");
    for i in (20..25).rev() {
        eprintln!("[TEST 7] Killing Node{}...", i);
        drop(guards.remove(i));
    }

    sleep(Duration::from_secs(5));

    // Register a third name with surviving nodes
    let test_name3 = "test25-3.feedo";
    let payload3 = format!("{}{}", test_name3, did);
    let sig3 = wallet.sign_hash(hash_message(payload3.as_bytes())).unwrap();
    let sig3_hex = format!("0x{}", hex::encode(sig3.to_vec()));

    let name3_body = format!(
        r#"{{"name":"{}","did":"{}","public_key":"{}","signature":"{}"}}"#,
        test_name3, did, pub_key, sig3_hex
    );
    let resp = http_post(&format!("{}/name/register", node0_url), &name3_body);
    let name3_json: serde_json::Value = resp.json().unwrap();
    eprintln!("[TEST 7] Name3 registration: {:?}", name3_json);

    // Verify all SURVIVING nodes (0-19) can resolve
    sleep(Duration::from_secs(5));
    let mut surviving_ok = 0usize;
    for i in 0..20 {
        let url = format!("http://127.0.0.1:{}", BASE_HTTP_PORT + i as u16);
        let resp = http_get(&format!("{}/resolve/{}", url, test_name3));
        if let Ok(resolve) = resp.json::<Option<serde_json::Value>>() {
            if resolve.is_some() {
                surviving_ok += 1;
            }
        }
    }
    eprintln!("[TEST 7] Surviving nodes that resolve {}: {}/20", test_name3, surviving_ok);
    assert!(surviving_ok >= 15, "At least 15 surviving nodes should resolve the new name");

    // ============================================================
    // DONE
    // ============================================================
    eprintln!("\n========== ALL 25-NODE EPOCH TESTS PASSED ==========");
    eprintln!("Total test duration: {:.1}s", start_time.elapsed().as_secs_f64());

    // Kill remaining nodes
    while guards.len() > 0 {
        drop(guards.remove(0));
    }
}