/**
 * 配套存储与组网拓扑建模（硬件反选 §3.13 完整版）——前端镜像。
 *
 * 与 `backend/app/calc/supporting_cost.py` 逐位同构（纯函数、Decimal 全程、常量一致）：
 * - `estimateStorage`：模型规模/量化/上下文/并发 → 存储容量（权重落盘 + KV cache +
 *   数据集 + 日志/快照）→ 一次性 CAPEX 与月度运维费；
 * - `estimateNetwork`：卡数/单机插槽上限/互联形态 → **分层 BOM**：算力交换机（IB/RoCE）、
 *   存储交换机、管理交换机、NIC、400G/100G 光模块、AOC、MPO 线缆的数量与成本；
 * - `NetworkCatalogPrices`：配件库价格覆盖（有 DB 数据用 DB、无则默认经验常量）。
 *
 * 联动语义（`recomputeSupportingCapex`）：硬件反选「一键应用」装配时把推导输入快照
 * （`hw.supporting_fabric` / `hw.supporting_mem_gb`）写入方案参数；用户在 Wizard 修改
 * 卡数后，前端按同一口径重算配套 CAPEX（`hw.P_aux`），保证「改卡数 ⇒ 辅助设备金额
 * 联动」，且与后端推荐引擎数值逐位一致。
 */
import { Decimal } from './decimalConfig';
import { ZERO, D } from './decimalConfig';
import type { ScenarioParams } from './parameters';

// --------------------------------------------------------------------------- 常量（与 supporting_cost.py 一致）
export const KV_BYTES_PER_TOKEN = D('2');
export const WEIGHTS_MULT = D('2.0');
export const DATASET_MULT = D('20');
export const LOG_MULT = D('0.5');
export const STORAGE_PRICE_PER_GB = D('1.0');
export const STORAGE_MONTHLY_PER_GB = D('0.02');

export const UPLINKS_PER_NODE = 2;
export const PORT_SPEED_GBPS = D('400');
export const SWITCH_PORTS = 32;
// 端口速率 → 硬件单价倍率（与后端 PORT_SPEED_MULT 一致；200G≈0.6×，800G≈1.8×）
export const PORT_SPEED_MULT: Record<number, Decimal> = { 100: D('0.45'), 200: D('0.6'), 400: D('1.0'), 800: D('1.8') };
export const PORT_SPEED_OPTIONS = new Set([100, 200, 400, 800]);
export const SWITCH_CAPEX = D(250000);
export const NIC_CAPEX = D(15000);
export const OPTICS_CAPEX = D(5000);
export const SWITCH_MONTHLY = D(5000);
export const RDMA_INTERCONNECT_LOSS = D('0.05');
export const ETH_INTERCONNECT_LOSS = D('0.08');
export const STORAGE_POWER_KW_PER_TB = D('0.3');
export const SWITCH_POWER_KW = D('1.5');
export const STORAGE_TB_PER_NODE = D(60);
export const MGMT_PORTS_PER_NODE = 2;
// Spine 交换机单价（核心层，与 Leaf 同级，量级可改）——与 backend NetworkCatalogPrices 对齐
export const SPINE_SWITCH_IB_CAPEX = D(250000);
export const SPINE_SWITCH_ROCE_CAPEX = D(200000);

export const FABRIC_NONE = 'none';
export const FABRIC_RDMA = 'rdma';
export const FABRIC_ETHERNET = 'ethernet';
export const FABRIC_IB = 'ib';
export const FABRIC_ROCE = 'roce';
export const FABRICS = new Set([FABRIC_NONE, FABRIC_RDMA, FABRIC_ETHERNET, FABRIC_IB, FABRIC_ROCE]);

