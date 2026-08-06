import axios from 'axios';
import scrape from 'website-scraper';
import pLimit from 'p-limit';
import { exec } from 'child_process';
import { promisify } from 'util';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

import puppeteer from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';
puppeteer.use(StealthPlugin());

const execAsync = promisify(exec);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

class StealthPuppeteerPlugin {
    constructor() { this.browser = null; }
    apply(registerAction) {
        registerAction('beforeStart', async () => {
            this.browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--disable-setuid-sandbox'] });
        });
        registerAction('afterResponse', async ({response}) => {
            const contentType = response.headers['content-type'];
            if (contentType && contentType.includes('text/html')) {
                const page = await this.browser.newPage();
                try {
                    await page.goto(response.url, { waitUntil: 'networkidle2', timeout: 30000 });
                } catch (e) {
                    console.error(`[Puppeteer] Error for ${response.url}:`, e.message);
                }
                const content = await page.content();
                await page.close();
                return { body: content, encoding: 'utf8' };
            }
            return response.body;
        });
        registerAction('afterFinish', () => this.browser && this.browser.close());
    }
}

// Configuration
const CONCURRENCY_LIMIT = 3;
const MAX_SITES = 3000; // Parse up to 3000 sites
const TEMP_DIR = path.join(__dirname, 'temp');

let successfulCount = 0;
const processedDomains = new Set();

// Ensure temp directory exists
if (!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR, { recursive: true });
}

async function fetchProtocols() {
    console.log('fetching protocols from DefiLlama...');
    const response = await axios.get('https://api.llama.fi/protocols');
    return response.data;
}

function extractDomain(urlStr) {
    try {
        const url = new URL(urlStr);
        let domain = url.hostname;
        if (domain.startsWith('www.')) {
            domain = domain.substring(4);
        }
        return domain;
    } catch (e) {
        return null;
    }
}

async function processSite(protocol, siteNumber) {
    if (!protocol.url) return;
    
    const domain = extractDomain(protocol.url);
    if (!domain) return;
    
    if (processedDomains.has(domain)) {
        console.log(`[${siteNumber}] [${domain}] Already processed (duplicate), skipping...`);
        return;
    }
    processedDomains.add(domain);
    
    const feedoDomain = `snapshot.${domain.substring(0, domain.lastIndexOf('.'))}.feedo`;
    const siteDir = path.join(TEMP_DIR, domain);
    
    console.log(`[${siteNumber}] [${domain}] Starting processing...`);
    
    try {
        // Step 1: Clean up old temp directory if exists
        if (fs.existsSync(siteDir)) {
            fs.rmSync(siteDir, { recursive: true, force: true });
        }
        
        // Step 2: Download the static build
        console.log(`[${domain}] Downloading build from ${protocol.url}...`);
        await scrape({
            urls: [protocol.url],
            directory: siteDir,
            sources: [
                { selector: 'img', attr: 'src' },
                { selector: 'link[rel="stylesheet"]', attr: 'href' }
                // JavaScript explicitly removed to prevent React hydration crashes in sandbox
            ],
            recursive: false,
            request: {
                timeout: 30000,
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'identity', // Forces servers to send raw, uncompressed files (fixes broken characters)
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1'
                }
            },
            plugins: [new StealthPuppeteerPlugin()]
        });
        
        // Step 3: Publish to Feedo Network using the CLI SDK
        console.log(`[${domain}] Publishing to Feedo as ${feedoDomain}...`);
        // Use the CLI script directly
        const cliPath = path.resolve(__dirname, '../../sdk/cli/dist/cli.js');
        const command = `node ${cliPath} deploy "${siteDir}" -d ${feedoDomain}`;
        
        const { stdout, stderr } = await execAsync(command, { timeout: 120000 });
        
        // Check if the CLI caught an error internally
        if (stdout.includes('Deployment failed') || stderr.includes('Deployment failed')) {
            throw new Error('CLI deployment failed internally');
        }
        
        console.log(`[${domain}] SUCCESS!`);
        
        // Extract CID from stdout
        const cidMatch = stdout.match(/CID:\s+([a-f0-9]+)/i);
        if (!cidMatch) {
            throw new Error('Could not find CID in CLI output');
        }
        const cid = cidMatch[1];
        
        successfulCount++;
        
        // Save to markdown log
        const mdLog = `### ${successfulCount}. [${feedoDomain}](https://gateway.feedo.ink/${feedoDomain})
- **Original Domain:** [${domain}](https://${domain})
- **CID:** \`${cid}\`
- **Web2 Gateway (Path):** [https://gateway.feedo.ink/${feedoDomain}](https://gateway.feedo.ink/${feedoDomain})
- **Web2 Gateway (Subdomain):** [https://${feedoDomain.replaceAll('.', '-')}.gateway.feedo.ink](https://${feedoDomain.replaceAll('.', '-')}.gateway.feedo.ink)

`;
        fs.appendFileSync(path.join(__dirname, 'indexed_sites.md'), mdLog);
        
    } catch (error) {
        console.error(`[${domain}] ERROR: ${error.message}`);
    } finally {
        // Step 4: Cleanup
        if (fs.existsSync(siteDir)) {
            fs.rmSync(siteDir, { recursive: true, force: true });
        }
    }
}

function loadCheckpoints() {
    const logFilePath = path.join(__dirname, 'indexed_sites.md');
    if (fs.existsSync(logFilePath)) {
        const content = fs.readFileSync(logFilePath, 'utf8');
        const matches = [...content.matchAll(/- \*\*Original Domain:\*\* \[([^\]]+)\]/g)];
        for (const match of matches) {
            processedDomains.add(match[1]);
        }
        // Also update successfulCount to be the max number in the file
        const countMatches = [...content.matchAll(/### (\d+)\./g)];
        if (countMatches.length > 0) {
            const counts = countMatches.map(m => parseInt(m[1], 10));
            successfulCount = Math.max(...counts);
        }
        console.log(`[Checkpoint] Resuming from ${processedDomains.size} already indexed sites...`);
    }
}

async function main() {
    loadCheckpoints();
    
    const protocols = await fetchProtocols();
    const targetProtocols = protocols.slice(0, MAX_SITES); // Take the first N sites
    
    console.log(`Starting indexer queue for ${targetProtocols.length} sites with concurrency ${CONCURRENCY_LIMIT}...`);
    
    const limit = pLimit(CONCURRENCY_LIMIT);
    
    const tasks = targetProtocols.map((protocol, index) => {
        return limit(() => processSite(protocol, index + 1));
    });
    
    await Promise.all(tasks);
    console.log('All done!');
}

main().catch(console.error);
