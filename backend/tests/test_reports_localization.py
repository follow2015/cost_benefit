"""P2-5 信创合规报表变体回归测试。

验证 `ai_roi.infrastructure.reports.template` 的 `assemble_report` / `_localization`：
- 标准报告不含 localization 段落；
- compliance=localization 时追加段落且标题变体；
- CN_cfg 与国产卡占比阈值（<50% / ≥50% / 缺失）触发正确合规提示。
"""

from __future__ import annotations

from ai_roi.infrastructure.reports.template import assemble_report, _localization, CN_CFG_LABELS


def _scenario(domestic_gpu_share="0.6", cn_cfg="partial"):
    return {
        "name": "测试方案",
        "version": 1,
        "params": {
            "hw": {
                "N_gpu": "8",
                "domestic_gpu_share": domestic_gpu_share,
                "CN_cfg": cn_cfg,
            }
        },
    }


def _payload():
    return {
        "engine_version": "1.0.0",
        "formula_spec_version": "1.0.0",
        "kpis": [],
        "financials": {},
        "warnings": [],
    }


def test_standard_report_has_no_localization():
    report = assemble_report(_scenario(), _payload())
    assert report.get("localization") is None
    assert "信创合规" not in report["title"]


def test_localization_variant_present_and_title():
    report = assemble_report(_scenario(), _payload(), compliance="localization")
    loc = report["localization"]
    assert loc is not None
    assert report["title"].endswith("（信创合规版）")
    assert loc["cn_cfg"] == "partial"
    assert loc["cn_cfg_label"] == CN_CFG_LABELS["partial"]
    assert "60.00%" in loc["domestic_gpu_share"]
    assert loc["conclusion"]
    assert isinstance(loc["prompts"], list) and len(loc["prompts"]) > 0


def test_localization_share_ge_50_passes():
    loc = _localization(_scenario(domestic_gpu_share="0.7", cn_cfg="full"))
    joined = " ".join(loc["prompts"])
    assert "≥ 50%" in joined
    assert "信创达标存在缺口" not in joined


def test_localization_share_lt_50_warning():
    loc = _localization(_scenario(domestic_gpu_share="0.3", cn_cfg="partial"))
    joined = " ".join(loc["prompts"])
    assert "低于 50%" in joined
    assert "信创达标存在缺口" in joined


def test_localization_none_cfg_prompt():
    loc = _localization(_scenario(domestic_gpu_share="0", cn_cfg="none"))
    joined = " ".join(loc["prompts"])
    assert "CN_cfg=none" in joined


def test_localization_missing_share_prompt():
    loc = _localization(_scenario(domestic_gpu_share=None, cn_cfg="full"))
    joined = " ".join(loc["prompts"])
    assert "未填写国产卡占比" in joined
