"""anomaly-atlas：把一条时间序列变成可复算的异常档案。

- 确定性内核：CSV 契约解析、数据剖面、4 类检测器、Episode 合并、规范 JSON 与 sha256。
- 交付形态：单文件 HTML（内嵌原始数据与手写 JS 镜像，加载时当场复算出同一指纹 → VERIFIED）。
- 模型只做表达层：异常点、参数最终值、排序、指纹全部由本包代码产出。

版本与规范版本分开：`VERSION` 是包版本，规范 JSON 的形态版本见 `canon.CANON_VERSION`。
"""

VERSION = "0.1.0"

__all__ = ["VERSION"]
