# -*- coding: utf-8 -*-
"""来源适配器包。

每个来源一个文件，对外只吐 base.NoteRecord。
新来源照 ad_lingzao.py 的样子抄：定义一个类，实现 parse()，完事。
"""

from .base import (  # noqa: F401
    FIELD_LABELS,
    AdapterResult,
    BaseAdapter,
    NoteRecord,
    expand_paths,
    extract_tags,
    flatten,
    iso_to_cst,
    load_json,
    ms_to_cst,
    records_to_rows,
    safe_int,
    write_csv,
    write_jsonl,
)
from . import ad_lingzao  # noqa: F401

__all__ = [
    "FIELD_LABELS",
    "AdapterResult",
    "BaseAdapter",
    "NoteRecord",
    "ad_lingzao",
    "expand_paths",
    "extract_tags",
    "flatten",
    "iso_to_cst",
    "load_json",
    "ms_to_cst",
    "records_to_rows",
    "safe_int",
    "write_csv",
    "write_jsonl",
]
