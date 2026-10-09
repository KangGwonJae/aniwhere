"""docs/workflow 흐름도 생성기. 그림을 고치면 다시 실행: cd docs/workflow && python3 src/gen_workflow.py src/template.html AniWhere_워크플로우_전후비교.html"""
import sys
from html import escape

BW, BH = 176, 70          # 기본 상자
DW, DH = 80, 46           # 마름모 반폭·반높이


class Fig:
    def __init__(self, fid, w, h, label):
        self.fid, self.w, self.h, self.label = fid, w, h, label
        self.parts, self.edges = [], []

    def text(self, x, y, s, cls="t", anchor="middle"):
        self.parts.append(f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(s)}</text>')

    def box(self, cx, cy, title, subs=(), kind="n", w=BW, h=BH):
        x, y = cx - w / 2, cy - h / 2
        rx = h / 2 if kind == "start" else 10
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

    def diamond(self, cx, cy, lines):
        pts = f"{cx},{cy - DH} {cx + DW},{cy} {cx},{cy + DH} {cx - DW},{cy}"
        self.parts.append(f'<polygon points="{pts}" class="b-d"/>')
        top = cy - (len(lines) - 1) * 8 + 4
        for i, s in enumerate(lines):
            self.text(cx, top + i * 16, s, "td")

    def edge(self, pts, kind="e", label=None, at=None, anchor="middle", lcls=None):
        d = " ".join(f"{x},{y}" for x, y in pts)
        marker = {"e": "a", "e-key": "k", "e-pain": "p"}[kind]
        self.edges.append(f'<polyline points="{d}" class="{kind}" marker-end="url(#{self.fid}-{marker})"/>')
        if label:
            lx, ly = at
            self.edges.append(f'<text x="{lx}" y="{ly}" class="{lcls or "tl"}" text-anchor="{anchor}">{escape(label)}</text>')

    def badge(self, cx, y, s):
        """불편·스포일러 지점 표시: 빨간 원 + 느낌표 + 글"""
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
        return (f'<svg viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.label)}" '
                f'xmlns="http://www.w3.org/2000/svg"><defs>{defs}</defs>' + "".join(self.edges + self.parts) + "</svg>")


R = lambda cx, w=BW: cx + w / 2
L = lambda cx, w=BW: cx - w / 2
C = [95, 285, 475, 665, 855, 1045]
Y1, Y2, YD = 100, 390, 225
LOOP_Y = 282


def row_labels(f, a, b):
    f.text(120, 26, a, "row", "start")
    f.text(120, 322, b, "row", "start")


def tally(f, lines):
    y = 352
    for s, cls in lines:
        f.text(960, y, s, cls, "start")
        y += 22 if cls == "tally-h" else 19


# ① 없이 볼 때
b = Fig("bf", 1140, 550, "AniWhere 없이 애니를 볼 때: 다섯 종류의 서비스를 돌아다니고, 위키와 요약 영상에서 스포일러를 보며, 기록이 남지 않아 다음에 처음부터 기억에 의존한다")
row_labels(b, "찾고 보기 · 02 탐색 → 03 시청", "몇 달 뒤 이어보기 · 04 이어보기")
b.box(C[0], Y1, ["그 장면,", "몇 화였지?"], kind="start", h=60)
b.box(C[1], Y1, "검색창에 장면 묘사", ["구글·네이버"], "n")
b.diamond(C[2], Y1, ["제목·이름이", "떠오르나?"])
b.box(C[3], Y1, "위키 줄거리 하나씩", ["나무위키·팬 위키", "회차 목록을 차례로 열기"], "n")
b.badge(C[3], 52, "다음 화 줄거리가 같이 보임")
b.box(C[4], Y1, "OTT 앱 하나씩 검색", ["라프텔·넷플릭스·티빙…", "어디에 있는지 모름"], "n")
b.box(C[5], Y1, "보다가 멈춤", ["어디까지 봤는지", "아무 데도 안 남음"], "pain")
b.edge([(R(C[0]), Y1), (L(C[1]), Y1)])
b.edge([(R(C[1]), Y1), (C[2] - DW, Y1)])
b.edge([(C[2] + DW, Y1), (L(C[3]), Y1)], label="예", at=(C[2] + DW + 12, Y1 - 8))
b.edge([(R(C[3]), Y1), (L(C[4]), Y1)])
b.edge([(R(C[4]), Y1), (L(C[5]), Y1)])
b.box(C[2], YD, "남에게 물어보기", ["커뮤니티 글은 답을 기다리고", "AI 챗봇은 근거 없이 단정"], "pain", w=196)
b.edge([(C[2], Y1 + DH), (C[2], YD - BH / 2)], label="아니오", at=(C[2] + 8, Y1 + DH + 22), anchor="start")
b.edge([(R(C[2], 196), YD), (C[3], YD), (C[3], Y1 + BH / 2)], label="답을 받으면", at=(C[3] + 8, YD - 14), anchor="start")
b.edge([(C[5], Y1 + BH / 2), (C[5], LOOP_Y), (C[0], LOOP_Y), (C[0], Y2 - 30)], "e-pain",
       label="기록이 없으니 다음엔 기억에만 의존", at=(570, LOOP_Y - 8), lcls="tl-pain")
