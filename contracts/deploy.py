import os
import json
import getpass
from web3 import Web3
from solcx import compile_source, install_solc

def deploy_contract():
    # Setup
    print("Installing solc 0.8.19...")
    install_solc("0.8.19")
    
    # Read Contract
    contract_path = os.path.join(os.path.dirname(__file__), "PporTreasury.sol")
    with open(contract_path, "r", encoding="utf-8") as f:
        contract_source = f.read()
    
    print("Compiling contract...")
    compiled_sol = compile_source(
        contract_source,
        output_values=["abi", "bin"],
        solc_version="0.8.19"
    )
    
    contract_id, contract_interface = compiled_sol.popitem()
    abi = contract_interface['abi']
    bytecode = contract_interface['bin']
    
    # Web3 Connection
    rpc_url = input("Enter Polygon Mainnet RPC URL (or press Enter for default public RPCs): ").strip()
    
    w3 = None
    if rpc_url:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            print(f"Failed to connect to {rpc_url}.")
            return
        print(f"Connected to {rpc_url}")
    else:
        # Try a list of public RPCs
        public_rpcs = [
            "https://polygon.drpc.org",
            "https://1rpc.io/matic",
            "https://polygon.meowrpc.com",
            "https://polygon.rpc.blxrbdn.com"
        ]
        print("Testing public RPC endpoints...")
        for rpc in public_rpcs:
            temp_w3 = Web3(Web3.HTTPProvider(rpc))
            if temp_w3.is_connected():
                w3 = temp_w3
                rpc_url = rpc
                print(f"Successfully connected to {rpc_url}")
                break
                
        if not w3:
            print("Failed to connect to any public Polygon Mainnet RPC. Please provide a custom RPC URL (like Alchemy or Infura).")
            return
    print(f"Current Block: {w3.eth.block_number}")
    
    private_key = getpass.getpass("Enter your wallet Private Key (hidden): ").strip()
    if not private_key:
        print("Private key is required!")
        return
        
    account = w3.eth.account.from_key(private_key)
    print(f"Deploying from address: {account.address}")
    
    balance = w3.eth.get_balance(account.address)
    print(f"Account Balance: {w3.from_wei(balance, 'ether')} MATIC")
    
    if balance == 0:
        print("Insufficient MATIC balance for deployment. Please fund your wallet.")
        return
        
    print("Creating contract transaction...")
    PporTreasury = w3.eth.contract(abi=abi, bytecode=bytecode)
    
    usdt_address = input("Enter USDT token address on Polygon (e.g., 0xc2132d05d31c914a87c6611c10748aeb04b58e8f): ").strip()
    if not usdt_address or not w3.is_address(usdt_address):
        print("Invalid USDT address!")
        return
    usdt_address = Web3.to_checksum_address(usdt_address)

    committee_input = input("Enter initial committee addresses (comma separated): ").strip()
    initial_committee = [Web3.to_checksum_address(addr.strip()) for addr in committee_input.split(",") if w3.is_address(addr.strip())]
    if not initial_committee:
        print("Invalid committee addresses!")
        return
    
    try:
        construct_txn = PporTreasury.constructor(usdt_address, initial_committee).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gasPrice': w3.eth.gas_price
        })
        gas_estimate = w3.eth.estimate_gas(construct_txn)
        construct_txn['gas'] = int(gas_estimate * 1.2)
    except Exception as e:
        print(f"Error estimating gas: {e}")
        return

    print("Signing transaction...")
    signed_txn = w3.eth.account.sign_transaction(construct_txn, private_key=private_key)
    
    print("Sending transaction to network...")
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    print(f"Transaction Hash: {w3.to_hex(tx_hash)}")
    
    print("Waiting for transaction receipt...")
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    contract_address = tx_receipt.contractAddress
    print(f"\n✅ Success! Contract deployed to: {contract_address}")
    
    output_data = {
        "address": contract_address,
        "abi": abi
    }
    
    output_file = os.path.join(os.path.dirname(__file__), "PporTreasury.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
        
    print(f"Contract data saved to {output_file}")

if __name__ == "__main__":
    deploy_contract()
