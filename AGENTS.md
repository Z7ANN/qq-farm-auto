# AGENTS.md

## 项目概览

- 项目名称：`QQ Farm Vision Bot`
- 技术栈：`Python + PyQt6 + OpenCV + mss + pyautogui + pydantic + loguru`
- 平台约束：`Windows 10/11`（依赖 `pygetwindow` 与 Win32 API）
- 运行方式：纯视觉识别与鼠标模拟，不调用游戏接口

## 功能现状

### 已实现（代码已落地）

- 农场主循环调度：定时触发、可暂停/恢复/停止
- 窗口查找与调整：按标题定位窗口并调整尺寸/位置
- 截图与识别：模板匹配（多尺度 + NMS）与场景识别
- 自动收获：`btn_harvest`
- 自动维护：`btn_weed / btn_bug / btn_water`
- 自动播种：识别空地后拖拽播种
- 缺种自动购买：打开商店匹配 `shop_作物名` 完成购买
- 扩建土地：`btn_expand -> btn_expand_confirm`
- 任务处理：任务奖励领取、任务触发的仓库出售
- 好友帮忙：进入好友农场后浇水/除草/除虫并回家
- 弹窗处理：关闭、确认、分享后 `Esc` 取消（双倍奖励）
- GUI：状态/设置/出售三页，实时保存 `config.json`
- 热键：`F9` 暂停/恢复，`F10` 停止

### 未完成（当前为占位/空实现）

- `check_friends()` 主流程仅返回“开发中”
- 自动偷菜：`FriendStrategy.try_steal()` 未实现
- 自动同意好友：`FriendStrategy.try_accept_friend()` 未实现
- `ExpandStrategy.try_claim_task()` 未实现

## 核心架构

### 分层职责

1. GUI 层：`gui/`
2. 主控编排层：`core/bot_engine.py`
3. 识别层：`core/cv_detector.py` + `core/scene_detector.py`
4. 策略层：`core/strategies/*.py`
5. 执行层：`core/action_executor.py`
6. 基础设施：窗口管理、截图、调度、日志、配置与静态数据

### 关键执行链路

1. `main.py` 启动 GUI，加载 `config.json`
2. `MainWindow` 创建 `BotEngine`
3. `BotEngine.start()`：
   - 加载模板
   - 查找/调整游戏窗口
   - 初始化执行器与策略依赖
   - 启动 `TaskScheduler` 定时器
4. 定时触发后由 `BotWorker(QThread)` 执行 `check_farm()`
5. 每轮执行：
   - 截图 -> 检测 -> 场景识别
   - 按优先级策略尝试动作
   - 记录动作并计算下一次检查时间

### 策略优先级（实际注册顺序）

1. `PopupStrategy`（P-1）
2. `HarvestStrategy`（P0）
3. `MaintainStrategy`（P1）
4. `PlantStrategy`（P2）
5. `ExpandStrategy`（P3）
6. `TaskStrategy`（P3.5）
7. `FriendStrategy`（P4）

## 实现要点

### 视觉识别

- 模板目录：`templates/`
- 分类依据：文件名前缀（`btn/icon/crop/land/seed/shop`）
- 匹配策略：`cv2.matchTemplate`，尺度 `[1.0, 0.9, 0.8, 1.1, 1.2]`
- 去重：NMS（IoU 阈值 0.5）
- 特殊阈值：
  - `land` 类别默认 0.89
  - `button`/其他默认 0.8
  - `shop_` 种子卡片通常用更高阈值（0.9）

### 场景识别

- 入口：`identify_scene()`
- 通过检测结果组合判断：
  - 购买弹窗、商店页、好友家园、地块菜单、种子选择、通用弹窗、升级弹窗、农场主界面、未知场景

### 配置与实时生效

- 配置模型：`models/config.py`（Pydantic）
- GUI 设置自动保存到 `config.json`
- `MainWindow._on_config_changed()` -> `BotEngine.update_config()`
- 出售配置由 `TaskStrategy.sell_config` 使用

### 日志与产物

- 日志目录：`logs/`（按天滚动，保留 7 天）
- 截图目录：`screenshots/`
- 每轮结束会清理截图（当前调用为 `cleanup_old_screenshots(0)`，实际会尽量不保留历史）

## 目录速览

- `main.py`：程序入口
- `core/`：调度、识别、策略、执行
- `gui/`：主窗口与面板
- `models/`：配置、动作模型、作物静态数据
- `templates/`：模板资源（识别能力核心输入）
- `tools/template_collector.py`：模板采集工具
- `tools/import_seeds.py`：种子模板批量导入

## Agent 协作准则

### 新增自动化能力的标准路径

1. 在 `core/strategies/` 新增策略类（继承 `BaseStrategy`）
2. 在 `core/strategies/__init__.py` 导出
3. 在 `BotEngine.__init__` 注册并确定优先级
4. 在 `check_farm()` 或对应流程接入开关与执行分支
5. 在 `models/config.py` 增加功能开关
6. 在 `gui/widgets/settings_panel.py` 暴露配置项
7. 补充所需模板（`templates/`）与采集说明

### 修改识别能力时

- 优先补模板，其次再调阈值
- 调阈值时需同步评估误检率与漏检率
- 新模板命名必须遵守前缀规范，否则不会被自动归类

### 修改调度/线程时

- `TaskScheduler` 基于 Qt 事件循环，避免阻塞 UI 线程
- 重任务放在 `BotWorker(QThread)`，不要在主线程做耗时循环
- `ScreenCapture` 每次截图新建 `mss` 实例（代码中用于规避跨线程问题）

### 已知实现缺口（改动前先确认）

- `features.auto_sell` 当前未直接参与决策分支，出售主要由 `auto_task + TaskStrategy` 驱动
- 好友巡查主流程仍是占位实现，若接入需先补导航与返回闭环

## 本地开发命令

```bash
pip install -r requirements.txt
python main.py
python tools/template_collector.py
python tools/import_seeds.py
```

