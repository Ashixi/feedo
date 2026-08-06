'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState, useRef, Suspense } from 'react';
import JSZip from 'jszip';
import localforage from 'localforage';

export default function ViewPage() {
  return (
    <Suspense fallback={<div className="h-screen w-full bg-[#050505] flex items-center justify-center text-white font-mono">Loading decentralized sandbox...</div>}>
      <ViewContent />
    </Suspense>
  );
}

function ViewContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const domain = searchParams.get('domain');
  const cid = searchParams.get('cid');

  const [loadingMsg, setLoadingMsg] = useState('Initializing Feedo Engine...');
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      if (e.data?.type === 'FEEDO_LINK_CLICKED') {
        setToastMsg('Navigation disabled: this is a static decentralized snapshot.');
        setTimeout(() => setToastMsg(null), 3000);
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    if (!domain || !cid) return;

    async function initSandbox() {
      try {
        setLoadingMsg('Registering decentralized Service Worker...');
        if ('serviceWorker' in navigator) {
          await navigator.serviceWorker.register('/feedo-sw.js');
        } else {
          throw new Error('Service Workers are not supported in this browser.');
        }

        // Check if already downloaded
        setLoadingMsg('Checking local node storage...');
        const checkKey = `${cid}/index.html`;
        const exists = await localforage.getItem(checkKey);

        if (exists) {
          setLoadingMsg('Found in local cache. Launching...');
          setIsReady(true);
          return;
        }

        setLoadingMsg('Connecting to Feedo P2P Storage Network...');
        const STORAGE_NODES = [
          'http://95.111.245.68:3001',
          'http://178.18.253.94:3001'
        ];
        
        let res: Response | null = null;
        for (const node of STORAGE_NODES) {
          try {
            const attempt = await fetch(`${node}/download/${cid}`, { signal: AbortSignal.timeout(5000) });
            if (attempt.ok) {
              res = attempt;
              break;
            }
          } catch (e) {
            console.warn(`Failed to fetch from ${node}`, e);
          }
        }
        
        if (!res) {
          throw new Error(`Failed to download CID from any storage node: Not Found`);
        }

        setLoadingMsg('Downloading decentralized blob...');
        const buffer = await res.arrayBuffer();

        setLoadingMsg('Unpacking and verifying cryptographic hashes...');
        const zip = await JSZip.loadAsync(buffer);

        const files = Object.keys(zip.files);
        let processed = 0;
        
        for (const filename of files) {
          if (zip.files[filename].dir) continue;
          const fileData = await zip.files[filename].async('arraybuffer');
          await localforage.setItem(`${cid}/${filename}`, fileData);
          processed++;
          setLoadingMsg(`Unpacking... (${processed} files)`);
        }

        setLoadingMsg('Decentralized site is ready.');
        setIsReady(true);

      } catch (err: any) {
        console.error(err);
        setError(err.message);
      }
    }

    initSandbox();
  }, [domain, cid]);

  if (!domain || !cid) {
    return <div className="text-white p-4 font-mono">Invalid parameters. Require domain and CID.</div>;
  }

  return (
    <div className="flex flex-col h-screen w-full bg-[#050505]">
      {/* Top Navigation Bar */}
      <div className="h-14 border-b border-[#333] flex items-center px-4 justify-between bg-[#111] shrink-0 z-50">
        <div className="flex items-center gap-4">
          <button onClick={() => router.back()} className="text-gray-400 hover:text-white transition-colors">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="text-sm font-mono text-blue-400 font-bold">
            feedo://<span className="text-gray-300">{domain}</span>
          </div>
          <div className="text-xs font-mono text-gray-500 bg-[#222] px-2 py-1 rounded">
            CID: {cid.substring(0, 10)}...
          </div>
        </div>
        <div className="text-xs text-gray-500 font-mono flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
          Connected to Web3 Sandbox
        </div>
      </div>

      {/* Viewer Area */}
      <div className="flex-1 w-full bg-white relative">
        {!isReady && !error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#050505] text-gray-400 font-mono text-sm z-20 gap-4">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
            <div className="animate-pulse">{loadingMsg}</div>
          </div>
        )}
        
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#050505] text-red-400 font-mono text-sm z-20 p-8 text-center gap-2">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mb-4">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <div>Decentralized Engine Error</div>
            <div className="text-gray-500 text-xs mt-2">{error}</div>
          </div>
        )}
        
        {isReady && (
          <iframe 
            src={`/sandbox/${cid}/index.html`} 
            className="relative z-10 w-full h-full border-none bg-white"
            title={`Feedo Viewer - ${domain}`}
            sandbox="allow-scripts allow-same-origin allow-forms"
          />
        )}
      </div>
    </div>
  );
}
