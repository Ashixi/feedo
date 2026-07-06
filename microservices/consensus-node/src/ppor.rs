use std::collections::{HashMap, HashSet};
use shared_proto::feedo::{PbftMessage, PbftPhase};
use sha2::{Sha256, Digest};
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;

pub const TX_TYPE_DATA: i32 = 0;
pub const TX_TYPE_MICRO_TX_BATCH: i32 = 1;
pub const TX_TYPE_SLASHING: i32 = 2;

#[derive(Debug, Clone)]
pub struct ReputationRecord {
    pub node_id: String,
    pub score: u64,
}

#[derive(Debug)]
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
        }
    }

    pub fn required_votes(&self) -> usize {
        // 2/3 of committee size + 1
        (2 * self.committee.len() / 3) + 1
    }

    pub fn process_message(&mut self, msg: &PbftMessage) -> Option<PbftPhase> {
        // Дозволяємо брати участь в консенсусі тільки членам комітету
        if !self.committee.contains(&msg.sender) {
            return None;
        }

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

pub struct PporManager {
    pub states: HashMap<String, PporState>,
    pub view: u64,
    pub node_id: String,
    pub secret_key: Option<secp256k1::SecretKey>,
    pub secp: secp256k1::Secp256k1<secp256k1::All>,
    
    // Репутація та комітет
    pub reputation_table: HashMap<String, u64>,
    pub current_committee: HashSet<String>,
    pub last_finalized_hash: String,
}

impl PporManager {
    pub fn new(node_id: String) -> Self {
        let mut rep = HashMap::new();
        rep.insert(node_id.clone(), 100);
        
        let mut comm = HashSet::new();
        comm.insert(node_id.clone());

        Self {
            states: HashMap::new(),
            view: 0,
            node_id,
            secret_key: None,
            secp: secp256k1::Secp256k1::new(),
            reputation_table: rep,
            current_committee: comm,
            last_finalized_hash: "genesis_hash".to_string(),
        }
    }

    pub fn set_secret_key(&mut self, hex_key: &str) {
        if let Ok(decoded) = hex::decode(hex_key.trim_start_matches("0x")) {
            if let Ok(sk) = secp256k1::SecretKey::from_slice(&decoded) {
                self.secret_key = Some(sk);
            }
        }
    }

    // VRF Лотерея: Вибір Топ-21 валідаторів з використанням хешу як Seed
    pub fn select_committee(&mut self, seed_hash: &str) {
        let mut hasher = Sha256::new();
        hasher.update(seed_hash.as_bytes());
        let result = hasher.finalize();
        
        let mut seed = [0u8; 32];
        seed.copy_from_slice(&result);
        let mut rng = StdRng::from_seed(seed);
        
        let mut nodes: Vec<String> = self.reputation_table.keys().cloned().collect();
        nodes.sort(); // Детермінованість
        
        use rand::seq::SliceRandom;
        nodes.shuffle(&mut rng);
        
        let committee_size = std::cmp::min(21, nodes.len());
        self.current_committee.clear();
        for i in 0..committee_size {
            self.current_committee.insert(nodes[i].clone());
        }
        println!("New Committee selected based on {}: {:?}", seed_hash, self.current_committee);
    }

    pub fn reward_node(&mut self, node_id: &str, points: u64) {
        let entry = self.reputation_table.entry(node_id.to_string()).or_insert(10);
        *entry += points;
    }

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

    pub fn propose(&mut self, tx_hash: String, sequence: u64, tx_type: i32) -> Option<PbftMessage> {
        if !self.current_committee.contains(&self.node_id) {
            return None; // Тільки комітет може пропонувати
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
        if !self.reputation_table.contains_key(&msg.sender) {
            self.reputation_table.insert(msg.sender.clone(), 10);
        }

        let (new_phase, s_view, s_seq, s_tx_hash, s_tx_type) = {
            let state = self.states.entry(msg.tx_hash.clone()).or_insert_with(|| {
                PporState::new(msg.view, msg.sequence, msg.tx_hash.clone(), msg.tx_type, self.current_committee.clone())
            });
            match state.process_message(&msg) {
                Some(p) => (Some(p), state.view, state.sequence, state.tx_hash.clone(), state.tx_type),
                None => (None, 0, 0, String::new(), 0),
            }
        };

        if let Some(phase) = new_phase {
            if phase == PbftPhase::Finalized {
                self.last_finalized_hash = s_tx_hash.clone();
                // Ротація комітету після кожної фіналізованої транзакції (або блоку)
                self.select_committee(&self.last_finalized_hash.clone());
            }

            // Відповідаємо тільки якщо ми в комітеті
            if self.current_committee.contains(&self.node_id) {
                return Some(PbftMessage {
                    phase: phase as i32,
                    view: s_view,
                    sequence: s_seq,
                    tx_hash: s_tx_hash.clone(),
                    sender: self.node_id.clone(),
                    signature: self.generate_signature(&s_tx_hash, s_seq, phase as i32),
                    tx_type: s_tx_type,
                });
            }
        }
        None
    }

    pub fn mark_validated(&mut self, tx_hash: &str, tx_type: i32) -> Option<PbftMessage> {
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
            if self.current_committee.contains(&self.node_id) {
                return Some(PbftMessage {
                    phase: phase as i32,
                    view: s_view,
                    sequence: s_seq,
                    tx_hash: s_tx_hash.clone(),
                    sender: self.node_id.clone(),
                    signature: self.generate_signature(&s_tx_hash, s_seq, phase as i32),
                    tx_type: s_tx_type,
                });
            }
        }
        None
    }
}
