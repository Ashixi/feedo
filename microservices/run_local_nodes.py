import subprocess
import re
import os
import time
import sys

def main():
    print("Building consensus-node...")
    subprocess.run(["cargo", "build"], cwd="consensus-node", check=True)
    
    executable = os.path.join("target", "debug", "consensus-node.exe")
    if not os.path.exists(executable):
        print(f"Executable not found at {executable}!")
        return

    # Clean DBs
    import shutil
    if os.path.exists("consensus_db1"):
        shutil.rmtree("consensus_db1")
    if os.path.exists("consensus_db2"):
        shutil.rmtree("consensus_db2")

    print("Starting Node 1...")
    env1 = os.environ.copy()
    env1.update({
        "RUST_LOG": "info",
        "GRPC_PORT": "50051",
        "HTTP_PORT": "3000",
        "P2P_PORT": "8041",
        "DB_DIR": "consensus_db1",
        "NODE_WALLET_ADDRESS": "0x0827e8caf5ff9652c5d89eb69d55ce083c750b21",
        "ETH_RPC_URL": "https://polygon.llamarpc.com"
    })
    
    node1 = subprocess.Popen(
        [executable],
        env=env1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    peer_id = None
    print("Waiting for Node 1 to output peer ID...")
    
    # We will read node1 output in a separate thread so we can keep printing it
    import threading
    def read_output(proc, prefix):
        nonlocal peer_id
        for line in iter(proc.stdout.readline, ''):
            if "Consensus Local peer id: PeerId(\"" in line and peer_id is None:
                match = re.search(r'PeerId\("([^"]+)"\)', line)
                if match:
                    peer_id = match.group(1)
            print(f"{prefix}: {line}", end="")
            
    t1 = threading.Thread(target=read_output, args=(node1, "NODE1"))
    t1.daemon = True
    t1.start()
    
    while peer_id is None:
        time.sleep(0.5)
        if node1.poll() is not None:
            print("Node 1 exited prematurely!")
            return
            
    print(f"\nFound Node 1 Peer ID: {peer_id}\n")
    
    print("Starting Node 2...")
    env2 = os.environ.copy()
    env2.update({
        "RUST_LOG": "info",
        "GRPC_PORT": "50052",
        "HTTP_PORT": "3001",
        "P2P_PORT": "8042",
        "DB_DIR": "consensus_db2",
        "BOOTSTRAP_NODES": f"/ip4/127.0.0.1/udp/8041/quic-v1/p2p/{peer_id}",
        "NODE_WALLET_ADDRESS": "0x89bf2d987a05d6244bcef70f1d66fd4395c1588d",
        "ETH_RPC_URL": "https://polygon.llamarpc.com"
    })
    
    node2 = subprocess.Popen(
        [executable],
        env=env2,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    t2 = threading.Thread(target=read_output, args=(node2, "NODE2"))
    t2.daemon = True
    t2.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping nodes...")
        node1.kill()
        node2.kill()

if __name__ == "__main__":
    main()