// --------------------------------------------------------------------------- 目录覆盖参数（与后端 NetworkCatalogPrices 一致）
export interface NetworkCatalogPrices {
  compute_switch_ib_capex: Decimal;
  compute_switch_roce_capex: Decimal;
  compute_switch_ports: number; // 默认 32（SWITCH_PORTS）；配件库可覆盖为真实机型端口数
  compute_switch_speed?: number; // Leaf 端口速率（Gbps），缺省由 portSpeed 参数决定
  compute_switch_monthly: Decimal;
  spine_switch_ib_capex: Decimal;
  spine_switch_roce_capex: Decimal;
  spine_switch_ports?: number; // Spine 端口数（缺省回落 compute_switch_ports）
  spine_switch_speed?: number; // Spine 端口速率（Gbps），缺省由 spinePortSpeed 参数决定
  spine_switch_monthly: Decimal;
  storage_switch_capex: Decimal;
  storage_switch_ports: number;
  storage_switch_monthly: Decimal;
  mgmt_switch_capex: Decimal;
  mgmt_switch_ports: number;
  mgmt_switch_monthly: Decimal;
  nic_ib_capex: Decimal;
  nic_roce_capex: Decimal;
  optics_400g_capex: Decimal;
  optics_100g_capex: Decimal;
  aoc_capex: Decimal;
  mpo_capex: Decimal;
  uplinks_per_node: number;
  storage_tb_per_node: Decimal;
  mgmt_ports_per_node: number;
  storage_per_gb: Decimal;
  storage_monthly_per_gb: Decimal;
}

export const DEFAULT_CATALOG: NetworkCatalogPrices = {
  compute_switch_ib_capex: SWITCH_CAPEX,
  compute_switch_roce_capex: D(200000),
  compute_switch_ports: SWITCH_PORTS,
  compute_switch_monthly: SWITCH_MONTHLY,
  spine_switch_ib_capex: SPINE_SWITCH_IB_CAPEX,
  spine_switch_roce_capex: SPINE_SWITCH_ROCE_CAPEX,
  spine_switch_monthly: SWITCH_MONTHLY,
  storage_switch_capex: D(120000),
  storage_switch_ports: 48,
  storage_switch_monthly: D(3000),
  mgmt_switch_capex: D(8000),
  mgmt_switch_ports: 48,
  mgmt_switch_monthly: D(300),
  nic_ib_capex: NIC_CAPEX,
  nic_roce_capex: D(8000),
  optics_400g_capex: OPTICS_CAPEX,
  optics_100g_capex: D(1500),
  aoc_capex: D(3000),
  mpo_capex: D(2000),
  uplinks_per_node: UPLINKS_PER_NODE,
  storage_tb_per_node: STORAGE_TB_PER_NODE,
  mgmt_ports_per_node: MGMT_PORTS_PER_NODE,
  storage_per_gb: STORAGE_PRICE_PER_GB,
  storage_monthly_per_gb: STORAGE_MONTHLY_PER_GB,
};

export interface StorageEstimate {
  capacity_gb: Decimal;
  weights_gb: Decimal;
  kv_cache_gb: Decimal;
  dataset_gb: Decimal;
  log_snapshot_gb: Decimal;
  capex: Decimal;
  monthly: Decimal;
  power_kw: Decimal;
  assumptions: string[];
}

export interface NetworkEstimate {
  node_count: number;
  fabric: string;
  port_speed_gbps: Decimal;
  spine_port_speed_gbps: Decimal;
  storage_port_speed_gbps: Decimal;
  switches: number;
  compute_switch_capex: Decimal;
  spine_switches: number;
  spine_switch_capex: Decimal;
  storage_switch_qty: number;
  storage_switch_capex: Decimal;
  mgmt_switch_qty: number;
  mgmt_switch_capex: Decimal;
  nic_qty: number;
  nic_capex: Decimal;
  optics_400g_qty: number;
  optics_400g_capex: Decimal;
  optics_100g_qty: number;
  optics_100g_capex: Decimal;
  aoc_qty: number;
  aoc_capex: Decimal;
  mpo_qty: number;
  mpo_capex: Decimal;
  capex: Decimal;
  monthly: Decimal;
  power_kw: Decimal;
  interconnect_loss: Decimal;
  prices: Record<string, { unit_price: Decimal; unit: string; qty: number; fabric?: string; port_speed_gbps?: Decimal; ports?: number }>;
  assumptions: string[];
}

