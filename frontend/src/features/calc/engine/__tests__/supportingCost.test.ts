/**
 * 前端 supportingCost 镜像一致性 + Wizard 联动回归测试。
 *
 * 数值基准与 `backend/app/calc/__tests__/test_supporting_cost.py` 逐位一致
 * （同一套输入 ⇒ 同一套输出），保证「前端改卡数联动重算」与后端推荐引擎同口径。
 */
import { describe, it, expect } from 'vitest';
import { Decimal } from '../decimalConfig';
import { defaultParams, withOverride } from '../parameters';
import {
  estimateStorage,
  estimateNetwork,
  recomputeSupportingCapex,
  DEFAULT_CATALOG,
  WEIGHTS_MULT,
  DATASET_MULT,
  LOG_MULT,
  KV_BYTES_PER_TOKEN,
  STORAGE_MONTHLY_PER_GB,
  STORAGE_PRICE_PER_GB,
  RDMA_INTERCONNECT_LOSS,
  ETH_INTERCONNECT_LOSS,
} from '../supportingCost';

// --------------------------------------------------------------------------- 存储估算（镜像后端 test_capacity_breakdown）
describe('estimateStorage 镜像一致性', () => {
  it('70B FP8（Mem_w=80.5GB）、N=8、Ctx=8192、B_max=64 与后端逐位一致', () => {
    const memW = new Decimal('80.5');
    const s = estimateStorage(memW, new Decimal(70), new Decimal(8192), new Decimal(64), new Decimal(8));
    expect(s.weights_gb.eq(memW.times(WEIGHTS_MULT))).toBe(true); // 161
    expect(
      s.kv_cache_gb.eq(new Decimal(8192).times(8).times(64).times(KV_BYTES_PER_TOKEN).div(new Decimal(1e9))),
    ).toBe(true); // 0.008388608
    expect(s.dataset_gb.eq(new Decimal(70).times(DATASET_MULT))).toBe(true); // 1400
    expect(s.log_snapshot_gb.eq(s.weights_gb.times(LOG_MULT))).toBe(true);
    const expectedCapacity = s.weights_gb.plus(s.kv_cache_gb).plus(s.dataset_gb).plus(s.log_snapshot_gb);
    expect(s.capacity_gb.eq(expectedCapacity)).toBe(true); // 1641.508388608
    expect(s.capex.eq(expectedCapacity.times(STORAGE_PRICE_PER_GB))).toBe(true);
    expect(s.monthly.eq(expectedCapacity.times(STORAGE_MONTHLY_PER_GB))).toBe(true);
  });

  it('卡数越多 ⇒ KV cache 越大 ⇒ 容量/成本越大', () => {
    const s1 = estimateStorage(new Decimal('80.5'), new Decimal(70), new Decimal(8192), new Decimal(64), new Decimal(4));
    const s2 = estimateStorage(new Decimal('80.5'), new Decimal(70), new Decimal(8192), new Decimal(64), new Decimal(16));
    expect(s2.capacity_gb.gt(s1.capacity_gb)).toBe(true);
  });
});

