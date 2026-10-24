# uml-diagram

UML 图生成与校验 Skill，基于本地 PlantUML + Graphviz，支持七类 UML 图和用例图双档布局。

## 安装

适用于支持 Skill / 技能机制的 Agent。把下面的地址发给你的 Agent，请它直接安装：

```text
https://github.com/WLYSZB/uml-diagram
```

示例提示词：

```text
请根据这个地址安装 Skill：
https://github.com/WLYSZB/uml-diagram
```

如果 Agent 不支持从 URL 安装，再下载 Release 中的 `uml-diagram.zip`，让 Agent 从本地压缩包安装。

- Release 下载地址：https://github.com/WLYSZB/uml-diagram/releases/latest/download/uml-diagram.zip

## 支持图种

- 类图
- 用例图
- 时序图
- 状态机图
- 活动图
- 组件图
- 部署图

## 主要能力

- 先校验后渲染，失败不交付报错图
- Graphviz `-testdot` 预检，降级行为显式可判定
- 大图使用 `-DPLANTUML_LIMIT_SIZE=16384`，避免静默截断
- 用例图自动版 + 坐标化 precise 版双档输出
- 本地离线运行，不依赖 Docker、Node 或云端渲染

## 目录

```text
uml-diagram/
├── SKILL.md
├── scripts/
├── templates/
├── examples/
└── references/
```

## 版本

- `0.1.0`：首个可安装版本，包含七类模板、校验渲染闭环、用例图坐标化输出和故障处理文档。
