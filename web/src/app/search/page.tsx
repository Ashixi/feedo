import Link from 'next/link';

const NODES = [
  'http://178.18.253.94:8000',
  'http://95.111.245.68:8000'
];

const CONSENSUS_NODES = [
  'http://95.111.245.68:3000',
  'http://178.18.253.94:3000'
];

async function fetchFromNodes(query: string) {
  for (const node of NODES) {
    try {
      const q = query ? encodeURIComponent(query) : 'defi'; // fallback query if empty
      const url = `${node}/query?text=${q}&limit=50&item_type=website`;
      const res = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
      if (!res.ok) continue;
      
      const data = await res.json();
      if (data && data.results) {
        const mappedResults = await Promise.all(data.results.map(async (r: any) => {
          let domain = r.metadata?.domain;
          if (!domain) {
            for (const cNode of CONSENSUS_NODES) {
              try {
                const resolveRes = await fetch(`${cNode}/resolve_cid/${r.hash_id}`, { signal: AbortSignal.timeout(2000) });
                if (resolveRes.ok) {
                  const resolved = await resolveRes.json();
                  if (resolved) {
                    domain = resolved;
                    break;
                  }
                }
              } catch (e) {
                // Ignore resolve errors and try the next node
              }
            }
          }
          domain = domain || 'unknown.feedo';

          return {
            title: r.metadata?.title || domain || r.hash_id,
            domain: domain,
            cid: r.hash_id,
            description: r.metadata?.description || r.text?.substring(0, 200) || 'Decentralized build for this protocol. Indexed and archived on the Feedo Network.'
          };
        }));
        return mappedResults;
      }
    } catch (e) {
      console.error(`Failed to fetch from ${node}:`, e);
    }
  }
  return [];
}

export default async function SearchResults({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const resolvedParams = await searchParams;
  const query = (typeof resolvedParams.q === 'string' ? resolvedParams.q : '') || '';
  const results = await fetchFromNodes(query);

  return (
    <div className="min-h-screen bg-transparent pt-8 px-6 md:px-24 w-full max-w-5xl">
      {/* Top Search Bar (Mini version) */}
      <div className="flex items-center gap-8 mb-12">
        <Link href="/" className="text-2xl font-bold tracking-widest text-white/90">
          FEEDO
        </Link>
        <form action="/search" method="GET" className="flex-1 max-w-2xl relative">
          <input
            type="text"
            name="q"
            defaultValue={query}
            className="w-full bg-[#111111]/80 backdrop-blur-md border border-[#333] rounded-full px-5 py-3 text-white placeholder-gray-500 outline-none focus:border-white/50 transition-all"
          />
          <button type="submit" className="hidden">Search</button>
        </form>
      </div>

      {/* Results List */}
      <div className="flex flex-col gap-10 pb-20">
        <p className="text-gray-500 text-sm">About {results.length} results found in Feedo Network</p>
        
        {results.map((res, i) => (
          <div key={i} className="flex flex-col gap-1 max-w-2xl group animate-in fade-in slide-in-from-bottom-4" style={{ animationDelay: `${Math.min(i * 50, 1000)}ms` }}>
            <div className="text-sm text-gray-400 font-mono">
              {res.domain} <span className="text-gray-600 ml-2">CID: {res.cid.substring(0, 12)}...{res.cid.substring(res.cid.length - 8)}</span>
            </div>
            <Link 
              href={`/view?domain=${res.domain}&cid=${res.cid}`}
              className="text-2xl text-blue-400 group-hover:underline decoration-blue-400 cursor-pointer"
            >
              {res.title}
            </Link>
            <p className="text-gray-300 mt-1 leading-relaxed">
              {res.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
