"""涌现：从一群只想着吃饱喝足的人身上，长出聚落、分工、贸易、战争与文明。

这里没有"进入农业时代"的指令，只有一连串微小的选择。
"""
from __future__ import annotations

import math
import random

import numpy as np

from .agents import Human, human_name, place_name

ERA_ORDER = ["蒙昧", "定居", "狩猎采集", "农耕", "城邦", "文明"]

CONCEPT_DESC = {
    "火": "学会了保留火种",
    "工具": "学会了打磨石器",
    "狩猎": "掌握了围猎的诀窍",
    "贮藏": "懂得了把食物存起来",
    "农业": "悟出了播种与收获",
    "制陶": "学会了烧制陶器",
    "交易": "懂得了交换比抢夺更长久",
    "文字": "在陶片上刻下了第一个记号",
    "律法": "约定了一起遵守的规矩",
    "祭祀": "对着天空埋葬了死者",
    "城防": "懂得筑起墙来保护自己",
}

# 感知节流：人不必每 tick 都重新打量脚下。按 id 错开相位，避免所有人挤在
# 同一 tick 集中观察造成周期性卡顿；喝水、采集等动作带来的记忆不受影响。
OBSERVE_EVERY = 3


class Settlement:
    """一群决定在同一片土地上活下去的人。"""

    def __init__(self, sid: int, name: str, x: float, y: float, tick: int):
        self.id = sid
        self.name = name
        self.x = float(x)
        self.y = float(y)
        self.founded = tick
        self.members: list[int] = []
        self.stock = {"food": 0.0}
        self.knowledge: set[str] = set()
        self.institutions: set[str] = set()
        self.relations: dict[int, float] = {}
        self.era = "蒙昧"
        self.conflicts = 0
        self.trades = 0
        self.wars = 0

    @property
    def pop(self) -> int:
        return len(self.members)


