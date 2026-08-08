const { FeedoClient } = require('./dist/index.js');
const crypto = require('crypto');
const { ethers } = require('ethers');

async function main() {
    const size = 11 * 1024 * 1024;
    console.log('Generating ' + size + ' bytes...');
    const data = crypto.randomBytes(size);

    const privKey = '0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
    const client = new FeedoClient({ privateKey: privKey });

    console.log('Registering DID...');
    try {
        const wallet = new ethers.Wallet(privKey);
        const pubKey = wallet.signingKey.publicKey;
        await client.consensus.registerDid(pubKey, "dummy_sig");
        console.log('DID registered.');
    } catch (e) {
        console.log('DID might already be registered or error:', e.message);
    }

    console.log('Testing raw file upload (uploadFile)...');
    const t1 = Date.now();
    const hash = await client.storage.uploadFile(data, 'large_file.bin');
    console.log('Uploaded! Hash: ' + hash + ' in ' + (Date.now() - t1) + 'ms');

    console.log('Testing raw file download (downloadFile)...');
    const t2 = Date.now();
    const downloaded = await client.storage.downloadFile(hash);
    const downloadedBuf = Buffer.from(downloaded);
    console.log('Downloaded ' + downloadedBuf.byteLength + ' bytes in ' + (Date.now() - t2) + 'ms');
    
    if (downloadedBuf.equals(data)) {
        console.log('SUCCESS: Raw downloaded data matches original data!');
    } else {
        console.error('ERROR: Raw downloaded data DOES NOT match!');
    }

    console.log('\nTesting private E2EE upload...');
    const t3 = Date.now();
    const privHash = await client.uploadPrivateFile(data, undefined, false);
    console.log('Uploaded! Hash: ' + privHash + ' in ' + (Date.now() - t3) + 'ms');

    console.log('Testing private E2EE download...');
    const t4 = Date.now();
    const privDownloaded = await client.downloadPrivateFile(privHash);
    console.log('Downloaded ' + privDownloaded.byteLength + ' bytes in ' + (Date.now() - t4) + 'ms');
    
    if (privDownloaded.equals(data)) {
        console.log('SUCCESS: Private downloaded data matches original data!');
    } else {
        console.error('ERROR: Private downloaded data DOES NOT match!');
    }
}

main().catch(console.error);
