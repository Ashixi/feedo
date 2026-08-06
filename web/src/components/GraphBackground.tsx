'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  id: number;
}

interface Signal {
  from: Node;
  to: Node;
  progress: number;
  speed: number;
}

export default function GraphBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    if (pathname.startsWith('/view')) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let nodes: Node[] = [];
    let signals: Signal[] = [];
    let edges: { i: number; j: number }[] = [];
    
    const numNodes = 40;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', resize);
    resize();

    // Initialize nodes
    for (let i = 0; i < numNodes; i++) {
      nodes.push({
        id: i,
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
      });
    }

    // Initialize permanent random edges
    for (let i = 0; i < nodes.length; i++) {
      // Connect each node to 2-3 other random nodes
      const numConnections = 2 + Math.floor(Math.random() * 2);
      for (let c = 0; c < numConnections; c++) {
        const target = Math.floor(Math.random() * nodes.length);
        if (target !== i) {
          // Check if edge already exists to prevent duplicates
          const exists = edges.some(e => (e.i === i && e.j === target) || (e.i === target && e.j === i));
          if (!exists) {
            edges.push({ i, j: target });
          }
        }
      }
    }

    const drawRoundedRect = (ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) => {
      ctx.beginPath();
      ctx.moveTo(x + radius, y);
      ctx.lineTo(x + width - radius, y);
      ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
      ctx.lineTo(x + width, y + height - radius);
      ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
      ctx.lineTo(x + radius, y + height);
      ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
      ctx.lineTo(x, y + radius);
      ctx.quadraticCurveTo(x, y, x + radius, y);
      ctx.closePath();
      ctx.fill();
    };

    const render = () => {
      ctx.fillStyle = '#050505';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Move nodes
      nodes.forEach(node => {
        node.x += node.vx;
        node.y += node.vy;
        if (node.x < 0 || node.x > canvas.width) node.vx *= -1;
        if (node.y < 0 || node.y > canvas.height) node.vy *= -1;
      });

      // Draw edges and spawn signals
      ctx.lineWidth = 1;
      ctx.strokeStyle = `rgba(100, 100, 100, 0.15)`;
      
      edges.forEach(edge => {
        const n1 = nodes[edge.i];
        const n2 = nodes[edge.j];
        
        ctx.beginPath();
        ctx.moveTo(n1.x, n1.y);
        ctx.lineTo(n2.x, n2.y);
        ctx.stroke();

        // Randomly spawn a signal on this edge
        if (Math.random() < 0.002) {
          // Check if this node is already emitting a signal
          const isEmitting = signals.some(s => s.from.id === n1.id);
          if (!isEmitting) {
            signals.push({
              from: n1,
              to: n2,
              progress: 0,
              speed: 0.001 + Math.random() * 0.002
            });
          }
        }
      });

      // Draw and update signals
      for (let i = signals.length - 1; i >= 0; i--) {
        const s = signals[i];
        s.progress += s.speed;
        if (s.progress >= 1) {
          signals.splice(i, 1);
          continue;
        }

        const currentX = s.from.x + (s.to.x - s.from.x) * s.progress;
        const currentY = s.from.y + (s.to.y - s.from.y) * s.progress;

        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(currentX, currentY, 2, 0, Math.PI * 2);
        ctx.fill();
        
        // Add a slight glow
        ctx.shadowBlur = 10;
        ctx.shadowColor = '#ffffff';
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // Draw nodes (rounded squares)
      nodes.forEach(node => {
        ctx.fillStyle = '#333333';
        const size = 12;
        drawRoundedRect(ctx, node.x - size/2, node.y - size/2, size, size, 3);
      });

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      window.removeEventListener('resize', resize);
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
    };
  }, [pathname]);

  if (pathname.startsWith('/view')) return null;

  return (
    <canvas
      ref={canvasRef}
      className="fixed top-0 left-0 w-full h-full -z-10 bg-black pointer-events-none"
    />
  );
}