class Simulation:
    def __init__(self, world, seed: int = 1):
        self.world = world
        self.rng = np.random.default_rng(seed + 7)
        self.py_rng = random.Random(seed * 31 + 5)

        self.humans: dict[int, Human] = {}
        self.settlements: dict[int, Settlement] = {}
        self.next_hid = 1
        self.next_sid = 1
        self.tick = 0

        self.log: list[tuple[int, str, str]] = []
        # 文明史卷：只记世上第一次发生的事，重复的岁月只留在记录栏里
        self.chronicle: list[tuple[int, str]] = []
        self._chronicle_seen: set[str] = set()
        self.births = 0
        self.deaths = 0
        self.trade_events = 0
        self.war_events = 0
        self.discovery_events = 0

        self.possessed_id: int | None = None
        self.max_population = 700
        self._cluster_memory: dict[tuple[int, int], int] = {}
        # 每 tick 一次批量算好的"最近他人"（id -> (距离平方, 人)），
        # 让 _closest_other 变成 O(1) 查表，后期几百人口也能保持流畅
        self._nn_best: dict[int, tuple[float, Human | None]] = {}
        self._log_limit = 600

    # ---------------------------------------------------------------- 日志
    def add_log(self, text: str, kind: str = "life") -> None:
        self.log.append((self.tick, text, kind))
        if len(self.log) > self._log_limit:
            del self.log[: len(self.log) - self._log_limit]

    def clear_log(self) -> None:
        """清空记录栏。文明史卷不受影响——那里只记第一次。"""
        self.log.clear()

    def add_chronicle(self, key: str, text: str) -> None:
        """记入文明史卷。同一件事（同一个 key）只记第一次。"""
        if key in self._chronicle_seen:
            return
        self._chronicle_seen.add(key)
        self.chronicle.append((self.tick, text))

    def _add_discovery(self, global_key: str, owner_key: str | None,
                       text_global: str, text_owner: str | None = None) -> None:
        """记一次"发现"：世上第一次记一条；之后各聚落自己独立的首现，也各记一条。

        同一件事的重复（比如聚落里第二个人学会用火）不进史卷，只留在记录栏。
        """
        if global_key not in self._chronicle_seen:
            self._chronicle_seen.add(global_key)
            if owner_key is not None:
                self._chronicle_seen.add(owner_key)
            self.chronicle.append((self.tick, text_global))
            return
        if owner_key is not None and owner_key not in self._chronicle_seen:
            self._chronicle_seen.add(owner_key)
            self.chronicle.append((self.tick, text_owner or text_global))

    # ---------------------------------------------------------------- 造人
    def spawn_humans(self, gx: float, gy: float, radius: int, count: int) -> int:
        """在世界某处放下几个凡人——他们什么都不会，只会活下去。"""
        w = self.world
        made = 0
        for _ in range(count):
            if len(self.humans) >= self.max_population:
                break
            for _try in range(20):
                px = gx + (self.py_rng.random() - 0.5) * radius * 2
                py = gy + (self.py_rng.random() - 0.5) * radius * 2
                if w.is_walkable(px, py):
                    px, py = w.clamp(px, py)
                    self._new_human(px, py, age=self.py_rng.uniform(16, 34))
                    made += 1
                    break
        if made:
            self.add_log(f"神明向大地吹入了一口气：{made} 个人睁开了眼睛", "god")
        return made

    def _new_human(self, x, y, age=0.0, parents=None) -> Human:
        hid = self.next_hid
        self.next_hid += 1
        h = Human(hid, x, y, self.py_rng, tick=self.tick, age=age,
                  parents=parents, name=human_name(self.py_rng))
        if parents is not None and self.py_rng.random() < 0.7:
            h.home = parents[0].home
        st = self.settlements.get(h.home) if h.home is not None else None
        if st is not None:
            h.anchor = (st.x, st.y)
        self.humans[hid] = h
        return h

    def _drift_anchor(self, h: Human) -> None:
        """人在哪里吃饱喝足，就把哪里当成自己的地盘。"""
        ax, ay = h.anchor
        h.anchor = (ax * 0.97 + h.x * 0.03, ay * 0.97 + h.y * 0.03)

    def _kill(self, h: Human, cause: str) -> None:
        if not h.alive:
            return
        h.alive = False
        h.death_cause = cause
        self.deaths += 1
        self.humans.pop(h.id, None)
        if self.possessed_id == h.id:
            self.possessed_id = None
        if cause in ("战乱", "灾祸", "饥荒") or self.py_rng.random() < 0.18:
            self.add_log(f"{h.name}（{int(h.age)}岁）{cause}了", "life")

    # ---------------------------------------------------------------- 主循环
    def tick_once(self) -> None:
        self.tick += 1
        self.world.tick = self.tick
        if self.tick % 3 == 0:
            self.world.evolve()

        self._prepare_nn()
        for h in list(self.humans.values()):
            if h.alive:
                self._update_human(h)

        if self.tick % 12 == 0:
            self._settlement_formation()
            self._settlement_upkeep()
        if self.tick % 40 == 0:
            self._settlement_interactions()
            self._births()
            self._institutions()

    # ------------------------------------------------------------ 空间索引
    def _prepare_nn(self) -> None:
        """每 tick 批量算一次所有人的"最近他人"。

        和原来的逐人九宫格扫描完全等价：候选就是 3×3 桶内的所有活人，
        只是改用 numpy 一次性算完，后期几百人口时比逐个 Python 循环快数倍。
        """
        hs = list(self.humans.values())
        n = len(hs)
        if n == 0:
            self._nn_best = {}
            return
        cell = 5.0
        CW = int(self.world.w // cell) + 2
        xs = np.array([h.x for h in hs], np.float64)
        ys = np.array([h.y for h in hs], np.float64)
        kx = (xs // cell).astype(np.int64)
        ky = (ys // cell).astype(np.int64)
        keys = ky * CW + kx
        order = np.argsort(keys, kind="stable")
        k_sorted = keys[order]
        x_sorted = xs[order]
        y_sorted = ys[order]
        idx = np.arange(n, dtype=np.int64)
        BIG = np.int64(1 << 60)
        best_d2 = np.full(n, np.inf)
        best_pos = np.full(n, BIG, np.int64)  # 哨兵必须是大数：minimum.at 只会往小里写
        inv = np.empty(n, np.int64)
        inv[order] = np.arange(n)  # 原序号 -> 排序后位置
        for ody in (-1, 0, 1):
            for odx in (-1, 0, 1):
                ok = keys + (ody * CW + odx)
                lo = np.searchsorted(k_sorted, ok, side="left")
                hi = np.searchsorted(k_sorted, ok, side="right")
                cnt = hi - lo
                if not cnt.any():
                    continue
                reps = np.repeat(idx, cnt)
                cum = np.add.accumulate(cnt) - cnt
                pos = lo[reps] + (np.arange(reps.size) - np.repeat(cum, cnt))
                d2 = x_sorted[pos] - xs[reps]
                d2 = d2 * d2
                d2 += (y_sorted[pos] - ys[reps]) * (y_sorted[pos] - ys[reps])
                d2 = np.where(pos == inv[reps], 1e18, d2)  # 排除自己
                before = best_d2[reps]
                better = d2 < before
                if better.any():
                    # 出现严格更优的人：先把该槽位的"最优者"重置，避免旧的残留
                    # （对同一槽位重复写 BIG 幂等，无需 unique 去重）
                    best_pos[reps[better]] = BIG
                np.minimum.at(best_d2, reps, d2)
                is_best = d2 == best_d2[reps]
                np.minimum.at(best_pos, reps, np.where(is_best, pos, BIG))
        nn: dict[int, tuple[float, Human | None]] = {}
        for i, h in enumerate(hs):
            p = int(best_pos[i])
            nn[h.id] = (np.inf, None) if p >= n else (float(best_d2[i]), hs[int(order[p])])
        self._nn_best = nn

    def _closest_other(self, h: Human, radius: float):
        d2, other = self._nn_best.get(h.id, (float("inf"), None))
        if other is None or other is h or d2 > radius * radius:
            return None
        if not other.alive:  # tick 中途死去的不算
            return None
        return other

    # ------------------------------------------------------------ 个人决策
    def _update_human(self, h: Human) -> None:
        w = self.world
        prev_age = h.age
        h.age += 1.0 / 12.0

        h.food = max(0.0, h.food - 0.075)
        h.water = max(0.0, h.water - 0.028)
        h.energy = max(0.0, h.energy - 0.055)
        # 渴急了会加快脚步
        h.speed_now = h.speed * (1.5 if h.water < 0.28 else 1.0)

        # 长大成人时，从聚落里学到先辈的经验
        if prev_age < 14.0 <= h.age and h.home in self.settlements:
            st = self.settlements[h.home]
            for concept in sorted(st.knowledge):
                h.learn(concept)

        if h.manual:
            self._manual_move(h)
        else:
            self._think(h)
        if (self.tick + h.id) % OBSERVE_EVERY == 0:
            self._observe(h)

        if h.food <= 0.02 or h.water <= 0.02:
            h.health -= 0.013
            if h.food <= 0.02:
                cause = "饿死"
            else:
                cause = "渴死"
            if h.health <= 0:
                self._kill(h, "饥荒" if cause == "饿死" else cause)
                return
        elif h.food > 0.5 and h.water > 0.5:
            h.health = min(1.0, h.health + 0.006)

        if h.age >= h.lifespan:
            self._kill(h, "寿终")

    def _think(self, h: Human) -> None:
        if h.water < 0.45:
            h.goal = "drink"
        elif h.food < 0.45:
            h.goal = "eat"
        elif h.energy < 0.32:
            h.goal = "rest"
        else:
            other = self._closest_other(h, 4.0)
            if other is not None and h.sociability > 0.3 and self.py_rng.random() < 0.5:
                h.goal = "social"
            else:
                h.goal = "work"

        if h.goal == "drink":
            self._act_drink(h)
        elif h.goal == "eat":
            self._act_eat(h)
        elif h.goal == "rest":
            self._act_rest(h)
        elif h.goal == "social":
            self._act_social(h)
        else:
            self._act_work(h)

    # ---- 喝水 -------------------------------------------------------
    def _act_drink(self, h: Human) -> None:
        w = self.world
        xi, yi = int(h.x), int(h.y)
        if w.in_bounds(xi, yi) and (self._adjacent_water(xi, yi) or w.moisture[yi, xi] > 0.32):
            h.water = min(1.0, h.water + 0.9)
            h.action = "饮水"
            h.remember(xi, yi, "water", 1.0, self.tick)
            self._drift_anchor(h)
            return
        h.action = "找水"
        # 水在哪里，是一个人一辈子都不会忘的事
        spot = h.recall("water", self.tick, max_age=2400)
        if spot is None:
            spot = self._scan_for(h, "water", 22 if h.water < 0.2 else 16)
        if spot is not None:
            self._step_toward(h, spot[0], spot[1])
            return
        # 看不到水，就顺着地势往低处走——水总是在低处
        low = self._scan_lowest(h, 24)
        if low is not None:
            self._step_toward(h, low[0], low[1])
            return
        # 实在找不到，就退回自己熟悉的地方
        ax, ay = h.anchor
        if math.hypot(h.x - ax, h.y - ay) > 4:
            self._step_toward(h, ax, ay)
            return
        self._wander(h)

    # ---- 吃 ---------------------------------------------------------
    def _act_eat(self, h: Human) -> None:
        if h.inventory["food"] >= 0.15:
            take = min(h.inventory["food"], 0.3)
            h.inventory["food"] -= take
            h.food = min(1.0, h.food + take * 2.6)
            h.action = "吃存粮"
            return
        w = self.world
        xi, yi = int(h.x), int(h.y)
        if w.in_bounds(xi, yi):
            if w.plants[yi, xi] > 0.18:
                self._harvest(h, xi, yi)
                return
            if w.animals[yi, xi] > 0.18:
                self._hunt(h, xi, yi)
                return
        h.action = "觅食"
        spot = h.recall("food", self.tick)
        if spot is not None:
            arrived = self._step_toward(h, spot[0], spot[1])
            if arrived:
                x2, y2 = int(spot[0]), int(spot[1])
                if w.in_bounds(x2, y2) and w.plants[y2, x2] > 0.15:
                    self._harvest(h, x2, y2)
                else:
                    h.forget(x2, y2, "food")
            return
        spot = self._scan_for(h, "food", 10)
        if spot is not None:
            self._step_toward(h, spot[0], spot[1])
            return
        self._wander(h)

    def _harvest(self, h: Human, xi: int, yi: int) -> None:
        w = self.world
        amount = float(w.plants[yi, xi])
        takes = min(amount, 0.30)
        bonus = 1.9 if "农业" in h.knowledge else 1.0
        got = takes * bonus
        w.plants[yi, xi] = max(0.0, amount - takes * 0.7)
        if "农业" in h.knowledge:
            w.plants[yi, xi] = min(1.0, w.plants[yi, xi] + 0.045)
            w.farms[yi, xi] = 1.0
        h.food = min(1.0, h.food + min(got, 0.5) * 2.2)
        if got > 0.34:
            h.inventory["food"] += (got - 0.34) * 0.6
        h.harvest_count += 1
        h.action = "采集"
        self._bump_skill(h, "采集")
        h.remember(xi, yi, "food", amount, self.tick)
        self._drift_anchor(h)

        if h.harvest_count == 14 and h.home is not None and "农业" not in h.knowledge:
            if w.soil[yi, xi] > 0.25 and self.py_rng.random() < 0.7:
                if h.learn("农业"):
                    self._announce_concept(h, "农业")
        if h.inventory["food"] > 0.85 and "贮藏" not in h.knowledge:
            if self.py_rng.random() < 0.4 and h.learn("贮藏"):
                self._announce_concept(h, "贮藏")

    def _hunt(self, h: Human, xi: int, yi: int) -> None:
        w = self.world
        amount = float(w.animals[yi, xi])
        takes = min(amount, 0.22)
        skill = 1.6 if "狩猎" in h.knowledge else 0.75
        got = takes * skill
        w.animals[yi, xi] = max(0.0, amount - takes * 0.8)
        h.food = min(1.0, h.food + min(got, 0.5) * 2.4)
        h.hunt_count += 1
        h.action = "狩猎"
        self._bump_skill(h, "狩猎")
        h.remember(xi, yi, "food", amount, self.tick)
        self._drift_anchor(h)

        if h.hunt_count >= 6 and "狩猎" not in h.knowledge:
            if self.py_rng.random() < 0.45 and h.learn("狩猎"):
                self._announce_concept(h, "狩猎")

    # ---- 休息 -------------------------------------------------------
    def _act_rest(self, h: Human) -> None:
        h.action = "休息"
        h.energy = min(1.0, h.energy + 0.30)
        w = self.world
        xi, yi = int(h.x), int(h.y)
        if w.in_bounds(xi, yi) and w.temperature[yi, xi] < 0.42 and "火" not in h.knowledge:
            if self.py_rng.random() < 0.07 * (0.3 + h.curiosity):
                if h.learn("火"):
                    self._announce_concept(h, "火")

    # ---- 交往 -------------------------------------------------------
    def _act_social(self, h: Human) -> None:
        other = self._closest_other(h, 4.0)
        if other is None:
            self._wander(h)
            return
        h.action = "走向" + other.name
        if self._step_toward(h, other.x, other.y):
            self._interact(h, other)

    def _interact(self, h: Human, o: Human) -> None:
        if self.tick - h.last_social_tick < 2:
            return
        h.last_social_tick = self.tick
        o.last_social_tick = self.tick

        # 交换：多的人给少的人
        if h.inventory["food"] > 0.45 and o.food < 0.5:
            give = min(0.25, h.inventory["food"] - 0.25)
            if give > 0:
                h.inventory["food"] -= give
                o.food = min(1.0, o.food + give * 2.0)
                h.action = f"分给{o.name}食物"
        elif o.inventory["food"] > 0.45 and h.food < 0.5:
            give = min(0.25, o.inventory["food"] - 0.25)
            if give > 0:
                o.inventory["food"] -= give
                h.food = min(1.0, h.food + give * 2.0)
                h.action = f"接受{o.name}的食物"

        # 观念传播：一个人知道的，会慢慢变成一群人知道的
        h.action = h.action if h.action.startswith(("分给", "接受")) else f"与{o.name}交谈"
        # 集合迭代要排序：str 的 hash 每次运行随 PYTHONHASHSEED 变化，
        # 乱序迭代会同 shuffle 随机数的消耗顺序，导致历史不可重现
        for concept in sorted(o.knowledge):
            if concept not in h.knowledge and self.py_rng.random() < 0.30 * (0.35 + o.sociability):
                if h.learn(concept):
                    self.discovery_events += 1
                    self.add_log(f"{h.name}从{o.name}那里学会了{CONCEPT_DESC.get(concept, concept)}", "know")

        delta = 0.05 + 0.06 * (h.sociability + o.sociability) * 0.5
        h.relations[o.id] = min(1.0, h.relations.get(o.id, 0.0) + delta)
        o.relations[h.id] = min(1.0, o.relations.get(h.id, 0.0) + delta)

        # 冲突：都饿着，又都不肯让
        if h.aggression > 0.6 and o.aggression > 0.6 and (h.food < 0.3 or o.food < 0.3):
            if self.py_rng.random() < 0.35:
                self._bump_skill(h, "战斗")
                self._bump_skill(o, "战斗")
                h.fight_count += 1
                o.fight_count += 1
                loser = h if h.aggression < o.aggression else o
                loser.health -= 0.25
                h.relations[o.id] = max(-1.0, h.relations.get(o.id, 0.0) - 0.4)
                o.relations[h.id] = max(-1.0, o.relations.get(h.id, 0.0) - 0.4)
                if loser.health <= 0:
                    self._kill(loser, "被同类所伤")
                else:
                    self.add_log(f"{h.name}与{o.name}为了一口食物动了手", "war")

    # ---- 干活 / 探索 ------------------------------------------------
    def _act_work(self, h: Human) -> None:
        w = self.world
        xi, yi = int(h.x), int(h.y)
        st = self.settlements.get(h.home) if h.home else None

        if st is not None and "农业" in h.knowledge:
            if math.hypot(h.x - st.x, h.y - st.y) > 6.0:
                h.action = "返回" + st.name
                self._step_toward(h, st.x, st.y)
                return
            if w.in_bounds(xi, yi) and w.plants[yi, xi] > 0.2:
                self._harvest(h, xi, yi)
                return
            h.action = "耕作"
            self._bump_skill(h, "耕作")
            if w.in_bounds(xi, yi) and (self._adjacent_water(xi, yi) or w.moisture[yi, xi] > 0.28):
                w.plants[yi, xi] = min(1.0, float(w.plants[yi, xi]) + 0.05)
                w.farms[yi, xi] = 1.0
            else:
                self._wander(h)
            return

        if w.in_bounds(xi, yi) and w.plants[yi, xi] > 0.3 and h.inventory["food"] < 0.6:
            self._harvest(h, xi, yi)
            return

        if h.inventory["food"] > 0.5 and self.py_rng.random() < 0.3 * h.diligence:
            h.craft_count += 1
            self._bump_skill(h, "制作")
            h.inventory["goods"] += 0.08
            h.action = "制作器物"
            if h.craft_count == 4 and h.learn("工具"):
                self._announce_concept(h, "工具")
            if h.craft_count >= 9 and h.inventory["goods"] > 0.4:
                if self._adjacent_water(xi, yi) and h.learn("制陶"):
                    self._announce_concept(h, "制陶")
            return

        h.action = "探索"
        self._wander(h)

    # ---- 移动 -------------------------------------------------------
    def _wander(self, h: Human) -> None:
        w = self.world
        step = h.speed_now
        # 走得太远了就掉头回家——人是有活动范围的
        ax, ay = h.anchor
        if math.hypot(h.x - ax, h.y - ay) > 24:
            h.heading = math.atan2(ay - h.y, ax - h.x)
        for _ in range(3):
            nx = h.x + math.cos(h.heading) * step
            ny = h.y + math.sin(h.heading) * step
            if w.is_walkable(nx, ny):
                h.x, h.y = w.clamp(nx, ny)
                h.stuck = 0
                return
            h.heading += math.pi * (0.5 + self.py_rng.random())
        h.stuck += 1
        if h.stuck > 5:
            h.heading = self.py_rng.random() * math.tau
            h.stuck = 0

    def _step_toward(self, h: Human, tx: float, ty: float) -> bool:
        w = self.world
        dx, dy = tx - h.x, ty - h.y
        dist = math.hypot(dx, dy)
        if dist <= 0.6:
            return True
        step = min(h.speed_now, dist)
        ux, uy = dx / dist, dy / dist
        nx, ny = h.x + ux * step, h.y + uy * step
        if w.is_walkable(nx, ny):
            h.x, h.y = w.clamp(nx, ny)
            h.heading = math.atan2(uy, ux)
            h.stuck = 0
            return dist <= step + 0.6
        if w.is_walkable(h.x + ux * step, h.y):
            h.x += ux * step
            return False
        if w.is_walkable(h.x, h.y + uy * step):
            h.y += uy * step
            return False
        h.heading += 1.2
        return False

    def _manual_move(self, h: Human) -> None:
        """凡人视角：由玩家操纵。"""
        w = self.world
        vx, vy = h.manual_vec
        if vx == 0.0 and vy == 0.0:
            h.action = "驻足"
            return
        norm = math.hypot(vx, vy)
        vx, vy = vx / norm, vy / norm
        h.heading = math.atan2(vy, vx)
        step = h.speed_now * 1.35
        nx, ny = h.x + vx * step, h.y + vy * step
        if w.is_walkable(nx, ny):
            h.x, h.y = w.clamp(nx, ny)
            h.action = "行走"
        elif w.is_walkable(h.x + vx * step, h.y):
            h.x += vx * step
            h.action = "行走"
        elif w.is_walkable(h.x, h.y + vy * step):
            h.y += vy * step
            h.action = "行走"
        else:
            h.action = "被水拦住"

    # ---- 感知 -------------------------------------------------------
    def _observe(self, h: Human) -> None:
        w = self.world
        xi, yi = int(h.x), int(h.y)
        if not w.in_bounds(xi, yi):
            return
        if self._adjacent_water(xi, yi):
            h.remember(xi, yi, "water", 1.0, self.tick)
        p = float(w.plants[yi, xi])
        if p > 0.12:
            h.remember(xi, yi, "food", p, self.tick)

    def _adjacent_water(self, x: int, y: int) -> bool:
        w = self.world
        if not w.in_bounds(x, y):
            return True
        wp = w.water_pad
        return bool(wp[y + 1, x + 1] or wp[y + 1, x] or wp[y + 1, x + 2]
                    or wp[y, x + 1] or wp[y + 2, x + 1])

    def _scan_for(self, h: Human, kind: str, radius: int):
        """本能的搜寻：只看附近，看不到就不存在。"""
        w = self.world
        xi, yi = int(h.x), int(h.y)
        x0, x1 = max(0, xi - radius), min(w.w, xi + radius + 1)
        y0, y1 = max(0, yi - radius), min(w.h, yi + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return None
        if kind == "water":
            sub = w.elevation[y0:y1, x0:x1] <= w.sea_level
        else:
            sub = (w.plants[y0:y1, x0:x1] > 0.15) & w.land_mask[y0:y1, x0:x1]
        ys, xs = np.nonzero(sub)
        if len(ys) == 0:
            return None
        d2 = (xs + x0 - h.x) ** 2 + (ys + y0 - h.y) ** 2
        i = int(np.argmin(d2))
        return (float(xs[i] + x0) + 0.5, float(ys[i] + y0) + 0.5)

    def _scan_lowest(self, h: Human, radius: int):
        """顺着地形往下走：水一定在最低的地方。"""
        w = self.world
        xi, yi = int(h.x), int(h.y)
        x0, x1 = max(0, xi - radius), min(w.w, xi + radius + 1)
        y0, y1 = max(0, yi - radius), min(w.h, yi + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return None
        sub = w.elevation[y0:y1, x0:x1]
        if float(sub.min()) >= float(w.elevation[yi, xi]):
            return None
        iy, ix = np.unravel_index(int(np.argmin(sub)), sub.shape)
        return (float(ix + x0) + 0.5, float(iy + y0) + 0.5)

    # ------------------------------------------------------------ 聚落
    def _settlement_near(self, x: float, y: float, radius: float):
        for st in self.settlements.values():
            if math.hypot(st.x - x, st.y - y) <= radius:
                return st
        return None

    def _settlement_formation(self) -> None:
        w = self.world
        buckets: dict[tuple[int, int], list[Human]] = {}
        for h in self.humans.values():
            buckets.setdefault((int(h.x // 5), int(h.y // 5)), []).append(h)

        seen = set()
        for (cx, cy), group in buckets.items():
            if len(group) < 5:
                continue
            seen.add((cx, cy))
            gx, gy = cx * 5 + 2.5, cy * 5 + 2.5
            if not w.is_walkable(gx, gy):
                continue
            if self._settlement_near(gx, gy, 7.0) is not None:
                continue
            streak = self._cluster_memory.get((cx, cy), 0) + 1
            self._cluster_memory[(cx, cy)] = streak
            # 聚落不是"路过"，而是决定留下
            if streak >= 3:
                self._found_settlement(gx, gy, group)
                self._cluster_memory.pop((cx, cy), None)

        for key in list(self._cluster_memory):
            if key not in seen:
                self._cluster_memory[key] -= 1
                if self._cluster_memory[key] <= 0:
                    del self._cluster_memory[key]

    def _found_settlement(self, gx: float, gy: float, group: list[Human]) -> None:
        w = self.world
        sid = self.next_sid
        self.next_sid += 1
        name = place_name(self.py_rng, w, int(gx), int(gy))
        st = Settlement(sid, name, gx, gy, self.tick)
        movers = [h for h in group if h.home is None]
        if len(movers) < 4:
            return
        for h in movers:
            h.home = sid
            h.anchor = (gx, gy)
        for h in movers:
            st.knowledge |= h.knowledge
        st.members = [h.id for h in movers]
        self.settlements[sid] = st
        self.add_log(f"{name}：{len(movers)} 个人在同一片土地上停下了脚步", "settle")
        self.add_chronicle("first_settlement",
                           f"第一座聚落「{name}」诞生：{len(movers)} 个人第一次在同一片土地上停下了脚步")

    def _settlement_upkeep(self) -> None:
        for st in list(self.settlements.values()):
            members = []
            for h in self.humans.values():
                if not h.alive or h.home != st.id:
                    continue
                if math.hypot(h.x - st.x, h.y - st.y) > 22:
                    h.home = None
                    continue
                members.append(h)
            st.members = [h.id for h in members]
            if not members:
                self.add_log(f"{st.name}被遗弃了，只剩冷灶与空屋", "settle")
                del self.settlements[st.id]
                continue
            for h in members:
                if h.knowledge - st.knowledge:
                    st.knowledge |= h.knowledge
            st.era = self._era_of(st)

    def _settlement_interactions(self) -> None:
        for st in list(self.settlements.values()):
            members = [self.humans[i] for i in st.members if i in self.humans]
            if not members:
                continue
            # 集体储备
            for h in members:
                if h.inventory["food"] > 0.7 and ("贮藏" in h.knowledge or "农业" in h.knowledge):
                    give = min(0.4, h.inventory["food"] - 0.4)
                    if give > 0:
                        h.inventory["food"] -= give
                        st.stock["food"] += give
            for h in members:
                if h.food < 0.3 and st.stock["food"] > 0:
                    take = min(0.4, st.stock["food"])
                    st.stock["food"] -= take
                    h.food = min(1.0, h.food + take * 2.2)
            st.stock["food"] *= 0.985

            per_capita = st.stock["food"] / max(1, st.pop)

            # 贸易：互通有无。没有人教过他们"贸易"，只是住得近了，自然开始交换
            for other in list(self.settlements.values()):
                if other.id <= st.id:
                    continue
                d = math.hypot(st.x - other.x, st.y - other.y)
                if d > 30 or st.pop < 4 or other.pop < 4:
                    continue
                rel = st.relations.get(other.id, 0.0)
                if rel < -0.2:
                    continue
                knows = ("交易" in st.knowledge) or ("交易" in other.knowledge)
                if not knows:
                    # 还没人想到"交换"这回事：住得近，才慢慢开始互通有无
                    if d <= 20 and self.py_rng.random() < 0.30:
                        self._do_trade(st, other)
                    elif d <= 26 and self.py_rng.random() < 0.20:
                        st.relations[other.id] = min(1.0, rel + 0.06)
                        other.relations[st.id] = min(
                            1.0, other.relations.get(st.id, 0.0) + 0.06)
                    continue
                if self.py_rng.random() < 0.55:
                    self._do_trade(st, other)

            # 人丁兴旺，就有人另立门户
            if st.pop >= 55 and "农业" in st.knowledge:
                self._colonize(st, members)

            # 迁徙：活不下去就走了
            starving = sum(1 for h in members if h.food < 0.3) / len(members)
            if per_capita < 0.15 and starving > 0.5:
                self._migrate(st, members)

            # 战争：饿了又凶，就会去抢
            avg_aggr = sum(h.aggression for h in members) / len(members)
            if per_capita < 0.4 and avg_aggr > 0.55 and len(members) >= 8:
                target = self._weaker_neighbor(st, per_capita)
                if target is not None and self.py_rng.random() < 0.45:
                    self._do_war(st, target)

    def _do_trade(self, st: Settlement, other: Settlement) -> None:
        self.trade_events += 1
        st.trades += 1
        other.trades += 1
        self.add_chronicle("first_trade", f"{st.name}与{other.name}第一次互通有无——世上从此有了交换")
        st.relations[other.id] = min(1.0, st.relations.get(other.id, 0.0) + 0.18)
        other.relations[st.id] = min(1.0, other.relations.get(st.id, 0.0) + 0.18)

        giver, taker = (st, other) if st.stock["food"] >= other.stock["food"] else (other, st)
        amount = min(1.5, giver.stock["food"] * 0.15)
        giver.stock["food"] -= amount
        taker.stock["food"] += amount * 1.15

        for s in (st, other):
            if "交易" not in s.knowledge:
                s.knowledge.add("交易")
                for hid in s.members:
                    hm = self.humans.get(hid)
                    if hm is None:
                        continue
                    if hm.learn("交易"):
                        self._bump_skill_if_missing(hm, "交易")
                self._announce_settlement(s, "交易")

        if self.py_rng.random() < 0.07 or max(st.trades, other.trades) <= 1:
            self.add_log(f"{st.name}与{other.name}交换了食物与器物", "trade")

    def _colonize(self, st: Settlement, members: list[Human]) -> None:
        """人口太多，一部分人离开故土，到别处重新开始。"""
        if len(members) < 30 or self.py_rng.random() > 0.35:
            return
        w = self.world
        for _ in range(12):
            ang = self.py_rng.random() * math.tau
            dist = 16 + self.py_rng.random() * 12
            nx = st.x + math.cos(ang) * dist
            ny = st.y + math.sin(ang) * dist
            if not w.is_walkable(nx, ny) or self._settlement_near(nx, ny, 9) is not None:
                continue
            xi, yi = int(nx), int(ny)
            if w.plants[yi, xi] < 0.15 and w.moisture[yi, xi] < 0.2:
                continue
            group = self.py_rng.sample(members, max(4, len(members) // 4))
            sid = self.next_sid
            self.next_sid += 1
            name = place_name(self.py_rng, w, xi, yi)
            child = Settlement(sid, name, nx, ny, self.tick)
            child.knowledge |= st.knowledge
            child.relations[st.id] = 0.4
            st.relations[sid] = 0.4
            for h in group:
                h.home = sid
                h.anchor = (nx, ny)
            child.members = [h.id for h in group]
            self.settlements[sid] = child
            self.add_log(f"{st.name}人丁兴旺，{len(group)} 个人离开了故土，建立了{name}", "settle")
            return

    def _migrate(self, st: Settlement, members: list[Human]) -> None:
        leavers = sorted(members, key=lambda h: h.food)[: max(2, len(members) // 2)]
        for h in leavers:
            h.home = None
            h.heading = self.py_rng.random() * math.tau
            h.inventory["food"] = 0.0
        st.members = [h.id for h in members if h.home == st.id]
        if leavers:
            self.add_log(f"{st.name}闹了饥荒，{len(leavers)} 个人背起行囊走向了远方", "settle")

    def _weaker_neighbor(self, st: Settlement, per_capita: float):
        best, best_d = None, 1e9
        for other in self.settlements.values():
            if other.id == st.id or other.pop < 4:
                continue
            oc = other.stock["food"] / max(1, other.pop)
            if oc <= per_capita:
                continue
            d = math.hypot(st.x - other.x, st.y - other.y)
            if d < best_d:
                best_d, best = d, other
        return best

    def _do_war(self, a: Settlement, b: Settlement) -> None:
        self.war_events += 1
        a.wars += 1
        b.wars += 1
        a.conflicts += 1
        b.conflicts += 1
        a.relations[b.id] = max(-1.0, a.relations.get(b.id, 0.0) - 0.65)
        b.relations[a.id] = max(-1.0, b.relations.get(a.id, 0.0) - 0.65)

        a_members = [self.humans[i] for i in a.members if i in self.humans]
        b_members = [self.humans[i] for i in b.members if i in self.humans]
        losses = []
        for group in (a_members, b_members):
            n = max(1, int(len(group) * 0.12))
            victims = self.py_rng.sample(group, min(n, len(group)))
            for h in victims:
                self._kill(h, "战乱")
                losses.append(h)

        a_power = sum(h.aggression + h.skills.get("战斗", 0) * 0.05 for h in a_members)
        b_power = sum(h.aggression + h.skills.get("战斗", 0) * 0.05 for h in b_members)
        winner, loser = (a, b) if a_power >= b_power else (b, a)
        loot = loser.stock["food"] * 0.4
        loser.stock["food"] -= loot
        winner.stock["food"] += loot

        for s in (a, b):
            if "城防" not in s.knowledge:
                s.knowledge.add("城防")
                s.institutions.add("筑墙自卫")
                self._announce_settlement(s, "城防")

        self.add_log(
            f"{a.name}与{b.name}爆发冲突，{len(losses)} 人再没有回来，{winner.name}掠走了存粮", "war"
        )
        self.add_chronicle("first_war",
                           f"{a.name}与{b.name}之间爆发了世上第一场战争，{winner.name}掠走了存粮")

    def _births(self) -> None:
        if len(self.humans) >= self.max_population:
            return
        adults = [h for h in self.humans.values()
                  if h.alive and 16 <= h.age <= 46 and h.health > 0.5 and h.food > 0.35]
        if len(adults) < 2:
            return
        self.py_rng.shuffle(adults)
        used: set[int] = set()
        for a in adults:
            if a.id in used:
                continue
            b = self._find_partner(a, adults, used)
            if b is None:
                continue
            # 身边有吃的、聚落有余粮，才养得起孩子
            xi, yi = int(a.x), int(a.y)
            local = float(self.world.plants[yi, xi]) if self.world.in_bounds(xi, yi) else 0.0
            st = self.settlements.get(a.home)
            surplus = (st.stock["food"] / max(1, st.pop)) if st is not None else 0.0
            fertility = min(1.6, 0.52 + local + surplus * 0.5)
            if self.py_rng.random() > 0.42 * (0.6 + a.sociability) * fertility:
                continue

            used.add(a.id)
            used.add(b.id)
            a.partner = b.id
            b.partner = a.id
            jx = a.x + (self.py_rng.random() - 0.5)
            jy = a.y + (self.py_rng.random() - 0.5)
            if not self.world.is_walkable(jx, jy):
                jx, jy = a.x, a.y
            child = self._new_human(jx, jy, age=0.0, parents=(a, b))
            child.home = a.home if a.home is not None else b.home
            a.child_count += 1
            b.child_count += 1
            self.births += 1
            if self.births == 1:
                self.add_chronicle("first_child", f"{child.name}是这块土地上出生的第一个婴孩")
            if st is not None and self.py_rng.random() < 0.10:
                self.add_log(f"{st.name}添了一个孩子：{child.name}", "life")

    def _find_partner(self, a: Human, adults: list[Human], used: set[int]):
        """先找旧伴侣，再找身边亲近的人。"""
        if a.partner is not None and a.partner not in used:
            p = self.humans.get(a.partner)
            if (p is not None and p.alive and 16 <= p.age <= 46 and
                    math.hypot(p.x - a.x, p.y - a.y) < 12):
                return p
        best, best_d = None, 9.0
        for b in adults:
            if b.id == a.id or b.id in used:
                continue
            d = math.hypot(a.x - b.x, a.y - b.y)
            if d < best_d and a.relations.get(b.id, 0.0) > 0.18:
                best_d, best = d, b
        if best is not None:
            return best
        # 人丁稀少时，住得近的男女自然走到一起——否则小族群会断了香火
        if len(adults) <= 14:
            best_d = 6.0
            for b in adults:
                if b.id == a.id or b.id in used:
                    continue
                d = math.hypot(a.x - b.x, a.y - b.y)
                if d < best_d:
                    best_d, best = d, b
        return best

    def _institutions(self) -> None:
        for st in self.settlements.values():
            pop = st.pop
            k = st.knowledge
            if pop >= 12 and "长老议事" not in st.institutions:
                st.institutions.add("长老议事")
                self.add_log(f"{st.name}的长者开始一同决定事务", "settle")
            if pop >= 18 and st.conflicts >= 1 and "律法" not in k:
                k.add("律法")
                st.institutions.add("约定成文")
                self._announce_settlement(st, "律法")
            if "农业" in k and "交易" in k and pop >= 14 and "文字" not in k:
                k.add("文字")
                st.institutions.add("刻痕记事")
                self._announce_settlement(st, "文字")
            if "火" in k and pop >= 10 and "祭祀" not in k:
                if self.deaths > 0 and self.py_rng.random() < 0.35:
                    k.add("祭祀")
                    st.institutions.add("祭天")
                    self._announce_settlement(st, "祭祀")
            st.era = self._era_of(st)

    def _era_of(self, st: Settlement) -> str:
        k = st.knowledge
        pop = st.pop
        if "文字" in k and "律法" in k and pop >= 22:
            return "文明"
        if pop >= 18 and "农业" in k:
            return "城邦"
        if "农业" in k:
            return "农耕"
        if "狩猎" in k or "火" in k:
            return "狩猎采集"
        if pop >= 5:
            return "定居"
        return "蒙昧"

    # ------------------------------------------------------------ 工具
    def _bump_skill(self, h: Human, name: str) -> None:
        h.skills[name] = h.skills.get(name, 0) + 1

    def _bump_skill_if_missing(self, h: Human, name: str) -> None:
        if h.skills.get(name, 0) < 3:
            self._bump_skill(h, name)

    def _announce_concept(self, h: Human, concept: str) -> None:
        self.discovery_events += 1
        desc = CONCEPT_DESC.get(concept, concept)
        self.add_log(f"{h.name}{desc}", "know")
        st = self.settlements.get(h.home) if h.home is not None else None
        owner_key = f"concept:{concept}:st{st.id}" if st is not None else None
        self._add_discovery(
            f"concept:{concept}", owner_key,
            f"{h.name}成了世上第一个{desc}的人",
            f"「{st.name}」的人们第一次{desc}" if st is not None else None,
        )

    def _announce_settlement(self, st: Settlement, concept: str) -> None:
        self.discovery_events += 1
        desc = CONCEPT_DESC.get(concept, concept)
        self.add_log(f"{st.name}有人{desc}", "know")
        self._add_discovery(
            f"concept:{concept}", f"concept:{concept}:st{st.id}",
            f"{st.name}的人们成了世上第一批{desc}的人",
            f"「{st.name}」的人们第一次{desc}",
        )

    # ------------------------------------------------------------ 神的行为
    def god_action(self, tool: str, gx: int, gy: int, radius: int) -> str | None:
        w = self.world
        if tool == "land_up":
            w.reshape(gx, gy, radius, 0.055)
            return "大地隆起"
        if tool == "land_down":
            w.reshape(gx, gy, radius, -0.055)
            return "大地沉降"
        if tool == "water":
            w.add_moisture(gx, gy, radius, 0.28)
            return "降下雨水"
        if tool == "dry":
            w.add_moisture(gx, gy, radius, -0.32)
            return "收回水汽"
        if tool == "warm":
            w.add_temperature(gx, gy, radius, 0.10)
            return "暖风拂过"
        if tool == "cool":
            w.add_temperature(gx, gy, radius, -0.10)
            return "寒霜降下"
        if tool == "fertile":
            w.add_soil(gx, gy, radius, 0.12)
            w.add_plants(gx, gy, radius, 0.07)
            return "土地变得肥沃"
        if tool == "plants":
            w.add_plants(gx, gy, radius, 0.24)
            return "草木破土而出"
        if tool == "animals":
            w.add_animals(gx, gy, radius, 0.24)
            return "走兽出现在这片土地上"
        if tool == "humans":
            n = self.spawn_humans(gx, gy, radius, 4)
            return f"{n} 个凡人开始在这片土地上呼吸" if n else "这里无法落脚"
        if tool == "disaster":
            w.blight(gx, gy, radius, 0.55)
            victims = [h for h in self.humans.values()
                       if math.hypot(h.x - gx, h.y - gy) <= radius]
            for h in victims:
                h.health -= 0.6
                if h.health <= 0:
                    self._kill(h, "灾祸")
            self.add_log("灾祸降临，草木枯萎，生灵涂炭", "god")
            return None
        return None

    def possess(self, hid: int) -> bool:
        h = self.humans.get(hid)
        if h is None or not h.alive:
            return False
        if self.possessed_id is not None:
            old = self.humans.get(self.possessed_id)
            if old is not None:
                old.possessed = False
                old.manual = False
                old.manual_vec = (0.0, 0.0)
        self.possessed_id = hid
        h.possessed = True
        h.manual = True
        h.manual_vec = (0.0, 0.0)
        self.add_log(f"神明走进了{h.name}的身体——从此他要自己找水、自己觅食", "god")
        return True

    def release(self) -> None:
        h = self.humans.get(self.possessed_id) if self.possessed_id else None
        if h is not None:
            h.possessed = False
            h.manual = False
            h.manual_vec = (0.0, 0.0)
            self.add_log(f"神明离开了{h.name}，回到高处静静看着", "god")
        self.possessed_id = None

    def possessed_human(self) -> Human | None:
        if self.possessed_id is None:
            return None
        return self.humans.get(self.possessed_id)

    # ------------------------------------------------------------ 统计
    def era(self) -> str:
        if not self.settlements:
            return "蒙昧"
        return max((s.era for s in self.settlements.values()),
                   key=lambda e: ERA_ORDER.index(e))

    def stats(self) -> dict:
        alive = len(self.humans)
        known: set[str] = set()
        professions: dict[str, int] = {}
        for h in self.humans.values():
            known |= h.knowledge
            professions[h.profession] = professions.get(h.profession, 0) + 1
        return {
            "tick": self.tick,
            "population": alive,
            "settlements": len(self.settlements),
            "era": self.era(),
            "knowledge": sorted(known),
            "professions": professions,
            "trades": self.trade_events,
            "wars": self.war_events,
            "births": self.births,
            "deaths": self.deaths,
        }