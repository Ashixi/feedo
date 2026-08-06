'use client';

import { useEffect, useRef } from 'react';

interface LoadingNode {
  x: number;
  y: number;
  id: number;
  connectedTo: number[];
  spawnedAt: number;
}

export default function LoadingGraph() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let startTime = performance.now();
    
    // Start with 1 center node
    const nodes: LoadingNode[] = [{
      id: 0,
      x: canvas.width / 2,
      y: canvas.height / 2,
      connectedTo: [],
      spawnedAt: startTime
    }];

    const spawnDelay = 400; // spawn new nodes every 400ms

    const resize = () => {
      canvas.width = 400;
      canvas.height = 400;
      if (nodes[0]) {
        nodes[0].x = canvas.width / 2;
        nodes[0].y = canvas.height / 2;
      }
    };
    resize();

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

    const render = (time: number) => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Spawn new nodes over time
      const expectedNodes = Math.min(1 + Math.floor((time - startTime) / spawnDelay), 15);
      if (nodes.length < expectedNodes) {
        const parentNode = nodes[Math.floor(Math.random() * nodes.length)];
        const angle = Math.random() * Math.PI * 2;
        const distance = 40 + Math.random() * 60;
        
        nodes.push({
          id: nodes.length,
          x: parentNode.x + Math.cos(angle) * distance,
          y: parentNode.y + Math.sin(angle) * distance,
          connectedTo: [parentNode.id],
          spawnedAt: time
        });
      }

      // Draw edges
      ctx.lineWidth = 1;
      nodes.forEach(node => {
        node.connectedTo.forEach(targetId => {
          const target = nodes[targetId];
          ctx.strokeStyle = '#555';
          ctx.beginPath();
          ctx.moveTo(node.x, node.y);
          ctx.lineTo(target.x, target.y);
          ctx.stroke();

          // Draw moving signal along the line
          const progress = ((time - node.spawnedAt) % 1000) / 1000;
          const currentX = node.x + (target.x - node.x) * progress;
          const currentY = node.y + (target.y - node.y) * progress;
          
          ctx.fillStyle = '#fff';
          ctx.beginPath();
          ctx.arc(currentX, currentY, 2, 0, Math.PI * 2);
          ctx.fill();
        });
      });

      // Draw nodes
      nodes.forEach(node => {
        // Fade in animation
        const age = time - node.spawnedAt;
        const opacity = Math.min(age / 500, 1);
        
        ctx.fillStyle = `rgba(150, 150, 150, ${opacity})`;
        const size = 12;
        drawRoundedRect(ctx, node.x - size/2, node.y - size/2, size, size, 3);
      });

      // Text below
      ctx.fillStyle = '#888';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Searching Feedo Network...', canvas.width / 2, canvas.height - 20);

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => cancelAnimationFrame(animationFrameId);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center animate-in fade-in duration-500">
      <canvas ref={canvasRef} style={{ width: 400, height: 400 }} />
    </div>
  );
}
