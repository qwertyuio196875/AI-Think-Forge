"""知识库夹具语料的契约测试。

这些语料（`fixtures/knowledge/`）同时是 RAG 的验收夹具与检索质量的回归测试集
（规格 #2「夹具」、ADR-0005）。本文件只钉**契约**，不断言语料正文里的具体句子：

- 目录存在，且恰好 15 份 `.md`（`README.md` 是文件说明，不算语料）；
- 每份非空，汉字数落在 400–900 之间（用 `app.hanzi.count_hanzi`，不另写一套）；
- `index.json` 与实际文件一一对应，不多不少，且类别取值在四类之内；
- 四个类别各自的份数之和等于总份数。

数值改动（增删语料、调区间）应当是有意的：`index.json` 里的示例查询是按现有
正文写的，增删文件必须同步更新清单与本文件的契约常量，不能只改一边。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.hanzi import count_hanzi

# 语料目录相对仓库根。测试从仓库根跑（pyproject 的 testpaths 已固定）。
CORPUS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "knowledge"

# 契约常量：改了语料就同时改这里，别让测试变成「按当前内容倒推」。
EXPECTED_FILE_COUNT = 15
MIN_HANZI = 400
MAX_HANZI = 900
CATEGORIES = ("tech", "product", "research", "interview")

# README 是给人看的说明，不是检索语料，不计入 15 份。
NON_CORPUS_FILES = {"README.md"}
INDEX_FILENAME = "index.json"


def _corpus_files() -> list[Path]:
    """返回目录里的语料文件（`.md`，排除 README），按文件名排序。"""
    return sorted(
        path
        for path in CORPUS_DIR.glob("*.md")
        if path.name not in NON_CORPUS_FILES
    )


def _load_index() -> dict:
    """读取 `index.json`；解析失败让测试直接失败，不静默返回空。"""
    return json.loads((CORPUS_DIR / INDEX_FILENAME).read_text(encoding="utf-8"))


def test_corpus_directory_exists() -> None:
    """语料目录必须存在：没有它就没有检索质量的验收标准。"""
    assert CORPUS_DIR.is_dir(), f"缺少夹具语料目录：{CORPUS_DIR}"


def test_corpus_holds_exactly_expected_number_of_markdown_files() -> None:
    """恰好 15 份 `.md` 语料，README 不算。"""
    files = _corpus_files()
    assert len(files) == EXPECTED_FILE_COUNT, [path.name for path in files]


@pytest.mark.parametrize("path", _corpus_files(), ids=lambda path: path.name)
def test_each_corpus_file_is_non_empty_and_within_hanzi_range(path: Path) -> None:
    """每份语料非空，且汉字数在 400–900 之间（按 `count_hanzi` 计）。"""
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path.name} 是空文件"

    hanzi = count_hanzi(text)
    assert MIN_HANZI <= hanzi <= MAX_HANZI, f"{path.name} 汉字数 {hanzi}，超出 {MIN_HANZI}-{MAX_HANZI}"


def test_index_declares_every_corpus_file_exactly_once() -> None:
    """`index.json` 的文件名与实际文件一一对应：不许多、不许少、不许重复。"""
    declared = [entry["file"] for entry in _load_index()["files"]]
    actual = [path.name for path in _corpus_files()]

    assert len(declared) == len(set(declared)), f"清单里有重复文件名：{declared}"
    assert sorted(declared) == actual


def test_index_entries_carry_category_topic_and_example_queries() -> None:
    """每条清单项都必须带类别、一句话主题，以及 2–3 个示例查询（验收判据）。"""
    for entry in _load_index()["files"]:
        name = entry["file"]
        assert entry["category"] in CATEGORIES, f"{name} 的类别 {entry['category']} 不在四类之内"
        assert entry["topic"].strip(), f"{name} 缺少一句话主题"
        queries = entry["queries"]
        assert 2 <= len(queries) <= 3, f"{name} 的示例查询有 {len(queries)} 条，应为 2–3 条"
        assert all(query.strip() for query in queries), f"{name} 有空白示例查询"


def test_categories_cover_the_whole_corpus() -> None:
    """四类各自的份数之和等于语料总份数；每类至少一份。"""
    counts: dict[str, int] = {category: 0 for category in CATEGORIES}
    for entry in _load_index()["files"]:
        counts[entry["category"]] += 1

    assert sum(counts.values()) == EXPECTED_FILE_COUNT
    assert set(counts) == set(CATEGORIES)
    assert all(count > 0 for count in counts.values()), counts
