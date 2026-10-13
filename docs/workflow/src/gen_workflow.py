"""docs/workflow 흐름도 생성기. 그림을 고치면 다시 실행:
    cd docs/workflow && python3 src/gen_workflow.py src/template.html AniWhere_워크플로우_전후비교.html

그림 하나 = 기능 하나. 위 줄이 AniWhere 없이(BEFORE), 아래 줄이 AniWhere를 쓸 때(AFTER)이며 열 위치를 맞춰
위아래를 맞대어 읽는다. 아래 줄의 판단(마름모)에서 갈라지는 가지는 세 번째 줄에 둔다.
좌표는 4px 단위, 연결선은 직각 꺾임(모서리 둥글림), 선 위 글자는 뒤에 바탕을 깔고 선에서 띄운다."""
import sys
from html import escape

BW, BH = 176, 72          # 기본 상자
SH = 64                   # 시작(알약) 상자 높이
DW, DH = 80, 44           # 마름모 반폭·반높이
R_ELBOW = 8               # 꺾임 반지름
W = 1200                  # 그림 너비
C = [104, 304, 504, 704, 904, 1104]   # 열 중심
YB, YA, YX = 104, 300, 444            # BEFORE 줄 · AFTER 줄 · AFTER의 가지 줄
SEP = 196                             # 두 줄 사이 가는 선

R = lambda cx, w=BW: cx + w / 2
L = lambda cx, w=BW: cx - w / 2


