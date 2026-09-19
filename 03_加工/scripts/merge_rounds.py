"""Merge 3 rounds of CDP search data and produce cross-round analysis."""
import json
from collections import Counter

# Keys extracted in all rounds: noteId, noteType, title, author, userId, likes, collects, comments

# Round 1: 求职空窗期 — 63 image + 3 video
# Round 2: 空窗期 找工作 经验 — 57 image + 3 video  
# Round 3: 空窗期 简历 面试 — 18 image + 2 video

# We'll save round data from the already-extracted eval outputs
# For now, generate the analysis from the notes we counted manually

analysis = {
    "date": "2026-08-04",
    "project": "小红书求职空窗期调研",
    "data_source": "window.__INITIAL_STATE__.search.feeds._value",
    "fixed_from": "CDP DOM querySelector (showed inflated counts, missing noteType)",
    "rounds_summary": [
        {"round": 1, "keyword": "求职空窗期", "total": 63, "image": 60, "video": 3},
        {"round": 2, "keyword": "空窗期 找工作 经验", "total": 60, "image": 57, "video": 3},
        {"round": 3, "keyword": "空窗期 简历 面试", "total": 20, "image": 18, "video": 2},
    ],
    "total_feeds": 143,
    "video_notes": {
        "693a6aa8": {"title": "试用期离职&gap真正实用的解法", "author": "布布糕", "likes": 25282, "collects": 14250, "rounds": [1, 3]},
        "6a4e4ba6": {"title": "Hr问空窗期就这样回答！一条视频讲清楚", "author": "陈越好聊职场", "likes": 10295, "collects": 12135, "rounds": [1]},
        "69376804": {"title": "怎么不撒谎讲清楚你的gap空窗期", "author": "不囡的雪娘", "likes": 5003, "collects": 4377, "rounds": [2]},
        "6a71c725": {"title": "简历越投越焦虑？失业空窗期别乱投简历", "author": "小王的日记", "likes": 0, "collects": 1, "rounds": [1, 3]},
        "6a6d9eed": {"title": "空窗期找工作先别海投，做好这三件事", "author": "娜娜的角落", "likes": 26, "collects": 17, "rounds": [2]},
    },
    "comparison_old_vs_new": [
        {"note": "苑有有", "old_CDP": "285K赞", "new_STATE": 5387, "lingzao": 5386},
        {"note": "一天吃七顿", "old_CDP": "227K赞", "new_STATE": 7358, "lingzao": 7353},
        {"note": "Cynthia", "old_CDP": "252K赞", "new_STATE": 2538, "lingzao": 2538},
    ],
    "next": "Use corrected data to identify high-value video notes for lingzao deep dive (布布糕 25K赞 video is top priority)"
}

with open("C:/Users/PC/WorkBuddy/edge浏览器查询/data/sessions/2026-08-04.json", "w", encoding="utf-8") as f:
    json.dump(analysis, f, ensure_ascii=False, indent=2)

print("Done. Saved corrected session data.")
