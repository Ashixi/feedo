let userAddress = null;

const connectBtn = document.getElementById('connect-btn');
const dashboard = document.getElementById('dashboard');
const walletAddressSpan = document.getElementById('wallet-address');
const tokenBalanceSpan = document.getElementById('token-balance');
const freeQueriesSpan = document.getElementById('free-queries');

const showTopupBtn = document.getElementById('show-topup-btn');
const topUpSection = document.getElementById('top-up-section');
const submitTxBtn = document.getElementById('submit-tx-btn');
const depositAmount = document.getElementById('deposit-amount');
const loader = document.getElementById('loader');
const txStatus = document.getElementById('tx-status');

// Feedo Treasury Address (should match backend)
const TREASURY_ADDRESS = "0x0000000000000000000000000000000000000000";

async function fetchBalances(address) {
    try {
        const res = await fetch(`/api/v1/tokenomics/${address}`);
        const data = await res.json();
        if (data && data.balances) {
            tokenBalanceSpan.innerText = data.balances.tokens;
            freeQueriesSpan.innerText = data.balances.free_search_queries;
        }
    } catch (e) {
        console.error("Failed to fetch balances", e);
    }
}

connectBtn.addEventListener('click', async () => {
    if (typeof window.ethereum !== 'undefined') {
        try {
            await window.ethereum.request({ method: 'eth_requestAccounts' });
            const provider = new ethers.providers.Web3Provider(window.ethereum);
            const signer = provider.getSigner();
            userAddress = await signer.getAddress();
            
            connectBtn.style.display = 'none';
            dashboard.style.display = 'block';
            walletAddressSpan.innerText = userAddress.substring(0, 6) + "..." + userAddress.substring(38);
            
            await fetchBalances(userAddress);
        } catch (error) {
            alert("User rejected connection or error occurred.");
            console.error(error);
        }
    } else {
        alert("Please install MetaMask to use the Feedo Protocol Dashboard.");
    }
});

showTopupBtn.addEventListener('click', () => {
    topUpSection.style.display = 'block';
    showTopupBtn.style.display = 'none';
});

submitTxBtn.addEventListener('click', async () => {
    if (!userAddress) return;
    
    const amount = depositAmount.value;
    if (amount <= 0) {
        alert("Please enter a valid amount");
        return;
    }

    try {
        submitTxBtn.disabled = true;
        loader.style.display = 'block';
        txStatus.innerText = "Please confirm the transaction in MetaMask...";
        
        const provider = new ethers.providers.Web3Provider(window.ethereum);
        const signer = provider.getSigner();
        
        const tx = await signer.sendTransaction({
            to: TREASURY_ADDRESS,
            value: ethers.utils.parseEther(amount.toString())
        });
        
        txStatus.innerText = "Transaction submitted! Waiting for network confirmation...";
        await tx.wait(); // Wait for it to be mined
        
        txStatus.innerText = "Transaction confirmed! Verifying with Feedo Node...";
        
        // Call backend API to verify
        const verifyRes = await fetch('/api/v1/tokenomics/verify_deposit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                tx_hash: tx.hash,
                wallet_address: userAddress
            })
        });
        
        const verifyData = await verifyRes.json();
        if (verifyRes.ok) {
            txStatus.style.color = "var(--accent-color)";
            txStatus.innerText = "Success! " + verifyData.message;
            if (verifyData.balances) {
                tokenBalanceSpan.innerText = verifyData.balances.tokens;
                freeQueriesSpan.innerText = verifyData.balances.free_search_queries;
            }
        } else {
            txStatus.style.color = "red";
            txStatus.innerText = "Verification failed: " + (verifyData.detail || "Unknown error");
        }
        
    } catch (e) {
        console.error(e);
        txStatus.style.color = "red";
        txStatus.innerText = "Error: " + (e.message || "Transaction failed");
    } finally {
        submitTxBtn.disabled = false;
        loader.style.display = 'none';
    }
});