class Fig:
    def __init__(self, fid, h, title, desc):
        self.fid, self.w, self.h = fid, W, h
        self.title, self.desc = title, desc
        self.under, self.edges, self.parts = [], [], []   # 그리는 순서: 바탕 → 선 → 상자

    # --- 글자 ---
    def text(self, x, y, s, cls="t", anchor="middle"):
        self.parts.append(f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(s)}</text>')

    # --- 줄 머리: 왼쪽에 BEFORE/AFTER 표시, 오른쪽에 집계 ---
    def row(self, y, tag, title, stat, kind):
        ty = y - 76
        self.parts.append(f'<rect x="24" y="{ty - 14}" width="{len(tag) * 8 + 16}" height="20" rx="4" class="tag-{kind}"/>')
        self.text(32, ty, tag, f"tagt-{kind}", "start")
        self.text(32 + len(tag) * 8 + 16 + 10, ty, title, "rowt", "start")
        self.text(W - 24, ty, stat, f"stat-{kind}", "end")

    def sep(self, y=SEP):
        self.under.append(f'<line x1="24" y1="{y}" x2="{W - 24}" y2="{y}" class="sep"/>')

    # --- 상자 ---
    def box(self, cx, cy, title, subs=(), kind="n", w=BW, h=BH):
        x, y = cx - w / 2, cy - h / 2
        rx = h / 2 if kind == "start" else 8
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="mask"/>')
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="b-{kind}"/>')
        lines = [title] if isinstance(title, str) else list(title)
        if kind == "start":
            top = cy - (len(lines) - 1) * 9 + 5
            for i, s in enumerate(lines):
                self.text(cx, top + i * 18, s, "t-start")
            return
        top = cy - 12 if subs else cy + 5
        if len(subs) == 1:
            top = cy - 6
        self.text(cx, top, lines[0], "t")
        for i, s in enumerate(subs):
            self.text(cx, top + 18 + i * 15, s, "ts")

    def start(self, cx, cy, lines):
        self.box(cx, cy, lines, kind="start", h=SH)

    def diamond(self, cx, cy, lines):
        pts = f"{cx},{cy - DH} {cx + DW},{cy} {cx},{cy + DH} {cx - DW},{cy}"
        self.parts.append(f'<polygon points="{pts}" class="mask"/>')
        self.parts.append(f'<polygon points="{pts}" class="b-d"/>')
        top = cy - (len(lines) - 1) * 8 + 4
        for i, s in enumerate(lines):
            self.text(cx, top + i * 16, s, "td")

    # --- 연결선: 직각 꺾임 + 둥근 모서리 ---
    @staticmethod
    def _path(pts, r=R_ELBOW):
        if len(pts) == 2:
            return f"M{pts[0][0]},{pts[0][1]} L{pts[1][0]},{pts[1][1]}"
        d = [f"M{pts[0][0]},{pts[0][1]}"]
        for i in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
            dx1, dy1 = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
            dx2, dy2 = (x2 > x1) - (x2 < x1), (y2 > y1) - (y2 < y1)
            d.append(f"L{x1 - dx1 * r},{y1 - dy1 * r} Q{x1},{y1} {x1 + dx2 * r},{y1 + dy2 * r}")
        d.append(f"L{pts[-1][0]},{pts[-1][1]}")
        return " ".join(d)

    def edge(self, pts, kind="e", label=None, at=None, anchor="middle", lcls=None):
        marker = {"e": "a", "e-key": "k", "e-pain": "p"}[kind]
        self.edges.append(f'<path d="{self._path(pts)}" class="{kind}" marker-end="url(#{self.fid}-{marker})"/>')
        if label:
            self.label(label, at, anchor, lcls)

    def label(self, s, at, anchor="middle", lcls=None):
        """선 위 글자. 뒤에 바탕을 깔아 선이 비치지 않게 하고, 선에서 6px 이상 띄운 자리에 둔다."""
        lx, ly = at
        wpx = len(s) * 12 + 8
        x = {"middle": lx - wpx / 2, "start": lx - 4, "end": lx - wpx + 4}[anchor]
        self.edges.append(f'<rect x="{x}" y="{ly - 12}" width="{wpx}" height="16" rx="3" class="mask"/>')
        self.edges.append(f'<text x="{lx}" y="{ly}" class="{lcls or "tl"}" text-anchor="{anchor}">{escape(s)}</text>')

    def chain(self, y, cols, kind="e"):
        """같은 줄에서 왼쪽 열 → 오른쪽 열로 이어지는 화살표. cols는 (열 번호, 모양) 목록. 모양: b=상자, d=마름모, s=시작."""
        for (ca, ka), (cb, kb) in zip(cols, cols[1:]):
            x0 = C[ca] + (DW if ka == "d" else BW / 2)
            x1 = C[cb] - (DW if kb == "d" else BW / 2)
            self.edge([(x0, y), (x1, y)], kind)

    def badge(self, cx, y, s):
        """불편·스포일러 지점: 빨간 원 + 느낌표 + 글. 상자 위에 둔다."""
        width = len(s) * 11.5 + 30
        x = cx - width / 2
        self.parts.append(f'<rect x="{x}" y="{y - 11}" width="{width}" height="22" rx="11" class="bad-bg"/>')
        self.parts.append(f'<circle cx="{x + 12}" cy="{y}" r="7" class="bad-dot"/>')
        self.parts.append(f'<text x="{x + 12}" y="{y + 4}" class="bad-mark" text-anchor="middle">!</text>')
        self.text(x + 24, y + 4, s, "bad-t", "start")

    def svg(self):
        defs = "".join(
            f'<marker id="{self.fid}-{m}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ah-{m}"/></marker>' for m in "akp")
        return (f'<svg viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="{self.fid}-title {self.fid}-desc" '
                f'xmlns="http://www.w3.org/2000/svg"><title id="{self.fid}-title">{escape(self.title)}</title>'
                f'<desc id="{self.fid}-desc">{escape(self.desc)}</desc><defs>{defs}</defs>'
                + "".join(self.under + self.edges + self.parts) + "</svg>")


def yes_right(f, col, y, text="예"):
    """마름모 오른쪽 가지 라벨. 마름모와 다음 상자 사이 틈이 좁아, 긴 글자는 상자 윗선보다 위에 둔다."""
    mid = C[col] + DW + 16
    if len(text) == 1:
        f.label(text, (mid, y - 12))
    else:
        f.label(text, (mid, y - BH / 2 - 10))