b.box(C[0], Y2, ["다시 보려는데", "다 까먹었어"], kind="start", h=60)
b.diamond(C[1], Y2, ["어디까지 봤는지", "기억나나?"])
b.box(C[1], 500, "시청 기록 뒤지기", ["OTT마다 따로, 없으면", "처음부터 다시"], "pain")
b.box(C[2], Y2, "위키·요약 영상 복습", ["시즌 전체 요약을 찾아봄"], "n")
b.badge(C[2], 342, "결말까지 섞인 요약")
b.box(C[3], Y2, "이어서 시청", [], "n")
b.edge([(R(C[0]), Y2), (C[1] - DW, Y2)])
b.edge([(C[1] + DW, Y2), (L(C[2]), Y2)], label="예", at=(C[1] + DW + 12, Y2 - 8))
b.edge([(C[1], Y2 + DH), (C[1], 500 - BH / 2)], label="아니오", at=(C[1] + 8, Y2 + DH + 16), anchor="start")
b.edge([(R(C[1]), 500), (C[2], 500), (C[2], Y2 + BH / 2)], label="찾으면", at=(C[2] + 8, 488), anchor="start")
b.edge([(R(C[2]), Y2), (L(C[3]), Y2)])
tally(b, [("들른 곳 5종류", "tally-h"), ("검색 포털 · 커뮤니티·챗봇", "tally"), ("위키 · OTT 앱 여러 개", "tally"),
          ("요약 영상", "tally"), ("스포일러가 보이는 곳 2곳", "tally-bad")])

# ② AniWhere를 쓸 때
a = Fig("af", 1140, 550, "AniWhere를 쓸 때: 한 곳에서 찾기·시청처·기록·복습이 이어지고, 근거가 약하면 되묻고, 기록장의 본 회차가 복습의 스포일러 범위가 된다")
row_labels(a, "찾고 보기 · 02 탐색 → 03 시청 → 05 기록", "몇 달 뒤 이어보기 · 04 이어보기")
a.box(C[0], Y1, ["그 장면,", "몇 화였지?"], kind="start", h=60)
a.box(C[1], Y1, "AniWhere에 묘사 입력", ["이름을 몰라도 기억나는 대로"], "ai")
a.box(C[2], Y1, "에이전트가 찾기", ["단서 추출 → 검색 → 판정", "③ 그림에서 자세히"], "ai")
a.diamond(C[3], Y1, ["근거가", "충분한가?"])
a.box(C[4], Y1, "작품·회차 + 근거", ["근거 줄거리와 출처", "시청처도 같은 화면에"], "ai")
a.box(C[5], Y1, "기록장에 회차 저장", ["13 시청 기록장", "본 작품·회차·평점"], "ai")
a.edge([(R(C[0]), Y1), (L(C[1]), Y1)])
a.edge([(R(C[1]), Y1), (L(C[2]), Y1)])
a.edge([(R(C[2]), Y1), (C[3] - DW, Y1)])
a.edge([(C[3] + DW, Y1), (L(C[4]), Y1)], label="예", at=(C[3] + DW + 12, Y1 - 8))
a.edge([(R(C[4]), Y1), (L(C[5]), Y1)])
a.box(C[3], YD, "되묻기", ["생김새·장소·앞뒤 장면을", "더 알려 주세요"], "ai")
a.edge([(C[3], Y1 + DH), (C[3], YD - BH / 2)], label="아니오", at=(C[3] + 8, Y1 + DH + 22), anchor="start")
a.edge([(L(C[3]), YD), (C[1], YD), (C[1], Y1 + BH / 2)], label="답하면 다시 찾기", at=(C[1] + 8, YD - 14), anchor="start")
a.edge([(C[5], Y1 + BH / 2), (C[5], LOOP_Y), (C[0], LOOP_Y), (C[0], Y2 - 30)], "e-key",
       label="기록장의 본 회차가 복습 범위가 됨", at=(570, LOOP_Y - 8), lcls="tl-key")
