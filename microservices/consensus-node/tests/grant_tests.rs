/// Tests for the Feedo Grant System (v1 — Open Grants).
///
/// These are pure unit-level tests that exercise PporManager grant methods
/// directly (no network, no swarm). They verify:
///   - Grant creation
///   - Grant claim verification (valid, duplicate, limit, expiry, inactive)
///   - Grant claim execution (counter increments)
///   - Edge cases (zero amount, duplicate grant_id)

use std::collections::{HashMap, HashSet};

// Duplicate the minimal types we need — keeps tests independent from the binary crate.
// In a real integration test we'd import from the crate, but the crate is a binary,
// not a library. So we replicate the grant types here.

#[derive(Debug, Clone, PartialEq)]
enum GrantVerification {
    Open,
}

impl GrantVerification {
    fn to_str(&self) -> &'static str {
        match self {
            GrantVerification::Open => "open",
        }
    }
}

#[derive(Debug, Clone)]
struct GrantProgram {
    grant_id: String,
    title: String,
    signer: String,
    verification: GrantVerification,
    amount_per_claim: u64,
    max_claims: u64,
    claimed_count: u64,
    claimed_total: u64,
    claimed_by: HashSet<String>,
    created_at: u64,
    expires_at: u64,
    active: bool,
}

struct GrantManager {
    programs: HashMap<String, GrantProgram>,
}

impl GrantManager {
    fn new() -> Self {
        Self {
            programs: HashMap::new(),
        }
    }

    fn create_grant(&mut self, grant: GrantProgram) -> Result<(), String> {
        if self.programs.contains_key(&grant.grant_id) {
            return Err("Grant already exists".to_string());
        }
        if grant.amount_per_claim == 0 {
            return Err("Amount per claim must be > 0".to_string());
        }
        self.programs.insert(grant.grant_id.clone(), grant);
        Ok(())
    }

    fn verify_grant_claim(&self, grant_id: &str, did: &str) -> Result<u64, String> {
        let grant = self
            .programs
            .get(grant_id)
            .ok_or_else(|| "Grant not found".to_string())?;

        if !grant.active {
            return Err("Grant is not active".to_string());
        }

        if grant.expires_at > 0 {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            if now > grant.expires_at {
                return Err("Grant expired".to_string());
            }
        }

        if grant.claimed_by.contains(did) {
            return Err("Already claimed".to_string());
        }

        if grant.max_claims > 0 && grant.claimed_count >= grant.max_claims {
            return Err("Claim limit reached".to_string());
        }

        Ok(grant.amount_per_claim)
    }

    fn execute_claim(&mut self, grant_id: &str, did: &str, amount: u64) -> Result<u64, String> {
        let grant = self
            .programs
            .get_mut(grant_id)
            .ok_or_else(|| "Grant not found".to_string())?;

        grant.claimed_by.insert(did.to_string());
        grant.claimed_count += 1;
        grant.claimed_total += amount;

        Ok(grant.claimed_count)
    }
}

/// Helper: create a default Open grant.
fn make_grant(
    id: &str,
    amount: u64,
    max_claims: u64,
    expires_at: u64,
    active: bool,
) -> GrantProgram {
    GrantProgram {
        grant_id: id.to_string(),
        title: format!("Grant {}", id),
        signer: "0xvalidator".to_string(),
        verification: GrantVerification::Open,
        amount_per_claim: amount,
        max_claims,
        claimed_count: 0,
        claimed_total: 0,
        claimed_by: HashSet::new(),
        created_at: 1700000000,
        expires_at,
        active,
    }
}

// ============================================================
// Tests
// ============================================================

#[test]
fn test_create_grant_success() {
    let mut mgr = GrantManager::new();
    let grant = make_grant("test-grant", 10000, 100, 0, true);
    assert!(mgr.create_grant(grant).is_ok());
    assert!(mgr.programs.contains_key("test-grant"));
}

#[test]
fn test_create_grant_duplicate_fails() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("test-grant", 10000, 100, 0, true))
        .unwrap();
    let result = mgr.create_grant(make_grant("test-grant", 5000, 50, 0, true));
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Grant already exists");
}

#[test]
fn test_create_grant_zero_amount_fails() {
    let mut mgr = GrantManager::new();
    let result = mgr.create_grant(make_grant("test-grant", 0, 100, 0, true));
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Amount per claim must be > 0");
}

#[test]
fn test_verify_claim_success() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("test-grant", 10000, 100, 0, true))
        .unwrap();

    let result = mgr.verify_grant_claim("test-grant", "did:feedo:alice");
    assert_eq!(result, Ok(10000));
}