def no_down(f, col, y, y_to):
    """마름모 아래로 '아니오' 가지. y_to는 가지 줄 상자의 중심."""
    f.edge([(C[col], y + DH), (C[col], y_to - BH / 2)], label="아니오", at=(C[col] + 12, y + DH + 28), anchor="start")


def back_up(f, col_from, col_to, y_from, y_to, label, w=BW):
    """가지 줄 상자의 왼쪽에서 나와 위 줄 상자의 아래로 되돌아가는 선."""
    f.edge([(L(C[col_from], w), y_from), (C[col_to], y_from), (C[col_to], y_to + BH / 2)], "e-key",
           label=label, at=(C[col_to] + 12, y_from - 12), anchor="start", lcls="tl-key")


FIGS = {}


# ──────────────────────────────────────────────────────────────────────────
# 1. 핵심: 기억으로 작품·회차 찾기
# ──────────────────────────────────────────────────────────────────────────
f = Fig("find", 500, "기억으로 작품·회차 찾기: AniWhere 없이 vs 쓸 때",
        "없이는 검색어가 안 맞아 커뮤니티에 묻고 위키 회차 줄거리를 하나씩 열며 뒷 화를 보게 되고, AniWhere는 묘사를 그대로 받아 단서를 뽑고 범위 안에서 검색해 근거가 있을 때만 회차로 답한다")