export function estimateStorage(
  memWGb: Decimal,
  mParam: Decimal,
  ctx: Decimal,
  bMax: Decimal,
  nGpu: Decimal,
  catalog: NetworkCatalogPrices = DEFAULT_CATALOG,
): StorageEstimate {
  const assumptions: string[] = [];
  const price = catalog.storage_per_gb;
  const monthlyRate = catalog.storage_monthly_per_gb;
  const weights = memWGb.times(WEIGHTS_MULT);
  // KV cache：单卡并发上限 × 上下文 × 每 token 字节；多卡线性叠加（保守）
  const kv = ctx.times(nGpu).times(bMax).times(KV_BYTES_PER_TOKEN).div(D(1_000_000_000));
  const dataset = mParam.times(DATASET_MULT);
  const logSnapshot = weights.times(LOG_MULT);
  const capacity = weights.plus(kv).plus(dataset).plus(logSnapshot);
  const capex = capacity.times(price);
  const monthly = capacity.times(monthlyRate);
  const powerKw = capacity.div(D(1_000)).times(STORAGE_POWER_KW_PER_TB); // 1TB=1000GB ⇒ kW
  assumptions.push(
    `存储估算：权重落盘 ${weights}GB（≈Mem_w×${WEIGHTS_MULT}）+ KV cache ${kv}GB` +
      `（Ctx×N×B_max×2B）+ 数据集 ${dataset}GB + 日志/快照 ${logSnapshot}GB ⇒ ` +
      `共 ${capacity}GB；CAPEX≈${capex} 元、月费≈${monthly} 元（启发式，可手动调整 Co_stor）。`,
  );
  return {
    capacity_gb: capacity,
    weights_gb: weights,
    kv_cache_gb: kv,
    dataset_gb: dataset,
    log_snapshot_gb: logSnapshot,
    capex,
    monthly,
    power_kw: powerKw,
    assumptions,
  };
}

