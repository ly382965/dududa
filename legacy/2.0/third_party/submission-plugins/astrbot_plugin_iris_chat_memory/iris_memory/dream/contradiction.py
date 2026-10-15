"""
Iris Chat Memory - 梦境阶段3：矛盾消解

检测记忆间的逻辑冲突，保留更新、更可靠的那一条。

Features:
    - 基于向量检索的近邻矛盾检测
    - LLM 矛盾判断
    - 多维度冲突解决策略（时间 > 置信度 > 访问频率）
    - 批量处理优化
"""

from typing import List, Optional, cast

from iris_memory.core import get_logger
from iris_memory.config import get_config
from iris_memory.l2_memory.adapter import L2MemoryAdapter
from iris_memory.l3_kg.adapter import L3KGAdapter
from iris_memory.llm.manager import LLMManager
from iris_memory.l2_memory.models import MemoryEntry

logger = get_logger("dream.contradiction")


class ContradictionPhase:
    """矛盾消解阶段

    检测记忆间的逻辑冲突，保留更新、更可靠的那一条。
    """

    def __init__(self):
        self._similarity_floor = 0.55
        self._similarity_ceiling = 0.85
        self._max_groups = 20

    async def execute(
        self,
        l2: "L2MemoryAdapter",
        l3: Optional["L3KGAdapter"],
        llm: Optional["LLMManager"],
        entries: Optional[List["MemoryEntry"]] = None,
        persona_id: str = "default",
    ) -> dict:
        config = get_config()
        self._similarity_floor = cast(
            float, config.get("dream_contradiction_similarity_floor")
        )
        self._similarity_ceiling = cast(
            float, config.get("dream_contradiction_similarity_ceiling")
        )
        self._max_groups = cast(int, config.get("dream_contradiction_max_groups"))

        if not llm:
            logger.warning("LLMManager 不可用，跳过矛盾消解")
            return {"groups_checked": 0, "contradictions_found": 0, "resolved": 0}

        try:
            if entries is None:
                entries = await l2.get_all_entries(persona_id=persona_id)

            if len(entries) < 2:
                logger.debug("记忆数量不足，无需矛盾检测")
                return {"groups_checked": 0, "contradictions_found": 0, "resolved": 0}

            logger.info(f"开始检测 {len(entries)} 条记忆的逻辑矛盾...")

            candidate_groups = await self._find_contradiction_candidates(
                entries, l2, persona_id
            )

            if not candidate_groups:
                logger.debug("未发现矛盾候选")
                return {"groups_checked": 0, "contradictions_found": 0, "resolved": 0}

            logger.info(f"发现 {len(candidate_groups)} 组矛盾候选")

            groups_checked = 0
            contradictions_found = 0
            resolved = 0

            for group in candidate_groups[: self._max_groups]:
                groups_checked += 1

                try:
                    result = await self._check_and_resolve(group, l2, llm)
                    if result is not None:
                        contradictions_found += 1
                        if result:
                            resolved += 1
                except Exception as e:
                    logger.error(f"矛盾消解失败：{e}", exc_info=True)

            logger.info(
                f"矛盾消解完成：检查 {groups_checked} 组，"
                f"发现 {contradictions_found} 个矛盾，解决 {resolved} 个"
            )
            return {
                "groups_checked": groups_checked,
                "contradictions_found": contradictions_found,
                "resolved": resolved,
            }

        except Exception as e:
            logger.error(f"矛盾消解失败：{e}", exc_info=True)
            return {
                "groups_checked": 0,
                "contradictions_found": 0,
                "resolved": 0,
                "error": str(e),
            }

    async def _find_contradiction_candidates(
        self,
        entries: List["MemoryEntry"],
        l2: "L2MemoryAdapter",
        persona_id: str = "default",
    ) -> List[List["MemoryEntry"]]:
        config = get_config()
        enable_group_isolation = bool(
            config.get("isolation_config.enable_group_memory_isolation")
        )

        candidates: List[List["MemoryEntry"]] = []
        seen_pairs: set = set()

        for entry in entries:
            group_id = entry.group_id if enable_group_isolation else None

            try:
                results = await l2.retrieve(
                    entry.content, group_id=group_id, top_k=5, persona_id=persona_id
                )
            except Exception as e:
                logger.debug(f"检索矛盾候选失败：{e}")
                continue

            related = []
            for result in results:
                if result.entry.id == entry.id:
                    continue
                if result.score < self._similarity_floor:
                    continue
                if result.score >= self._similarity_ceiling:
                    continue

                pair_key = tuple(sorted([entry.id, result.entry.id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                related.append(result.entry)

            if related:
                candidates.append([entry] + related)

        return candidates

    async def _check_and_resolve(
        self,
        group: List["MemoryEntry"],
        l2: "L2MemoryAdapter",
        llm: "LLMManager",
    ) -> Optional[bool]:
        if len(group) < 2:
            return None

        memory_texts = []
        for i, entry in enumerate(group):
            ts = entry.metadata.get("timestamp", "未知时间")
            memory_texts.append(f"[{i + 1}] {ts}: {entry.content}")

        prompt = f"""以下记忆可能存在逻辑矛盾，请分析：

{chr(10).join(memory_texts)}

如果存在矛盾：
1. 指出哪条记忆更新/更可靠
2. 输出合并后的正确记忆（保留正确信息，去除过时或错误信息）
3. 格式：
RESOLVED: <保留的记忆编号>
MERGED: <合并后的正确记忆内容>

如果不矛盾，回复 NO_CONFLICT。"""

        try:
            response = await llm.generate_direct(
                prompt=prompt, module="dream_contradiction"
            )

            if not response or not response.strip():
                return None

            response = response.strip()

            if response.upper().startswith("NO_CONFLICT"):
                return None

            if "RESOLVED:" not in response or "MERGED:" not in response:
                logger.debug(f"LLM 矛盾判断格式不符：{response[:100]}")
                return None

            resolved_idx = self._parse_resolved_index(response, group_size=len(group))
            merged_content = self._parse_merged_content(response)

            if resolved_idx is None or not merged_content:
                return None

            keep_entry = group[resolved_idx]
            delete_ids = [e.id for e in group if e.id != keep_entry.id]

            success = await l2.update_content(keep_entry.id, merged_content)
            if success:
                keep_entry.metadata["confidence"] = min(
                    1.0, keep_entry.metadata.get("confidence", 0.5) + 0.1
                )
                await l2.update_metadata(keep_entry.id, keep_entry.metadata)

            if delete_ids:
                await l2.delete_entries(delete_ids)

            logger.info(
                f"矛盾消解：保留 [{resolved_idx + 1}]，删除 {len(delete_ids)} 条"
            )
            return True

        except Exception as e:
            logger.error(f"矛盾消解 LLM 调用失败：{e}")
            return None

    def _parse_resolved_index(
        self, response: str, group_size: int = 0
    ) -> Optional[int]:
        try:
            for line in response.split("\n"):
                if line.strip().upper().startswith("RESOLVED:"):
                    val = line.split(":", 1)[1].strip()
                    idx = int(val) - 1
                    if idx < 0 or (group_size > 0 and idx >= group_size):
                        logger.warning(
                            f"RESOLVED 索引越界：{val}，group_size={group_size}"
                        )
                        return None
                    return idx
        except (ValueError, IndexError):
            pass
        return None

    def _parse_merged_content(self, response: str) -> Optional[str]:
        try:
            in_merged = False
            lines = []
            for line in response.split("\n"):
                if line.strip().upper().startswith("MERGED:"):
                    in_merged = True
                    remainder = line.split(":", 1)[1].strip()
                    if remainder:
                        lines.append(remainder)
                    continue
                if in_merged:
                    if (
                        line.strip()
                        .upper()
                        .startswith(
                            ("RESOLVED:", "PATTERN:", "EVIDENCE:", "CONFIDENCE:")
                        )
                    ):
                        break
                    lines.append(line)
            if lines:
                return "\n".join(lines).strip()
        except (ValueError, IndexError):
            pass
        return None