f.sep()
f.row(YB, "BEFORE", "이름을 모르면 검색이 막힌다", "들르는 곳 3 · 스포일러 1곳", "b")
f.start(C[0], YB, ["그 장면,", "몇 화였지?"])
f.box(C[1], YB, "포털에 장면 묘사", ["이름을 모르면 검색어가 안 맞음"], "n")
f.box(C[2], YB, "커뮤니티·챗봇에 묻기", ["기다리거나, 근거 없이 단정"], "pain")
f.box(C[3], YB, "위키 줄거리 하나씩", ["회차 목록을 차례로 열기"], "n")
f.badge(C[3], YB - 50, "다음 화 줄거리가 같이 보임")
f.box(C[4], YB, "회차 확인", ["맞는지는 직접 봐야 앎"], "n")
f.chain(YB, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b")])

f.row(YA, "AFTER", "근거가 있을 때만 회차로 답한다", "들르는 곳 1 · 스포일러 0곳", "a")
f.start(C[0], YA, ["묘사 그대로", "입력"])
f.box(C[1], YA, "단서 추출", ["이름·키워드 → 작품 후보 4편"], "ai")
f.box(C[2], YA, "회차 검색", ["본 회차까지만", "장면 청크 벡터 + 키워드"], "guard")
f.diamond(C[3], YA, ["근거 문장이", "줄거리에 있나?"])
f.box(C[4], YA, "작품·회차 + 근거", ["출처와 시청처도 같은 화면"], "ai")
f.box(C[5], YA, "기록장에 저장", ["칩 한 번"], "ai")
f.chain(YA, [(0, "s"), (1, "b"), (2, "b"), (3, "d")])
f.edge([(C[3] + DW, YA), (L(C[4]), YA)])
yes_right(f, 3, YA)
f.edge([(R(C[4]), YA), (L(C[5]), YA)])
no_down(f, 3, YA, YX)
f.box(C[3], YX, "후보 제시 또는 되묻기", ["회차를 단정하지 않음"], "ai")
back_up(f, 3, 1, YX, YA, "답하면 다시 찾기")
FIGS["{{FIND}}"] = f.svg()


# ──────────────────────────────────────────────────────────────────────────
# 1-b. 핵심: 에이전트 안 — 찾기의 실제 순서
# ──────────────────────────────────────────────────────────────────────────
f = Fig("inside", 448, "에이전트가 찾는 과정",
        "단서 추출, 작품 후보, 스포일러 범위, 회차 재검색, 판정을 거쳐 근거를 확인하고 회차·작품·후보·못 찾음 네 결과 중 하나로 답한다")
YT, YJ, BUS, YO = 80, 216, 300, 384
f.start(C[0], YT, ["질문 +", "앞선 대화"])
f.box(C[1], YT, "단서 추출", ["제목·이름·키워드·영어 질의"], "ai")
f.box(C[2], YT, "작품 후보 4편", ["제목을 말했으면 그 작품"], "ai")
f.box(C[3], YT, "스포일러 범위", ["기록 있으면 본 회차까지만"], "guard")
f.text(C[3], YT + 56, "기록 없으면 전 회차, 답에는 번호·제목만", "tnote")
f.box(C[4], YT, "회차 검색", ["장면 청크 → 회차로 묶음"], "ai")
f.box(C[5], YT, "판정", ["검색된 자료만 읽고 고름"], "ai")
f.chain(YT, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b"), (5, "b")])
f.diamond(C[5], YJ, ["판정 결과", "+ 근거 확인"])
f.edge([(C[5], YT + BH / 2), (C[5], YJ - DH)])
OW = 216
OC = [144, 400, 656, 912]
f.under.append(f'<path d="{Fig._path([(C[5], YJ + DH), (C[5], BUS), (OC[0], BUS)])}" class="e"/>')
outs = [("회차로 답", ["근거 문장이 줄거리에 있을 때만"], "episode"),
        ("작품만 답", ["장면을 더 묻고 회차를 찾음"], "series"),
        ("후보 제시 + 되묻기", ["비슷한 후보가 여럿일 때"], "ambiguous"),
        ("못 찾음 + 되묻기", ["회차를 단정하지 않음"], "none")]
for cx, (t, s, code) in zip(OC, outs):
    f.edge([(cx, BUS), (cx, YO - BH / 2)])
    f.label(code, (cx + 12, BUS + 28), "start", "tcode")
    f.box(cx, YO, t, s, "ai", w=OW)
FIGS["{{INSIDE}}"] = f.svg()


# ──────────────────────────────────────────────────────────────────────────
# 2. 핵심: 시청처 안내
# ──────────────────────────────────────────────────────────────────────────
f = Fig("watch", 360, "시청처 안내: AniWhere 없이 vs 쓸 때",
        "없이는 OTT 앱을 하나씩 열어 검색하고, AniWhere는 작품이 정해지는 순간 같은 화면에 시즌별 제공처와 확인일을 보여 준다")
f.sep()
f.row(YB, "BEFORE", "앱을 하나씩 연다", "들르는 곳 2~5", "b")
f.start(C[0], YB, ["이거", "어디서 보지?"])
f.box(C[1], YB, "OTT 앱 열어 검색", ["라프텔·넷플릭스·티빙·왓챠…"], "n")
f.box(C[2], YB, "없으면 다음 앱", ["시즌마다 있는 곳이 다름"], "pain")
f.badge(C[2], YB - 50, "어느 시즌이 어디 있는지 모름")
f.box(C[3], YB, "구독 여부 확인", [], "n")
f.box(C[4], YB, "시청", [], "n")
f.chain(YB, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b")])

f.row(YA, "AFTER", "작품이 정해지면 시청처가 따라온다", "들르는 곳 1", "a")
f.start(C[0], YA, ["작품", "확정"])
f.box(C[1], YA, "시청처 조회", ["국내 구독형, 시즌별"], "ai")
f.box(C[2], YA, "제공처 + 확인일 + 링크", ["같은 화면의 카드"], "ai")
f.box(C[3], YA, "시청", [], "n")
f.box(C[4], YA, "멈추면 기록", ["\"N화까지 봤어\""], "ai")
f.chain(YA, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b")])
FIGS["{{WATCH}}"] = f.svg()


# ──────────────────────────────────────────────────────────────────────────
# 3. 핵심: 스포일러 차단 (모든 기능에 걸리는 원칙)
# ──────────────────────────────────────────────────────────────────────────
f = Fig("guard", 500, "스포일러 차단: AniWhere 없이 vs 쓸 때",
        "없이는 위키 회차 목록, 시즌 요약 영상, 챗봇에서 뒷 내용이 보이고, AniWhere는 기록장의 본 회차를 기준으로 검색 전에 이후 청크를 빼고 답 직전에 다시 확인한다")
f.sep()
f.row(YB, "BEFORE", "뒷 내용을 감수해야 한다", "스포일러 3곳", "b")
f.start(C[0], YB, ["줄거리·인물이", "궁금함"])
f.box(C[1], YB, "위키 회차 목록", [], "n")
f.badge(C[1], YB - 50, "다음 화 줄거리 노출")
f.box(C[2], YB, "시즌 요약 영상", [], "n")
f.badge(C[2], YB - 50, "결말까지 섞임")
f.box(C[3], YB, "AI 챗봇", ["어디까지 봤는지 모름"], "n")
f.badge(C[3], YB - 50, "반전을 먼저 말함")
f.box(C[4], YB, "결말을 알고 봄", [], "pain")
f.chain(YB, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b")])

f.row(YA, "AFTER", "본 회차 이후는 검색되지 않는다", "스포일러 0곳", "a")
f.start(C[0], YA, ["기록장의", "본 회차"])
f.diamond(C[1], YA, ["기록이", "있나?"])
f.box(C[2], YA, "검색 전에 제외", ["조건: 회차 ≤ 본 회차"], "guard")
f.box(C[3], YA, "답 직전 재확인", ["섞였으면 코드가 멈춤"], "guard")
f.box(C[4], YA, "자료만으로 답", ["출처마다 회차 표기"], "ai")
f.box(C[5], YA, "시청", [], "n")
f.chain(YA, [(0, "s"), (1, "d")])
f.edge([(C[1] + DW, YA), (L(C[2]), YA)])
yes_right(f, 1, YA)
f.chain(YA, [(2, "b"), (3, "b"), (4, "b"), (5, "b")])
no_down(f, 1, YA, YX)
f.box(C[1], YX, "먼저 묻기", ["찾기만 전 회차, 번호·제목만 답"], "ai", w=200)
f.edge([(R(C[1], 200), YX), (C[2], YX), (C[2], YA + BH / 2)], "e-key", label="답한 회차가 범위",
       at=(C[2] + 12, YX - 12), anchor="start", lcls="tl-key")
FIGS["{{GUARD}}"] = f.svg()


# ──────────────────────────────────────────────────────────────────────────
# 4. 부가: 맞춤 복습
# ──────────────────────────────────────────────────────────────────────────
f = Fig("review", 500, "맞춤 복습: AniWhere 없이 vs 쓸 때",
        "없이는 어디까지 봤는지부터 떠올려 요약 영상과 위키에서 결말까지 보게 되고, AniWhere는 기록장의 본 회차까지만 자료로 복습 글을 만들고 기록이 없으면 먼저 묻는다")
f.sep()
f.row(YB, "BEFORE", "복습하다 결말을 본다", "들르는 곳 3 · 스포일러 1곳", "b")
f.start(C[0], YB, ["다시 보려는데", "다 까먹었어"])
f.box(C[1], YB, "어디까지 봤더라", ["OTT마다 기록이 따로"], "pain")
f.box(C[2], YB, "위키·요약 영상", [], "n")
f.badge(C[2], YB - 50, "결말까지 섞인 요약")
f.box(C[3], YB, "인물 관계는 또 검색", ["관계도에 뒷 정체가 적힘"], "n")
f.box(C[4], YB, "이어서 시청", [], "n")
f.chain(YB, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b")])

f.row(YA, "AFTER", "본 회차까지만 복습", "들르는 곳 1 · 스포일러 0곳", "a")
f.start(C[0], YA, ["\"지금까지", "복습해 줘\""])
f.diamond(C[1], YA, ["기록장에", "본 회차가 있나?"])
f.box(C[2], YA, "방식 고르기", ["요약 · 인물 · 마지막 화 · 질문"], "ai")
f.box(C[3], YA, "본 회차까지 청크만", ["회차 순으로 읽음"], "guard")
f.box(C[4], YA, "복습 글 + 출처", ["자료에 없으면 \"확인 불가\""], "ai")
f.box(C[5], YA, "이어서 시청", [], "n")
f.chain(YA, [(0, "s"), (1, "d")])
f.edge([(C[1] + DW, YA), (L(C[2]), YA)])
yes_right(f, 1, YA)
f.chain(YA, [(2, "b"), (3, "b"), (4, "b"), (5, "b")])
no_down(f, 1, YA, YX)
f.box(C[1], YX, "어디까지 봤어요?", ["검색 전에 묻기"], "ai")
f.edge([(R(C[1]), YX), (C[2], YX), (C[2], YA + BH / 2)], "e-key", label="답하면 저장 뒤 복습",
       at=(C[2] + 12, YX - 12), anchor="start", lcls="tl-key")
FIGS["{{REVIEW}}"] = f.svg()


# ──────────────────────────────────────────────────────────────────────────
# 5. 부가: 시청 기록장
# ──────────────────────────────────────────────────────────────────────────
f = Fig("record", 500, "시청 기록장: AniWhere 없이 vs 쓸 때",
        "없이는 OTT마다 흩어진 기록과 머릿속 기억에 기대다 몇 달 뒤 잊고, AniWhere는 온보딩과 대화 중 한 문장으로 기록장을 채우며 그 기록이 모든 기능의 스포일러 범위가 된다")
f.sep()
f.row(YB, "BEFORE", "기록이 남지 않는다", "기록 0곳", "b")
f.start(C[0], YB, ["보다가", "멈춤"])
f.box(C[1], YB, "OTT 시청 기록", ["앱마다 따로"], "n")
f.box(C[2], YB, "머리로 기억", [], "pain")
f.box(C[3], YB, "몇 달 뒤", ["기억 안 남"], "pain")
f.badge(C[3], YB - 50, "다음엔 기억에만 의존")
f.box(C[4], YB, "처음부터 다시", ["또는 요약 검색"], "n")
f.chain(YB, [(0, "s"), (1, "b"), (2, "b"), (3, "b"), (4, "b")])

f.row(YA, "AFTER", "기록장이 모든 기능의 기준", "기록 1곳", "a")
f.start(C[0], YA, ["첫 실행 /", "보다가 멈춤"])
f.box(C[1], YA, "온보딩", ["본 애니와 회차 입력"], "ai")
f.box(C[2], YA, "대화 중 저장", ["\"N화까지 봤어\" → 확인 없이"], "ai")
f.diamond(C[3], YA, ["시즌 표기", "(3기 11화)?"])
f.box(C[4], YA, "기록장", ["작품·회차·평점"], "ai")
f.box(C[5], YA, "스포일러 범위", ["복습·사전·찾기 공통"], "guard")
f.chain(YA, [(0, "s"), (1, "b"), (2, "b"), (3, "d")])
f.edge([(C[3] + DW, YA), (L(C[4]), YA)])
yes_right(f, 3, YA, "아니오")
f.edge([(R(C[4]), YA), (L(C[5]), YA)], "e-key")
f.edge([(C[3], YA + DH), (C[3], YX - BH / 2)], label="예", at=(C[3] + 12, YA + DH + 28), anchor="start")
f.box(C[3], YX, "전체 기준 몇 화인지 묻기", [], "ai", w=200)
f.edge([(L(C[3], 200), YX), (C[2], YX), (C[2], YA + BH / 2)], "e-key", label="답하면 저장",
       at=(C[2] + 12, YX - 12), anchor="start", lcls="tl-key")
FIGS["{{RECORD}}"] = f.svg()


if __name__ == "__main__":
    tpl = open(sys.argv[1], encoding="utf-8").read()
    for k, v in FIGS.items():
        assert k in tpl, f"템플릿에 {k} 자리가 없습니다"
        tpl = tpl.replace(k, v)
    open(sys.argv[2], "w", encoding="utf-8").write(tpl)