// --------------------------------------------------------------------------- 组网估算（镜像后端 test_estimate_network）
describe('estimateNetwork 镜像一致性', () => {
  it('单机零成本', () => {
    const net = estimateNetwork(new Decimal(8), new Decimal(8), 'rdma');
    expect(net.node_count).toBe(1);
    expect(net.fabric).toBe('none');
    expect(net.capex.eq(new Decimal(0))).toBe(true);
    expect(net.monthly.eq(new Decimal(0))).toBe(true);
    expect(net.interconnect_loss.eq(new Decimal(0))).toBe(true);
  });

  it('单机部署：prices 仍含完整 9 项（qty=0），避免 BOM 卡片读 .fabric 崩溃', () => {
    const net = estimateNetwork(new Decimal(8), new Decimal(8), 'rdma');
    expect(net.node_count).toBe(1);
    expect(Object.keys(net.prices)).toHaveLength(9);
    expect(net.prices.compute_switch?.qty).toBe(0);
    expect(net.prices.compute_switch?.fabric).toBe('none');
    expect(net.prices.spine_switch?.qty).toBe(0);
    expect(net.prices.nic?.qty).toBe(0);
    expect(net.prices.mpo?.qty).toBe(0);
  });

  it('通用节点并入上联 + Spine 全互联推导', () => {
    const net = estimateNetwork(new Decimal(128), new Decimal(8), 'ib', undefined, new Decimal(300000), 4);
    expect(net.node_count).toBe(16);
    expect(net.switches).toBe(2); // (16+4)*2 / 32 = 1.25 → 2 台 Leaf
    expect(net.spine_switches).toBe(2); // fat-tree：Leaf≥2 ⇒ Spine=2
    expect(net.nic_qty).toBe(128 + 4 * 2); // GPU 卡 + 通用节点上联(2/机)
    expect(net.mpo_qty).toBe(net.switches * net.spine_switches * 2);
    // 显式覆盖 spine
    const net2 = estimateNetwork(new Decimal(128), new Decimal(8), 'ib', undefined, new Decimal(300000), 4, 4);
    expect(net2.spine_switches).toBe(4);
  });

  it('多机 RDMA：20 卡/3 机/1 台 32 口交换机，CAPEX=648000（含管理交换机与 AOC）', () => {
    const net = estimateNetwork(new Decimal(20), new Decimal(8), 'rdma');
    expect(net.node_count).toBe(3); // ceil(20/8)
    expect(net.fabric).toBe('rdma');
    // 6 口上联 → 1 台算力交换机；管理交换机 3 节点×2 口→1 台；无存储（容量 0）
    expect(
      net.capex.eq(
        new Decimal(250000)
          .plus(8000) // 管理交换机
          .plus(new Decimal(20).times(15000)) // NIC
          .plus(new Decimal(6).times(5000)) // 400G 模块
          .plus(new Decimal(20).times(3000)), // AOC
      ),
    ).toBe(true);
    expect(net.monthly.eq(new Decimal(5000).plus(300))).toBe(true);
    expect(net.interconnect_loss.eq(RDMA_INTERCONNECT_LOSS)).toBe(true);
  });

  it('多机以太网折损 0.08', () => {
    const net = estimateNetwork(new Decimal(20), new Decimal(8), 'ethernet');
    expect(net.interconnect_loss.eq(ETH_INTERCONNECT_LOSS)).toBe(true);
  });

  it('200G 组网：硬件单价按 ×0.6（相对 400G）', () => {
    const net400 = estimateNetwork(new Decimal(20), new Decimal(8), 'rdma', undefined, undefined, 0, undefined, 400);
    const net200 = estimateNetwork(new Decimal(20), new Decimal(8), 'rdma', undefined, undefined, 0, undefined, 200);
    expect(net200.switches).toBe(net400.switches);
    expect(net200.compute_switch_capex.eq(net400.compute_switch_capex.times(new Decimal('0.6')))).toBe(true);
    expect(net200.nic_capex.eq(net400.nic_capex.times(new Decimal('0.6')))).toBe(true);
    // 非法速率回落 400G
    const netBad = estimateNetwork(new Decimal(20), new Decimal(8), 'rdma', undefined, undefined, 0, undefined, 123);
    expect(netBad.port_speed_gbps.eq(new Decimal(400))).toBe(true);
  });

  it('Leaf 400G + Spine 800G：Spine 单价/主干按 800G 倍率', () => {
    const net = estimateNetwork(
      new Decimal(128), new Decimal(8), 'ib', undefined, undefined, 4, undefined, 400, 800,
    );
    expect(net.port_speed_gbps.eq(new Decimal(400))).toBe(true);
    expect(net.spine_port_speed_gbps.eq(new Decimal(800))).toBe(true);
    expect(net.spine_switches).toBe(net.switches);
    expect(net.spine_switch_capex.eq(net.compute_switch_capex.times(new Decimal('1.8')))).toBe(true);
    expect(net.mpo_capex.eq(new Decimal(net.mpo_qty).times(new Decimal(2000)).times(new Decimal('1.8')))).toBe(true);
  });

  it('配件库 spec.ports/speed 驱动拓扑（MQM9790=64 口/200G）', () => {
    const cat64: any = { ...DEFAULT_CATALOG, compute_switch_ports: 64 };
    // 128 卡 → 16 节点 × 2 = 32 口：32 口需 1 台，64 口仍 1 台（验证 ports 字段生效）
    const net64 = estimateNetwork(new Decimal(128), new Decimal(8), 'ib', cat64 as any);
    expect((net64.prices.compute_switch as any).ports).toBe(64);
    // 大端口需求：128 节点 × 2 = 256 口，32 口需 8 台，64 口仅需 4 台
    const big = estimateNetwork(new Decimal(1024), new Decimal(8), 'ib');
    const big64 = estimateNetwork(new Decimal(1024), new Decimal(8), 'ib', cat64 as any);
    expect(big.switches).toBe(8);
    expect(big64.switches).toBe(4);
    // spec.speed 优先：录入 200G 机型 ⇒ 拓扑按 200G（×0.6）
    const catSpeed: any = { ...DEFAULT_CATALOG, compute_switch_speed: 200 };
    const netSpeed = estimateNetwork(new Decimal(20), new Decimal(8), 'rdma', catSpeed as any);
    expect(netSpeed.port_speed_gbps.eq(new Decimal(200))).toBe(true);
    expect(netSpeed.compute_switch_capex.eq(new Decimal(250000).times(new Decimal('0.6')))).toBe(true);
  });
});