a.box(C[0], Y2, ["다시 보려는데", "다 까먹었어"], kind="start", h=60)
a.diamond(C[1], Y2, ["기록장에", "본 회차가 있나?"])
a.box(C[1], 500, "어디까지 봤어요?", ["모르면 검색하지 않고", "먼저 물어봄"], "ai")
a.box(C[2], Y2, "복습 방식 고르기", ["전체 요약 · 인물 관계", "마지막 화 · 직접 질문"], "ai")
a.box(C[3], Y2, "본 회차까지만 복습", ["이후 회차는 검색 전에 제외", "답마다 출처 표시"], "guard")
a.box(C[4], Y2, "이어서 시청", [], "n")
a.edge([(R(C[0]), Y2), (C[1] - DW, Y2)])
a.edge([(C[1] + DW, Y2), (L(C[2]), Y2)], label="예", at=(C[1] + DW + 12, Y2 - 8))
a.edge([(C[1], Y2 + DH), (C[1], 500 - BH / 2)], label="아니오", at=(C[1] + 8, Y2 + DH + 16), anchor="start")
a.edge([(R(C[1]), 500), (C[2], 500), (C[2], Y2 + BH / 2)], label="답하면", at=(C[2] + 8, 488), anchor="start")
a.edge([(R(C[2]), Y2), (L(C[3]), Y2)])
a.edge([(R(C[3]), Y2), (L(C[4]), Y2)])
tally(a, [("들른 곳 1곳", "tally-h"), ("AniWhere 안에서", "tally"), ("찾기 → 시청처 → 기록", "tally"),
          ("→ 복습이 이어짐", "tally"), ("스포일러가 보이는 곳 0곳", "tally-good")])

# ③ 에이전트 안: 기억으로 찾기
g = Fig("ag", 1140, 440, "에이전트의 찾기 흐름: 단서 추출, 작품 후보, 스포일러 범위, 회차 재검색, 판정 뒤 근거를 확인해 네 가지 결과 중 하나로 답한다")
YA, YO = 80, 380
g.box(C[0], YA, ["질문 +", "앞선 대화"], kind="start", h=60)
g.box(C[1], YA, "단서 추출", ["LLM이 제목·이름·키워드,", "영어 질의를 뽑음"], "ai")
g.box(C[2], YA, "작품 후보 최대 4편", ["제목을 말했으면 그 작품", "아니면 짐작 + 전체 검색"], "ai")
g.box(C[3], YA, "스포일러 범위", ["기록 있는 작품은", "본 회차까지만 검색"], "guard")
g.text(C[3], YA + 54, "기록 없는 작품은 전 회차를 찾되", "tnote")
g.text(C[3], YA + 69, "답에는 회차 번호·제목만", "tnote")
g.box(C[4], YA, "회차 다시 검색", ["장면 청크 벡터 + 키워드", "맞은 장면을 회차로 묶음"], "ai")
g.box(C[5], YA, "판정", ["LLM이 검색된 줄거리·", "인물 설명만 읽고 고름"], "ai")
for i in range(5):
    g.edge([(R(C[i]), YA), (L(C[i + 1]), YA)])
YJ = 215
g.diamond(C[5], YJ, ["판정 결과", "+ 근거 확인"])
g.edge([(C[5], YA + BH / 2), (C[5], YJ - DH)])
OW = 214
OC = [140, 395, 650, 905]
BUS = 300
g.parts.append(f'<polyline points="{C[5]},{YJ + DH} {C[5]},{BUS} {OC[0]},{BUS}" class="e" fill="none"/>')
outs = [("회차로 답", ["근거 문장이 줄거리에 실제로", "있을 때만 (낱말 70% 일치)"], "ai", "episode"),
        ("작품만 답", ["회차는 장면을", "더 물어보고 찾음"], "ai", "series"),
        ("후보 제시 + 되묻기", ["비슷한 작품·회차가", "여러 개일 때"], "ai", "ambiguous"),
        ("못 찾음 + 되묻기", ["근거 확인에 실패해도", "회차를 단정하지 않음"], "ai", "none")]
for cx, (t, s, k, code) in zip(OC, outs):
    g.edge([(cx, BUS), (cx, YO - BH / 2)], label=code, at=(cx + 8, BUS + 24), anchor="start", lcls="tcode")
    g.box(cx, YO, t, s, k, w=OW)

FIGS = {"{{BEFORE}}": b.svg(), "{{AFTER}}": a.svg(), "{{AGENT}}": g.svg()}

if __name__ == "__main__":
    tpl = open(sys.argv[1], encoding="utf-8").read()
    for k, v in FIGS.items():
        tpl = tpl.replace(k, v)
    open(sys.argv[2], "w", encoding="utf-8").write(tpl)
