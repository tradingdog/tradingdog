# 播放列表多平台自动化管理工具 - 项目记忆

版本: v0.1.19  
最后更新: 2026-04-04  
状态: 新目录主版本维护中

---

## 头部维护规范

1. 默认维护目录: adding_playlist_main。
2. 只要程序代码有修改，必须同步执行以下动作:
- 递增 APP_VERSION。
- 更新 UPDATE_NOTES。
- 更新本文件的版本与更新历史。
- 提交到仓库，并推送到远端。
3. 历史写入策略: 仅在平台流程成功后提交历史；失败或中断不写入专辑历史与播放列表历史。
4. 日志命名策略: 统一写入 logs 目录，命名格式为 playlist_run_平台_模式_时间.log。

---

## 当前版本概览

- 主程序入口: main.py
- 配置文件: config.py
- 平台模块: platforms/tidal.py, platforms/apple.py, platforms/qobuz.py
- 工具模块: utils/browser.py, utils/logging_setup.py, utils/helpers.py, utils/playlist_core.py
- 事务日志文件: .history_tx.log
- 运行日志目录: logs/

---

## 当前核心行为

### 1) 历史事务化写入

- prepare: 先生成清单与待提交历史，不立即写 album history。
- commit: 平台执行成功后再提交历史。
- discard: 失败或中断时写事务日志并放弃提交。

对应实现:
- prepare_playlist_output: utils/playlist_core.py
- commit_prepared_history: utils/playlist_core.py
- append_history_tx_log: utils/playlist_core.py

### 2) Tidal 多账号隔离

- 每个账号独立生成一次清单。
- 账号成功才提交该账号历史。
- 账号失败只记录 discard，不污染历史池。

### 3) Apple / Qobuz

- 流程成功后才提交历史并写入已使用播放列表名。
- 中断或失败时不提交历史。

### 4) 日志规范

- 文件目录: logs/
- 文件命名: playlist_run_平台_模式_yyyyMMdd_HHmmss.log
- 示例: playlist_run_T_run_20260404_040856.log

---

## 运行参数

主参数:
- --Platform {A,T,Q}
- --Count 数量
- --tidal
- --tidal-delete
- --version

默认行为:
- 平台为 T 且未显式指定时，默认启用 tidal 添加流程。
- 当配置中 TIDAL_MODE=2 时，自动进入 tidal 删除模式。

---

## 关键文件说明

- config.py: 全局配置、版本号、日志路径、历史文件路径。
- main.py: 参数解析、平台调度、成功后提交历史。
- utils/playlist_core.py: 抽样、历史、事务日志。
- utils/logging_setup.py: 统一日志初始化与命名。

---

## 更新历史

### v0.1.19 - 2026-04-04

- 规范化日志命名与目录。
- 新日志写入 logs/ 目录。
- 日志格式统一为 playlist_run_平台_模式_时间.log。

### v0.1.18 - 2026-04-04

- 增加历史事务日志 .history_tx.log。
- 记录 prepare/commit/discard。
- 中断场景补齐 discard 记录。

### v0.1.17 - 2026-04-04

- 历史改为成功后提交。
- 失败账号和中断流程不写入历史。

### v0.1.16 - 2026-04-04

- 新目录入口兼容调整（历史阶段性变更记录）。

### v0.1.15 - 2026-04-04

- 新旧目录版本号统一。

---

## 待办

1. 对 Apple/Qobuz 页面选择器做鲁棒性增强。
2. 增加历史事务日志的自动清理策略（按天轮转）。
3. 为历史事务流程补充最小化测试样例。
