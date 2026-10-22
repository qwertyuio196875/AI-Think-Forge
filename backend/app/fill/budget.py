"""目标字数的逐章分摊（工单 15 / ADR-0006）。

规格（issue #2 §字数控制）原文：「逐章分摊：按章节权重（由方案里的『建议字数』或字数
均值给出）分配，余数给最后一章，保证各章之和 = 目标字数。」

三条不可让的纪律：

1. **和恒等于目标**：分摊结果各章相加**恰好**等于目标字数。差一个字的误差都会让下游
   #16 的偏差校验失去基准，也会让用户数出来的数与系统给的数对不上（US 18）。
2. **权重来自方案，不来自章节表**：章节表的 `target_length` 是**上一次分摊的产物**，
   拿它当权重会让每次重新分摊都放大上次的偏差（重分配 2000 字后再按 1200/800 当权重，
   权重比例会被固化）。所以权重一律回源头读方案「章节」一节的「建议字数」。
3. **不静默改用户的数**：用户逐章改过的值原样保留；剩余的额度才由系统分摊。额度不够
   分（用户改后的和已超目标、或剩余额度连每章 1 字都不够）时明确拒绝，不偷偷压缩。

分摊算法本身是纯函数，`allocate_lengths` 不碰库、不抛 HTTPException，由 `app.fill.service`
把失败原因翻成 422。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AllocationError(Exception):
    """分摊不成立的原因（由服务层翻成 422，不在这里抛 HTTP 异常）。

    `detail` 面向用户，必须说清「为什么不行」与「差多少」，不能只说「参数非法」。
    """

    detail: str


def allocate_lengths(
    *,
    target_length: int,
    seqs: Sequence[int],
    weights: Mapping[int, int | None],
    overrides: Mapping[int, int] | None = None,
) -> list[int]:
    """把 `target_length` 分给 `seqs` 里的各章，返回与 `seqs` 同序的字数清单。

    - `weights`：各章权重（方案的建议字数）；缺失或非正数的章，整份清单退化为**均分**
      （规格的「字数均值」），而不是把缺失章当 0 权重饿死；
    - `overrides`：用户逐章改过的值（序号 → 字数），原样保留，只分摊剩余额度；
    - 余数一律归**最后一章**（规格明文），保证各章之和恰好等于目标。

    分摊不成立时抛 `AllocationError`，调用方据此拒绝请求。
    """
    seq_list = list(seqs)
    if not seq_list:
        raise AllocationError("没有可分摊的章节，无法按目标字数分摊")

    fixed = dict(overrides or {})
    unknown = sorted(set(fixed) - set(seq_list))
    if unknown:
        # 服务层已先行校验过；这里兜底，避免静默丢弃用户给的数。
        raise AllocationError(
            f"逐章字数里出现了当前方案不存在的章节序号：{'、'.join(str(seq) for seq in unknown)}"
        )

    fixed_total = sum(fixed.values())
    if fixed_total > target_length:
        raise AllocationError(
            f"逐章字数之和 {fixed_total} 已超过目标字数 {target_length}："
            "请调低某些章的字数，或提高目标字数"
        )

    rest = [seq for seq in seq_list if seq not in fixed]
    remaining = target_length - fixed_total

    if not rest:
        if remaining != 0:
            raise AllocationError(
                f"逐章字数之和 {fixed_total} 与目标字数 {target_length} 不一致："
                f"差 {abs(remaining)} 字；请补齐差额或调整目标字数"
            )
        return [fixed[seq] for seq in seq_list]

    if remaining < len(rest):
        raise AllocationError(
            f"目标字数 {target_length} 不足以给剩余 {len(rest)} 章各分 1 字："
            "请提高目标字数，或直接逐章指定字数"
        )

    shares = _split(remaining, [weights.get(seq) for seq in rest])
    allocated = dict(fixed)
    for seq, share in zip(rest, shares, strict=True):
        allocated[seq] = share
    return [allocated[seq] for seq in seq_list]


def _split(total: int, raw_weights: Sequence[int | None]) -> list[int]:
    """按权重把 `total` 切成整数份额，和恰好为 `total`，余数归最后一章。

    权重缺失或全为非正数 → 均分（规格的「字数均值」）。任何一个份额算出 0 时退化为
    「每章先 1 字、余量再按权重分」：0 字意味着那一章不用写，而分摊的语义是「每章都写」。
    """
    if not raw_weights:
        return []

    weights = _normalized_weights(raw_weights)
    shares = [total * weight // _sum(weights) for weight in weights]
    if min(shares) >= 1:
        shares[-1] += total - sum(shares)
        return shares

    # 份额出现 0：先保底每章 1 字，剩下的按同一套权重再分一次。
    head = total - len(weights)
    extra = [head * weight // _sum(weights) for weight in weights]
    shares = [1 + value for value in extra]
    shares[-1] += total - sum(shares)
    return shares


def _normalized_weights(raw_weights: Sequence[int | None]) -> list[int]:
    """权重规整：全部为正数就用原值，否则整份退化为等权（每章 1）。"""
    if all(isinstance(weight, int) and weight > 0 for weight in raw_weights):
        return [int(weight) for weight in raw_weights]  # type: ignore[arg-type]
    return [1 for _ in raw_weights]


def _sum(weights: Sequence[int]) -> int:
    """权重之和；调用方保证非空且全为正。"""
    return sum(weights)
