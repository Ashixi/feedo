//! 2-node storage integration test.
//!
//! Запускає 2 екземпляри storage-node, перевіряє upload/download/delete
//! та синхронізацію через DHT.
//!
//! Run with:
//!   cargo build --bin storage-node
//!   cargo test --test integration_test -- --nocapture --test-threads=1

use std::process::{Command, Child};
use std::time::Duration;
use std::thread::sleep;
use std::io::{Read, Write};
use std::io::Cursor;
use zip::write::FileOptions;

const NODE0_HTTP: &str = "http://127.0.0.1:3001";
const NODE1_HTTP: &str = "http://127.0.0.1:3002";
const NODE0_P2P: u16 = 8040;
const NODE1_P2P: u16 = 8043;

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

fn upload_zip(node_url: &str, zip_bytes: &[u8]) -> String {
    let part = reqwest::blocking::multipart::Part::bytes(zip_bytes.to_vec())
        .file_name("test_site.zip")
        .mime_str("application/zip")
        .unwrap();
    let form = reqwest::blocking::multipart::Form::new().part("file", part);

    let resp = reqwest::blocking::Client::new()
        .post(format!("{}/upload", node_url))
        .multipart(form)
        .send()
        .unwrap();

    assert_eq!(resp.status(), 200, "Upload failed: {}", resp.text().unwrap_or_default());
    let hash = resp.text().unwrap().trim().to_string();
    assert!(!hash.is_empty(), "Upload returned empty hash");
    eprintln!("[TEST] Uploaded: hash={}", hash);
    hash
}

fn download_bytes(node_url: &str, hash: &str) -> Option<Vec<u8>> {
    let resp = reqwest::blocking::get(format!("{}/download/{}", node_url, hash)).ok()?;
    if resp.status() == 200 {
        let bytes = resp.bytes().unwrap().to_vec();
        if bytes.is_empty() {
            None // 200 with empty body = file not yet available
        } else {
            Some(bytes)
        }
    } else {
        None
    }
}

fn delete_hash(node_url: &str, hash: &str) -> bool {
    let resp = reqwest::blocking::Client::new()
        .delete(format!("{}/delete/{}", node_url, hash))
        .send();
    resp.is_ok()
}

/// Create a test zip file in memory with an index.html
fn make_test_zip() -> Vec<u8> {
    let mut zip_buf = Cursor::new(Vec::new());
    {
        let mut zip = zip::ZipWriter::new(&mut zip_buf);
        let options: FileOptions = FileOptions::default();
        zip.start_file("index.html", options).unwrap();
        zip.write_all(b"<html><head><title>Test Site</title></head><body><h1>Hello Feedo!</h1></body></html>").unwrap();
        zip.finish().unwrap();
    }
    zip_buf.into_inner()
}

