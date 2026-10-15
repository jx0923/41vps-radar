"""测试夹具与共享工具。"""

from __future__ import annotations

import os
import sys

import pytest

# 让测试可以直接 import letdeals
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def root() -> str:
    return ROOT


@pytest.fixture(scope="session")
def data_dir(root: str) -> str:
    return os.path.join(root, "data")


@pytest.fixture(scope="session")
def fixtures_dir(root: str) -> str:
    return os.path.join(root, "tests", "fixtures")


@pytest.fixture(scope="session")
def let_feed(fixtures_dir: str) -> str:
    """LET 精简夹具（含 BERO 十周年黄金样本）。

    优先用夹具而非实时缓存 —— 夹具稳定、体积小，适合进仓库。
    """
    p = os.path.join(fixtures_dir, "let_offers_sample.xml")
    if not os.path.exists(p):
        pytest.skip("缺少 tests/fixtures/let_offers_sample.xml"
                    "（运行 python tools/make_fixtures.py 生成）")
    return p


@pytest.fixture(scope="session")
def leb_feed(fixtures_dir: str) -> str:
    """LEB 精简夹具（含真优惠 / 新闻 / 抽奖三类样本）。"""
    p = os.path.join(fixtures_dir, "leb_sample.xml")
    if not os.path.exists(p):
        pytest.skip("缺少 tests/fixtures/leb_sample.xml"
                    "（运行 python tools/make_fixtures.py 生成）")
    return p


@pytest.fixture(scope="session")
def reply_cache_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "replies")


# BERO 十周年帖子：本项目的黄金样本
BERO_THREAD_ID = "221713"


@pytest.fixture(scope="session")
def bero_expected_plans():
    """BERO 十周年的真实套餐（名称, vcpu, ram_gb, storage_gb, price_eur）。"""
    return [
        ("Anniversary S", 2, 6, 60, 39),
        ("Anniversary M", 4, 12, 120, 49),
        ("Anniversary L", 4, 20, 200, 69),
        ("Anniversary XL", 6, 24, 300, 89),
        ("Anniversary XXL", 8, 32, 300, 129),
    ]


@pytest.fixture(scope="session")
def bero_plan_lines() -> str:
    """BERO 帖子里被拍平的套餐表文本（模拟 strip_html 的输出）。"""
    return "\n".join([
        "EPYC Turin VPS", "Powered by:", "AMD EPYC Turin 9275F",
        "DDR5 RAM", "Fast NVMe storage", "KVM virtualization",
        "Location: Frankfurt, Germany", "Traffic: 25 TB included per package",
        "Plan", "CPU", "RAM", "NVMe", "IPv4", "IPv6", "Traffic",
        "Recurring price/year", "First year with LET10",
        "Anniversary S", "2 Cores", "6 GB", "60 GB", "1 IPv4", "/64 IPv6",
        "25 TB", "€39", "€35.10",
        "Anniversary M", "4 Cores", "12 GB", "120 GB", "1 IPv4", "/64 IPv6",
        "25 TB", "€49", "€44.10",
        "Anniversary L", "4 Cores", "20 GB", "200 GB", "1 IPv4", "/64 IPv6",
        "25 TB", "€69", "€62.10",
        "Anniversary XL", "6 Cores", "24 GB", "300 GB", "1 IPv4", "/64 IPv6",
        "25 TB", "€89", "€80.10",
        "Anniversary XXL", "8 Cores", "32 GB", "300 GB", "1 IPv4", "/64 IPv6",
        "25 TB", "€129", "€116.10",
    ])
