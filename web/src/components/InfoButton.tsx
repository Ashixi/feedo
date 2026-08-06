'use client';

import { useState } from 'react';

export default function InfoButton() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="absolute top-6 right-6 z-50">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="w-10 h-10 rounded-full border border-[#333] bg-[#111] text-gray-400 hover:text-white flex items-center justify-center transition-colors"
      >
        ?
      </button>

      {isOpen && (
        <div className="absolute top-12 right-0 mt-2 w-72 p-4 bg-[#111] border border-[#333] rounded-lg shadow-xl animate-in fade-in slide-in-from-top-2">
          <p className="text-sm text-gray-300">
            Feedo is an alternative layer of the internet. We do not claim any rights to the decentralized applications indexed here. 
            This is a neutral search engine and rendering protocol for Web3.
          </p>
        </div>
      )}
    </div>
  );
}
