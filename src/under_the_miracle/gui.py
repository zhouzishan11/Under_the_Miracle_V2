"""《神迹之下》图形界面。

左边是你创造的世界，右边是你仅有的权柄：
你只能改变风雨寒暑、草木走兽，不能直接造出城市与文明。
"""
from __future__ import annotations

import math
import random
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .simulation import Simulation
from .world import World

SCALE = 6
# 记录栏最多保留这么多行，再多会自动裁掉最旧的——不然界面会被拖垮
MAX_LOG_LINES = 800
# 史卷窗口同样只展示最近这么多行；完整记载仍保留在 sim.chronicle 里
CHRONICLE_MAX_LINES = 800

TOOLS = [
    ("inspect", "察看", "看看这片土地的状况，不改变任何东西"),
    ("land_up", "抬升大地", "让大地隆起成山"),
    ("land_down", "沉降大地", "让大地凹陷，低处自会积水成湖"),
    ("water", "降下雨水", "水汽滋养土地，人能在此饮水，草木得以生长"),
    ("dry", "收回水汽", "让土地变得干旱"),
    ("warm", "送来暖风", "提高这一带的温度"),
    ("cool", "降下寒霜", "降低这一带的温度"),
    ("fertile", "赐福土壤", "让土地变得肥沃"),
    ("plants", "播撒草木", "让植物在这片土地上生长"),
    ("animals", "播撒走兽", "让动物出现在这片土地上"),
    ("humans", "播撒凡人", "放下几个凡人。他们什么都不懂，只会活下去"),
    ("disaster", "降下灾祸", "草木枯萎，生灵涂炭"),
]

JOB_COLOR = {
    "农夫": (150, 214, 110),
    "采集者": (238, 238, 232),
    "猎人": (226, 156, 92),
    "工匠": (162, 176, 240),
    "商人": (248, 208, 84),
    "战士": (232, 92, 92),
    "智者": (196, 140, 244),
    "游民": (176, 176, 176),
    "孩童": (255, 246, 190),
}
DEFAULT_COLOR = (255, 255, 255)

LOG_COLOR = {
    "god": "#ffe9a8",
    "life": "#d8d8d8",
    "settle": "#8fd6ff",
    "know": "#b9f2a8",
    "trade": "#ffd479",
    "war": "#ff8f8f",
}

# 地图上要标聚落的名字，得找一个能写汉字的字体
CJK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def load_cjk_font(size: int = 13):
    for path in CJK_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


