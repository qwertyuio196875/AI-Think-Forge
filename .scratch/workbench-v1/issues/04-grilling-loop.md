# 04 - 拷问闭环（价值核心）

Status: ready-for-agent

## 目标

LangGraph 状态机移植 grilling 规则（ADR-0001）：每轮输出前沿式问题集（1~N 独立题，各附 ➡️ 推荐），回答后重算；不重复问已知信息；不确定时给备选方向；关键问题解决即收敛生成结构化方案（Markdown）；方案对话式修订；显式确认闸门后才放行生成。系统提示词以 `C:\Users\33569\.agents\skills\grilling\SKILL.md` 规则为底，MIT 署名写入代码注释。messages/plans 每轮落库（接 05）。

## 验收

- 模拟对话单测：简单任务 ≤2 轮收敛、复杂任务动态追答、确认前不触发生成；一轮真人演示记录。

## Comments

- （待补）
