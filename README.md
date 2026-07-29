# 半导体信号系统

回答一个问题：**存储/半导体现在处于周期什么位置？**
五个公开数据信号 → 三盏灯 → 一张记分卡。个人学习研究工具，不构成投资建议。

## 快速开始

双击 `run_app.bat`，浏览器打开 http://localhost:8501 。

1. 先到「数据更新」点**一键更新全部数据源**
2. 回首页看记分卡（综合评分 + 五张信号卡）
3. 不懂原理看「新手教程」（5 分钟入门 + 进阶决策手册）；想深究某个信号看「信号详情」（历史曲线 + 阈值可调）；想看现货价对三只模组股（江波龙/佰维存储/德明利）的实际映射力度看「映射分析」

建议频率：价格/拥挤度/热搜每周，盈利预测每周（积累修正轨迹），台股营收每月 10 日后。

## 五个信号与数据源

| 信号 | 数据源 | 频率 | 打分规则（默认，可调） |
|:--|:--|:--|:--|
| 存储价格趋势 | CFM 中国闪存市场 `/price/ddr`（DRAM 现货周价） | 每周 | 涨🟢 平🟡 跌🔴 |
| 台系营收验证 | TWSE 官方开放数据 `t187ap05_L`（南亚科/华邦电/旺宏/台积电月营收） | 每月 | 同比>20%🟢 0~20%🟡 <0%🔴 |
| 盈利预测修正 | 同花顺（akshare `stock_profit_forecast_ths`，6 只 A 股存储） | 每周快照积累 | 当年预测 30 日修正 >0🟢 ≈0🟡 <0🔴（不足两次快照 ⚪） |
| 板块拥挤度 | 新浪日线成交额 / 20 日均值 | 每日 | 量比>2🔴 1~2🟡 <1🟢 |
| 热搜情绪温度 | 热榜雷达库（mrs.db，微博热搜存档，只读） | 每日 | 60 日分位 >90%🔴 >50%🟡 其他🟢 |

综合评分 = 🟢数 − 🔴数（⚪ 不参与）。**经验规则，未经回测，不构成投资建议。**

## 原理（一句话版）

存储是强周期行业，股价跑在财报前面，所以盯比财报更快的信号：
现货价（领先业绩 1~2 个季度）、台股月营收（月度客观验证）、盈利预测修正（聪明钱风向）、
拥挤度与热搜（两盏风险灯——实证研究证明热搜爆表是见顶信号而非买入信号）。

## 已知限制

- CFM 价格页与 TWSE 开放接口只给最新一期；台系营收可从 MOPS 回填近 12 个月，存储现货价可从 CFM 产品详情页回填近半年（一年期需 CFM 会员，未接入），其余历史靠系统持续积累，越用越准
- 盈利预测为快照式，「修正」需至少两次快照
- 热搜热度由本系统每日自采微博热搜快照积累（历史已从热榜雷达库一次性迁移）；热度稀疏，多数天数为 0 属正常
- 本机东财接口不可用，行情走新浪源；网络异常时代理/直连自动切换

## 测试

```
python tests/test_sources.py    # 逐源真实抓取
python tests/test_pipeline.py   # 端到端冒烟
```

## 命令行采集（本地手动 / CI 自动）

除了 Streamlit 看板的「一键更新」按钮，也可以命令行直接采集，便于定时任务或 CI：

```
python scripts/collect.py                                  # 跑全部 5 个采集器
python scripts/collect.py --only crowding,hot_heat         # 只跑指定源
python scripts/collect.py --backfill tw_revenue            # 顺带回填台股近 12 月
python scripts/collect.py --backfill dram_price            # 顺带回填存储价近半年
python scripts/collect.py --json                           # 输出 JSON 摘要（CI 友好）
```

退出码：`0` 全部成功，`1` 有失败源（已写 fetch_log，可重试），`2` 参数错误。

## 回测验证（Backtrader）

**把"经验规则，未经回测"换成实测数据。** 在看板「回测验证」页（`app/pages/5_回测验证.py`）：

1. 系统从 db 读取 5 个信号的历史数据，对每个交易日重新计算综合评分（与首页记分卡同逻辑）
2. 评分作为交易信号：≥3 满仓 / 1~2 半仓 / 0 观望 / -1~-2 半仓 / ≤-3 清仓
3. 标的为 6 只 A 股存储股等权组合，Backtrader 跑回测
4. 对比"买入持有"基准，输出：夏普 / 最大回撤 / 年化收益 / 资金曲线 / 交易明细

### 当前回测结果（2026-01-01 ~ 2026-07-29）

| 指标 | 策略（评分信号） | 基准（买入持有） |
|:--|:--|:--|
| 总收益 | +21.64% | +53.10% |
| 年化收益 | +41.78% | +113.60% |
| 夏普比率 | 0.060 | — |
| 最大回撤 | 44.37% | — |
| 超额收益 | -31.46% | — |

**关键发现**：在 2026 上半年的单边上行市中，评分信号策略跑输买入持有。这说明评分信号的减仓动作在牛市中损失收益，**可能在震荡市/下行市更有价值**——这正是回测揭示的、仅凭直觉看不到的事实。