// --------------------------------------------------------------------------- Wizard 联动：recomputeSupportingCapex
function recommendedParams(fabric: string, nGpu: number): ReturnType<typeof defaultParams> {
  return withOverride(
    withOverride(
      withOverride(withOverride(withOverride(defaultParams(), 'hw.N_gpu', new Decimal(nGpu)), 'hw.supporting_fabric', fabric), 'hw.supporting_mem_gb', new Decimal('80.5')),
      'perf.M_param',
      new Decimal(70),
    ),
    'perf.B_max',
    new Decimal(64),
  );
}

describe('recomputeSupportingCapex 联动重算', () => {
  it('非反选来源（fabric 空）⇒ 返回 null 不联动', () => {
    const p = defaultParams();
    expect(recomputeSupportingCapex(p, new Decimal(16))).toBeNull();
  });

  it('24 卡（3 机 rdma）⇒ P_aux = 存储 1641.53 + 组网 775350（存储网 100G×0.45）', () => {
    const aux24 = recomputeSupportingCapex(recommendedParams('rdma', 24), new Decimal(24))!;
    // 存储：weights 161 + kv(8192×24×64×2/1e9=0.025165824) + dataset 1400 + log 80.5
    const storageCapex24 = new Decimal('1641.525165824');
    // 组网：算力交换机 25万(6口→1台) + 存储交换机 12万×0.45(100G 倍率) + 管理交换机 0.8万 +
    //       NIC 24×1.5万 + 400G 6×0.5万 + 100G 2×0.15万×0.45 + AOC 24×0.3万
    const networkCapex24 = new Decimal(775350);
    expect(aux24.eq(storageCapex24.plus(networkCapex24))).toBe(true);
  });

  it('改卡数联动：24 → 16 卡，P_aux 由 776991.5 降为 620991.5（存储微降 + 组网 3机→2机）', () => {
    const p24 = recommendedParams('rdma', 24);
    const aux24 = recomputeSupportingCapex(p24, new Decimal(24))!;
    const aux16 = recomputeSupportingCapex(p24, new Decimal(16))!;
    // 16 卡：存储 kv=8192×16×64×2/1e9=0.016777216 ⇒ 1641.516777216；
    //       组网 2 机：算力 25万 + 存储 12万×0.45 + 管理 0.8万 + NIC 24万 + 400G 2万 + 100G 0.3万×0.45 + AOC 4.8万
    const storageCapex16 = new Decimal('1641.516777216');
    const networkCapex16 = new Decimal(621350);
    expect(aux16.eq(storageCapex16.plus(networkCapex16))).toBe(true);
    expect(aux24.gt(aux16)).toBe(true);
    // 关键：P_aux 是「一次性快照」不再成立——改卡数后联动重算生效
    expect(aux16.eq(p24.hw.P_aux)).toBe(false);
  });

  it('单机与多机边界：24 → 8 卡（单机）组网归零，P_aux 只剩存储', () => {
    const p24 = recommendedParams('rdma', 24);
    const aux8 = recomputeSupportingCapex(p24, new Decimal(8))!;
    // 8 卡单机：存储 kv=8192×8×64×2/1e9=0.008388608 ⇒ 1641.508388608；组网 0
    expect(aux8.eq(new Decimal('1641.508388608'))).toBe(true);
  });
});
