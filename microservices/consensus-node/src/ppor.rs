use std::collections::{HashMap, HashSet};
use shared_proto::feedo::{PbftMessage, PbftPhase};
use sha2::{Sha256, Digest};
use std::time::{Duration, Instant};

pub const TX_TYPE_DATA: i32 = 0;
pub const TX_TYPE_MICRO_TX_BATCH: i32 = 1;
pub const TX_TYPE_SLASHING: i32 = 2;
pub const TX_TYPE_NAME_REGISTRATION: i32 = 3;
pub const TX_TYPE_UPDATE_CID: i32 = 4;
pub const TX_TYPE_LEDGER: i32 = 5;
pub const TX_TYPE_UPDATE_METADATA: i32 = 6;
pub const TX_TYPE_GRANT_CREATE: i32 = 7;
pub const TX_TYPE_GRANT_CLAIM: i32 = 8;

/// Duration of one epoch (10 minutes).
pub const EPOCH_DURATION_SECS: u64 = 600;

/// Maximum time a transaction can remain in PrePrepare before being discarded.
pub const TX_TIMEOUT_SECS: u64 = 30;

/// Reputation change constants.
pub const REP_PREPARE_VOTE: i64 = 1;
pub const REP_COMMIT_VOTE: i64 = 2;
pub const REP_INVALID_SIG: i64 = -5;
pub const REP_TIMEOUT: i64 = -3;
pub const REP_DAILY_DECAY: i64 = -1; // per 24h of inactivity, min 1

#[derive(Debug, Clone)]
pub struct PporState {
    pub view: u64,
    pub sequence: u64,
    pub tx_hash: String,
    pub tx_type: i32,
    pub phase: PbftPhase,
    pub prepares: HashSet<String>,
    pub commits: HashSet<String>,
    pub committee: HashSet<String>,
    pub is_validated: bool,
    pub created_at: Instant,
}

impl PporState {
    pub fn new(view: u64, sequence: u64, tx_hash: String, tx_type: i32, committee: HashSet<String>) -> Self {
        Self {
            view,
            sequence,
            tx_hash,
            tx_type,
            phase: PbftPhase::PrePrepare,
            prepares: HashSet::new(),
            commits: HashSet::new(),
            committee,
            is_validated: false,
            created_at: Instant::now(),
        }
    }

    pub fn required_votes(&self) -> usize {
        let len = self.committee.len();
        if len <= 1 {
            return 1;
        }
        (2 * len / 3) + 1
    }

    /// Returns true if the transaction has timed out.
    pub fn is_timed_out(&self) -> bool {
        self.created_at.elapsed() > Duration::from_secs(TX_TIMEOUT_SECS)
    }

    pub fn process_message(&mut self, msg: &PbftMessage) -> Option<PbftPhase> {
        let msg_phase = msg.phase();
        match msg_phase {
            PbftPhase::PrePrepare => {
                if self.phase == PbftPhase::PrePrepare && self.is_validated {
                    self.phase = PbftPhase::Prepare;
                    return Some(PbftPhase::Prepare);
                }
            }
            PbftPhase::Prepare => {
                self.prepares.insert(msg.sender.clone());
                if self.phase == PbftPhase::Prepare && self.prepares.len() >= self.required_votes() {
                    self.phase = PbftPhase::Commit;
                    return Some(PbftPhase::Commit);
                }
            }
            PbftPhase::Commit => {
                self.commits.insert(msg.sender.clone());
                if self.phase == PbftPhase::Commit && self.commits.len() >= self.required_votes() {
                    self.phase = PbftPhase::Finalized;
                    return Some(PbftPhase::Finalized);
                }
            }
            PbftPhase::Finalized => {}
        }
        None
    }

    pub fn mark_validated(&mut self) -> Option<PbftPhase> {
        self.is_validated = true;
        if self.phase == PbftPhase::PrePrepare {
            self.phase = PbftPhase::Prepare;
            return Some(PbftPhase::Prepare);
        }
        None
    }
}

