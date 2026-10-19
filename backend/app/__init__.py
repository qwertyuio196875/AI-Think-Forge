"""ThinkForge 后端应用包。

分层：包含 api（HTTP 边界）、db（SQLite 访问）、models（Pydantic 数据结构）、
providers（模型客户端 / URL 抓取器接缝）、grilling / analysis / generation
（业务管线，后续工单填充）、security（安全策略，后续工单填充）。
"""