export function estimateNetwork(
  nGpu: Decimal,
  cardsPerNode: Decimal,
  fabric: string = FABRIC_RDMA,
  catalog: NetworkCatalogPrices = DEFAULT_CATALOG,
  storageCapacityGb: Decimal = ZERO,
  extraNodes: number = 0,
  spineSwitches?: number,
  portSpeed: number = 400,
  spinePortSpeed?: number,
  storagePortSpeed: number = 100,
): NetworkEstimate {
  const f = FABRICS.has(fabric) ? fabric : FABRIC_RDMA;
  const extraNodesSafe = Math.max(0, Math.floor(extraNodes));
  // 速率解析：配件库 spec.speed（真实机型速率）优先，其次显式参数，最后回落 400G
  const leafSpeed = catalog.compute_switch_speed && PORT_SPEED_OPTIONS.has(catalog.compute_switch_speed)
    ? catalog.compute_switch_speed
    : PORT_SPEED_OPTIONS.has(portSpeed)
    ? portSpeed
    : 400;
  const spineSpeed = catalog.spine_switch_speed && PORT_SPEED_OPTIONS.has(catalog.spine_switch_speed)
    ? catalog.spine_switch_speed
    : spinePortSpeed && PORT_SPEED_OPTIONS.has(spinePortSpeed)
    ? spinePortSpeed
    : leafSpeed;
  const speedMult = PORT_SPEED_MULT[leafSpeed];
  const spineSpeedMult = PORT_SPEED_MULT[spineSpeed];
  // 存储网速率：独立平面，默认 100G（IP SAN 常规），可升到 200/400G
  const storageSpeed = PORT_SPEED_OPTIONS.has(storagePortSpeed) ? storagePortSpeed : 100;
  const storageSpeedMult = PORT_SPEED_MULT[storageSpeed];
  // 端口数解析：配件库 spec.ports 优先，其次内置常量
  const computePorts = catalog.compute_switch_ports || SWITCH_PORTS;
  const spinePorts = catalog.spine_switch_ports || computePorts;
  // 单价快照（与多机分支同口径），便于 BOM 始终含完整条目；单机 qty=0
  const computeUnit =
    (f === FABRIC_IB || f === FABRIC_RDMA ? catalog.compute_switch_ib_capex : catalog.compute_switch_roce_capex)
    .times(speedMult);
  const spineUnit =
    (f === FABRIC_IB || f === FABRIC_RDMA ? catalog.spine_switch_ib_capex : catalog.spine_switch_roce_capex)
    .times(spineSpeedMult);
  const nicUnit =
    (f === FABRIC_IB || f === FABRIC_RDMA ? catalog.nic_ib_capex : catalog.nic_roce_capex).times(speedMult);
  const assumptions: string[] = [];
  const nodeCount = Math.max(1, Math.ceil(Number(nGpu) / Number(cardsPerNode)));
  if (nodeCount <= 1 && extraNodesSafe === 0) {
    assumptions.push('单机部署（卡间 NVLink 内置），无需外部 fabric，组网 CAPEX/月费为 0。');
    return {
      node_count: 1,
      fabric: FABRIC_NONE,
      port_speed_gbps: ZERO,
      spine_port_speed_gbps: ZERO,
      storage_port_speed_gbps: ZERO,
      switches: 0,
      compute_switch_capex: ZERO,
      spine_switches: 0,
      spine_switch_capex: ZERO,
      storage_switch_qty: 0,
      storage_switch_capex: ZERO,
      mgmt_switch_qty: 0,
      mgmt_switch_capex: ZERO,
      nic_qty: 0,
      nic_capex: ZERO,
      optics_400g_qty: 0,
      optics_400g_capex: ZERO,
      optics_100g_qty: 0,
      optics_100g_capex: ZERO,
      aoc_qty: 0,
      aoc_capex: ZERO,
      mpo_qty: 0,
      mpo_capex: ZERO,
      capex: ZERO,
      monthly: ZERO,
      power_kw: ZERO,
      interconnect_loss: ZERO,
      // 与多机分支同构：始终返回完整 9 项（qty=0），避免下游读 .fabric 时 undefined 崩溃
      prices: {
        compute_switch: { unit_price: computeUnit, unit: '台', qty: 0, fabric: FABRIC_NONE },
        spine_switch: { unit_price: spineUnit, unit: '台', qty: 0 },
        storage_switch: { unit_price: catalog.storage_switch_capex, unit: '台', qty: 0 },
        mgmt_switch: { unit_price: catalog.mgmt_switch_capex, unit: '台', qty: 0 },
        nic: { unit_price: nicUnit, unit: '卡', qty: 0 },
        optics_400g: { unit_price: catalog.optics_400g_capex, unit: '个', qty: 0 },
        optics_100g: { unit_price: catalog.optics_100g_capex, unit: '个', qty: 0 },
        aoc: { unit_price: catalog.aoc_capex, unit: '根', qty: 0 },
        mpo: { unit_price: catalog.mpo_capex, unit: '根', qty: 0 },
      },
      assumptions,
    };
  }

  // ---- 算力交换机（数据面 Leaf）----
  const requiredPorts = (nodeCount + extraNodesSafe) * catalog.uplinks_per_node;
  const switches = Math.ceil(requiredPorts / computePorts);
  const computeSwitchCapex = D(switches).times(computeUnit);
  // ---- Spine 交换机（核心层，Leaf 全互联）----
  const spineSw =
    spineSwitches !== undefined
      ? spineSwitches
      : switches >= 2
      ? Math.max(2, switches) // fat-tree 全互联：Leaf≥2 时 Spine=Leaf（至少 2 台冗余）
      : 0;
  const spineSwitchCapex = D(spineSw).times(spineUnit);
  // ---- 存储交换机（IP SAN，速率独立平面 storageSpeed）----
  const storageNodes =
    storageCapacityGb.gt(ZERO)
      ? Math.ceil(Number(storageCapacityGb) / (Number(catalog.storage_tb_per_node) * 1000))
      : 0;
  const storagePorts = storageNodes * catalog.uplinks_per_node;
  const storageSwitchQty = storagePorts > 0 ? Math.ceil(storagePorts / catalog.storage_switch_ports) : 0;
  const storageSwitchCapex = D(storageSwitchQty).times(catalog.storage_switch_capex).times(storageSpeedMult);
  // ---- 管理交换机 ----
  const mgmtPorts = (nodeCount + extraNodesSafe + storageNodes) * catalog.mgmt_ports_per_node;
  const mgmtSwitchQty = mgmtPorts > 0 ? Math.ceil(mgmtPorts / catalog.mgmt_switch_ports) : 0;
  const mgmtSwitchCapex = D(mgmtSwitchQty).times(catalog.mgmt_switch_capex);
  // ---- 线缆明细 ----
  const nicQty = Number(nGpu) + extraNodesSafe * catalog.uplinks_per_node; // GPU 卡 + 通用节点上联
  const nicCapex = D(nicQty).times(nicUnit);
  const optics400gQty = requiredPorts;
  const optics400gCapex = D(optics400gQty).times(catalog.optics_400g_capex).times(speedMult);
  const optics100gQty = storagePorts;
  const optics100gCapex = D(optics100gQty).times(catalog.optics_100g_capex).times(storageSpeedMult);
  const aocQty = nicQty; // 每跨机卡 1 根 AOC（服务器→TOR）
  const aocCapex = D(aocQty).times(catalog.aoc_capex).times(speedMult);
  // Leaf↔Spine 主干：每台 Leaf 上联到每台 Spine（全互联），冗余 2 根/链路；速率随 Spine
  const mpoQty = spineSw > 0 ? switches * spineSw * 2 : 0;
  const mpoCapex = D(mpoQty).times(catalog.mpo_capex).times(spineSpeedMult);

  const capex = computeSwitchCapex
    .plus(spineSwitchCapex)
    .plus(storageSwitchCapex)
    .plus(mgmtSwitchCapex)
    .plus(nicCapex)
    .plus(optics400gCapex)
    .plus(optics100gCapex)
    .plus(aocCapex)
    .plus(mpoCapex);
  const monthly = D(switches)
    .times(catalog.compute_switch_monthly)
    .plus(D(spineSw).times(catalog.spine_switch_monthly))
    .plus(D(storageSwitchQty).times(catalog.storage_switch_monthly))
    .plus(D(mgmtSwitchQty).times(catalog.mgmt_switch_monthly));
  const powerKw = D(switches)
    .times(SWITCH_POWER_KW)
    .plus(D(spineSw).times(SWITCH_POWER_KW))
    .plus(D(storageSwitchQty).times(D('1.2')))
    .plus(D(mgmtSwitchQty).times(D('0.3')));
  const loss = f === FABRIC_ETHERNET || f === FABRIC_ROCE ? ETH_INTERCONNECT_LOSS : RDMA_INTERCONNECT_LOSS;
  const prices: NetworkEstimate['prices'] = {
    compute_switch: { unit_price: computeUnit, unit: '台', qty: switches, fabric: f, port_speed_gbps: D(leafSpeed), ports: computePorts },
    spine_switch: { unit_price: spineUnit, unit: '台', qty: spineSw, fabric: f, port_speed_gbps: D(spineSpeed), ports: spinePorts },
    storage_switch: { unit_price: catalog.storage_switch_capex, unit: '台', qty: storageSwitchQty },
    mgmt_switch: { unit_price: catalog.mgmt_switch_capex, unit: '台', qty: mgmtSwitchQty },
    nic: { unit_price: nicUnit, unit: '卡', qty: nicQty },
    optics_400g: { unit_price: catalog.optics_400g_capex, unit: '个', qty: optics400gQty },
    optics_100g: { unit_price: catalog.optics_100g_capex, unit: '个', qty: optics100gQty },
    aoc: { unit_price: catalog.aoc_capex, unit: '根', qty: aocQty },
    mpo: { unit_price: catalog.mpo_capex, unit: '根', qty: mpoQty },
  };
  assumptions.push(
    `组网估算：${nGpu} 卡 / 每机 ≤${cardsPerNode} 卡 ⇒ ${nodeCount} 台 GPU 机` +
      (extraNodesSafe > 0 ? ` + ${extraNodesSafe} 台通用节点` : '') +
      `；fabric=${f}（Leaf ${leafSpeed}Gbps×${catalog.uplinks_per_node} 上联/机` +
      (spineSpeed !== leafSpeed ? `、Spine ${spineSpeed}Gbps` : '') +
      `，${speedMult.eq(D(1)) ? '400G' : `${leafSpeed}G 硬件单价按 ×${speedMult}`}` +
      (!spineSpeedMult.eq(speedMult) ? `、Spine 单价按 ×${spineSpeedMult}` : '') +
      `），` +
      `Leaf 算力交换机 ${switches} 台（${computePorts} 口/台，${requiredPorts} 上联口）+ Spine ${spineSw} 台（${spinePorts} 口/台）` +
      ` + 存储交换机 ${storageSwitchQty} 台（存储 ${storageNodes} 节点）` +
      ` + 管理交换机 ${mgmtSwitchQty} 台 + NIC ${nicQty} 卡 + ${leafSpeed}G 模块 ${optics400gQty}` +
      ` + 100G 模块 ${optics100gQty} + AOC ${aocQty} 根 + MPO ${mpoQty} 根` +
      ` ⇒ 组网 CAPEX≈${capex} 元、月费≈${monthly} 元；跨机吞吐按 ×${D(1).minus(loss)} 折损。`,
  );
  return {
    node_count: nodeCount,
    fabric: f,
      port_speed_gbps: D(leafSpeed),
      spine_port_speed_gbps: D(spineSpeed),
      storage_port_speed_gbps: D(storageSpeed),
      switches,
    compute_switch_capex: computeSwitchCapex,
    spine_switches: spineSw,
    spine_switch_capex: spineSwitchCapex,
    storage_switch_qty: storageSwitchQty,
    storage_switch_capex: storageSwitchCapex,
    mgmt_switch_qty: mgmtSwitchQty,
    mgmt_switch_capex: mgmtSwitchCapex,
    nic_qty: nicQty,
    nic_capex: nicCapex,
    optics_400g_qty: optics400gQty,
    optics_400g_capex: optics400gCapex,
    optics_100g_qty: optics100gQty,
    optics_100g_capex: optics100gCapex,
    aoc_qty: aocQty,
    aoc_capex: aocCapex,
    mpo_qty: mpoQty,
    mpo_capex: mpoCapex,
    capex,
    monthly,
    power_kw: powerKw,
    interconnect_loss: loss,
    prices,
    assumptions,
  };
}

