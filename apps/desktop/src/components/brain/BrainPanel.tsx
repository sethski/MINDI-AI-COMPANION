import { useEffect, useMemo, useState } from "react";
import type { MemoryGraphNode, MemoryGraphNodeKind, MemoryGraphResponse } from "@mindi/shared";
import { fetchMemoryGraph, scanAutoIndexNow } from "../../lib/agent-api";

const KIND_COLORS: Record<MemoryGraphNodeKind, string> = {
  note: "oklch(0.72 0.14 210)",
  document: "oklch(0.7 0.12 145)",
  folder: "oklch(0.68 0.08 85)",
  tag: "oklch(0.75 0.1 300)",
  task: "oklch(0.72 0.16 35)",
  perception: "oklch(0.7 0.14 260)",
};

const FILTER_OPTIONS: Array<MemoryGraphNodeKind | "all"> = [
  "all",
  "note",
  "document",
  "folder",
  "tag",
  "task",
  "perception",
];

type LayoutNode = MemoryGraphNode & { x: number; y: number };

function layoutNodes(nodes: MemoryGraphNode[], width: number, height: number): LayoutNode[] {
  if (nodes.length === 0) return [];
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.36;
  return nodes.map((node, index) => {
    const angle = (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
    return {
      ...node,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    };
  });
}

export function BrainPanel() {
  const [graph, setGraph] = useState<MemoryGraphResponse | null>(null);
  const [filter, setFilter] = useState<MemoryGraphNodeKind | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState("Loading brain graph...");

  async function loadGraph() {
    try {
      const response = await fetchMemoryGraph();
      setGraph(response);
      setStatus(
        `${response.nodes.length} nodes, ${response.edges.length} edges. Updated ${new Date(response.generatedAt).toLocaleString()}.`,
      );
    } catch {
      setStatus("Could not load brain graph. Is the agent running?");
    }
  }

  useEffect(() => {
    void loadGraph();
  }, []);

  const filteredNodes = useMemo(() => {
    if (!graph) return [];
    if (filter === "all") return graph.nodes;
    return graph.nodes.filter((node) => node.kind === filter);
  }, [filter, graph]);

  const layout = useMemo(() => layoutNodes(filteredNodes, 720, 420), [filteredNodes]);
  const layoutById = useMemo(
    () => new Map(layout.map((node) => [node.id, node])),
    [layout],
  );

  const visibleEdges = useMemo(() => {
    if (!graph) return [];
    const ids = new Set(filteredNodes.map((node) => node.id));
    return graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  }, [filteredNodes, graph]);

  const selected = graph?.nodes.find((node) => node.id === selectedId) ?? null;

  return (
    <section className="hub brain-hub">
      <div className="card brain-card">
        <div className="brain-toolbar">
          <h3>Brain Graph</h3>
          <div className="brain-actions">
            <button type="button" onClick={() => void loadGraph()}>
              Refresh
            </button>
            <button
              type="button"
              onClick={() => {
                void scanAutoIndexNow().then(() => loadGraph());
              }}
            >
              Scan files
            </button>
          </div>
        </div>

        <div className="brain-filters">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className={filter === option ? "brain-filter active" : "brain-filter"}
              onClick={() => setFilter(option)}
            >
              {option}
            </button>
          ))}
        </div>

        <p className="assistant-reply">{status}</p>

        <div className="brain-canvas-wrap">
          <svg className="brain-canvas" viewBox="0 0 720 420" role="img" aria-label="Memory graph">
            {visibleEdges.map((edge) => {
              const source = layoutById.get(edge.source);
              const target = layoutById.get(edge.target);
              if (!source || !target) return null;
              return (
                <line
                  key={edge.id}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className="brain-edge"
                />
              );
            })}
            {layout.map((node) => (
              <g
                key={node.id}
                className={selectedId === node.id ? "brain-node selected" : "brain-node"}
                onClick={() => setSelectedId(node.id)}
                style={{ cursor: "pointer" }}
              >
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={selectedId === node.id ? 14 : 10}
                  fill={KIND_COLORS[node.kind]}
                />
                <text x={node.x} y={node.y + 22} textAnchor="middle" className="brain-label">
                  {node.label.slice(0, 18)}
                </text>
              </g>
            ))}
          </svg>
        </div>
      </div>

      <div className="card brain-inspector">
        <h3>Inspect</h3>
        {selected ? (
          <div className="stack">
            <p>
              <strong>{selected.label}</strong>
            </p>
            <p>Kind: {selected.kind}</p>
            <pre className="brain-meta">{JSON.stringify(selected.meta ?? {}, null, 2)}</pre>
          </div>
        ) : (
          <p className="assistant-reply">Click a node to inspect what MINDI remembers.</p>
        )}
      </div>
    </section>
  );
}
