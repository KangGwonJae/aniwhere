# eval/

검색 품질을 숫자로 기록합니다. (`tests/`는 "고장 났나", `eval/`은 "얼마나 잘 찾나")

- `questions.jsonl` — 질문과 정답(작품·회차) 쌍. 30개로 시작해 100개까지
- `results/날짜_설정.json` — 실행마다 결과 저장 (예: `2026-10-08_chunk-memory-unit.json`)
- 비교 대상: 청킹 방식 A/B, 임베딩 교체 전/후, 하이브리드·2단계 검색 적용 전/후

## 실행

```bash
make eval                                                  # 벡터 검색만 (LLM 없음): 청크 종류별로 정답 회차가 몇 위인지
.venv/bin/python eval/run.py --pipeline --label 이름         # 찾기 기능 전체 (LLM 포함, 질문당 4~6초, API 비용 발생)
.venv/bin/python eval/run.py --pipeline --chunk-types plot  # 장면 검색 대상을 바꿔서 비교
.venv/bin/python eval/make_questions.py --per-series 12     # 질문 다시 만들기 (사람이 쓴 질문은 그대로 둠)
```

## 질문셋

`questions.jsonl` 한 줄이 질문 하나입니다: `question`, 정답 `series_id`·`abs_eps`(여러 화에 걸친 장면이면 여러 개),
`style`(named: 이름을 말함 / unnamed: 이름 없이 묘사), `source`(manual: 사람이 씀 / synthetic: LLM이 장면 청크를 보고 만듦).

- LLM이 만든 질문은 실제 사용자 질문보다 길고 자세합니다. 그리고 장면 청크에서 만들었기 때문에 장면 단위 검색에
  조금 유리합니다. 발표에 쓰는 숫자는 사람이 쓴 질문의 결과와 같이 보세요. 사람이 쓴 질문을 늘리는 것이 가장 좋습니다.
- 지금은 데모 3작품(진격의 거인, 귀멸의 칼날, 나의 히어로 아카데미아)만 들어 있습니다.
