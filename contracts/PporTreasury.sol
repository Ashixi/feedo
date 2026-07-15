// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IERC20 {
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
}

/**
 * @title PporTreasury
 * @dev Цей смарт-контракт виступає в ролі казни (Treasury) для Feedo мережі на базі PPoR консенсусу.
 * Використовує токен USDT (або інший ERC20).
 * Валідатори (комітет з 21 ноди) керують казною через мультипідписи.
 */
contract PporTreasury {
    address public owner;
    IERC20 public usdt;

    uint256 public constant PROTOCOL_FEE_PERCENTAGE = 5;
    uint256 public constant NODE_DEPOSIT_AMOUNT = 1 * 10**6; // 1 USDT (якщо 6 decimals)

    // Поточний комітет валідаторів
    address[] public committee;
    mapping(address => bool) public isCommitteeMember;
    
    // Захист від Replay атак для мультипідписів
    uint256 public nextNonce;

    // Депозити нод (Anti-Sybil)
    mapping(address => uint256) public nodeDeposits;

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
    
    // Допоміжна функція для хешування дії
    function getMessageHash(bytes32 actionHash, uint256 nonce) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(actionHash, nonce));
    }
    
    // Додає стандартний Ethereum префікс
    function getEthSignedMessageHash(bytes32 _messageHash) public pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", _messageHash));
    }
    
    /**
     * @dev Перевіряє масив підписів.
     * Підписи мають бути відсортовані за адресою підписанта за зростанням, щоб уникнути дублікатів.
     */
    function verifySignatures(bytes32 dataHash, bytes[] memory signatures) internal view returns (bool) {
        uint256 requiredSignatures = (committee.length * 2) / 3 + 1; // 2/3 + 1 (наприклад 15 з 21)
        require(signatures.length >= requiredSignatures, "Not enough signatures");
        
        bytes32 ethSignedHash = getEthSignedMessageHash(dataHash);
        address lastSigner = address(0);
        
        for (uint i = 0; i < signatures.length; i++) {
            address signer = recoverSigner(ethSignedHash, signatures[i]);
            
            require(isCommitteeMember[signer], "Invalid signer");
            // Гарантуємо унікальність та відсортованість
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

    /**
     * @dev Реєстрація ноди через лок депозиту
     */
    function registerNode() external {
        require(nodeDeposits[msg.sender] == 0, "Already registered");
        require(usdt.transferFrom(msg.sender, address(this), NODE_DEPOSIT_AMOUNT), "Transfer failed");
        
        nodeDeposits[msg.sender] = NODE_DEPOSIT_AMOUNT;
        emit NodeRegistered(msg.sender, NODE_DEPOSIT_AMOUNT);
    }

    /**
     * @dev Клієнт платить за послугу. 5% йде власнику, 95% залишається в пулі.
     */
    function payForService(bytes32 serviceHash, uint256 amount) external {
        require(amount > 0, "Amount must be > 0");
        
        uint256 protocolFee = (amount * PROTOCOL_FEE_PERCENTAGE) / 100;
        uint256 poolAmount = amount - protocolFee;
        
        // Переказ комісії протоколу власнику
        if (protocolFee > 0) {
            require(usdt.transferFrom(msg.sender, owner, protocolFee), "Fee transfer failed");
        }
        
        // Переказ пулу винагород на баланс контракту
        if (poolAmount > 0) {
            require(usdt.transferFrom(msg.sender, address(this), poolAmount), "Pool transfer failed");
        }
        
        emit PaymentReceived(msg.sender, serviceHash, poolAmount, protocolFee);
    }

    /**
     * @dev Мультипідпис: виведення накопичених коштів нодою
     */
    function withdraw(address to, uint256 amount, bytes[] memory signatures) external {
        bytes32 actionHash = keccak256(abi.encodePacked("WITHDRAW", to, amount));
        bytes32 messageHash = getMessageHash(actionHash, nextNonce);
        
        require(verifySignatures(messageHash, signatures), "Signature verification failed");
        
        nextNonce++;
        require(usdt.transfer(to, amount), "Transfer failed");
        
        emit Withdrawn(to, amount, nextNonce - 1);
    }

    /**
     * @dev Мультипідпис: оновлення комітету валідаторів на наступну епоху
     */
    function updateCommittee(address[] memory newCommittee, bytes[] memory signatures) external {
        require(newCommittee.length > 0, "Empty new committee");
        
        // Хешуємо адреси нового комітету
        bytes32 actionHash = keccak256(abi.encodePacked("UPDATE_COMMITTEE", abi.encode(newCommittee)));
        bytes32 messageHash = getMessageHash(actionHash, nextNonce);
        
        require(verifySignatures(messageHash, signatures), "Signature verification failed");
        
        nextNonce++;
        
        // Видаляємо старий комітет
        for (uint i = 0; i < committee.length; i++) {
            isCommitteeMember[committee[i]] = false;
        }
        
        // Встановлюємо новий комітет
        delete committee;
        for (uint i = 0; i < newCommittee.length; i++) {
            require(!isCommitteeMember[newCommittee[i]], "Duplicate in new committee array");
            committee.push(newCommittee[i]);
            isCommitteeMember[newCommittee[i]] = true;
        }
        
        emit CommitteeUpdated(newCommittee, nextNonce - 1);
    }
}
