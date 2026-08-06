#!/usr/bin/env python3
"""Generic semantic tests for decision-oriented Chinese short titles."""

from __future__ import annotations

import unittest

import zotero_declarative_bridge as bridge


class ChineseDecisionShortTitleTests(unittest.TestCase):
    def validate(self, value: str, source: str = "A generic source title") -> None:
        bridge.validate_research_short_title(
            value,
            source,
            policy=bridge.DECISION_SHORT_TITLE_POLICY,
            language="zh-CN",
        )

    def test_accepts_grouped_decision_and_warning_predicates(self) -> None:
        valid = [
            "相关输入分析：主效应稳定但交互误差偏高",
            "高维筛选：须先降维再估计总效应",
            "小样本排序：名次未必稳定",
            "分布敏感性：方差指标不覆盖尾部变化",
            "代理相关性：高相关不代表高敏感",
            "零方差输出：归一化指标无效",
            "候选设计比较：方案甲最优、方案乙次优",
            "成本精度权衡：低成本方案优于高方差方案",
        ]
        for value in valid:
            with self.subTest(value=value):
                self.validate(value)

    def test_rejects_empty_or_descriptive_only_decisions(self) -> None:
        invalid = [
            "高维筛选：",
            "高维筛选：代理模型方法",
            "候选设计：最优采样算法",
            "方法综述：全局敏感性分析",
            "分类任务：支持向量机方法",
            "方法比较：代理模型但核方法",
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(bridge.BridgeError):
                    self.validate(value)

    def test_rejects_bibliography_title_abbreviation_after_semantic_check(self) -> None:
        value = "相关性分析：高相关不代表高敏感"
        with self.assertRaisesRegex(bridge.BridgeError, "bibliography-title"):
            self.validate(value, source=value)

    def test_accepts_causal_warning_equivalence_and_determination(self) -> None:
        valid = [
            "采样分布漂移：会改变变量重要性排序",
            "相关输入忽略：会破坏方差分解解释",
            "代理误差累积：会导致交互项排序反转",
            "输出尺度变换：会影响敏感度量结论",
            "噪声传播分析：可能扭曲变量重要性排序",
            "度量解释边界：相关性不等同于敏感性",
            "预算配置分析：复制次数决定排序稳定性",
        ]
        for value in valid:
            with self.subTest(value=value):
                self.validate(value)

    def test_rejects_causal_words_used_as_descriptive_nouns(self) -> None:
        invalid = [
            "因果研究：影响因素分析",
            "算法综述：决定理论方法",
            "模型综述：改变检测方法",
            "误差研究：破坏机制分析",
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(bridge.BridgeError):
                    self.validate(value)


if __name__ == "__main__":
    unittest.main()