/// Archive entry for a finalized transaction — stores minimal metadata for audit.
#[derive(Debug, Clone)]
pub struct FinalizedArchiveEntry {
    pub tx_hash: String,
    pub finalized_at: u64, // UNIX timestamp
    pub finalized_epoch: u64, // epoch when finalized
}

// --- Grant System ---

/// Тип верифікації гранту.
/// v1 — тільки Open (будь-хто може клеймити, ліміт по кількості).
/// Решта будуть додані в майбутніх ітераціях.
#[derive(Debug, Clone, PartialEq)]
pub enum GrantVerification {
    Open,
}

impl GrantVerification {
    pub fn to_str(&self) -> &'static str {
        match self {
            GrantVerification::Open => "open",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "open" => Some(GrantVerification::Open),
            _ => None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct GrantProgram {
    pub grant_id: String,
    pub title: String,
    pub signer: String,
    pub verification: GrantVerification,
    pub amount_per_claim: u64,
    pub max_claims: u64,            // 0 = без ліміту
    pub claimed_count: u64,
    pub claimed_total: u64,
    pub claimed_by: HashSet<String>,
    pub created_at: u64,
    pub expires_at: u64,            // 0 = безстроково
    pub active: bool,
}

pub struct PporManager {
    pub states: HashMap<String, PporState>,
    pub view: u64,
    pub node_id: String,
    pub secret_key: Option<secp256k1::SecretKey>,
    pub secp: secp256k1::Secp256k1<secp256k1::All>,

    // Reputation & Committee
    pub reputation_table: HashMap<String, u64>,
    pub current_committee: HashSet<String>,
    pub last_finalized_hash: String,

    // Epoch tracking
    pub current_epoch: u64,
    pub epoch_start: Instant,
    pub epoch_duration: Duration,

    // Garbage collection: archive of finalized transactions
    pub finalized_archive: Vec<FinalizedArchiveEntry>,
    /// Maximum number of finalized entries to keep (prevents unbounded growth).
    pub max_archive_size: usize,

    // Grant system
    pub grant_programs: HashMap<String, GrantProgram>,
}

impl PporManager {
    pub fn new(node_id: String) -> Self {
        let mut rep = HashMap::new();
        rep.insert(node_id.clone(), 100);
        let mut comm = HashSet::new();
        comm.insert(node_id.clone());
        Self::build(node_id, rep, comm, Duration::from_secs(EPOCH_DURATION_SECS))
    }

    pub fn new_with_committee_and_epoch(
        node_id: String,
        committee_addrs: Vec<String>,
        epoch_duration: Duration,
    ) -> Self {
        let mut rep = HashMap::new();
        let mut comm = HashSet::new();
        if !committee_addrs.is_empty() {
            for addr in &committee_addrs {
                rep.insert(addr.clone(), 100);
                comm.insert(addr.clone());
            }
            eprintln!("PporManager initialized with on-chain committee: {:?}", committee_addrs);
        } else {
            rep.insert(node_id.clone(), 100);
            comm.insert(node_id.clone());
            eprintln!("PporManager: no on-chain committee found, fallback to self-only committee");
        }
        eprintln!("PporManager: epoch duration = {:?}", epoch_duration);
        Self::build(node_id, rep, comm, epoch_duration)
    }

    pub fn new_with_committee(node_id: String, committee_addrs: Vec<String>) -> Self {
        Self::new_with_committee_and_epoch(
            node_id,
            committee_addrs,
            Duration::from_secs(EPOCH_DURATION_SECS),
        )
    }

    fn build(node_id: String, reputation_table: HashMap<String, u64>, current_committee: HashSet<String>, epoch_duration: Duration) -> Self {
        Self {
            states: HashMap::new(),
            view: 0,
            node_id,
            secret_key: None,
            secp: secp256k1::Secp256k1::new(),
            reputation_table,
            current_committee,
            last_finalized_hash: "genesis_hash".to_string(),
            current_epoch: 0,
            epoch_start: Instant::now(),
            epoch_duration,
            finalized_archive: Vec::new(),
            max_archive_size: 10_000,
            grant_programs: HashMap::new(),
        }
    }

    pub fn set_secret_key(&mut self, hex_key: &str) {
        if let Ok(decoded) = hex::decode(hex_key.trim_start_matches("0x")) {
            if let Ok(sk) = secp256k1::SecretKey::from_slice(&decoded) {
                self.secret_key = Some(sk);
            }
        }
    }

    // --- Epoch ---

    pub fn is_epoch_expired(&self) -> bool {
        self.epoch_start.elapsed() >= self.epoch_duration
    }

    pub fn rotate_epoch(&mut self) {
        self.states.retain(|_, s| !s.is_timed_out());
        self.current_epoch += 1;
        self.epoch_start = Instant::now();
        let seed = format!("{}:{}", self.last_finalized_hash, self.current_epoch);
        self.select_committee_weighted(&seed);
        eprintln!(
            "[EPOCH] Rotated to epoch {} with committee size {} members",
            self.current_epoch,
            self.current_committee.len()
        );
    }

    pub fn maybe_rotate_epoch(&mut self) {
        if self.is_epoch_expired() {
            self.rotate_epoch();
        }
    }

    // --- Committee selection ---

    pub fn select_committee_weighted(&mut self, seed: &str) {
        let mut scored: Vec<(String, u64)> = self
            .reputation_table
            .iter()
            .map(|(node, rep)| {
                let mut hasher = Sha256::new();
                hasher.update(seed.as_bytes());
                hasher.update(node.as_bytes());
                let h = u64::from_be_bytes(hasher.finalize()[..8].try_into().unwrap_or([0u8; 8]));
                let score = h.wrapping_mul(*rep);
                (node.clone(), score)
            })
            .collect();
        scored.sort_by(|a, b| b.1.cmp(&a.1));
        let size = scored.len().min(21).max(1);
        self.current_committee.clear();
        for (node, _) in scored.into_iter().take(size) {
            self.current_committee.insert(node);
        }
        eprintln!(
            "[COMMITTEE] Selected {} validators (seed={:.16}...)",
            self.current_committee.len(),
            seed
        );
    }

    pub fn select_committee(&mut self, seed_hash: &str) {
        self.select_committee_weighted(seed_hash);
    }

    // --- Validator check ---

    pub fn is_validator(&self) -> bool {
        self.current_committee.contains(&self.node_id)
    }

    // --- Reputation ---

    pub fn adjust_reputation(&mut self, node_id: &str, delta: i64) {
        let entry = self.reputation_table.entry(node_id.to_string()).or_insert(10);
        let new_val = (*entry as i64 + delta).max(1);
        *entry = new_val as u64;
        eprintln!("[REPUTATION] {} adjusted by {} => {}", node_id, delta, entry);
    }

    // --- Signing ---

    fn generate_signature(&self, tx_hash: &str, sequence: u64, phase: i32) -> String {
        if let Some(sk) = &self.secret_key {
            let payload = format!("{}:{}:{}", tx_hash, sequence, phase);
            let message = secp256k1::Message::from_hashed_data::<secp256k1::hashes::sha256::Hash>(payload.as_bytes());
            let sig = self.secp.sign_ecdsa(&message, sk);
            hex::encode(sig.serialize_compact())
        } else {
            "sig_placeholder".to_string()
        }
    }

    // --- Transaction lifecycle ---

    pub fn propose(&mut self, tx_hash: String, sequence: u64, tx_type: i32) -> Option<PbftMessage> {
        if !self.is_validator() {
            return None;
        }
        let state = PporState::new(self.view, sequence, tx_hash.clone(), tx_type, self.current_committee.clone());
        self.states.insert(tx_hash.clone(), state);
        Some(PbftMessage {
            phase: PbftPhase::PrePrepare as i32,
            view: self.view,
            sequence,
            tx_hash: tx_hash.clone(),
            sender: self.node_id.clone(),
            signature: self.generate_signature(&tx_hash, sequence, PbftPhase::PrePrepare as i32),
            tx_type,
        })
    }

    pub fn handle_message(&mut self, msg: PbftMessage) -> Option<PbftMessage> {
        self.maybe_rotate_epoch();
        if !self.reputation_table.contains_key(&msg.sender) {
            self.reputation_table.insert(msg.sender.clone(), 10);
        }

        let (new_phase, s_view, s_seq, s_tx_hash, s_tx_type) = {
            let state = self.states.entry(msg.tx_hash.clone()).or_insert_with(|| {
                PporState::new(msg.view, msg.sequence, msg.tx_hash.clone(), msg.tx_type, self.current_committee.clone())
            });
            if !self.current_committee.contains(&msg.sender) {
                eprintln!("[PBFT] Rejected message from non-committee member {}", msg.sender);
                return None;
            }
            match state.process_message(&msg) {
                Some(p) => (Some(p), state.view, state.sequence, state.tx_hash.clone(), state.tx_type),
                None => (None, 0, 0, String::new(), 0),
            }
        };

        if let Some(phase) = new_phase {
            eprintln!(
                "[PBFT] Phase transition: tx={}, phase={:?}, sender={}, votes_prepare={}, votes_commit={}",
                s_tx_hash, phase, msg.sender,
                self.states.get(&s_tx_hash).map(|s| s.prepares.len()).unwrap_or(0),
                self.states.get(&s_tx_hash).map(|s| s.commits.len()).unwrap_or(0),
            );
            match phase {
                PbftPhase::Prepare => self.adjust_reputation(&msg.sender, REP_PREPARE_VOTE),
                PbftPhase::Commit => self.adjust_reputation(&msg.sender, REP_COMMIT_VOTE),
                PbftPhase::Finalized => { self.last_finalized_hash = s_tx_hash.clone(); }
                _ => {}
            }
            if self.is_validator() {
                return Some(PbftMessage {
                    phase: phase as i32, view: s_view, sequence: s_seq,
                    tx_hash: s_tx_hash.clone(), sender: self.node_id.clone(),
                    signature: self.generate_signature(&s_tx_hash, s_seq, phase as i32),
                    tx_type: s_tx_type,
                });
            }
        }
        None
    }

    pub fn mark_validated(&mut self, tx_hash: &str, tx_type: i32) -> Option<PbftMessage> {
        self.maybe_rotate_epoch();
        let (new_phase, s_view, s_seq, s_tx_hash, s_tx_type) = {
            let state = self.states.entry(tx_hash.to_string()).or_insert_with(|| {
                PporState::new(self.view, 0, tx_hash.to_string(), tx_type, self.current_committee.clone())
            });
            match state.mark_validated() {
                Some(p) => (Some(p), state.view, state.sequence, state.tx_hash.clone(), state.tx_type),
                None => (None, 0, 0, String::new(), 0),
            }
        };
        if let Some(phase) = new_phase {
            eprintln!("[PBFT] Validated: tx={}, phase={:?}, validator={}", s_tx_hash, phase, self.node_id);
            if self.is_validator() {
                return Some(PbftMessage {
                    phase: phase as i32, view: s_view, sequence: s_seq,
                    tx_hash: s_tx_hash.clone(), sender: self.node_id.clone(),
                    signature: self.generate_signature(&s_tx_hash, s_seq, phase as i32),
                    tx_type: s_tx_type,
                });
            }
        }
        None
    }

    // --- Garbage Collection ---

    /// Move a finalized transaction from active states to the archive.
    /// Keeps only (tx_hash, finalized_at, epoch) for audit purposes.
    pub fn archive_finalized_state(&mut self, tx_hash: &str) {
        if self.states.remove(tx_hash).is_some() {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            self.finalized_archive.push(FinalizedArchiveEntry {
                tx_hash: tx_hash.to_string(),
                finalized_at: now,
                finalized_epoch: self.current_epoch,
            });
            // Trim archive if it exceeds max size
            while self.finalized_archive.len() > self.max_archive_size {
                self.finalized_archive.remove(0);
            }
            eprintln!("[GC] Archived finalized tx: {} (archive size={})", tx_hash, self.finalized_archive.len());
        }
    }

    /// Remove finalized archive entries older than `keep_epochs` epochs ago.
    /// This is the periodic cleanup called at epoch rotation.
    pub fn cleanup_finalized_states(&mut self, keep_epochs: u64) {
        let cutoff_epoch = self.current_epoch.saturating_sub(keep_epochs);
        let before = self.finalized_archive.len();
        self.finalized_archive.retain(|entry| entry.finalized_epoch >= cutoff_epoch);
        let removed = before - self.finalized_archive.len();
        if removed > 0 {
            eprintln!(
                "[GC] Cleaned up {} finalized entries older than epoch {} (remaining: {})",
                removed, cutoff_epoch, self.finalized_archive.len()
            );
        }
    }

    /// Clean up timed-out states. Call periodically.
    pub fn cleanup_timed_out(&mut self) {
        let before = self.states.len();
        let mut penalties: Vec<String> = Vec::new();
        self.states.retain(|hash, s| {
            if s.is_timed_out() && s.phase != PbftPhase::Finalized {
                for member in &s.committee {
                    if !s.prepares.contains(member) && !s.commits.contains(member) {
                        penalties.push(member.clone());
                    }
                }
                eprintln!("[TX_TIMEOUT] Transaction {} timed out after {:?}", hash, s.created_at.elapsed());
                false
            } else {
                true
            }
        });
        for member in &penalties {
            self.adjust_reputation(member, REP_TIMEOUT);
        }
        if before != self.states.len() {
            eprintln!("[CLEANUP] Removed {} timed-out transactions", before - self.states.len());
        }
    }

    // --- Grant System ---

    /// Створити новий грант. Викликається після перевірки прав через GrantAuthority.
    pub fn create_grant(&mut self, grant: GrantProgram) -> Result<(), String> {
        if self.grant_programs.contains_key(&grant.grant_id) {
            return Err("Grant already exists".to_string());
        }
        if grant.amount_per_claim == 0 {
            return Err("Amount per claim must be > 0".to_string());
        }
        eprintln!(
            "[GRANT] Created: id={}, signer={}, amount={}, max_claims={}",
            grant.grant_id, grant.signer, grant.amount_per_claim, grant.max_claims
        );
        self.grant_programs.insert(grant.grant_id.clone(), grant);
        Ok(())
    }

    /// Перевірити чи DID може клеймити грант. Повертає amount якщо OK.
    pub fn verify_grant_claim(&self, grant_id: &str, did: &str) -> Result<u64, String> {
        let grant = self
            .grant_programs
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

    /// Виконати клейм (мутує стан). Викликати після verify_grant_claim.
    pub fn execute_claim(&mut self, grant_id: &str, did: &str, amount: u64) -> Result<u64, String> {
        let grant = self
            .grant_programs
            .get_mut(grant_id)
            .ok_or_else(|| "Grant not found".to_string())?;

        grant.claimed_by.insert(did.to_string());
        grant.claimed_count += 1;
        grant.claimed_total += amount;

        eprintln!(
            "[GRANT] Claim: grant={}, did={}, amount={}, count={}/{:?}",
            grant_id, did, amount, grant.claimed_count, grant.max_claims
        );

        Ok(grant.claimed_count)
    }
}
