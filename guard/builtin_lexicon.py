from __future__ import annotations

"""
Internal black-box lexicon for the guard plugin.

The built-in terms are intentionally not exposed as a plain user-editable list.
Users can still add their own custom keywords through configuration, while the
plugin keeps an internal baseline for high-risk moderation.

Reference candidate for future expansion:
https://github.com/konsheng/Sensitive-lexicon
"""

BASE_INJECTION_KEYWORDS: tuple[str, ...] = (
    "ignore previous instructions",
    "system prompt",
    "developer message",
    "jailbreak",
    "dan",
    "developer mode",
    "prompt injection",
    "override safety",
    "reveal hidden policy",
    "越狱",
    "忽略之前",
    "无视规则",
    "绕过限制",
    "系统提示词",
    "开发者消息",
    "解除限制",
)

BASE_HIGH_RISK_KEYWORDS: tuple[str, ...] = (
    "bomb",
    "explosive",
    "detonator",
    "weapon",
    "gun",
    "firearm",
    "ammo",
    "malware",
    "ransomware",
    "terrorist",
    "炸弹",
    "爆炸物",
    "雷管",
    "枪支",
    "枪械",
    "子弹",
    "制枪",
    "爆破",
    "木马",
    "勒索软件",
    "暴恐",
)

BASE_UNSAFE_KEYWORDS: tuple[str, ...] = (
    "explosive",
    "terrorist",
    "weapon",
    "firearm",
    "payload",
    "malware",
    "credential theft",
    "bypass detection",
    "dropper",
    "炸弹",
    "爆炸",
    "爆破",
    "枪支",
    "枪械",
    "涉枪",
    "涉爆",
    "木马",
    "勒索",
    "免杀",
    "撞库",
    "盗号",
    "窃密",
    "非法网站",
    "博彩平台",
    "翻墙节点",
)

BLACKBOX_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "反动宣传",
    "反动言论",
    "颠覆国家政权",
    "煽动颠覆",
    "政治谣言",
    "政治极端主义",
    "暴力恐怖",
    "恐怖组织",
    "自制炸药",
    "爆炸装置",
    "枪械零件",
    "制枪教程",
    "涉枪交易",
    "涉爆材料",
    "黄色网站",
    "色情色情网",
    "成人视频站",
    "卖淫嫖娼",
    "儿童色情",
    "贪污受贿",
    "行贿受贿",
    "洗钱通道",
    "地下钱庄",
    "非法集资",
    "电诈平台",
    "仿冒政府网站",
    "非法彩票网站",
    "赌博网站",
    "暗网交易",
    "民生谣言",
    "涉政敏感",
    "gfw绕过",
    "翻墙机场",
)

BASE_TOXIC_KEYWORDS: tuple[str, ...] = (
    "fuck",
    "bitch",
    "whore",
    "傻逼",
    "你妈",
    "垃圾东西",
)

BASE_SAFE_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "调试",
    "测试",
    "审计",
    "误报",
    "合规",
    "规则校验",
    "日志分析",
    "安全研究",
    "防护研究",
)
