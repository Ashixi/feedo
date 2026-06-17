use std::collections::{HashMap, HashSet};
use crate::proto::feedo::{PbftMessage, PbftPhase};

pub const TX_TYPE_DATA: i32 = 0;
pub const TX_TYPE_MICRO_TX_BATCH: i32 = 1;
pub const TX_TYPE_SLASHING: i32 = 2;

#[derive(Debug)]
pub struct PbftState {
    pub view: u64,
    pub sequence: u64,
    pub tx_hash: String,
    pub tx_type: i32,
    pub phase: PbftPhase,
    pub prepares: HashSet<String>,
    pub commits: HashSet<String>,
    pub total_nodes: usize,
    pub is_validated: bool,
}

impl PbftState {
    pub fn new(view: u64, sequence: u64, tx_hash: String, tx_type: i32, total_nodes: usize) -> Self {
        Self {
            view,
            sequence,
            tx_hash,
            tx_type,
            phase: PbftPhase::PrePrepare,
            prepares: HashSet::new(),
            commits: HashSet::new(),
            total_nodes,
            is_validated: false,
        }
    }

    pub fn required_votes(&self) -> usize {
        (2 * self.total_nodes / 3) + 1
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

pub struct PbftManager {
    pub states: HashMap<String, PbftState>,
    pub view: u64,
    pub node_id: String,
    pub secret_key: Option<secp256k1::SecretKey>,
    pub secp: secp256k1::Secp256k1<secp256k1::All>,
}

impl PbftManager {
    pub fn new(node_id: String) -> Self {
        Self {
            states: HashMap::new(),
            view: 0,
            node_id,
            secret_key: None,
            secp: secp256k1::Secp256k1::new(),
        }
    }

    pub fn set_secret_key(&mut self, hex_key: &str) {
        if let Ok(decoded) = hex::decode(hex_key.trim_start_matches("0x")) {
            if let Ok(sk) = secp256k1::SecretKey::from_slice(&decoded) {
                self.secret_key = Some(sk);
            }
        }
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

    pub fn propose(&mut self, tx_hash: String, sequence: u64, tx_type: i32, total_nodes: usize) -> PbftMessage {
        let state = PbftState::new(self.view, sequence, tx_hash.clone(), tx_type, total_nodes);
        self.states.insert(tx_hash.clone(), state);
        PbftMessage {
            phase: PbftPhase::PrePrepare as i32,
            view: self.view,
            sequence,
            tx_hash: tx_hash.clone(),
            sender: self.node_id.clone(),
            signature: self.generate_signature(&tx_hash, sequence, PbftPhase::PrePrepare as i32),
            tx_type,
        }
    }

    pub fn handle_message(&mut self, msg: PbftMessage, total_nodes: usize) -> Option<PbftMessage> {
        let (new_phase, s_view, s_seq, s_tx_hash, s_tx_type) = {
            let state = self.states.entry(msg.tx_hash.clone()).or_insert_with(|| {
                PbftState::new(msg.view, msg.sequence, msg.tx_hash.clone(), msg.tx_type, total_nodes)
            });
            match state.process_message(&msg) {
                Some(p) => (Some(p), state.view, state.sequence, state.tx_hash.clone(), state.tx_type),
                None => (None, 0, 0, String::new(), 0),
            }
        };

        if let Some(phase) = new_phase {
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
        None
    }

    pub fn mark_validated(&mut self, tx_hash: &str, tx_type: i32, total_nodes: usize) -> Option<PbftMessage> {
        let (new_phase, s_view, s_seq, s_tx_hash, s_tx_type) = {
            let state = self.states.entry(tx_hash.to_string()).or_insert_with(|| {
                PbftState::new(self.view, 0, tx_hash.to_string(), tx_type, total_nodes)
            });
            match state.mark_validated() {
                Some(p) => (Some(p), state.view, state.sequence, state.tx_hash.clone(), state.tx_type),
                None => (None, 0, 0, String::new(), 0),
            }
        };

        if let Some(phase) = new_phase {
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
        None
    }
}
