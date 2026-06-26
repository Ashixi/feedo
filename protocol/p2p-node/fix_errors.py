import sys
with open("src/main.rs", "r") as f:
    content = f.read()

# Fix mod did
content = content.replace("mod crdt;", "mod crdt;\nmod did;")

# Fix _sig in send_response
content = content.replace("DirectResponse::HandshakeResponse(_sig));", "DirectResponse::HandshakeResponse(sig));")

# Fix SwarmCommand enum (if it failed, let's just do it directly)
if "RunPoStChallenges" not in content[:1000]:
    content = content.replace(
        "    ResolveName(String, oneshot::Sender<Option<String>>),",
        "    ResolveName(String, oneshot::Sender<Option<String>>),\n    CrdtMutate(proto::feedo::CrdtOperation),\n    CrdtGet(String, oneshot::Sender<Option<String>>),\n    RunPoStChallenges,"
    )

# Fix propose
content = content.replace(
    "pbft_manager.propose(req.hash_id.clone(), req.sequence_number.unwrap_or(0) as u64, total_nodes);",
    "pbft_manager.propose(req.hash_id.clone(), req.sequence_number.unwrap_or(0) as u64, proto::feedo::TxType::Content as i32, total_nodes);"
)
content = content.replace(
    "pbft_manager.propose(tx_hash, sequence, total_nodes);",
    "pbft_manager.propose(tx_hash, sequence, proto::feedo::TxType::Content as i32, total_nodes);"
)

# Fix mark_validated
content = content.replace(
    "pbft_manager.mark_validated(&tx_hash, total_nodes)",
    "pbft_manager.mark_validated(&tx_hash, proto::feedo::TxType::Content as i32, total_nodes)"
)

# Fix chosen_peer deref
content = content.replace(
    "swarm.behaviour_mut().req_resp.send_request(*chosen_peer, DirectRequest::PoStChallengeReq {",
    "swarm.behaviour_mut().req_resp.send_request(chosen_peer, DirectRequest::PoStChallengeReq {"
)

# Fix _request_id
content = content.replace(
    "request_response::Message::Request { _request_id, request, channel } => {",
    "request_response::Message::Request { request_id, request, channel } => {"
)

with open("src/main.rs", "w") as f:
    f.write(content)
print("Fixed errors")
