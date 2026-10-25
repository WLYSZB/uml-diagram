---
name: uml-diagram
description: This skill should be used when users request UML 图、用例图、类图、时序图、状态机图、活动图、组件图、部署图、程序流程图、数据流图 DFD、业务流程图、泳道图、异常流程、对象图、通信图或设计模式类图的生成、校验、修改或批量重绘，并需要本地 PlantUML、规范 UML 表达、300dpi PNG 或用例图双档布局。Provides Windows/Git Bash workflows with syntax checks, semantic checks, Graphviz preflight, and precise use-case SVG/PNG output.
agent_created: true
---

# UML 图生成与校验（本地 PlantUML）

## 适用边界

- 支持十五类图（`templates/01` 至 `15`，图种清单见 `diagram-types.json`）：
  - UML 七类：类图、用例图、时序图、状态机图、活动图、组件图、部署图；
  - 流程类：程序流程图（08）、业务流程泳道图（12）、异常分支流程图（13）；
  - 数据流图：DFD 上下文图（09）、0 层图（10）、1 层分解图（11）；
  - 对象/通信：对象图（14）、通信图（15，object + 编号消息的近似表达，无独立通信图语法）。
- 设计模式类图示例（抽象工厂、类/对象适配器、策略、装饰器、观察者）在 `examples/patterns/`，属类图能力的示例扩展。
- 仅承诺 Windows + Git Bash + 本地 PlantUML + Graphviz；不引入 Docker、Node、云端渲染。带 `@diagram` 标记的图种语义校验需要 Python 3（仅标准库）。
- DFD 与通信图采用 PlantUML 图元的可复现近似表达，不承诺严格 Gane-Sarson/Yourdon 形状或严格 BPMN 2.0。
- 不做代码反向生成、像素级手工排版、报告标题/图注设计。
- 坐标化重排仅用于用例图，且只接受白名单子集（见 `references/modeling-rules.md` §8）。

## 资源路由

- 按图种在 `diagram-types.json` 查模板路径，选 `templates/01` 至 `15` 对应文件作为起点，替换业务元素。
- 08–15 模板首部带 `' @diagram <类型>` 标记（DFD 分解图另带 `' @parent <相对路径>`、`' @parent-process <别名>`）；新写文件保留这些标记，`uml.sh check` 会在语法校验后自动做语义校验。旧式无标记文件行为不变（只做语法校验）。
- 复制模板到工作目录时**必须同时复制 `templates/theme.puml` 并保持模板里的相对路径**（`templates/` 下是 `!include theme.puml`，`examples/` 下是 `!include ../../templates/theme.puml`）——缺主题文件校验必失败。
- DFD 成套交付（上下文图 + 0 层 + 1 层）时把三个文件放同一目录，`@parent` 写相对文件名；0 层图的外部实体数据流必须与上下文图逐条平衡（外部实体别名、方向、标签三者一致）。
- 调用脚本一律使用本 Skill 的绝对路径（下文 `<skill>` = 本 SKILL.md 所在目录），不假设用户当前目录，输出写到用户工作目录：
  - `<skill>/scripts/uml.sh`
  - `<skill>/scripts/usecase_layout.py`
  - `<skill>/scripts/diagram_check.py`（由 uml.sh 自动调用，一般不单独使用；`UML_PYTHON` 可指定解释器）

## 标准工作流

1. 写或修改 `.puml`。
2. 先校验（不出图，逐文件定位错误行）：

   ```bash
   bash <skill>/scripts/uml.sh check a.puml [b.puml ...]
   ```

3. 校验全过后渲染 PNG（内部：逐文件校验 → Graphviz `-testdot` 预检 → 隔离渲染到临时目录 → 产物齐全才替换正式产物）：

   ```bash
   bash <skill>/scripts/uml.sh png a.puml [b.puml ...]
   ```

4. 用例图追加坐标化双档（自动版不被覆盖）：

   ```bash
   python <skill>/scripts/usecase_layout.py a.puml a-precise.svg --png a-precise.png
   ```

5. 自动版 `<名>.png` 与坐标版 `<名>-precise.svg`/`-precise.png` 都保留，按版面要求选用；确认日志出现 `Graphviz: …（-testdot 预检通过）` 再交付。

## 失败处理

- check 失败：先修 DSL 再渲染；绝不交付报错图或旧图。
- 语义校验失败（`[失败] … (语义校验)`，错误定位到 `文件:行号`）：按 DFD/流程规则逐条修复建模错误，不要删掉 `@diagram` 标记绕过；校验器不会静默跳过已标记的图种。
- Graphviz 预检失败：默认停止（不渲染、不产图）。仅当用户明确要降级草稿时设置 `UML_ALLOW_DEGRADED=1`，产物带"降级"标记，不视为正式交付。
- 坐标化报"不支持的语法 / include 含模型定义 / 端点未定义"：按错误行号和原文逐条修复，不要绕过或静默忽略。
- Edge 失败（UML_EDGE 无效、PNG 尺寸与 viewBox 不符）：不交付任何产物；绝不交付新旧不一致的 SVG/PNG 组合。
- 详细处置见 `references/troubleshooting.md`。

## 输出与复杂度

- 正式交付 = `.puml` 源文件 + PNG（300dpi，微软雅黑）；SVG 只作可编辑中间产物，不外发（SVG 只引用字体不嵌入，换机走形）。
- 活动图超过 2–3 个泳道或嵌套判断层时拆图；活动图不走 Graphviz，工具救不了布局。
- 新图种可抄的完整范本：`examples/dfd/`（三层成套 + 父子平衡）、`examples/flow/`（当型/直到型循环）、`examples/business-process/`（泳道 + 异常分支）、`examples/patterns/`（六个设计模式类图）。
- 时序图过高时 `uml.sh` 已用 `-DPLANTUML_LIMIT_SIZE=16384` 保证完整不截断；版面仍过大就按业务段落拆分为多页。`examples/atm/atm3-sequence.puml` 是需要控制页高的长图示例。
- 超大类图（30 类以上）不承诺布局效果，建议拆分。

## 参考文档（按需读取，勿预载）

- `references/modeling-rules.md`：include/extend 方向、组合聚合菱形端、复合状态外部迁移、hide circle 与 stereotype、活动图泳道/嵌套限制、时序图 alt 与分页、用例图坐标化白名单与双档选择、DFD 三层结构与父子平衡、流程图分支标签与循环闭合规则。
- `references/troubleshooting.md`：-checkonly 与禁用 -syntax、语义校验错误定位与修复、-testdot 预检与降级策略、PLANTUML_LIMIT_SIZE、隔离渲染与提交回滚、SVG 字体与 PNG 交付、Edge 参数与 IHDR 校验、jar 下载镜像。