### 数据限制

- 系统从 2026-01 开始积累数据，回测窗口仅半年，**统计意义有限**
- 随 CI 自动积累，数据会越来越长，回测结果越来越可靠
- 回测避免了前视偏差：每个交易日只用截至当日已知信号
- 简化假设：等权组合作为单一资产回测，未考虑停牌/涨跌停/滑点；实盘表现可能差于回测

### 命令行跑回测

```bash
python tests/test_backtest_full.py    # 完整回测流程测试
```

## 自动采集与 Git 同步（GitHub Actions）

`.github/workflows/collect.yml` 已配置定时自动采集，**解决「历史靠积累」痛点**——无需每周手动点更新。但涉及"本机数据库"和"远端数据库"两份 db，容易绕晕。下面从原理到案例一次说清。

### 1. 它在做什么（白话版）

GitHub 在它的服务器上，按你设定的时间自动跑 `scripts/collect.py`，把抓到的数据写进**远端仓库**的 `data/signals.db`，然后 commit & push 回 GitHub。

**关键认知**：你有**两份** `signals.db`：

| 位置 | 谁会改它 | 你怎么看 |
|:--|:--|:--|
| **本机**：`D:\...\半导体信号系统\data\signals.db` | 你本机点「一键更新」或跑 `scripts/collect.py` | Streamlit 看板读的就是这份 |
| **远端**：GitHub 仓库里的 `data/signals.db` | GitHub Actions 每周一/周四自动跑 | 网页上看到的是这份 |

两份**互不自动同步**。CI 跑完不会魔法地更新你本机，本机改了也不会自动推到远端。要同步，必须手动 `git pull` 或 `git push`。

### 2. 第一次启用（手把手，含踩坑提示）

#### 步骤 1：在 GitHub 创建空仓库

去 https://github.com/new ，仓库名填 `semiconductor-signal-system`，**不要勾选** "Add a README" / "Add .gitignore" / "Add license"（保持空仓库，避免冲突），点 Create。

#### 步骤 2：本机初始化并推送

在 PowerShell 里：

```powershell
cd "D:\python projects\量化交易系统\半导体相关策略\半导体信号系统"

# 初始化 git 仓库
git init
git add .
git commit -m "init: semiconductor signal system with auto-collect"

# ⚠️ 关键：把默认分支改名为 main（GitHub 默认是 main，本机 git 默认可能是 master）
git branch -M main

# 关联远端仓库（注意：URL 不要用反引号包裹！直接贴裸 URL）
git remote add origin https://github.com/luozhengyuan/semiconductor-signal-system.git

# 推送
git push -u origin main
```

#### 步骤 3：开启 Workflow 写权限

去仓库网页 `https://github.com/luozhengyuan/semiconductor-signal-system`：

1. 点 `Settings` → 左侧 `Actions` → `General`
2. 滚到页面下方 **Workflow permissions**
3. 勾选 **Read and write permissions**
4. 点 Save

#### 步骤 4：手动跑一次验证

1. 仓库网页点 `Actions` 标签页
2. 左侧选 `Auto Collect`
3. 右侧点 `Run workflow` → 下拉选 `full` → 点绿色 `Run workflow` 按钮
4. 等待 2-3 分钟，跑完后会看到一次新的 commit（message 形如 `chore(data): auto-collect 2026-07-29 [mode=full]`）

### 3. 日常使用：三种场景对照

| 场景 | 你要做什么 | 为什么 |
|:--|:--|:--|
| **本机看实时数据** | 直接点 Streamlit 看板的「一键更新」 | 写的是本机 db，立即生效 |
| **同步 CI 这周自动积累的数据到本机** | `git pull` | 远端 db 被 CI 更新了，本机还是旧的 |
| **本机 db 改动想推到远端** | `git add data/signals.db && git commit && git push` | 把本机改动同步到远端 |

#### 案例 A：周三晚上想看最新信号

```powershell
# 本机直接点「一键更新」即可，不用 git pull
# 原因：本机 db 是最新的，CI 这周一跑过的数据在远端，但你不需要——本机自己也能采
```

#### 案例 B：出差两周没开本机，回来想看连续数据

```powershell
cd "D:\python projects\量化交易系统\半导体相关策略\半导体信号系统"
git pull
# 现在 data/signals.db 包含了 CI 这两周自动采集的连续数据
# 打开 Streamlit 看板，历史曲线会连续
```

#### 案例 C：本机点了「一键更新」后想把新数据推到远端

```powershell
git add data/signals.db
git commit -m "chore(data): manual collect on $(Get-Date -Format 'yyyy-MM-dd')"
git push
```

### 4. 推荐工作流（最省心）

为了避免冲突，建议**职责分离**：

- **CI 负责自动积累历史**：每周一/周四自动跑，更新远端 db
- **本机负责看实时**：点「一键更新」看当前信号，但**不要 commit 本机 db**
- **每周/每月一次同步**：`git pull` 把 CI 积累的数据拉到本机

