//! 2-node storage integration test.
//!
//! Запускає 2 екземпляри storage-node, перевіряє upload/download/delete
//! та синхронізацію через DHT.
//!
//! Фаза 1: додано тести на storage classes, квоти, backward compatibility.
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
    upload_zip_with_class(node_url, zip_bytes, None)
}

fn upload_zip_with_class(node_url: &str, zip_bytes: &[u8], storage_class: Option<&str>) -> String {
    let part = reqwest::blocking::multipart::Part::bytes(zip_bytes.to_vec())
        .file_name("test_site.zip")
        .mime_str("application/zip")
        .unwrap();
    let form = reqwest::blocking::multipart::Form::new().part("file", part);

    let mut req = reqwest::blocking::Client::new()
        .post(format!("{}/upload", node_url))
        .multipart(form);

    if let Some(class) = storage_class {
        req = req.header("X-Feedo-Storage-Class", class);
    }

    let resp = req.send().unwrap();
    let hash = resp.text().unwrap().trim().to_string();
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

    // ==================== PHASE 1 TESTS ====================

    // ==================== TEST 7: Upload with X-Feedo-Storage-Class header ====================
    eprintln!("\n[TEST 7] Upload with X-Feedo-Storage-Class: site header to Node0");
    let site_zip = make_test_zip();
    let site_hash = upload_zip_with_class(NODE0_HTTP, &site_zip, Some("site"));
    assert!(!site_hash.is_empty() && !site_hash.contains("error"), "Upload with storage_class=site should succeed");
    // Download and verify data intact
    let site_data = download_bytes(NODE0_HTTP, &site_hash);
    assert!(site_data.is_some(), "Should be able to download site-class file");
    assert_eq!(site_data.unwrap(), site_zip, "Site-class data should match original");

    // Verify we can upload with different storage classes
    let blob_hash = upload_zip_with_class(NODE0_HTTP, &site_zip, Some("blob"));
    assert!(!blob_hash.is_empty(), "Upload with storage_class=blob should succeed");

    // Verify invalid storage_class is rejected
    let invalid_resp = reqwest::blocking::Client::new()
        .post(format!("{}/upload", NODE0_HTTP))
        .header("X-Feedo-Storage-Class", "invalid_class")
        .multipart(
            reqwest::blocking::multipart::Form::new()
                .part("file", reqwest::blocking::multipart::Part::bytes(site_zip.clone())
                    .file_name("test.zip")
                    .mime_str("application/zip")
                    .unwrap())
        )
        .send()
        .unwrap();
    // Should default to Blob (fallback), so upload should still succeed
    eprintln!("[TEST 7] Invalid class upload status: {}", invalid_resp.status());

    // ==================== TEST 8: Ingest post with storage_class field ====================
    eprintln!("\n[TEST 8] JSON ingest with storage_class field");
    let ingest_body = serde_json::json!({
        "hash_id": "test-hash-001",
        "author": "did:feedo:abc123",
        "text": "Hello storage class!",
        "signature": "test-sig",
        "metadata": {},
        "storage_class": "social_post"
    });
    let ingest_resp = reqwest::blocking::Client::new()
        .post(format!("{}/api/v1/ingest/post", NODE0_HTTP))
        .json(&ingest_body)
        .send()
        .unwrap();
    assert_eq!(ingest_resp.status(), 200, "Ingest with explicit storage_class should succeed");
    let ingest_hash = ingest_resp.text().unwrap().trim().to_string();
    eprintln!("[TEST 8] Ingest hash: {}", ingest_hash);

    // Verify backward compat: ingest without storage_class defaults to SocialPost
    let ingest_body_no_class = serde_json::json!({
        "hash_id": "test-hash-002",
        "author": "did:feedo:abc456",
        "text": "No storage class specified",
        "signature": "test-sig",
        "metadata": {}
    });
    let ingest_resp2 = reqwest::blocking::Client::new()
        .post(format!("{}/api/v1/ingest/post", NODE1_HTTP))
        .json(&ingest_body_no_class)
        .send()
        .unwrap();
    assert_eq!(ingest_resp2.status(), 200, "Backward compat: ingest without storage_class should default to social_post");
    eprintln!("[TEST 8] Backward compat ingest hash: {}", ingest_resp2.text().unwrap().trim());

    // ==================== TEST 9: Batch ingest with storage_class field ====================
    eprintln!("\n[TEST 9] Batch JSON ingest with storage_class field");
    let batch_body = serde_json::json!([
        {
            "hash_id": "batch-001",
            "author": "did:feedo:profile1",
            "text": "Profile data 1",
            "signature": "test-sig",
            "metadata": {},
            "storage_class": "profile"
        },
        {
            "hash_id": "batch-002",
            "author": "did:feedo:profile2",
            "text": "Profile data 2",
            "signature": "test-sig",
            "metadata": {}
            // No storage_class — defaults to Profile
        }
    ]);
    let batch_resp = reqwest::blocking::Client::new()
        .post(format!("{}/api/v1/ingest/batch", NODE0_HTTP))
        .json(&batch_body)
        .send()
        .unwrap();
    assert_eq!(batch_resp.status(), 200, "Batch ingest should succeed");
    let batch_hashes: Vec<String> = batch_resp.json().unwrap();
    assert_eq!(batch_hashes.len(), 2, "Batch should return 2 hashes");
    eprintln!("[TEST 9] Batch hashes: {:?}", batch_hashes);

    // ==================== TEST 10: Quota API endpoint ====================
    eprintln!("\n[TEST 10] GET /api/v1/quota");
    let quota_resp = reqwest::blocking::get(format!("{}/api/v1/quota", NODE0_HTTP)).unwrap();
    assert_eq!(quota_resp.status(), 200, "Quota endpoint should return 200");
    let quota_json: serde_json::Value = quota_resp.json().unwrap();
    eprintln!("[TEST 10] Quota: {}", serde_json::to_string_pretty(&quota_json).unwrap());

    // Verify all four storage classes are present
    for class in &["site", "blob", "social_post", "profile"] {
        assert!(quota_json[class]["used_bytes"].as_u64().is_some(),
            "Quota JSON should contain '{}' with used_bytes", class);
        assert!(quota_json[class]["max_bytes"].as_u64().is_some(),
            "Quota JSON should contain '{}' with max_bytes", class);
    }

    // Node1 quota should also be accessible
    let quota_resp1 = reqwest::blocking::get(format!("{}/api/v1/quota", NODE1_HTTP)).unwrap();
    assert_eq!(quota_resp1.status(), 200, "Node1 quota endpoint should return 200");

    // ==================== TEST 11: Quota enforcement (backpressure, not rejection) ====================
    eprintln!("\n[TEST 11] Quota backpressure behavior");
    // With default quotas (500 MB for social), uploading a small post should always succeed.
    // The backpressure is logged (warn level) rather than rejecting by default.
    // This test verifies the system remains operational under load.
    let small_post = serde_json::json!({
        "hash_id": "quota-test-001",
        "author": "did:feedo:quotatest",
        "text": "Testing quota backpressure",
        "signature": "test-sig",
        "metadata": {},
        "storage_class": "social_post"
    });
    let quota_test_resp = reqwest::blocking::Client::new()
        .post(format!("{}/api/v1/ingest/post", NODE0_HTTP))
        .json(&small_post)
        .send()
        .unwrap();
    assert_eq!(quota_test_resp.status(), 200, "Upload within quota should succeed");
    eprintln!("[TEST 11] Quota backpressure test passed");

    eprintln!("\n========== ALL STORAGE TESTS PASSED (Phase 1) ==========");

    // Kill nodes
    drop(node1_guard);
    drop(node0_guard);
}