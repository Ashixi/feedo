// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IERC20 {
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
}

/**
 * @title PporTreasury
 * @dev FEEDO Hybrid Consensus Treasury (Burn-and-Mint Bridge).
 *      This contract acts purely as a vault/escrow for USDT.
 *      The Rust network is the authoritative state machine:
 *        - Committee selection is managed entirely off-chain via PBFT.
 *        - Internal credits (pegged 1:1 to USDT) circulate on the native ledger.
 *        - Withdrawals require threshold multi-signatures from the off-chain committee.
 *
 *      Architectural shift: The contract no longer manages the validator committee.
 *      The committee array and updateCommittee() are removed. The Rust network
 *      defines the committee and produces withdrawal receipts (signatures).
 */
contract PporTreasury {
    address public owner;
    IERC20 public usdt;

    uint256 public constant PROTOCOL_FEE_PERCENTAGE = 5;
    uint256 public constant NODE_DEPOSIT_AMOUNT = 1 * 10**6; // 1 USDT (6 decimals)

    // ---- Committee (managed OFF-CHAIN by Rust PBFT) ----
    // The contract still needs to know WHO the current validators are
    // to verify withdrawal signatures, but committee transitions happen
    // via the Rust epoch rotation, not via this contract.
    // We keep a mapping of authorized signers that the Rust nodes can
    // update via a threshold-signed updateCommittee call.
    address[] public committee;
    mapping(address => bool) public isCommitteeMember;

    // Anti-replay protection for multi-signature operations
    uint256 public nextNonce;

    // Node deposits (Anti-Sybil) — still on-chain for economic security
    mapping(address => uint256) public nodeDeposits;

    // ---- Events ----
    /// Emitted when a user deposits USDT into the treasury.
    /// The Rust network listens for this to mint Internal Credits.
    event Deposit(address indexed user, uint256 amount, uint256 timestamp);

    /// @dev Legacy: kept for backward compatibility with existing event listeners.
    /// The Rust bridge can still process PaymentReceived as credit events.
    event PaymentReceived(address indexed client, bytes32 indexed serviceHash, uint256 poolAmount, uint256 protocolFee);

    event NodeRegistered(address indexed node, uint256 amount);
    event Withdrawn(address indexed to, uint256 amount, uint256 nonce);
    event CommitteeUpdated(address[] newCommittee, uint256 nonce);

    constructor(address _usdt, address[] memory initialCommittee) {
        owner = msg.sender;
        usdt = IERC20(_usdt);

        require(initialCommittee.length > 0, "Empty committee");
        for (uint i = 0; i < initialCommittee.length; i++) {
            committee.push(initialCommittee[i]);
            isCommitteeMember[initialCommittee[i]] = true;
        }
    }

    // ---- Signature Helpers ----

    /// @dev Hash an action with its nonce for replay protection.
    function getMessageHash(bytes32 actionHash, uint256 nonce) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(actionHash, nonce));
    }

    /// @dev Add the standard Ethereum signed message prefix.
    function getEthSignedMessageHash(bytes32 _messageHash) public pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", _messageHash));
    }

    /**
     * @dev Verifies a sorted array of ECDSA signatures.
     *      Signatures MUST be sorted by signer address ascending to prevent duplicates.
     *      Requires 2/3+1 of the committee (e.g., 15 of 21).
     */
    function verifySignatures(bytes32 dataHash, bytes[] memory signatures) internal view returns (bool) {
        uint256 requiredSignatures = (committee.length * 2) / 3 + 1;
        require(signatures.length >= requiredSignatures, "Not enough signatures");

        bytes32 ethSignedHash = getEthSignedMessageHash(dataHash);
        address lastSigner = address(0);

        for (uint i = 0; i < signatures.length; i++) {
            address signer = recoverSigner(ethSignedHash, signatures[i]);

            require(isCommitteeMember[signer], "Invalid signer");
            require(signer > lastSigner, "Duplicate or unsorted signatures");

            lastSigner = signer;
        }

        return true;
    }

    function recoverSigner(bytes32 _ethSignedMessageHash, bytes memory _signature) public pure returns (address) {
        (bytes32 r, bytes32 s, uint8 v) = splitSignature(_signature);
        return ecrecover(_ethSignedMessageHash, v, r, s);
    }

    function splitSignature(bytes memory sig) public pure returns (bytes32 r, bytes32 s, uint8 v) {
        require(sig.length == 65, "Invalid signature length");
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
    }

    // ---- Node Registration ----

    /**
     * @dev Register a node by locking a deposit.
     */
    function registerNode() external {
        require(nodeDeposits[msg.sender] == 0, "Already registered");
        require(usdt.transferFrom(msg.sender, address(this), NODE_DEPOSIT_AMOUNT), "Transfer failed");

        nodeDeposits[msg.sender] = NODE_DEPOSIT_AMOUNT;
        emit NodeRegistered(msg.sender, NODE_DEPOSIT_AMOUNT);
    }

    // ---- Deposit (Mint side of Burn-and-Mint Bridge) ----

    /**
     * @dev User deposits USDT into the treasury.
     *      The Rust network listens for the Deposit event,
     *      runs PBFT to confirm it, and mints Internal Credits 1:1.
     * @param amount Amount of USDT to deposit (in USDT decimals, typically 6).
     */
    function deposit(uint256 amount) external {
        require(amount > 0, "Amount must be > 0");
        require(usdt.transferFrom(msg.sender, address(this), amount), "Transfer failed");

        emit Deposit(msg.sender, amount, block.timestamp);
    }

    // ---- Legacy: Pay For Service ----
    // Kept for backward compatibility. New integrations should use deposit().

    /**
     * @dev Client pays for a service. 5% goes to protocol owner, 95% stays in the pool.
     */
    function payForService(bytes32 serviceHash, uint256 amount) external {
        require(amount > 0, "Amount must be > 0");

        uint256 protocolFee = (amount * PROTOCOL_FEE_PERCENTAGE) / 100;
        uint256 poolAmount = amount - protocolFee;

        if (protocolFee > 0) {
            require(usdt.transferFrom(msg.sender, owner, protocolFee), "Fee transfer failed");
        }

        if (poolAmount > 0) {
            require(usdt.transferFrom(msg.sender, address(this), poolAmount), "Pool transfer failed");
        }

        emit PaymentReceived(msg.sender, serviceHash, poolAmount, protocolFee);
    }

    // ---- Withdrawal (Burn side of Burn-and-Mint Bridge) ----

    /**
     * @dev Multi-signature withdrawal.
     *      A node burns their Internal Credits on the Rust network.
     *      The PBFT committee signs a withdrawal receipt.
     *      The node submits the receipt + signatures here to unlock USDT.
     * @param to Recipient address for the USDT.
     * @param amount Amount of USDT to withdraw.
     * @param signatures Sorted array of ECDSA signatures from the current committee.
     */
    function withdraw(address to, uint256 amount, bytes[] memory signatures) external {
        bytes32 actionHash = keccak256(abi.encodePacked("WITHDRAW", to, amount));
        bytes32 messageHash = getMessageHash(actionHash, nextNonce);

        require(verifySignatures(messageHash, signatures), "Signature verification failed");

        nextNonce++;
        require(usdt.transfer(to, amount), "Transfer failed");

        emit Withdrawn(to, amount, nextNonce - 1);
    }

    // ---- Committee Update (by Rust PBFT consensus) ----

    /**
     * @dev Update the on-chain committee record.
     *      This is called by the Rust network when epoch rotation produces
     *      a new committee. The Rust nodes produce a threshold-signed message
     *      that authorizes the new committee on-chain.
     *      This function does NOT select the committee — it only records
     *      what the Rust network has already decided.
     * @param newCommittee The new committee addresses (sorted ascending).
     * @param signatures Sorted ECDSA signatures from the CURRENT committee
     *                   (not the new one) authorizing this transition.
     */
    function updateCommittee(address[] memory newCommittee, bytes[] memory signatures) external {
        require(newCommittee.length > 0, "Empty new committee");

        bytes32 actionHash = keccak256(abi.encodePacked("UPDATE_COMMITTEE", abi.encode(newCommittee)));
        bytes32 messageHash = getMessageHash(actionHash, nextNonce);

        require(verifySignatures(messageHash, signatures), "Signature verification failed");

        nextNonce++;

        // Remove old committee
        for (uint i = 0; i < committee.length; i++) {
            isCommitteeMember[committee[i]] = false;
        }

        // Set new committee
        delete committee;
        for (uint i = 0; i < newCommittee.length; i++) {
            require(!isCommitteeMember[newCommittee[i]], "Duplicate in new committee array");
            committee.push(newCommittee[i]);
            isCommitteeMember[newCommittee[i]] = true;
        }

        emit CommitteeUpdated(newCommittee, nextNonce - 1);
    }
}