"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

export function ConversationField({ variant = "dashboard" }: { variant?: "auth" | "dashboard" }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = host.current;
    if (!container) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0, variant === "auth" ? 8.4 : 10.5);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.7));
    renderer.setClearAlpha(0);
    container.appendChild(renderer.domElement);

    const group = new THREE.Group();
    scene.add(group);
    const palette = variant === "auth" ? [0x25e7d0, 0x7c68ff, 0x66a8ff] : [0x18c9b5, 0x6c5ce7, 0x2f80ed];

    const particleCount = variant === "auth" ? 260 : 150;
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);
    for (let index = 0; index < particleCount; index++) {
      const turn = index * 0.32;
      const spread = 1.15 + (index % 17) * 0.075;
      positions[index * 3] = Math.cos(turn) * spread + (Math.random() - 0.5) * 0.8;
      positions[index * 3 + 1] = Math.sin(turn * 0.67) * spread * 0.72 + (Math.random() - 0.5) * 0.65;
      positions[index * 3 + 2] = (Math.random() - 0.5) * 3.6;
      const color = new THREE.Color(palette[index % palette.length]);
      colors[index * 3] = color.r; colors[index * 3 + 1] = color.g; colors[index * 3 + 2] = color.b;
    }
    const pointsGeometry = new THREE.BufferGeometry();
    pointsGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    pointsGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const pointsMaterial = new THREE.PointsMaterial({ size: variant === "auth" ? 0.055 : 0.04, vertexColors: true, transparent: true, opacity: 0.78, depthWrite: false });
    const points = new THREE.Points(pointsGeometry, pointsMaterial);
    group.add(points);

    const waveMaterial = new THREE.LineBasicMaterial({ color: palette[0], transparent: true, opacity: 0.42 });
    const waveMaterialTwo = new THREE.LineBasicMaterial({ color: palette[1], transparent: true, opacity: 0.3 });
    const createWave = (phase: number, material: THREE.LineBasicMaterial) => {
      const vertices: THREE.Vector3[] = [];
      for (let index = 0; index <= 180; index++) {
        const x = (index / 180 - 0.5) * 8;
        const envelope = Math.exp(-Math.pow(x / 3.2, 2));
        vertices.push(new THREE.Vector3(x, Math.sin(x * 2.15 + phase) * envelope * 1.05, Math.cos(x * 0.7 + phase) * 0.48));
      }
      const geometry = new THREE.BufferGeometry().setFromPoints(vertices);
      const line = new THREE.Line(geometry, material);
      group.add(line);
      return line;
    };
    const waveOne = createWave(0, waveMaterial);
    const waveTwo = createWave(Math.PI, waveMaterialTwo);
    waveTwo.rotation.z = 0.38;

    const haloGeometry = new THREE.TorusGeometry(2.1, 0.008, 6, 130);
    const haloMaterial = new THREE.MeshBasicMaterial({ color: palette[2], transparent: true, opacity: 0.25 });
    const halo = new THREE.Mesh(haloGeometry, haloMaterial);
    halo.rotation.x = 1.15; halo.rotation.y = 0.45;
    group.add(halo);

    let pointerX = 0; let pointerY = 0; let frame = 0;
    const onPointer = (event: PointerEvent) => {
      pointerX = (event.clientX / window.innerWidth - 0.5) * 0.16;
      pointerY = (event.clientY / window.innerHeight - 0.5) * 0.12;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    const resize = () => {
      const width = Math.max(container.clientWidth, 1); const height = Math.max(container.clientHeight, 1);
      renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const render = (time = 0) => {
      group.rotation.y += (pointerX - group.rotation.y) * 0.025;
      group.rotation.x += (-pointerY - group.rotation.x) * 0.025;
      points.rotation.z = time * 0.000035;
      waveOne.rotation.z = Math.sin(time * 0.00028) * 0.06;
      waveTwo.rotation.z = 0.38 - Math.sin(time * 0.00022) * 0.07;
      halo.rotation.z = time * 0.00008;
      renderer.render(scene, camera);
      if (!reducedMotion) frame = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(frame); window.removeEventListener("pointermove", onPointer); observer.disconnect();
      pointsGeometry.dispose(); pointsMaterial.dispose(); waveOne.geometry.dispose(); waveTwo.geometry.dispose();
      waveMaterial.dispose(); waveMaterialTwo.dispose(); haloGeometry.dispose(); haloMaterial.dispose(); renderer.dispose();
      renderer.domElement.remove();
    };
  }, [variant]);

  return <div ref={host} className={`conversation-field ${variant}`} aria-hidden="true" />;
}
