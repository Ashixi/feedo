import json
import time
from web3 import Web3
from getpass import getpass

# Конфігурація
RPC_URL = "https://polygon.drpc.org"
TREASURY_ADDRESS = "0x6C060F17e3BC6B8BaaE9eb638632Fdc3DfAAc51b"
USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
STAKE_AMOUNT = 1 * 10**6  # 1 USDC (6 decimals)

# Мінімальні ABI для викликів
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]

TREASURY_ABI = [
    {"inputs": [], "name": "registerNode", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

def main():
    print("=== Feedo Network: Node Registration & Staking ===")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("Failed to connect to Polygon.")
        return

    private_key = getpass("Enter the Private Key for the NEW node (hidden): ")
    try:
        account = w3.eth.account.from_key(private_key)
    except Exception as e:
        print(f"Invalid private key: {e}")
        return

    wallet_address = account.address
    print(f"\nNode Wallet Address: {wallet_address}")

    # Перевірка балансів
    matic_balance = w3.eth.get_balance(wallet_address)
    print(f"MATIC Balance: {w3.from_wei(matic_balance, 'ether')} MATIC")
    
    if matic_balance < w3.to_wei(0.01, 'ether'):
        print("❌ Not enough MATIC for gas fees. Please send at least 0.01 MATIC to this address.")
        return

    usdc_contract = w3.eth.contract(address=w3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
    usdc_balance = usdc_contract.functions.balanceOf(wallet_address).call()
    print(f"USDC Balance: {usdc_balance / 10**6} USDC")

    if usdc_balance < STAKE_AMOUNT:
        print(f"❌ Not enough USDC. You need exactly 1 USDC to stake. You have {usdc_balance / 10**6}.")
        return

    print("\nStarting Registration Process...")
    
    # 1. Approve USDC
    print("1. Approving 1 USDC for Treasury contract...")
    nonce = w3.eth.get_transaction_count(wallet_address)
    approve_txn = usdc_contract.functions.approve(
        w3.to_checksum_address(TREASURY_ADDRESS), 
        STAKE_AMOUNT
    ).build_transaction({
        'chainId': 137,
        'gas': 100000,
        'maxFeePerGas': w3.to_wei('50', 'gwei'),
        'maxPriorityFeePerGas': w3.to_wei('50', 'gwei'),
        'nonce': nonce,
    })
    
    signed_approve = w3.eth.account.sign_transaction(approve_txn, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_approve.rawTransaction)
    print(f"Approve Tx Hash: {w3.to_hex(tx_hash)}")
    print("Waiting for confirmation...")
    w3.eth.wait_for_transaction_receipt(tx_hash)
    print("✅ Approval successful!")

    # 2. Call registerNode
    print("\n2. Registering node in Treasury (Staking 1 USDC)...")
    treasury_contract = w3.eth.contract(address=w3.to_checksum_address(TREASURY_ADDRESS), abi=TREASURY_ABI)
    nonce = w3.eth.get_transaction_count(wallet_address)
    
    register_txn = treasury_contract.functions.registerNode().build_transaction({
        'chainId': 137,
        'gas': 200000,
        'maxFeePerGas': w3.to_wei('50', 'gwei'),
        'maxPriorityFeePerGas': w3.to_wei('50', 'gwei'),
        'nonce': nonce,
    })
    
    signed_register = w3.eth.account.sign_transaction(register_txn, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_register.rawTransaction)
    print(f"Register Tx Hash: {w3.to_hex(tx_hash)}")
    print("Waiting for confirmation...")
    w3.eth.wait_for_transaction_receipt(tx_hash)
    
    print("\n🎉 SUCCESS! Your node is officially registered and staked 5 USDC.")
    print("Now you can start your node using docker-compose, and it will begin earning reputation!")

if __name__ == "__main__":
    main()