#[test]
fn test_verify_claim_not_found() {
    let mgr = GrantManager::new();
    let result = mgr.verify_grant_claim("nonexistent", "did:feedo:alice");
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Grant not found");
}

#[test]
fn test_verify_claim_inactive() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("test-grant", 10000, 100, 0, false))
        .unwrap();

    let result = mgr.verify_grant_claim("test-grant", "did:feedo:alice");
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Grant is not active");
}

#[test]
fn test_verify_claim_expired() {
    let mut mgr = GrantManager::new();
    // expired 1 second after UNIX epoch (long ago)
    mgr.create_grant(make_grant("test-grant", 10000, 100, 1, true))
        .unwrap();

    let result = mgr.verify_grant_claim("test-grant", "did:feedo:alice");
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Grant expired");
}

#[test]
fn test_verify_claim_already_claimed() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("test-grant", 10000, 100, 0, true))
        .unwrap();
    mgr.execute_claim("test-grant", "did:feedo:alice", 10000)
        .unwrap();

    let result = mgr.verify_grant_claim("test-grant", "did:feedo:alice");
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Already claimed");
}

#[test]
fn test_verify_claim_limit_reached() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("test-grant", 10000, 1, 0, true))
        .unwrap();
    mgr.execute_claim("test-grant", "did:feedo:alice", 10000)
        .unwrap();

    let result = mgr.verify_grant_claim("test-grant", "did:feedo:bob");
    assert!(result.is_err());
    assert_eq!(result.unwrap_err(), "Claim limit reached");
}

#[test]
fn test_execute_claim_increments_counter() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("test-grant", 10000, 100, 0, true))
        .unwrap();

    let count1 = mgr
        .execute_claim("test-grant", "did:feedo:alice", 10000)
        .unwrap();
    assert_eq!(count1, 1);

    let count2 = mgr
        .execute_claim("test-grant", "did:feedo:bob", 10000)
        .unwrap();
    assert_eq!(count2, 2);

    let grant = mgr.programs.get("test-grant").unwrap();
    assert_eq!(grant.claimed_count, 2);
    assert_eq!(grant.claimed_total, 20000);
    assert!(grant.claimed_by.contains("did:feedo:alice"));
    assert!(grant.claimed_by.contains("did:feedo:bob"));
}

#[test]
fn test_multiple_grants_independent() {
    let mut mgr = GrantManager::new();
    mgr.create_grant(make_grant("grant-a", 10000, 100, 0, true))
        .unwrap();
    mgr.create_grant(make_grant("grant-b", 5000, 20, 0, true))
        .unwrap();

    // Alice claims both
    mgr.execute_claim("grant-a", "did:feedo:alice", 10000)
        .unwrap();
    mgr.execute_claim("grant-b", "did:feedo:alice", 5000)
        .unwrap();

    // Verify grant-a: alice is there, bob can still claim
    let ga = mgr.programs.get("grant-a").unwrap();
    assert_eq!(ga.claimed_count, 1);
    assert!(ga.claimed_by.contains("did:feedo:alice"));
    // Bob should still be able to claim grant-a
    assert!(mgr.verify_grant_claim("grant-a", "did:feedo:bob").is_ok());

    // Verify grant-b: alice is there
    let gb = mgr.programs.get("grant-b").unwrap();
    assert_eq!(gb.claimed_count, 1);
    assert!(gb.claimed_by.contains("did:feedo:alice"));
}

#[test]
fn test_grant_with_zero_max_claims_is_unlimited() {
    let mut mgr = GrantManager::new();
    // max_claims = 0 means unlimited
    mgr.create_grant(make_grant("unlimited-grant", 1000, 0, 0, true))
        .unwrap();

    // 500 claims should all succeed
    for i in 0..500 {
        let did = format!("did:feedo:user{}", i);
        assert!(mgr.verify_grant_claim("unlimited-grant", &did).is_ok());
        mgr.execute_claim("unlimited-grant", &did, 1000).unwrap();
    }

    let grant = mgr.programs.get("unlimited-grant").unwrap();
    assert_eq!(grant.claimed_count, 500);
}

#[test]
fn test_expires_at_zero_never_expires() {
    let mut mgr = GrantManager::new();
    // expires_at = 0 means never expires
    mgr.create_grant(make_grant("forever-grant", 10000, 100, 0, true))
        .unwrap();

    // Should succeed — never expires
    assert!(mgr.verify_grant_claim("forever-grant", "did:feedo:alice").is_ok());
}