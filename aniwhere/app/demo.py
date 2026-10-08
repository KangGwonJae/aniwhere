"""기능 확인용 화면 (Streamlit). 발표용 화면이 아니라 백엔드 함수가 약속대로 동작하는지 눈으로 보기 위한 것입니다.

실행: make run   (또는 .venv/bin/streamlit run aniwhere/app/demo.py)
판단 로직은 두지 않고 aniwhere/service.py의 함수만 부릅니다.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))      # streamlit run은 저장소 루트를 경로에 넣지 않음
from aniwhere import service  # noqa: E402
from aniwhere.agent.llm import get_llm  # noqa: E402
from aniwhere.agent.review import MODES  # noqa: E402

st.set_page_config(page_title="AniWhere 기능 확인", layout="wide")
st.title("AniWhere 기능 확인")


@st.cache_resource(show_spinner="임베딩 모델을 불러오는 중… (처음 한 번)")
def warm_up():
    service.warm_up()
    return True


warm_up()
if not get_llm():
    st.warning("OPENAI_API_KEY가 없어 LLM 없이 검색 결과만 보여 줍니다. `.env`에 키를 넣고 다시 실행하세요.")


def pick_series(key):
    """작품 선택 → (series_id, 작품 정보). 기록장에 있는 작품이 목록 앞에 옵니다."""
    query = st.text_input("작품 제목 검색", key=f"{key}_q", placeholder="예: 진격, 귀멸, 히어로")
    recorded = [] if query else [{"series_id": r["series_id"], "name": r["name"]} for r in service.list_records()]
    rows = recorded + [r for r in service.search_series(query or None, limit=30)
                       if r["series_id"] not in {x["series_id"] for x in recorded}]
    if not rows:
        st.info("찾는 작품이 없습니다.")
        return None, None
    names = {r["series_id"]: r["name"] for r in rows}
    sid = st.selectbox("작품", list(names), format_func=lambda s: f"{names[s]} ({s})", key=f"{key}_sid")
    return sid, service.series(sid)


def seen_input(sid, info, key):
    """본 회차 입력. 기록장에 있으면 그 값이 기본값입니다."""
    record = service.get_record(sid)
    total = info["total_episodes"] or 1
    if record:
        st.caption(f"기록장: {record['seen_ep']}화까지 봄")
    return st.number_input(f"본 회차 (전체 회차 번호, 최대 {total})", 0, total, record["seen_ep"] if record else 0,
                           key=f"{key}_seen_{sid}")


def show_sources(sources):
    with st.expander(f"근거 {len(sources)}개"):
        for s in sources:
            ep = f"전체 {s['abs_ep']}화" if s.get("abs_ep") else "회차 무관"
            st.markdown(f"- {'[%s] ' % s['n'] if 'n' in s else ''}{ep} · [{s.get('name')}]({s.get('url')}) · "
                        f"{s.get('license')}")
            if s.get("text"):
                st.caption(s["text"])


tabs = st.tabs(["02 찾기 (05·06)", "03 시청처 (07)", "03 인물·용어 사전 (08)", "04 복습 (09)", "05 기록장 (13)",
                "01 취향 추천 (01)"])

with tabs[0]:
    st.caption("기억나는 장면이나 인물을 적으면 작품과 회차를 찾습니다. 기록장에 있는 작품은 본 회차까지만 찾습니다.")
    history = st.session_state.setdefault("find_history", [])
    for m in history:
        st.chat_message(m["role"]).write(m["content"])
    if st.button("대화 지우기"):
        history.clear()
        st.rerun()
    if q := st.chat_input("예: 올마이트가 올포원과 싸우고 손가락을 가리켰어"):
        st.chat_message("user").write(q)
        with st.spinner("찾는 중…"):
            r = service.find(q, history)
        answer = r["answer"] + (f"\n\n{r['follow_up']}" if r.get("follow_up") else "")
        st.chat_message("assistant").write(answer)
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
        st.write(f"status: `{r['status']}`")
        if r["candidates"]:
            st.dataframe(r["candidates"])
        show_sources(r["sources"])
        with st.expander("검색 내부 (단서, 순위)"):
            st.json(r["debug"])

with tabs[1]:
    sid, info = pick_series("watch")
    if sid:
        r = service.where_to_watch(sid)
        st.subheader(r["title"])
        if not r["seasons"]:
            st.info("국내 구독형 제공처 정보가 없습니다.")
        for s in r["seasons"]:
            st.markdown(f"**{s['name']}** — {', '.join(s['providers']) or '제공처 없음'}  \n"
                        f"확인일 {s['checked_at']} · [자세히]({s['link']})")
        st.caption(r["attribution"])

with tabs[2]:
    sid, info = pick_series("dict")
    if sid:
        seen = seen_input(sid, info, "dict")
        entries = service.dictionary(sid, int(seen))["entries"]
        st.write(f"{seen}화까지 나온 항목 {len(entries)}개")
        kinds = {"character": "인물", "term": "용어", "appearance": "인물 외형 (위키)"}
        for kind, label in kinds.items():
            with st.expander(f"{label} {sum(e['kind'] == kind for e in entries)}개", expanded=kind == "character"):
                for e in (e for e in entries if e["kind"] == kind):
                    cols = st.columns([1, 6])
                    if e.get("image_url"):
                        cols[0].image(e["image_url"], width=80)
                    first = f"{e['first_ep']}화부터" if e["first_ep"] else "처음부터"
                    cols[1].markdown(f"**{e['name']}** · {first} · [출처]({e['url']})")
                    cols[1].caption(e["text"][:500])

with tabs[3]:
    sid, info = pick_series("review")
    if sid:
        seen = seen_input(sid, info, "review")
        mode = st.radio("복습 종류", list(MODES), format_func=MODES.get, horizontal=True)
        question = st.text_input("질문") if mode == "ask" else None
        use_record = st.checkbox("본 회차를 넘기지 않고 기록장에서 읽기 (기록이 없으면 되묻는지 확인)")
        if st.button("복습하기"):
            with st.spinner("본 회차까지만 읽는 중…"):
                r = service.review(sid, None if use_record else int(seen), mode, question)
            st.write(f"seen_ep: `{r['seen_ep']}`")
            st.markdown(r["answer"] or f"**{r['follow_up']}**")
            if r["sources"]:
                st.caption(f"근거의 가장 뒤 회차: {max(s['abs_ep'] or 0 for s in r['sources'])}화")
                show_sources(r["sources"])

with tabs[4]:
    sid, info = pick_series("record")
    if sid:
        seen = seen_input(sid, info, "record")
        rating = st.slider("평점 (0은 평점 없음)", 0.0, 5.0, 0.0, 0.5)
        cols = st.columns(8)
        if cols[0].button("저장"):
            st.success(service.save_record(sid, int(seen), rating or None))
        if cols[1].button("삭제"):
            st.success("삭제됨" if service.delete_record(sid) else "기록이 없습니다")
    st.subheader("내 기록")
    st.dataframe([{k: r[k] for k in ("name", "seen_ep", "total_episodes", "rating", "updated_at", "series_id")}
                  for r in service.list_records()])

with tabs[5]:
    likes = st.text_input("재미있게 본 영화·드라마·웹툰", placeholder="예: 기생충, 오징어 게임, 더 글로리")
    if st.button("추천받기") and likes:
        with st.spinner("취향을 읽는 중…"):
            r = service.recommend(likes)
        if r.get("mood"):
            st.write(f"취향: {r['mood']}")
        if r.get("follow_up"):
            st.info(r["follow_up"])
        for p in r["picks"]:
            cols = st.columns([1, 6])
            if p.get("poster_url"):
                cols[0].image(p["poster_url"], width=90)
            cols[1].markdown(f"**{p['title']}** · {', '.join(p['genres'] or [])}  \n{p['reason']}")