/**
 * 按新卡数联动重算配套 CAPEX（纯函数）。
 *
 * 仅当方案来自硬件反选（`hw.supporting_fabric` 非空）时生效；否则返回 null（不改动）。
 * 返回值为新的 `hw.P_aux`（存储 + 组网 CAPEX，含分层交换机与线缆），与后端推荐引擎口径一致。
 */
export function recomputeSupportingCapex(
  params: ScenarioParams,
  newNGpu: Decimal,
  catalog: NetworkCatalogPrices = DEFAULT_CATALOG,
): Decimal | null {
  const fabric = params.hw.supporting_fabric;
  if (!fabric) return null;
  const memWGb = params.hw.supporting_mem_gb.gt(ZERO)
    ? params.hw.supporting_mem_gb
    : params.perf.M_param.times(D('2')).times(D('1.15')); // 兜底：无快照时按默认量化估算
  // 单机可插卡数用反选快照（5090=5 等），缺失时按 8 兜底
  const cardsPerNode = params.hw.supporting_cards_per_node.gt(ZERO)
    ? params.hw.supporting_cards_per_node
    : D(8);
  const storage = estimateStorage(
    memWGb,
    params.perf.M_param,
    params.perf.Ctx,
    params.perf.B_max,
    newNGpu,
    catalog,
  );
  const network = estimateNetwork(
    newNGpu,
    cardsPerNode,
    fabric,
    catalog,
    storage.capacity_gb,
    params.hw.extra_nodes,
    undefined,
    params.hw.supporting_port_speed || undefined,
    params.hw.supporting_spine_port_speed || undefined,
  );
  return storage.capex.plus(network.capex);
}

