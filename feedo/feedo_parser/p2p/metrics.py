from prometheus_client import Counter, Gauge

# P2P metrics
PEER_COUNT = Gauge('feedo_p2p_peer_count', 'Number of peers in cache')
REPLICA_REPAIRS_FAILED = Counter('feedo_replica_repairs_failed_total', 'Total failed replica repair attempts')
REPLICA_REPAIRS_SUCCEEDED = Counter('feedo_replica_repairs_succeeded_total', 'Total successful replica repairs')
ANNOUNCE_RATE = Counter('feedo_p2p_announce_total', 'Total announce messages sent')
DHT_PUT_ERRORS = Counter('feedo_dht_put_errors_total', 'Total DHT put errors')
REPLICATION_PUSH_SUCCEEDED = Counter('feedo_replication_push_succeeded_total', 'Total replication push successes')
REPLICATION_PUSH_FAILED = Counter('feedo_replication_push_failed_total', 'Total replication push failures')
REPLICATION_PUSH_LATENCY_SECONDS = Gauge('feedo_replication_push_latency_seconds', 'Latency seconds for last replication push')

