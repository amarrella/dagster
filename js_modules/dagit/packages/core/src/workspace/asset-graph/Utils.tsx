import {gql} from '@apollo/client';
import {pathVerticalDiagonal} from '@vx/shape';
import * as dagre from 'dagre';

import {AssetNodeDefinitionFragment} from '../../assets/types/AssetNodeDefinitionFragment';

import {getNodeDimensions} from './AssetNode';
import {getForeignNodeDimensions} from './ForeignNode';
import {AssetGraphLiveQuery_pipelineOrError_Pipeline_assetNodes_assetMaterializations} from './types/AssetGraphLiveQuery';
import {
  AssetGraphQuery_pipelineOrError_Pipeline_assetNodes,
  AssetGraphQuery_pipelineOrError_Pipeline_assetNodes_assetKey,
} from './types/AssetGraphQuery';
import {AssetNodeLiveFragment} from './types/AssetNodeLiveFragment';
import {InProgressRunsFragment} from './types/InProgressRunsFragment';

type AssetNode = AssetGraphQuery_pipelineOrError_Pipeline_assetNodes;
type AssetKey = AssetGraphQuery_pipelineOrError_Pipeline_assetNodes_assetKey;

export interface Node {
  id: string;
  assetKey: AssetKey;
  definition: AssetNode;
}
interface LayoutNode {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface GraphData {
  nodes: {[assetId: string]: Node};
  downstream: {[assetId: string]: {[childAssetId: string]: boolean}};
  upstream: {[assetId: string]: {[parentAssetId: string]: boolean}};
}
interface IPoint {
  x: number;
  y: number;
}
export type IEdge = {
  from: IPoint;
  to: IPoint;
  dashed: boolean;
};

export const buildGraphData = (assetNodes: AssetNode[]) => {
  const data: GraphData = {
    nodes: {},
    downstream: {},
    upstream: {},
  };

  assetNodes.forEach((definition: AssetNode) => {
    const assetKeyJson = JSON.stringify(definition.assetKey.path);
    definition.dependencyKeys.forEach(({path}) => {
      const upstreamAssetKeyJson = JSON.stringify(path);
      data.downstream[upstreamAssetKeyJson] = {
        ...(data.downstream[upstreamAssetKeyJson] || {}),
        [assetKeyJson]: true,
      };
      data.upstream[assetKeyJson] = {
        ...(data.upstream[assetKeyJson] || {}),
        [upstreamAssetKeyJson]: true,
      };
    });
    data.nodes[assetKeyJson] = {
      id: assetKeyJson,
      assetKey: definition.assetKey,
      definition,
    };
  });

  return data;
};

export const buildGraphDataFromSingleNode = (assetNode: AssetNodeDefinitionFragment) => {
  const graphData: GraphData = {
    downstream: {
      [assetNode.id]: {},
    },
    nodes: {
      [assetNode.id]: {
        id: assetNode.id,
        assetKey: assetNode.assetKey,
        definition: {...assetNode, dependencyKeys: []},
      },
    },
    upstream: {
      [assetNode.id]: {},
    },
  };

  for (const {asset} of assetNode.dependencies) {
    graphData.upstream[assetNode.id][asset.id] = true;
    graphData.downstream[asset.id] = {...graphData.downstream[asset.id], [assetNode.id]: true};
    graphData.nodes[asset.id] = {
      id: asset.id,
      assetKey: asset.assetKey,
      definition: {...asset, dependencyKeys: []},
    };
  }
  for (const {asset} of assetNode.dependedBy) {
    graphData.upstream[asset.id] = {...graphData.upstream[asset.id], [assetNode.id]: true};
    graphData.downstream[assetNode.id][asset.id] = true;
    graphData.nodes[asset.id] = {
      id: asset.id,
      assetKey: asset.assetKey,
      definition: {...asset, dependencyKeys: []},
    };
  }
  return graphData;
};

export const graphHasCycles = (graphData: GraphData) => {
  const nodes = new Set(Object.keys(graphData.nodes));
  const search = (stack: string[], node: string): boolean => {
    if (stack.indexOf(node) !== -1) {
      return true;
    }
    if (nodes.delete(node) === true) {
      const nextStack = stack.concat(node);
      return Object.keys(graphData.downstream[node] || {}).some((nextNode) =>
        search(nextStack, nextNode),
      );
    }
    return false;
  };
  let hasCycles = false;
  while (nodes.size !== 0) {
    hasCycles = hasCycles || search([], nodes.values().next().value);
  }
  return hasCycles;
};

export const layoutGraph = (
  graphData: GraphData,
  opts: {margin: number; mini: boolean} = {
    margin: 100,
    mini: false,
  },
) => {
  const g = new dagre.graphlib.Graph();

  g.setGraph({
    rankdir: 'TB',
    marginx: opts.margin,
    marginy: opts.margin,
    nodesep: opts.mini ? 20 : 50,
    edgesep: opts.mini ? 10 : 10,
    ranksep: opts.mini ? 20 : 50,
  });
  g.setDefaultEdgeLabel(() => ({}));

  const shouldRender = (node?: Node) => node && node.definition.opName;

  Object.values(graphData.nodes)
    .filter(shouldRender)
    .forEach((node) => {
      const {width, height} = getNodeDimensions(node.definition);
      g.setNode(node.id, {width: opts.mini ? 230 : width, height});
    });

  const foreignNodes = {};
  Object.keys(graphData.downstream).forEach((upstreamId) => {
    const downstreamIds = Object.keys(graphData.downstream[upstreamId]);
    downstreamIds.forEach((downstreamId) => {
      if (
        !shouldRender(graphData.nodes[downstreamId]) &&
        !shouldRender(graphData.nodes[upstreamId])
      ) {
        return;
      }
      g.setEdge({v: upstreamId, w: downstreamId}, {weight: 1});

      if (!shouldRender(graphData.nodes[downstreamId])) {
        foreignNodes[downstreamId] = true;
      } else if (!shouldRender(graphData.nodes[upstreamId])) {
        foreignNodes[upstreamId] = true;
      }
    });
  });

  Object.keys(foreignNodes).forEach((id) => {
    g.setNode(id, getForeignNodeDimensions(id));
  });

  dagre.layout(g);

  const dagreNodesById: {[id: string]: dagre.Node} = {};
  g.nodes().forEach((id) => {
    const node = g.node(id);
    if (!node) {
      return;
    }
    dagreNodesById[id] = node;
  });

  let maxWidth = 0;
  let maxHeight = 0;
  const nodes: LayoutNode[] = [];
  Object.keys(dagreNodesById).forEach((id) => {
    const dagreNode = dagreNodesById[id];
    nodes.push({
      id,
      x: dagreNode.x - dagreNode.width / 2,
      y: dagreNode.y - dagreNode.height / 2,
      width: dagreNode.width,
      height: dagreNode.height,
    });
    maxWidth = Math.max(maxWidth, dagreNode.x + dagreNode.width / 2);
    maxHeight = Math.max(maxHeight, dagreNode.y + dagreNode.height / 2);
  });

  const edges: IEdge[] = [];
  g.edges().forEach((e) => {
    const points = g.edge(e).points;
    edges.push({
      from: points[0],
      to: points[points.length - 1],
      dashed: false,
    });
  });

  return {
    nodes,
    edges,
    width: maxWidth + opts.margin,
    height: maxHeight + opts.margin,
  };
};

export const buildSVGPath = pathVerticalDiagonal({
  source: (s: any) => s.source,
  target: (s: any) => s.target,
  x: (s: any) => s.x,
  y: (s: any) => s.y,
});

export type Status = 'good' | 'old' | 'none' | 'unknown';

export interface LiveDataForNode {
  computeStatus: Status;
  unstartedRunIds: string[]; // run in progress and step not started
  inProgressRunIds: string[]; // run in progress and step in progress
  lastMaterialization: AssetGraphLiveQuery_pipelineOrError_Pipeline_assetNodes_assetMaterializations | null;
  lastStepStart: number;
}
export interface LiveData {
  [assetId: string]: LiveDataForNode;
}

export const buildLiveData = (
  graph: GraphData,
  nodes: AssetNodeLiveFragment[],
  inProgressRunsByStep: InProgressRunsFragment[],
) => {
  const data: LiveData = {};

  for (const node of nodes) {
    const lastMaterialization = node.assetMaterializations[0] || null;
    const lastStepStart = lastMaterialization?.materializationEvent.stepStats?.startTime || 0;
    const isForeignNode = !node.opName;
    const isPartitioned = graph.nodes[node.id].definition.partitionDefinition;

    const runs = inProgressRunsByStep.find((r) => r.stepKey === node.opName);

    data[node.id] = {
      lastStepStart,
      lastMaterialization,
      inProgressRunIds: runs?.inProgressRuns.map((r) => r.id) || [],
      unstartedRunIds: runs?.unstartedRuns.map((r) => r.id) || [],
      computeStatus: isForeignNode
        ? 'good' // foreign nodes are always considered up-to-date
        : isPartitioned
        ? // partitioned nodes are not supported, need to compare materializations
          // of the same partition key and the API does not make fetching this easy
          'none'
        : lastMaterialization
        ? 'unknown' // resolve to 'good' or 'old' by looking upstream
        : 'none',
    };
  }

  for (const asset of nodes) {
    data[asset.id].computeStatus = findComputeStatusForId(data, graph.upstream, asset.id);
  }

  return data;
};

function findComputeStatusForId(
  data: LiveData,
  upstream: {[assetId: string]: {[upstreamAssetId: string]: boolean}},
  assetId: string,
): Status {
  if (!data[assetId]) {
    // Currently compute status assumes foreign nodes are up to date
    // and only shows "upstream changed" for upstreams in the same job
    return 'good';
  }
  const ts = data[assetId].lastStepStart;
  const upstreamIds = Object.keys(upstream[assetId] || {});
  if (data[assetId].computeStatus !== 'unknown') {
    return data[assetId].computeStatus;
  }

  return upstreamIds.some((uid) => data[uid]?.lastStepStart > ts)
    ? 'old'
    : upstreamIds.some((uid) => findComputeStatusForId(data, upstream, uid) !== 'good')
    ? 'old'
    : 'good';
}

export const IN_PROGRESS_RUNS_FRAGMENT = gql`
  fragment InProgressRunsFragment on InProgressRunsByStep {
    stepKey
    unstartedRuns {
      id
    }
    inProgressRuns {
      id
    }
  }
`;
