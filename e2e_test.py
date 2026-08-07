import subprocess
import time
import requests
import os
import signal
import sys
import atexit

# Порти для тестування (використовуємо нестандартні, щоб не було конфліктів)
STORAGE_HTTP = 3011
STORAGE_P2P = 8011
STORAGE_GRPC = 50061

CONSENSUS_HTTP = 3012
CONSENSUS_P2P = 8012
CONSENSUS_GRPC = 50062

SEARCH_PORT = 8013

processes = []

def cleanup():
    print("\n[E2E] Stopping all nodes...")
    for p in processes:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            p.kill()
    print("[E2E] All nodes stopped.")

atexit.register(cleanup)

def wait_for_port(port, timeout=30):
    """Очікує, поки порт стане доступним для HTTP запитів"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/api/v1/peers", timeout=1)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        except Exception:
            pass
        time.sleep(1)
    return False

def wait_for_search_node(port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/query?text=test", timeout=1)
            # Якщо відповідає (навіть помилкою чи порожнім результатом) - значить сервер піднявся
            return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    return False

def main():
    print("[E2E] Building Rust projects...")
    subprocess.run(["cargo", "build"], cwd="microservices/storage-node", check=True)
    subprocess.run(["cargo", "build"], cwd="microservices/consensus-node", check=True)

    print("[E2E] Starting Storage Node...")
    env_storage = os.environ.copy()
    env_storage["HTTP_PORT"] = str(STORAGE_HTTP)
    env_storage["P2P_PORT"] = str(STORAGE_P2P)
    env_storage["GRPC_PORT"] = str(STORAGE_GRPC)
    env_storage["CONSENSUS_NODE_URL"] = f"http://127.0.0.1:{CONSENSUS_HTTP}"
    # Зберігаємо логи у файли
    storage_log = open("storage_test.log", "w")
    p_storage = subprocess.Popen(
        ["cargo", "run"], 
        cwd="microservices/storage-node",
        env=env_storage,
        stdout=storage_log,
        stderr=subprocess.STDOUT
    )
    processes.append(p_storage)

    print("[E2E] Starting Consensus Node...")
    env_consensus = os.environ.copy()
    env_consensus["HTTP_PORT"] = str(CONSENSUS_HTTP)
    env_consensus["P2P_PORT"] = str(CONSENSUS_P2P)
    env_consensus["GRPC_PORT"] = str(CONSENSUS_GRPC)
    consensus_log = open("consensus_test.log", "w")
    p_consensus = subprocess.Popen(
        ["cargo", "run"], 
        cwd="microservices/consensus-node",
        env=env_consensus,
        stdout=consensus_log,
        stderr=subprocess.STDOUT
    )
    processes.append(p_consensus)

    print(f"[E2E] Waiting for Storage ({STORAGE_HTTP}) and Consensus ({CONSENSUS_HTTP}) to start...")
    if not wait_for_port(STORAGE_HTTP):
        print("[ERROR] Storage Node failed to start. Check storage_test.log")
        sys.exit(1)
    if not wait_for_port(CONSENSUS_HTTP):
        print("[ERROR] Consensus Node failed to start. Check consensus_test.log")
        sys.exit(1)
    print("[SUCCESS] Both Rust nodes started successfully!")
    
    # Даємо їм пару секунд на P2P Discovery
    print("[E2E] Waiting 5 seconds for Kademlia/Gossipsub Discovery...")
    time.sleep(5)

    print("[E2E] Starting Search Node...")
    env_search = os.environ.copy()
    env_search["PORT"] = str(SEARCH_PORT)
    env_search["STORAGE_NODE_URL"] = f"http://127.0.0.1:{STORAGE_HTTP}"
    env_search["CONSENSUS_URL"] = f"127.0.0.1:{CONSENSUS_GRPC}"
    env_search["CONSENSUS_NODES"] = f"http://127.0.0.1:{CONSENSUS_HTTP}"
    env_search["CONSENSUS_NODE_URL"] = f"http://127.0.0.1:{CONSENSUS_HTTP}"
    search_log = open("search_test.log", "w")
    p_search = subprocess.Popen(
        [sys.executable, "main.py"], 
        cwd="microservices/search-node",
        env=env_search,
        stdout=search_log,
        stderr=subprocess.STDOUT
    )
    processes.append(p_search)

    print(f"[E2E] Waiting for Search Node ({SEARCH_PORT}) to start...")
    if not wait_for_search_node(SEARCH_PORT):
        print("[ERROR] Search Node failed to start. Check search_test.log")
        sys.exit(1)
    print("[SUCCESS] Search Node started successfully!")
    
    # Даємо Search Node час на опитування Peers
    print("[E2E] Waiting 3 seconds for Search Node to fetch peers...")
    time.sleep(3)

    print("\n[E2E] --- Executing HTTP tests ---")
    
    # 1. Перевірка Storage Peers
    print("[TEST 1] Requesting Storage Peers...")
    try:
        r = requests.get(f"http://127.0.0.1:{STORAGE_HTTP}/api/v1/peers")
        print(f"       Response: {r.json()}")
    except Exception as e:
        print(f"       Error: {e}")

    # 2. Перевірка Consensus Peers
    print("[TEST 2] Requesting Consensus Peers...")
    try:
        r = requests.get(f"http://127.0.0.1:{CONSENSUS_HTTP}/api/v1/peers")
        print(f"       Response: {r.json()}")
    except Exception as e:
        print(f"       Error: {e}")

    # 3. Перевірка App ID фільтрації
    print("[TEST 3] Requesting Search Node with app_id...")
    try:
        r = requests.get(f"http://127.0.0.1:{SEARCH_PORT}/query?text=test&app_id=com.myawesomeapp")
        print(f"       Response (HTTP {r.status_code}): {r.text[:150]}...")
    except Exception as e:
        print(f"       Error: {e}")

    # 4. Запуск TypeScript клієнта
    print("\n[TEST 4] Running TypeScript Client E2E Test...")
    try:
        # First ensure dependencies are installed
        npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run([npm_cmd, "install"], cwd="sdk/typescript", check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Run the test script using tsx for flawless execution
        env_ts = os.environ.copy()
        ts_process = subprocess.run(
            [npx_cmd, "tsx", "test_client.ts"], 
            cwd="sdk/typescript",
            env=env_ts,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        print(f"       TS Client Output:\n{ts_process.stdout}")
        if ts_process.stderr:
            print(f"       TS Client Errors:\n{ts_process.stderr}")
    except Exception as e:
        print(f"       Error running TS Client: {e}")

    print("\n[E2E] All tests completed! Waiting 2 seconds before cleanup...")
    time.sleep(2)

if __name__ == "__main__":
    main()