**铁律**：本机点完「一键更新」后，**不要** `git add data/signals.db`。本机 db 当作"临时视图"用，远端 db 才是"权威历史"。这样 `git pull` 永远不会冲突。

### 5. `git pull` 冲突了怎么办

`signals.db` 是二进制文件，git 没法自动合并。如果本机和远端都改了 db，pull 会报错：

```
CONFLICT (content): Merge conflict in data/signals.db
```

#### 选择一：放弃本机 db，用远端的（推荐）

```powershell
git checkout --theirs data/signals.db
git add data/signals.db
git commit -m "resolve: use remote db"
```

适用场景：你信任 CI 自动积累的数据，本机这次更新不要了。

#### 选择二：放弃远端 db，用本机的

```powershell
git checkout --ours data/signals.db
git add data/signals.db
git commit -m "resolve: use local db"
git push  # 把本机版本推到远端，覆盖 CI 这次的结果
```

适用场景：本机有 CI 没抓到的数据（比如你手动跑了回填）。

#### 选择三：完全避免冲突（终极方案）

让本机 db 不进 git 跟踪：

```powershell
# 从 git 跟踪中移除，但保留本机文件
git rm --cached data/signals.db
echo "data/signals.db" >> .gitignore
git add .gitignore
git commit -m "chore: stop tracking local signals.db"
git push
```

代价：CI 跑完后的数据无法通过 git 同步到本机，本机只能自己点「一键更新」。

### 6. 常见错误与解决

#### 错误 1：`error: src refspec main does not match any`

**原因**：本机分支叫 `master`，你却 `git push -u origin main`。

**解决**：

```powershell
git branch -M main   # 把 master 改名为 main
git push -u origin main
```

#### 错误 2：`fatal: invalid refspec` 或 remote URL 带反引号

**原因**：在 PowerShell 里用反引号 `` ` `` 包裹 URL（反引号在 PowerShell 是转义符，不是字符串引号）。

**错误写法**：

```powershell
git remote add origin `https://github.com/.../xxx.git`   # ❌ 反引号会被吃掉或保留
```

**正确写法**：

```powershell
git remote add origin https://github.com/.../xxx.git     # ✅ 裸 URL
```

**修复已经加错的 remote**：

```powershell
git remote remove origin
git remote add origin https://github.com/luozhengyuan/semiconductor-signal-system.git
git remote -v   # 验证 URL 干净，应该输出两行不带反引号的 URL
```

#### 错误 3：`warning: LF will be replaced by CRLF`

**这不是错误**，是 Windows 正常现象。Git 自动处理换行符：仓库里存 LF，工作区用 CRLF。可以忽略。

想消掉警告：

```powershell
git config core.autocrlf true
```

#### 错误 4：GitHub Actions 跑了但 db 没更新

**可能原因**：

1. Workflow permissions 没开（步骤 3 没做）→ 去 Settings → Actions → General → Workflow permissions 勾选 Read and write
2. Actions 被 GitHub 暂停（仓库长期不活动会自动暂停）→ 仓库 Actions 页会提示 "This scheduled workflow is disabled because there hasn't been activity in this repository for at least 60 days"，点 Enable 即可
3. 采集器全失败（akshare 接口临时不可用）→ 看 Actions 日志，重跑一次

#### 错误 5：`git pull` 时提示 `Your local changes to the following files would be overwritten by merge`

**原因**：本机 db 有未提交的改动，pull 会覆盖。

**解决**：

```powershell
# 方案 A：本机改动不要了
git checkout data/signals.db
git pull

# 方案 B：本机改动想留着，先暂存
git stash
git pull
git stash pop   # 恢复本机改动（可能冲突，需手动解）
```

### 7. 定时频率说明

`.github/workflows/collect.yml` 里的 cron 用的是 **UTC 时间**，北京时间 = UTC+8：

| cron (UTC) | 北京时间 | 跑什么 |
|:--|:--|:--|
| `0 1 * * 1` | 周一 09:00 | 全量（5 个信号源） |
| `0 1 * * 4` | 周四 09:00 | 高频（拥挤度 + 热搜） |

想改频率，编辑 `.github/workflows/collect.yml` 里的 `schedule` 部分。例如改成每天 09:00 跑高频：

```yaml
schedule:
  - cron: '0 1 * * 1'   # 周一全量
  - cron: '0 1 * * 2,3,4,5'  # 周二到周五高频
```

**注意**：GitHub Actions 的 cron 不保证准时，可能延迟 5-15 分钟，高峰期甚至更久。这是免费版的限制，不影响功能。

### 8. 失败容错

- **单源失败不阻塞**：5 个采集器中任一失败，其余照常跑，失败信息写入 `fetch_log` 表
- **Workflow 整体标红**：任一采集器失败，Actions 页这次运行会显示红色 ❌，便于发现
- **已积累数据不丢**：失败源的旧数据仍在 db 里，下次成功跑会更新
- **可重试**：失败后去 Actions 页点 `Re-run all jobs` 即可重跑

## 免责声明

本系统仅为个人学习与研究工具。所有信号、评分、仓位参考均为经验规则，未经严格回测，
不构成投资建议。据此操作，风险自负。
