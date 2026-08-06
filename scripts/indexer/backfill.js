import fs from 'fs';
import path from 'path';
import axios from 'axios';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function backfill() {
  const filePath = path.join(__dirname, 'indexed_sites.md');
  const content = fs.readFileSync(filePath, 'utf-8');
  const blocks = content.split('### ').slice(1);
  
  const sites = blocks.map(block => {
    const domainMatch = block.match(/\[([^\]]+\.feedo)\]/);
    const feedoDomain = domainMatch ? domainMatch[1] : 'unknown.feedo';
    
    const origMatch = block.match(/\*\*Original Domain:\*\* \[([^\]]+)\]/);
    const origDomain = origMatch ? origMatch[1] : feedoDomain;
    
    const cidMatch = block.match(/\*\*CID:\*\* `([^`]+)`/);
    const cid = cidMatch ? cidMatch[1] : 'unknown';
    
    return {
      title: origDomain,
      domain: feedoDomain,
      cid: cid,
      description: `Decentralized build for ${origDomain}. Indexed and archived on the Feedo Network.`
    };
  });

  console.log(`Found ${sites.length} sites. Pushing to VPS node...`);
  
  let success = 0;
  for (const site of sites) {
    if (site.cid === 'unknown') continue;
    
    try {
      await axios.post('https://api.feedo.ink/index_document', {
        hash_id: site.cid,
        item_type: 'website',
        text: `${site.title} ${site.description} decentralized defi protocol`,
        metadata: {
          title: site.title,
          domain: site.domain,
          description: site.description
        }
      });
      success++;
      process.stdout.write(`\rSuccessfully pushed ${success}/${sites.length}`);
    } catch (e) {
      console.error(`\nFailed to push ${site.domain}:`, e.message);
    }
  }
  console.log('\nBackfill complete!');
}

backfill().catch(console.error);