/**
 * 由方案参数重建硬件 BOM（前端镜像，与后端 `_build_bom` 同构）。
 * 仅反选来源（supporting_fabric 非空）有 BOM；否则返回 null。
 */
export function buildBomFromParams(
  params: ScenarioParams,
  catalog: NetworkCatalogPrices = DEFAULT_CATALOG,
): {
  servers: { name: string; cards_per_node: number; node_count: number; unit_price: Decimal; qty: number; subtotal: Decimal };
  compute_switch: { unit_price: Decimal; unit: string; qty: number; fabric?: string };
  spine_switch: { unit_price: Decimal; unit: string; qty: number; fabric?: string };
  storage_switch: { unit_price: Decimal; unit: string; qty: number };
  mgmt_switch: { unit_price: Decimal; unit: string; qty: number };
  nic: { unit_price: Decimal; unit: string; qty: number };
  optics_400g: { unit_price: Decimal; unit: string; qty: number };
  optics_100g: { unit_price: Decimal; unit: string; qty: number };
  aoc: { unit_price: Decimal; unit: string; qty: number };
  mpo: { unit_price: Decimal; unit: string; qty: number };
  storage: {
    capacity_gb: Decimal;
    unit_price_gb: Decimal;
    capex: Decimal;
    monthly_per_gb: Decimal;
    monthly: Decimal;
  };
  total_supporting_capex: Decimal;
} | null {
  const fabric = params.hw.supporting_fabric;
  if (!fabric) return null;
  const cardsPerNode = params.hw.supporting_cards_per_node.gt(ZERO)
    ? params.hw.supporting_cards_per_node
    : D(8);
  const memWGb = params.hw.supporting_mem_gb.gt(ZERO)
    ? params.hw.supporting_mem_gb
    : params.perf.M_param.times(D('2')).times(D('1.15'));
  const storage = estimateStorage(
    memWGb,
    params.perf.M_param,
    params.perf.Ctx,
    params.perf.B_max,
    params.hw.N_gpu,
    catalog,
  );
  const network = estimateNetwork(
    params.hw.N_gpu,
    cardsPerNode,
    fabric,
    catalog,
    storage.capacity_gb,
    params.hw.extra_nodes,
    undefined,
    params.hw.supporting_port_speed || undefined,
    params.hw.supporting_spine_port_speed || undefined,
  );
  const nodeCount = network.node_count;
  const gpuPrice = params.hw.P_gpu;
  return {
    servers: {
      name: `算力服务器（每台 ${cardsPerNode} 卡）`,
      cards_per_node: Number(cardsPerNode),
      node_count: nodeCount,
      // §2.3 修正：按实际插卡数计价（与后端 _build_bom 镜像），保证 unit_price × qty == subtotal
      unit_price: gpuPrice,
      qty: Number(params.hw.N_gpu),
      subtotal: gpuPrice.times(params.hw.N_gpu),
    },
    compute_switch: network.prices.compute_switch,
    spine_switch: network.prices.spine_switch,
    storage_switch: network.prices.storage_switch,
    mgmt_switch: network.prices.mgmt_switch,
    nic: network.prices.nic,
    optics_400g: network.prices.optics_400g,
    optics_100g: network.prices.optics_100g,
    aoc: network.prices.aoc,
    mpo: network.prices.mpo,
    storage: {
      capacity_gb: storage.capacity_gb,
      unit_price_gb: catalog.storage_per_gb,
      capex: storage.capex,
      monthly_per_gb: catalog.storage_monthly_per_gb,
      monthly: storage.monthly,
    },
    total_supporting_capex: storage.capex.plus(network.capex),
  };
}
