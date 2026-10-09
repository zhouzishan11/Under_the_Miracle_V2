"""凡人：他们拥有的只是最基础的生存需求、记忆、关系与倾向。

没有人告诉他们"文明"是什么，也没有人告诉他们"现在该进入农业时代"。
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------- 姓名生成
_GIVEN = list("禾石川岩木火云风山水田林牧舟原砂雪松藤麦鹿鹰熊狼星月日河谷丘青白赤金铁")
_PLACE_A = list("石青黑白赤金大高寒温幽明长风霜雨")
_PLACE_B = list("河谷林麓岗塬坡湾渡口村屯寨邑原丘滩")


def human_name(rng) -> str:
    return rng.choice(_GIVEN) + rng.choice(_GIVEN)


def place_name(rng, world, x: int, y: int) -> str:
    a = rng.choice(_PLACE_A)
    xi, yi = int(x), int(y)
    near_water = False
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            if world.is_water(xi + dx, yi + dy):
                near_water = True
    if near_water:
        b = rng.choice(["湾", "渡", "浦", "津", "洲"])
    elif world.plants[yi, xi] > 0.4:
        b = rng.choice(["林", "麓", "野"])
    elif yi < world.h * 0.35 or world.temperature[yi, xi] < 0.35:
        b = rng.choice(["塬", "岗", "原"])
    else:
        b = rng.choice(_PLACE_B)
    return a + b


# ---------------------------------------------------------------- 职业映射
SKILL_TO_JOB = {
    "采集": "采集者",
    "耕作": "农夫",
    "狩猎": "猎人",
    "制作": "工匠",
    "交易": "商人",
    "战斗": "战士",
    "传道": "智者",
}


class Human:
    """一个普通人。他只知道饿、渴、累，以及身边的人。"""

    def __init__(self, hid: int, x: float, y: float, rng, tick: int = 0,
                 age: float = 0.0, parents=None, name: str = ""):
        self.id = hid
        self.name = name
        self.x = float(x)
        self.y = float(y)
        self.alive = True
        self.age = age                      # 单位：年
        self.lifespan = 52.0 + rng.random() * 26.0
        self.born_tick = tick

        # 需求：1 = 满足，0 = 濒临崩溃
        self.food = 0.65
        self.water = 0.65
        self.energy = 0.85
        self.health = 1.0

        # 倾向（个体差异）
        if parents is not None:
            self.curiosity = _inherit(parents, "curiosity", rng)
            self.aggression = _inherit(parents, "aggression", rng)
            self.sociability = _inherit(parents, "sociability", rng)
            self.diligence = _inherit(parents, "diligence", rng)
        else:
            self.curiosity = float(rng.random())
            self.aggression = float(rng.random())
            self.sociability = float(rng.random())
            self.diligence = float(rng.random())
        self.speed = 0.40 + rng.random() * 0.18
        self.speed_now = self.speed

        # 记忆：记住"哪里有吃的、哪里有水"
        self.memory: dict[tuple, list] = {}
        # 活动范围：人不会漫无目的地走，总是绕着熟悉的地方转
        self.anchor = (float(x), float(y))
        # 关系：认识的人 -> 好感度 [-1, 1]
        self.relations: dict[int, float] = {}
        # 技能计数：做过多少次
        self.skills: dict[str, int] = {}
        # 知道的事（观念/技术）
        self.knowledge: set[str] = set()
        # 随身携带
        self.inventory = {"food": 0.0, "goods": 0.0}

        self.home: int | None = None
        self.goal = "explore"
        self.action = "游荡"
        self.heading = rng.random() * math.tau
        self.target: tuple[float, float] | None = None
        self.stuck = 0
        self.exhausted = 0

        self.harvest_count = 0
        self.hunt_count = 0
        self.craft_count = 0
        self.trade_count = 0
        self.fight_count = 0
        self.child_count = 0
        self.partner: int | None = None

        self.possessed = False
        self.manual = False
        self.manual_vec = (0.0, 0.0)
        self.last_social_tick = -999
        self.death_cause: str | None = None

    # ------------------------------------------------------------ 派生属性
    @property
    def profession(self) -> str:
        if self.age < 14:
            return "孩童"
        if not self.skills:
            return "游民"
        best = max(self.skills.items(), key=lambda kv: kv[1])
        if best[1] < 6:
            return "游民"
        return SKILL_TO_JOB.get(best[0], "游民")

    def relation_stats(self) -> tuple[int, int]:
        friends = sum(1 for v in self.relations.values() if v > 0.3)
        foes = sum(1 for v in self.relations.values() if v < -0.3)
        return friends, foes

    def remember(self, gx: int, gy: int, kind: str, value: float, tick: int) -> None:
        # 同一块地可以同时记住"有吃的"和"有水"
        key = (kind, gx, gy)
        old = self.memory.get(key)
        if old is None:
            self.memory[key] = [kind, value, tick, gx, gy]
            if len(self.memory) > 120:
                oldest = min(self.memory.items(), key=lambda kv: kv[1][2])
                self.memory.pop(oldest[0], None)
        else:
            old[1] = value
            old[2] = tick

    def recall(self, kind: str, tick: int, max_age: int = 260):
        """想起最近、最靠谱的一处资源。"""
        best = None
        best_score = -1e9
        for kind_v, value, t, gx, gy in self.memory.values():
            if kind_v != kind:
                continue
            age = tick - t
            if age > max_age or value <= 0.05:
                continue
            score = value * 2.0 - age * 0.004
            if score > best_score:
                best_score = score
                best = (gx + 0.5, gy + 0.5)
        return best

    def forget(self, gx: int, gy: int, kind: str | None = None) -> None:
        if kind is None:
            for k in [k for k in self.memory if k[1] == gx and k[2] == gy]:
                self.memory.pop(k, None)
        else:
            self.memory.pop((kind, gx, gy), None)

    def learn(self, concept: str) -> bool:
        if concept in self.knowledge:
            return False
        self.knowledge.add(concept)
        return True

    def status_text(self) -> str:
        if self.food < 0.15:
            return "饿得发慌"
        if self.water < 0.15:
            return "渴得发昏"
        if self.health < 0.4:
            return "奄奄一息"
        if self.energy < 0.25:
            return "精疲力尽"
        if self.food < 0.4:
            return "腹中饥饿"
        if self.water < 0.4:
            return "口干舌燥"
        return "尚可"

    def need_phrase(self) -> str:
        parts = []
        if self.food < 0.4:
            parts.append("饿")
        if self.water < 0.4:
            parts.append("渴")
        if self.energy < 0.35:
            parts.append("累")
        if not parts:
            return "吃饱喝足"
        return "又" + "又".join(parts)


def _inherit(parents, attr: str, rng) -> float:
    """孩子从父母身上继承倾向，但总会有自己的偏差。"""
    base = sum(getattr(p, attr) for p in parents) / len(parents)
    return float(min(1.0, max(0.0, base + (rng.random() - 0.5) * 0.24)))