class GodGame:
    def __init__(self, root: tk.Tk, seed: int | None = None):
        self.root = root
        self.seed = seed if seed is not None else random.randint(1, 10 ** 6)
        self.world = World(width=120, height=80, seed=self.seed)
        self.sim = Simulation(self.world, seed=self.seed)

        self.tool = tk.StringVar(value="inspect")
        self.brush = tk.IntVar(value=9)
        self.speed = tk.IntVar(value=1)
        self.pending_possess = False
        self.hover = (0, 0)
        self.hover_on = False
        self.dragging = False

        self._log_shown = 0
        self._chronicle_win: tk.Toplevel | None = None
        self._chronicle_text: tk.Text | None = None
        self._chronicle_note: tk.Label | None = None
        self._chronicle_page_label: tk.Label | None = None
        self._chronicle_prev_btn: tk.Button | None = None
        self._chronicle_next_btn: tk.Button | None = None
        self._chronicle_latest_btn: tk.Button | None = None
        # 史卷分页状态：_chronicle_page 为 None 表示跟随最新一卷
        self._chronicle_page: int | None = None
        self._chronicle_pages = 1
        self._chronicle_data_shown = 0
        self._chronicle_btn_count = -1
        self._last_stats = 0.0
        self._last_frame = 0.0
        self._photo = None
        self.label_font = load_cjk_font(13)
        self._keys: set[str] = set()
        self._build_ui()
        self._bind_events()

        self.sim.add_log("世界空无一物。没有水，没有草木，没有一个人。", "god")
        self.sim.add_log("先降下雨水，播撒草木走兽，再放下凡人——剩下的，交给他们自己。", "god")
        self._render()
        self.root.after(90, self._loop)

    # ---------------------------------------------------------------- 界面
    def _build_ui(self) -> None:
        self.root.title("神迹之下 —— 你只改变环境，文明自己长出来")
        self.root.configure(bg="#141821")

        self.canvas = tk.Canvas(self.root, width=self.world.w * SCALE,
                                height=self.world.h * SCALE, highlightthickness=0,
                                bg="#0b0e14")
        self.canvas.grid(row=0, column=0, rowspan=2, padx=10, pady=10, sticky="n")
        self.map_item = self.canvas.create_image(0, 0, anchor="nw")

        panel = tk.Frame(self.root, bg="#1b2130", width=350)
        panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(0, 10), pady=10)
        panel.grid_propagate(False)

        tk.Label(panel, text="神 迹 之 下", bg="#1b2130", fg="#e8d9a8",
                 font=("sans-serif", 18, "bold")).pack(pady=(12, 2))
        tk.Label(panel, text="你无法创造文明，只能给它一个可能",
                 bg="#1b2130", fg="#7d879c", font=("sans-serif", 9)).pack(pady=(0, 10))

        self.stat_label = tk.Label(panel, text="", bg="#1b2130", fg="#cdd6e6",
                                   justify="left", anchor="w", font=("monospace", 10))
        self.stat_label.pack(fill="x", padx=14)

        tk.Frame(panel, bg="#2a3348", height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(panel, text="神 之 权 柄", bg="#1b2130", fg="#9fb0cc",
                 font=("sans-serif", 10, "bold")).pack(anchor="w", padx=14)

        grid = tk.Frame(panel, bg="#1b2130")
        grid.pack(fill="x", padx=10, pady=6)
        for i, (key, label, _hint) in enumerate(TOOLS):
            tk.Radiobutton(grid, text=label, value=key, variable=self.tool,
                           indicatoron=False, width=7, pady=3,
                           bg="#232b3d", fg="#d5deee", selectcolor="#3a5f8a",
                           activebackground="#2d3964", bd=0, command=self._on_tool_change,
                           font=("sans-serif", 10)).grid(
                row=i // 2, column=i % 2, padx=3, pady=3, sticky="ew")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        brush_row = tk.Frame(panel, bg="#1b2130")
        brush_row.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(brush_row, text="笔刷", bg="#1b2130", fg="#9fb0cc").pack(side="left")
        tk.Scale(brush_row, from_=1, to=22, orient="horizontal", variable=self.brush,
                 bg="#1b2130", fg="#cdd6e6", troughcolor="#2a3348",
                 highlightthickness=0, showvalue=True, length=200).pack(side="left", padx=6)

        tk.Frame(panel, bg="#2a3348", height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(panel, text="时 间", bg="#1b2130", fg="#9fb0cc",
                 font=("sans-serif", 10, "bold")).pack(anchor="w", padx=14)
        speed_row = tk.Frame(panel, bg="#1b2130")
        speed_row.pack(fill="x", padx=12, pady=4)
        for text, val in (("暂停", 0), ("正常", 1), ("2 倍", 2), ("4 倍", 4)):
            tk.Radiobutton(speed_row, text=text, value=val, variable=self.speed,
                           indicatoron=False, width=6, bg="#232b3d", fg="#d5deee",
                           selectcolor="#3a5f8a", activebackground="#2d3964", bd=0,
                           font=("sans-serif", 9)).pack(side="left", padx=2)

        tk.Frame(panel, bg="#2a3348", height=1).pack(fill="x", padx=12, pady=8)
        self.possess_btn = tk.Button(panel, text="降临人间", command=self._toggle_possess,
                                     bg="#4a3b6b", fg="#eadcff", bd=0, pady=6,
                                     activebackground="#5d4a85",
                                     font=("sans-serif", 11, "bold"))
        self.possess_btn.pack(fill="x", padx=14)
        self.mortal_label = tk.Label(panel, text="（先点『降临人间』，再点击地图上的一个人）",
                                     bg="#1b2130", fg="#7d879c", justify="left",
                                     anchor="w", wraplength=310, font=("monospace", 9))
        self.mortal_label.pack(fill="x", padx=14, pady=(6, 0))

        tk.Frame(panel, bg="#2a3348", height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(panel, text="文 明 史 卷", bg="#1b2130", fg="#9fb0cc",
                 font=("sans-serif", 10, "bold")).pack(anchor="w", padx=14)
        self.chronicle_btn = tk.Button(panel, text="翻开文明史卷",
                                       command=self._open_chronicle,
                                       bg="#54421f", fg="#ffe9a8", bd=0, pady=6,
                                       activebackground="#6b5628",
                                       font=("sans-serif", 11, "bold"))
        self.chronicle_btn.pack(fill="x", padx=14, pady=(6, 0))

        tk.Frame(panel, bg="#2a3348", height=1).pack(fill="x", padx=12, pady=8)
        log_head = tk.Frame(panel, bg="#1b2130")
        log_head.pack(fill="x", padx=14, pady=(0, 2))
        tk.Label(log_head, text="世 间 大 事", bg="#1b2130", fg="#9fb0cc",
                 font=("sans-serif", 10, "bold")).pack(side="left")
        tk.Button(log_head, text="清理", command=self._clear_log,
                  bg="#232b3d", fg="#d5deee", activebackground="#2d3964",
                  bd=0, padx=8, font=("sans-serif", 9)).pack(side="right")
        tk.Button(log_head, text="文明史卷", command=self._open_chronicle,
                  bg="#4a3b6b", fg="#eadcff", activebackground="#5d4a85",
                  bd=0, padx=8, font=("sans-serif", 9)).pack(side="right", padx=4)
        log_frame = tk.Frame(panel, bg="#1b2130")
        log_frame.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        scroll = tk.Scrollbar(log_frame)
        scroll.pack(side="right", fill="y")
        self.log_text = tk.Text(log_frame, bg="#141821", fg="#cdd6e6", bd=0,
                                wrap="word", font=("sans-serif", 9), height=14,
                                yscrollcommand=scroll.set, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.log_text.yview)
        for kind, color in LOG_COLOR.items():
            self.log_text.tag_config(kind, foreground=color)

        self.status = tk.Label(self.root, text=self._tool_hint(), bg="#0b0e14",
                               fg="#8fa3c0", anchor="w", font=("monospace", 10))
        self.status.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.root.grid_rowconfigure(0, weight=1)

    def _bind_events(self) -> None:
        c = self.canvas
        c.bind("<Button-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", self._on_leave)
        self.root.bind("<KeyPress>", self._on_key_down)
        self.root.bind("<KeyRelease>", self._on_key_up)
        self.root.focus_set()

    def _on_tool_change(self) -> None:
        self.status.config(text=self._tool_hint())

    def _tool_hint(self) -> str:
        key = self.tool.get()
        for k, label, hint in TOOLS:
            if k == key:
                return f"【{label}】{hint}"
        return ""

    # ---------------------------------------------------------------- 输入
    def _tile_at(self, event) -> tuple[int, int]:
        return int(event.x // SCALE), int(event.y // SCALE)

    def _on_motion(self, event) -> None:
        self.hover = self._tile_at(event)
        self.hover_on = True
        info = self.world.tile_info(*self.hover)
        if not info:
            self.status.config(text="")
            return
        self.status.config(
            text=(f"({info['坐标'][0]}, {info['坐标'][1]})  {info['地貌']}   "
                  f"海拔{info['海拔']:.2f}  温度{info['温度']:.2f}  水汽{info['水汽']:.2f}   "
                  f"土壤{info['土壤']:.2f}   植被{info['植被']:.2f}   走兽{info['走兽']:.2f}"))

    def _on_leave(self, _event) -> None:
        self.hover_on = False
        self.status.config(text=self._tool_hint())

    def _on_press(self, event) -> None:
        self.root.focus_set()
        gx, gy = self._tile_at(event)
        if self.pending_possess:
            self._try_possess(gx, gy)
            return
        self.dragging = True
        self._apply(gx, gy, announce=True)

    def _on_drag(self, event) -> None:
        if not self.dragging:
            return
        tool = self.tool.get()
        if tool in ("inspect", "humans", "disaster"):
            return
        self._apply(*self._tile_at(event), announce=False)

    def _on_release(self, _event) -> None:
        self.dragging = False

    def _apply(self, gx: int, gy: int, announce: bool) -> None:
        if not self.world.in_bounds(gx, gy):
            return
        tool = self.tool.get()
        if tool == "inspect":
            return
        radius = self.brush.get()
        if tool == "humans":
            radius = max(2, radius // 2)
        msg = self.sim.god_action(tool, gx, gy, radius)
        if announce and msg:
            self.sim.add_log(msg, "god")

    def _try_possess(self, gx: int, gy: int) -> None:
        best, best_d = None, 6.0
        for h in self.sim.humans.values():
            d = math.hypot(h.x - gx, h.y - gy)
            if d < best_d:
                best_d, best = d, h
        self.pending_possess = False
        self.possess_btn.config(text="降临人间", bg="#4a3b6b")
        if best is None:
            self.sim.add_log("这里没有可以附身的人。", "god")
            return
        self.sim.possess(best.id)

    def _toggle_possess(self) -> None:
        if self.sim.possessed_id is not None:
            self.sim.release()
            self.possess_btn.config(text="降临人间", bg="#4a3b6b")
            return
        self.pending_possess = not self.pending_possess
        self.possess_btn.config(text="点选一个人…" if self.pending_possess else "降临人间",
                                bg="#7a5ea8" if self.pending_possess else "#4a3b6b")

    def _on_key_down(self, event) -> None:
        self._keys.add(event.keysym.lower())

    def _on_key_up(self, event) -> None:
        self._keys.discard(event.keysym.lower())

    def _manual_vector(self) -> tuple[float, float]:
        k = self._keys
        vx = (1.0 if ("d" in k or "right" in k) else 0.0) - (1.0 if ("a" in k or "left" in k) else 0.0)
        vy = (1.0 if ("s" in k or "down" in k) else 0.0) - (1.0 if ("w" in k or "up" in k) else 0.0)
        return vx, vy

    # ---------------------------------------------------------------- 循环
    def _loop(self) -> None:
        steps = self.speed.get()
        h = self.sim.possessed_human()
        if h is not None:
            h.manual_vec = self._manual_vector()
        if steps:
            self.sim.tick_once()
        # 渲染与模拟解耦：约 90ms 至多画一帧。高速倍率下 UI 事件（翻史卷、
        # 滚记录栏）在两次 tick 之间就能得到响应，不再被一帧内连跑数个 tick
        # 的垄断拖住——这是后期"史卷打不开/界面卡住"的直接原因。
        now = time.monotonic()
        if now - self._last_frame >= 0.085:
            self._render()
            self._last_frame = now
        # 每个回调只推 1 个 tick，间隔按倍速折算，总模拟速率与原实现基本一致
        self.root.after(max(12, round(90 / steps)) if steps else 90, self._loop)

    # ---------------------------------------------------------------- 绘制
    def _render(self) -> None:
        w = self.world
        base = Image.fromarray(w.color_array()).resize(
            (w.w * SCALE, w.h * SCALE), Image.NEAREST)
        draw = ImageDraw.Draw(base, "RGBA")

        for st in self.sim.settlements.values():
            px, py = st.x * SCALE, st.y * SCALE
            r = 5 + min(6.0, st.pop * 0.12)
            draw.ellipse([px - r, py - r, px + r, py + r],
                         fill=(255, 232, 130, 210), outline=(70, 45, 10, 255), width=2)
            draw.text((px + r + 3, py - 8), f"{st.name}·{st.pop}",
                      fill=(255, 255, 255, 240), font=self.label_font,
                      stroke_width=2, stroke_fill=(20, 16, 10, 220))

        for h in self.sim.humans.values():
            px, py = h.x * SCALE, h.y * SCALE
            if h.possessed:
                draw.ellipse([px - 7, py - 7, px + 7, py + 7],
                             outline=(255, 120, 200, 255), width=2)
                draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(255, 210, 240, 255))
                continue
            col = JOB_COLOR.get(h.profession, DEFAULT_COLOR)
            draw.ellipse([px - 2, py - 2, px + 2, py + 2], fill=col + (255,))

        if self.hover_on and self.tool.get() != "inspect":
            gx, gy = self.hover
            r = self.brush.get() * SCALE
            cx, cy = gx * SCALE + SCALE / 2, gy * SCALE + SCALE / 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         outline=(255, 255, 255, 170), width=2)

        self._photo = ImageTk.PhotoImage(base)
        self.canvas.itemconfig(self.map_item, image=self._photo)

        self._refresh_panels()

    def _refresh_panels(self) -> None:
        now = time.time()
        if now - self._last_stats < 0.25:
            return
        self._last_stats = now
        s = self.sim.stats()
        era = s["era"]
        self.stat_label.config(
            text=(f"第 {s['tick']:>6d} 步（约 {s['tick'] // 12:>4d} 年）\n"
                  f"时代   {era}\n"
                  f"人口   {s['population']:>5d}\n"
                  f"聚落   {s['settlements']:>5d}\n"
                  f"已知   {'、'.join(s['knowledge']) if s['knowledge'] else '无'}\n"
                  f"交换 {s['trades']} 次   冲突 {s['wars']} 次\n"
                  f"出生 {s['births']} 人   死去 {s['deaths']} 人"))

        pro = s["professions"]
        parts = [f"{k}×{v}" for k, v in sorted(pro.items(), key=lambda kv: -kv[1]) if k != "孩童"]
        self._refresh_mortal()
        if self.sim.possessed_id is None:
            self.mortal_label.config(
                text=f"职业分布：{'  '.join(parts) if parts else '尚无'}")

        if len(self.sim.log) != self._log_shown:
            self.log_text.config(state="normal")
            for tick, text, kind in self.sim.log[self._log_shown:]:
                self.log_text.insert("end", f"[{tick}] {text}\n", kind)
            self._log_shown = len(self.sim.log)
            # 记录越攒越多会拖垮界面：超过上限就裁掉最旧的部分
            n = int(self.log_text.index("end-1c").split(".")[0])
            if n > MAX_LOG_LINES:
                self.log_text.delete("1.0", f"{n - MAX_LOG_LINES + 1}.0")
            self.log_text.see("end")
            self.log_text.config(state="disabled")

        self._refresh_chronicle()
        n = len(self.sim.chronicle)
        if n != self._chronicle_btn_count:
            self._chronicle_btn_count = n
            self.chronicle_btn.config(text=f"翻开文明史卷（{n} 条）")

    def _clear_log(self) -> None:
        """动态清理：一键清空记录栏。文明史卷里的第一次不受影响。"""
        self.sim.clear_log()
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self._log_shown = 0

    def _open_chronicle(self) -> None:
        """翻开文明史卷——只记世上第一次发生的事。"""
        if self._chronicle_win is not None and self._chronicle_win.winfo_exists():
            self._chronicle_win.deiconify()
            self._chronicle_win.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("文明史卷")
        win.configure(bg="#141821")
        win.geometry("480x540")
        tk.Label(win, text="文 明 史 卷", bg="#141821", fg="#e8d9a8",
                 font=("sans-serif", 14, "bold")).pack(pady=(12, 2))
        tk.Label(win, text="只铭记第一次——重复的岁月都沉入尘埃",
                 bg="#141821", fg="#7d879c", font=("sans-serif", 9)).pack(pady=(0, 2))
        self._chronicle_note = tk.Label(win, text="", bg="#141821", fg="#7d879c",
                                        font=("sans-serif", 9))
        self._chronicle_note.pack(pady=(0, 6))
        frame = tk.Frame(win, bg="#141821")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        sbar = tk.Scrollbar(frame)
        sbar.pack(side="right", fill="y")
        text = tk.Text(frame, bg="#1b2130", fg="#cdd6e6", bd=0, wrap="word",
                       font=("sans-serif", 10), state="disabled", yscrollcommand=sbar.set)
        text.pack(side="left", fill="both", expand=True)
        sbar.config(command=text.yview)
        text.tag_config("chronicle", foreground="#ffe9a8")
        nav = tk.Frame(win, bg="#141821")
        nav.pack(fill="x", padx=12, pady=(0, 12))
        self._chronicle_prev_btn = tk.Button(
            nav, text="◀ 上一卷", command=self._chronicle_prev,
            bg="#232b3d", fg="#d5deee", activebackground="#2d3964",
            disabledforeground="#5a6478", bd=0, padx=10, font=("sans-serif", 9))
        self._chronicle_prev_btn.pack(side="left")
        self._chronicle_latest_btn = tk.Button(
            nav, text="回到最新", command=self._chronicle_latest,
            bg="#232b3d", fg="#d5deee", activebackground="#2d3964",
            disabledforeground="#5a6478", bd=0, padx=10, font=("sans-serif", 9))
        self._chronicle_latest_btn.pack(side="right")
        self._chronicle_next_btn = tk.Button(
            nav, text="下一卷 ▶", command=self._chronicle_next,
            bg="#232b3d", fg="#d5deee", activebackground="#2d3964",
            disabledforeground="#5a6478", bd=0, padx=10, font=("sans-serif", 9))
        self._chronicle_next_btn.pack(side="right", padx=4)
        self._chronicle_page_label = tk.Label(nav, text="第 1 / 1 卷", bg="#141821",
                                              fg="#cdd6e6", font=("sans-serif", 9))
        self._chronicle_page_label.pack(side="right", padx=8)
        self._chronicle_win = win
        self._chronicle_text = text
        self._chronicle_page = None
        self._chronicle_pages = 1
        self._chronicle_data_shown = 0
        win.protocol("WM_DELETE_WINDOW", self._close_chronicle)
        # 先让空窗口立即出现，内容等到下一轮事件再渲染，避免创建途中同步渲染拖住界面
        win.after(50, self._refresh_chronicle)

    def _close_chronicle(self) -> None:
        """关闭史卷窗口只是收起：内容保留，下次翻开不用重新渲染。"""
        if self._chronicle_win is not None:
            self._chronicle_win.withdraw()

    def _chronicle_prev(self) -> None:
        """往前翻一卷；跟随最新时先跳到倒数第二卷。"""
        if self._chronicle_page is None:
            if self._chronicle_pages <= 1:
                return
            self._chronicle_page = self._chronicle_pages - 2
        elif self._chronicle_page > 0:
            self._chronicle_page -= 1
        else:
            return
        self._render_chronicle()

    def _chronicle_next(self) -> None:
        """往后翻一卷；翻到最后一卷就恢复跟随最新。"""
        if self._chronicle_page is None or self._chronicle_page >= self._chronicle_pages - 1:
            return
        self._chronicle_page += 1
        if self._chronicle_page >= self._chronicle_pages - 1:
            self._chronicle_page = None
        self._render_chronicle()

    def _chronicle_latest(self) -> None:
        if self._chronicle_page is None:
            return
        self._chronicle_page = None
        self._render_chronicle()

    def _render_chronicle(self) -> None:
        """按当前页重建正文。一页最多 CHRONICLE_MAX_LINES 行，一次写入不会卡。"""
        text = self._chronicle_text
        total = len(self.sim.chronicle)
        pages = max(1, math.ceil(total / CHRONICLE_MAX_LINES))
        self._chronicle_pages = pages
        page = pages - 1 if self._chronicle_page is None else self._chronicle_page
        start = page * CHRONICLE_MAX_LINES
        end = min(total, start + CHRONICLE_MAX_LINES)
        block = "".join(f"[{t}] {e}\n" for t, e in self.sim.chronicle[start:end])
        text.config(state="normal")
        text.delete("1.0", "end")
        if block:
            text.insert("1.0", block, "chronicle")
        text.see("end" if self._chronicle_page is None else "1.0")
        text.config(state="disabled")
        self._update_chronicle_caption()

    def _update_chronicle_caption(self) -> None:
        """更新史卷窗口里的总数、页码与翻页按钮状态。"""
        if self._chronicle_note is None:
            return
        total = len(self.sim.chronicle)
        pages = self._chronicle_pages
        shown = pages if self._chronicle_page is None else self._chronicle_page + 1
        note = f"共 {total} 条第一次留下的记载"
        if pages > 1:
            note += f"（每卷 {CHRONICLE_MAX_LINES} 条）"
        self._chronicle_note.config(text=note)
        if self._chronicle_page_label is not None:
            self._chronicle_page_label.config(text=f"第 {shown} / {pages} 卷")
        self._chronicle_prev_btn.config(state=(
            "normal" if (self._chronicle_page is None and pages > 1)
            or (self._chronicle_page is not None and self._chronicle_page > 0)
            else "disabled"))
        self._chronicle_next_btn.config(state=(
            "normal" if self._chronicle_page is not None
            and self._chronicle_page < pages - 1
            else "disabled"))
        self._chronicle_latest_btn.config(state=(
            "normal" if self._chronicle_page is not None else "disabled"))

    def _refresh_chronicle(self) -> None:
        if self._chronicle_win is None or self._chronicle_text is None:
            return
        if not self._chronicle_win.winfo_ismapped():
            return  # 窗口收起着：后台不做任何渲染，等重新翻开再赶上
        total = len(self.sim.chronicle)
        pages = max(1, math.ceil(total / CHRONICLE_MAX_LINES))
        old_pages = self._chronicle_pages
        self._chronicle_pages = pages
        if self._chronicle_page is not None and self._chronicle_page >= pages:
            self._chronicle_page = pages - 1
        if total == self._chronicle_data_shown:
            return
        if self._chronicle_page is None:
            if pages != old_pages:
                # 出现新卷：整卷重画（一次写入）
                self._chronicle_data_shown = total
                self._render_chronicle()
            else:
                # 同一卷内新增：只追加新条目；贴底时才自动滚动，不打扰翻看
                text = self._chronicle_text
                block = "".join(f"[{t}] {e}\n"
                                for t, e in self.sim.chronicle[self._chronicle_data_shown:])
                text.config(state="normal")
                text.insert("end", block, "chronicle")
                self._chronicle_data_shown = total
                try:
                    at_bottom = text.yview()[1] >= 0.97
                except tk.TclError:
                    at_bottom = True
                if at_bottom:
                    text.see("end")
                text.config(state="disabled")
                self._update_chronicle_caption()
        else:
            # 正在翻看旧卷：正文不动，只更新计数
            self._chronicle_data_shown = total
            self._update_chronicle_caption()

    def _refresh_mortal(self) -> None:
        h = self.sim.possessed_human()
        if h is None:
            if self.sim.possessed_id is not None:
                self.mortal_label.config(text="你附身的那个人已经死了。")
            return
        st = self.sim.settlements.get(h.home)
        friends, foes = h.relation_stats()
        self.mortal_label.config(
            text=(f"你是 {h.name}，{int(h.age)} 岁，{h.profession}\n"
                  f"身体：{h.status_text()}（{h.need_phrase()}）\n"
                  f"食物 {h.food:.2f}  水 {h.water:.2f}  精力 {h.energy:.2f}  健康 {h.health:.2f}\n"
                  f"正在 {h.action}\n"
                  f"家乡：{st.name if st else '四处为家'}\n"
                  f"好友 {friends} 人，仇敌 {foes} 人，技能 "
                  f"{'、'.join(sorted(h.skills, key=lambda k: -h.skills[k])[:3]) or '无'}\n"
                  f"知道：{'、'.join(sorted(h.knowledge)) or '什么都不懂'}\n"
                  f"用 W A S D 或方向键行走"))


def run(seed: int | None = None) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(
            "无法打开图形界面（没有可用的显示器）。\n"
            "请在有桌面环境的机器上运行，或设置 DISPLAY 环境变量。\n"
            f"原始错误：{exc}"
        )
    root.geometry("1120x620")
    GodGame(root, seed=seed)
    root.mainloop()