# untangle-opt-lab

`untangle` 把 XML 转成 Python 对象；本仓库把它按标签查找子节点的线性扫描换成带长度守卫的名字索引，并用同一份基准测出：宽文档的查询开销从 O(n²) 回到 O(n)。

Upstream: https://github.com/stchris/untangle

上游提交：`8a4740cf5eb54bb4166e4a4986222a89549127f5`（2026-10-26）。改动只有一个文件、19 行新增 / 3 行删除，见 `patch.diff`。

## 结果

工作负载：解析一份「N 个互不相同的兄弟标签」的宽 XML，然后对每个标签调用一次 `get_elements(tag)`（XML→dict 消费者的典型用法）。每个规模 3 次 warmup + 5 次计时，取中位数；种子 `20261031`。

| 规模（不同兄弟标签数） | 基线中位数 | 优化后中位数 | 加速比 |
| --- | --- | --- | --- |
| 250 | 2.148 ms | 0.869 ms | 2.47x |
| 1000 | 25.206 ms | 3.408 ms | 7.40x |
| 4000 | 381.947 ms | 15.618 ms | 24.46x |

三个规模加速比的中位数：**7.40x**。最大规模（4000）加速比 **24.46x**，未退化。

完整分位数：

| 规模 | 基线 p25 / p75 | 优化 p25 / p75 | 基线 RSD | 优化 RSD |
| --- | --- | --- | --- | --- |
| 250 | 2.119 / 2.180 ms | 0.857 / 0.878 ms | 8.47% | 16.94% |
| 1000 | 25.080 / 25.255 ms | 3.402 / 3.426 ms | 0.41% | 2.07% |
| 4000 | 381.381 / 382.334 ms | 15.542 / 17.187 ms | 0.43% | 9.08% |

250 规模的优化后 RSD 为 16.94%（>10%）：该规模绝对耗时不足 1 ms，噪声主要来自 `perf_counter()` 分辨率、解释器调度与短生命周期对象的分配器抖动；同一规模的基线 RSD 为 8.47%，加速比 2.47x 远高于噪声幅度。原始 5 次样本全部保存在 `benchmark/raw/`。

## 差分与质量闸门

差分测试 `tests/test_diff.py`：**1215 组**输入（1200 组固定种子随机文档 + 15 组边界文档），覆盖空文档、单元素、重复标签、Unicode 标签/文本、CDATA、属性转义、注释/PI、500 兄弟、100 层嵌套、10k 长文本、关键字标签、非法 XML 与 XXE。每组把整棵树（标签名、属性、cdata、子节点顺序）序列化成规范 JSON 后逐字节比较，并比较 `str` / `repr` / `dir` / 每个标签的 `get_elements` / `hasattr` / `in`。结果：**0 差异**。

| 闸门 | 结论 | 复现命令 |
| --- | --- | --- |
| G1 上游测试全绿 | 通过：改动后 99 passed, 0 failed（0.93s） | 见下方 G1 命令 |
| G2 差分一致 | 通过：1215 组，0 差异 | `python -m pytest tests/test_diff.py -q` |
| G3 中位加速 ≥1.15x | 通过：7.40x | 读取 `benchmark/*.json` 的 `results.*.median_s` |
| G4 最大规模不退化 | 通过：24.46x（≥0.95x） | 同上，规模 4000 |
| G5 峰值 RSS ≤1.10x | 通过：26.4 MiB / 25.5 MiB = 1.035x | `python -c "import json;b=json.load(open('benchmark/baseline.json'));o=json.load(open('benchmark/optimized.json'));print(o['peak_rss_kb']/b['peak_rss_kb'])"` |

G1 的原始命令（在干净 clone 上先 `git apply --check`，再跑上游自己的测试）：

```bash
python3 -m venv /tmp/venv-untangle && /tmp/venv-untangle/bin/pip install 'defusedxml==0.7.1' 'pytest==9.2.0'
git clone --depth=1 git@github-linluozi:stchris/untangle.git /tmp/untangle-g1
cd /tmp/untangle-g1 && git apply /path/to/untangle-opt-lab/patch.diff
PYTHONPATH=src /tmp/venv-untangle/bin/python -m pytest tests -q
```

本机实测输出：`99 passed in 0.93s`（未改动基线为 `99 passed in 0.80s`）。`git apply --check patch.diff` 在干净 clone 上通过。

## 复现

```bash
python3 -m venv .venv && .venv/bin/pip install -q 'defusedxml==0.7.1' 'pytest==9.2.0' && .venv/bin/python -m pytest tests/test_diff.py -q
.venv/bin/python benchmark/bench.py --impl baseline --out benchmark/baseline.json
.venv/bin/python benchmark/bench.py --impl optimized --out benchmark/optimized.json
```

差分测试：`.venv/bin/python -m pytest tests/test_diff.py -q`（期望 `5 passed`，内部断言 1215 组）。

## 环境

- CPU：AMD EPYC 7K62 48-Core Processor，4 vCPU（KVM）
- 内存：3,812,564 kB（约 3.64 GiB）
- 运行时：Python 3.12.3；pytest 9.2.0；defusedxml 0.7.1
- 种子：20261031；warmup 3 次，计时 5 次；计时器 `time.perf_counter()`
- 上游：`stchris/untangle` @ `8a4740cf5eb54bb4166e4a4986222a89549127f5`

## 本轮创新

**首次把「XML 宽度」当作独立变量来测 untangle 的查询复杂度**：解析阶段随文档线性增长，但 `get_elements` / 未命中 `__getattr__` / `__hasattribute__` 每次都线性扫 `children`，因此「宽文档 + 按标签查询」是 O(兄弟数²)，而深文档不退化。实测 4000 个兄弟时查询占端到端 96.5%（parse 13.55 ms / query 373.95 ms，见 `benchmark/baseline.json` 的 `phase_split_4000`），把瓶颈从「SAX 解析」定位到「查询侧」；修法是长度守卫的名字索引（19 行新增），在 1215 组逐字节差分一致的前提下取得 7.40x 中位加速、24.46x 最大规模加速，RSS 仅 +3.5%。与只做一次 `root.tag` 访问的常见用法不同，这个退化只有在「按标签遍历整份宽文档」时才可见，也正是本次新测量的角落。

## 改动说明

`src/untangle_optimized.py` 是打好补丁的完整模块；`src/untangle_baseline.py` 是同一提交的未改动模块，供离线基准与差分复算。`Element.__init__` 建立 `_children_by_name` 索引，`add_child` 维护它；`_ensure_index()` 在 `len(children)` 与已索引数量不一致时重建，因此直接 `append` / `del` 公共 `children` 列表仍然正确。`get_elements` 返回新列表、`get_elements(None)` 仍返回 `self.children` 本身，公共 API 与返回语义不变。
