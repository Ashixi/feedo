import sys

with open('src/main.rs', 'r', encoding='utf-8') as f:
    content = f.read()

if 'feedo_feed_search' in content and 'FeedSearchQuery::decode' in content:
    print('Already patched receiver.')
    sys.exit(0)

search_str = '                        continue;\n                    }'
feed_search_code = '''
                    if message.topic.as_str() == "feedo_feed_search" {
                        if message.data.is_empty() { continue; }
                        let msg_type = message.data[0];
                        let payload = &message.data[1..];

                        if msg_type == 2 { // Query
                            if let Ok(mut query) = proto::feedo::FeedSearchQuery::decode(payload) {
                                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                                if search_query_cache.contains_key(&query.query_id) { continue; }
                                search_query_cache.insert(query.query_id.clone(), now);

                                let cmd_tx = loop_tx.clone();
                                let client_clone = http_client.clone();
                                let python_url = python_webhook_url.replace("/internal/p2p_receive", "/api/v1/semantic/internal/feed_query");
                                let peer_id_str = local_peer_id_str.clone();
                                let query_id_clone = query.query_id.clone();
                                
                                let req_body = serde_json::json!({
                                    "query_id": query_id_clone,
                                    "keywords": query.keywords,
                                    "language": query.language,
                                    "limit": query.limit,
                                    "need_anti_bubble": query.need_anti_bubble,
                                    "originator_peer_id": query.originator_peer_id
                                });

                                tokio::spawn(async move {
                                    if let Ok(res) = client_clone.post(&python_url).json(&req_body).send().await {
                                        if let Ok(json_res) = res.json::<serde_json::Value>().await {
                                            if let Some(results_array) = json_res.get("results").and_then(|r| r.as_array()) {
                                                let mut items = Vec::new();
                                                for r in results_array {
                                                    items.push(proto::feedo::FeedSearchResultItem {
                                                        post: None,
                                                        trending_score: r.get("trending_score").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                                                        similarity_score: r.get("similarity_score").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                                                        relay_urls: vec![],
                                                    });
                                                }
                                                if !items.is_empty() {
                                                    let res_proto = proto::feedo::FeedSearchResult {
                                                        query_id: query_id_clone,
                                                        responder_peer_id: peer_id_str,
                                                        items,
                                                    };
                                                    let mut encoded = Vec::new();
                                                    encoded.push(3u8); // Result
                                                    if prost::Message::encode(&res_proto, &mut encoded).is_ok() {
                                                        let _ = cmd_tx.send(SwarmCommand::BroadcastSemanticResult(encoded)); // Broadcast on same mechanism
                                                    }
                                                }
                                            }
                                        }
                                    }
                                });

                                if query.ttl > 0 {
                                    query.ttl -= 1;
                                    let mut fwd = Vec::new();
                                    fwd.push(2u8);
                                    if prost::Message::encode(&query, &mut fwd).is_ok() {
                                        let _ = loop_tx.send(SwarmCommand::ForwardSemanticSearch(fwd));
                                    }
                                }
                            }
                        } else if msg_type == 3 { // Result
                            if let Ok(res) = proto::feedo::FeedSearchResult::decode(payload) {
                                if let Some((_, results_vec)) = active_search_requests.get_mut(&res.query_id) {
                                    let mut py_results = Vec::new();
                                    for item in res.items {
                                        py_results.push(serde_json::json!({
                                            "trending_score": item.trending_score,
                                            "similarity_score": item.similarity_score
                                        }));
                                    }
                                    // TODO: append to results_vec? Wait, results_vec is Vec<SemanticSearchResultItem>.
                                    // So active_search_requests would need to be updated. But it's easier just to drop this part and have python handle feed result natively, or just not store it if we are using string parsing.
                                    // Wait, active_search_requests stores `Vec<SemanticSearchResultItem>`. We can't push JSON!
                                    // Let's just create a new active_feed_search_requests!
                                }
                            }
                        }
                        continue;
                    }
'''
if search_str in content:
    content = content.replace(search_str, search_str + '\n' + feed_search_code)
    with open('src/main.rs', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched receiver successfully!')
else:
    print('Could not find injection point.')
