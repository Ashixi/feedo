// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title FeedoPayment
 * @dev This contract handles micro-transactions and auto-claims for the Feedo protocol.
 * The PBFT leader periodically updates the Merkle Root representing the accumulated earnings of all nodes.
 * Nodes can then claim their funds locally, paying for their own gas.
 */
contract FeedoPayment {
    address public owner;
    address public protocolWallet;
    uint256 public constant PROTOCOL_FEE_PERCENTAGE = 5;
    
    bytes32 public currentMerkleRoot;
    
    // Mapping to track how much each address has already claimed
    // so they can't double-claim the same balance.
    mapping(address => uint256) public claimedAmounts;

    // A list of trusted PBFT leaders or validators allowed to update the root
    mapping(address => bool) public isValidator;

    event PaymentReceived(address indexed client, bytes32 indexed serviceHash, uint256 amount);
    event MerkleRootUpdated(bytes32 newRoot, address validator);
    event Claimed(address indexed node, uint256 amount);
    event Slashed(address indexed node, uint256 slashedAmount);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this");
        _;
    }

    modifier onlyValidator() {
        require(isValidator[msg.sender], "Only validator can call this");
        _;
    }

    constructor() {
        owner = msg.sender;
        protocolWallet = msg.sender; // За замовчуванням гаманець протоколу = власнику
        isValidator[msg.sender] = true; // Owner is initially a validator
    }

    function setProtocolWallet(address _newWallet) external onlyOwner {
        protocolWallet = _newWallet;
    }

    function addValidator(address _validator) external onlyOwner {
        isValidator[_validator] = true;
    }

    function removeValidator(address _validator) external onlyOwner {
        isValidator[_validator] = false;
    }

    // Client pays for a service (e.g. AI Compute or Storage)
    function payForService(bytes32 serviceHash) external payable {
        require(msg.value > 0, "Amount must be greater than 0");
        
        // 1. Calculate 5% protocol fee
        uint256 protocolFee = (msg.value * PROTOCOL_FEE_PERCENTAGE) / 100;
        
        // 2. Transfer fee directly to the protocol wallet
        if (protocolFee > 0) {
            (bool success, ) = protocolWallet.call{value: protocolFee}("");
            require(success, "Protocol fee transfer failed");
        }

        // 3. The remaining 95% stays in the contract to be claimed by nodes
        uint256 poolAmount = msg.value - protocolFee;
        
        emit PaymentReceived(msg.sender, serviceHash, poolAmount);
    }

    // PBFT Leader updates the Merkle Root representing the total cumulative earnings of each node
    function updateMerkleRoot(bytes32 newRoot) external onlyValidator {
        currentMerkleRoot = newRoot;
        emit MerkleRootUpdated(newRoot, msg.sender);
    }

    // Helper to verify Merkle Proof (equivalent to OpenZeppelin's MerkleProof.verify)
    function verifyProof(bytes32[] memory proof, bytes32 root, bytes32 leaf) internal pure returns (bool) {
        bytes32 computedHash = leaf;

        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 proofElement = proof[i];

            if (computedHash <= proofElement) {
                // Hash(current computed hash + current element of the proof)
                computedHash = keccak256(abi.encodePacked(computedHash, proofElement));
            } else {
                // Hash(current element of the proof + current computed hash)
                computedHash = keccak256(abi.encodePacked(proofElement, computedHash));
            }
        }

        return computedHash == root;
    }

    // Node claims its earned balance using a Merkle Proof
    // `totalEarned` is the absolute total the node has earned so far.
    function claim(uint256 totalEarned, bytes32[] calldata merkleProof) external {
        // 1. Verify the merkle proof
        // We use double hashing for the leaf to prevent second preimage attacks (standard practice)
        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(msg.sender, totalEarned))));
        require(verifyProof(merkleProof, currentMerkleRoot, leaf), "Invalid Merkle proof");

        // 2. Calculate how much is owed (totalEarned - already claimed)
        uint256 amountOwed = totalEarned - claimedAmounts[msg.sender];
        require(amountOwed > 0, "Nothing to claim");
        require(address(this).balance >= amountOwed, "Insufficient contract balance");

        // 3. Update claimed amount
        claimedAmounts[msg.sender] = totalEarned;

        // 4. Transfer the MATIC
        (bool success, ) = msg.sender.call{value: amountOwed}("");
        require(success, "Transfer failed");

        emit Claimed(msg.sender, amountOwed);
    }

    // Slash (Burn) a node's balance if it misbehaved
    // In this pull-based model, slashing means the validator forces an update to the user's claimedAmount 
    // without actually sending them the funds, effectively "burning" their owed balance.
    function slash(address node, uint256 slashAmount) external onlyValidator {
        claimedAmounts[node] += slashAmount;
        emit Slashed(node, slashAmount);
    }
    
    // Admin function to withdraw funds if needed, or to fund the contract
    receive() external payable {}
}