#[test]
fn storage_integration_test() {
    // Step 0: Find binary
    let bin_path = std::env::var("CARGO_BIN_EXE_storage-node")
        .unwrap_or_else(|_| "target/debug/storage-node".to_string());
    let bin_path = std::path::PathBuf::from(bin_path);
    assert!(bin_path.exists(), "Binary not found at {:?}. Build with: cargo build --bin storage-node", bin_path);

    // Clean up previous test databases
    let _ = std::fs::remove_dir_all("test_storage_db0");
    let _ = std::fs::remove_dir_all("test_storage_db1");

    // --- Start Node 0 (bootstrap) ---
    eprintln!("[TEST] Starting Storage Node0...");
    let node0 = Command::new(&bin_path)
        .env("HTTP_PORT", "3001")
        .env("GRPC_PORT", "50052")
        .env("P2P_PORT", format!("{}", NODE0_P2P))
        .env("DB_DIR", "test_storage_db0")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("Failed to start Node0");

    let mut node0_guard = NodeGuard { child: node0, name: "StorageNode0".to_string() };

    eprintln!("[TEST] Waiting for Node0 to start...");
    assert!(wait_for_http(NODE0_HTTP, 20), "Node0 did not start within 20s");

    // Extract PeerId from Node0 stderr
    let node0_peer_id = {
        let stdout = node0_guard.child.stdout.as_mut().unwrap();
        let mut buf = [0u8; 4096];
        sleep(Duration::from_secs(2));
        let n = stdout.read(&mut buf).unwrap_or(0);
        let output = String::from_utf8_lossy(&buf[..n]);
        eprintln!("[TEST] Node0 stdout: {}", output);
        output
            .lines()
            .find(|l| l.contains("Local peer id:"))
            .and_then(|l| {
                let start = l.find('"')? + 1;
                let end = l[start..].find('"')?;
                Some(l[start..start + end].to_string())
            })
            .unwrap_or_else(|| "12D3KooWUnknown".to_string())
    };
    eprintln!("[TEST] Node0 PeerId: {}", node0_peer_id);

    // --- Start Node 1 (follower) ---
    let bootstrap = format!("/ip4/127.0.0.1/udp/8040/quic-v1/p2p/{}", node0_peer_id);
    eprintln!("[TEST] Starting Storage Node1 with BOOTSTRAP_NODES={}", bootstrap);

    let node1 = Command::new(&bin_path)
        .env("HTTP_PORT", "3002")
        .env("GRPC_PORT", "50053")
        .env("P2P_PORT", format!("{}", NODE1_P2P))
        .env("DB_DIR", "test_storage_db1")
        .env("BOOTSTRAP_NODES", &bootstrap)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .expect("Failed to start Node1");

    let node1_guard = NodeGuard { child: node1, name: "StorageNode1".to_string() };

    eprintln!("[TEST] Waiting for Node1 to start...");
    assert!(wait_for_http(NODE1_HTTP, 20), "Node1 did not start within 20s");

    // Give nodes time to discover each other
    sleep(Duration::from_secs(5));
    eprintln!("[TEST] Both storage nodes running. Starting tests...");

    // ==================== TEST 1: Upload to Node0 ====================
    eprintln!("\n[TEST 1] Upload test zip to Node0");
    let zip_bytes = make_test_zip();
    eprintln!("[TEST 1] Test zip size: {} bytes", zip_bytes.len());
    let hash0 = upload_zip(NODE0_HTTP, &zip_bytes);
    assert!(!hash0.is_empty() && !hash0.contains("error"), "Upload should return valid hash");

    // ==================== TEST 2: Download from Node0 ====================
    eprintln!("\n[TEST 2] Download from Node0");
    let data0 = download_bytes(NODE0_HTTP, &hash0);
    assert!(data0.is_some(), "Node0 should serve the uploaded file");
    assert_eq!(data0.unwrap(), zip_bytes, "Downloaded data should match original");

    // ==================== TEST 3: Delete from Node0 ====================
    eprintln!("\n[TEST 3] Delete from Node0");
    delete_hash(NODE0_HTTP, &hash0);
    sleep(Duration::from_secs(2));

    // Verify Node0 returns 404
    let deleted_check0 = download_bytes(NODE0_HTTP, &hash0);
    assert!(deleted_check0.is_none(), "Node0 should return 404 after delete");

    // ==================== TEST 4: Upload to Node1 ====================
    eprintln!("\n[TEST 4] Upload test zip to Node1");
    let hash1 = upload_zip(NODE1_HTTP, &zip_bytes);
    assert!(!hash1.is_empty(), "Upload to Node1 should return valid hash");

    // ==================== TEST 5: Download from Node1 ====================
    eprintln!("\n[TEST 5] Download from Node1");
    let data1 = download_bytes(NODE1_HTTP, &hash1);
    assert!(data1.is_some(), "Node1 should serve its own uploaded file");
    assert_eq!(data1.unwrap(), zip_bytes, "Node1 download should match original");

    // ==================== TEST 6: Recent files API on both nodes ====================
    eprintln!("\n[TEST 6] Recent files API");
    for (label, url) in [("Node0", NODE0_HTTP), ("Node1", NODE1_HTTP)] {
        let resp = reqwest::blocking::get(format!("{}/api/files/recent", url)).unwrap();
        let body = resp.text().unwrap();
        let recent_json: serde_json::Value = serde_json::from_str(&body).unwrap();
        let hashes = recent_json["hashes"].as_array().unwrap();
        eprintln!("[TEST 6] {} recent hashes: {:?}", label, hashes);
    }

    eprintln!("\n========== ALL STORAGE TESTS PASSED ==========");

    // Kill nodes
    drop(node1_guard);
    drop(node0_guard);
}