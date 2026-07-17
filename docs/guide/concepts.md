# 개념 — factlog는 무엇이고 어떻게 동작하나

> 🌐 [English](concepts.en.md) | **한국어**

## 개요

factlog는 **프로젝트별 지식베이스(KB) 폴더**를 만들어, 그 안의 문서에서 뽑아낸
주장들을 검증 가능하고 출처로 뒷받침되는 사실로 유지해 주는 도구입니다. 위키 한 종류만을
위한 것이 아니라, 사람이 검토할 가치가 있는 문서라면 어디서든 KB 폴더를 만들 수 있습니다.

- 보고서 / 제안서
- 슬라이드(PPT)
- 논문 / 리서치 노트
- 코드 문서 / 설계 문서
- 데이터셋 설명 / 데이터 사전
- 개인·팀 프로젝트 노트
- 이미 운영 중인 wiki

핵심 흐름은 한 줄로 요약됩니다.

```text
문서 -> 후보 사실 -> 사람의 검토 -> accepted 사실 -> 엔진이 확인한 답변
```

> 처음이라면 자기 데이터 없이 흐름을 한 번 완주해 보는
> [빠른 시작 튜토리얼](../../examples/sample-kb/README.md)부터 시작하세요.

이 도구는 단 하나의 원칙을 따릅니다.

> 에이전트는 결론을 내리지 않는다. 에이전트는 파일을 만들고 CLI를 호출한다.
> CLI가 검증 가능한 리포트를 돌려준다.

- **LLM(세션 내의 Claude)이 추출합니다** — KB 폴더의 `sources/` 에서 후보 사실을
  뽑아내고, 자연어 질문으로부터 Datalog 쿼리 초안을 작성하며, 제한된 범위의 자기
  교정을 시도합니다.
- **결정론적 엔진([pyrewire](https://github.com/semantic-reasoning/PyreWire) 기반
  wirelog)이 검증합니다** — 확정된 사실을 컴파일하고, 로직 체크를 실행하며,
  정책 위반·모순·`review_required` 항목을 드러냅니다.

## KB 폴더 구조 — 내 파일은 어디에 넣나

`/factlog setup`(또는 `factlog init`)은 **KB 폴더 하나**를 만듭니다. 기본 위치는
홈 디렉터리 아래 `~/wiki` 이고(`~` 는 홈 디렉터리 — macOS `/Users/<이름>`,
Windows `C:\Users\<이름>`), `--target <경로>` 로 원하는 위치를 고를 수 있습니다
(예: `/factlog setup --target ~/my-report`). setup 은 만든 KB의 **절대경로를 요약에
출력**하므로, 그 경로를 파일 탐색기(Windows)·Finder(macOS)로 열면 됩니다.

```text
<KB>/                     ← setup이 만든 폴더 (기본 ~/wiki)
├── sources/              ← 여기에 내 문서를 넣습니다 (보고서·논문·노트·wiki 등)
├── facts/                ← (엔진 산출물) candidates.csv · accepted.dl · logic_report.txt
├── policy/               ← (선택) 검토 질문·정책 규칙
├── runs/                 ← (엔진 산출물) 추출 실행 기록, 바이너리 변환본(runs/sources/)
├── pages/ · decisions/   ← (엔진 산출물) 사람이 손대지 않음
└── templates/
```

> **핵심:** 내가 직접 넣는 것은 `<KB>/sources/` 안의 문서뿐입니다. 나머지 폴더는
> factlog가 채우고 관리합니다. `.docx`·`.pdf` 같은 바이너리도 `sources/` 에 두면
> `/factlog sync` 가 자동으로 텍스트로 변환합니다(→ `runs/sources/`).

## candidate vs accepted — 신뢰 경계

factlog에는 두 종류의 사실이 있습니다.

- **candidate(후보)** — 문서에서 추출된 *주장*일 뿐입니다. `sync` 는 후보를 만들어
  낼 뿐, 그 자체로 신뢰할 수 있는 사실을 만들지는 **않습니다**.
- **accepted(승인됨)** — 사람이 후보를 검토해 받아들인 사실입니다. **오직 accepted
  사실만 엔진의 입력**이 되고, 질문에 대한 답변의 근거가 됩니다.

이 사람의 검토 단계가 factlog의 **신뢰 경계**입니다. 모델이 만들어 낸 것은 무엇이든
사람이 accepted로 확정하기 전까지는 후보일 뿐입니다.

## 명령 한눈에 보기 — slash command · CLI command · KB 파일

factlog의 명령은 **어디서 실행하느냐**에 따라 두 계층으로 나뉩니다. 세 번째 행은
명령이 아니라 그 명령들이 읽고 쓰는 **KB 파일(산출물/위치)** 입니다.

| 구분 | 실행 위치 | 예시 | 역할 |
|------|-----------|------|------|
| **Claude Code slash command** | Claude Code 세션 안 | `/factlog setup`, `/factlog sync`, `/factlog query`, `/factlog check`, `/factlog ask` | 에이전트가 소스를 읽어 후보 사실을 추출하고, 자연어 질문에서 쿼리 초안을 잡고, 엔진 검증 흐름(컴파일·로직 체크·답변)을 호출합니다(검증 자체는 결정론 엔진이 수행). |
| **Python CLI command** | 터미널(shell) | `factlog status`, `factlog review`, `factlog accept`, `factlog reject`, `factlog amend` | KB 상태를 확인하고, 후보 사실을 **사람이** 검토·승인·폐기·수정합니다. `accept`/`reject` 는 후보를 accepted로 확정하거나 폐기하는 **사람의 게이트**입니다(자동 단계가 아님). |
| **KB 파일**(명령 아님 — 산출물/위치) | 프로젝트 KB 폴더 | `sources/`, `facts/candidates.csv`, `facts/accepted.dl`, `facts/logic_report.txt` | 원본(`sources/`), 후보(`candidates.csv`), 엔진 입력(`accepted.dl`)이 놓이는 자리입니다. `facts/logic_report.txt` 는 **엔진이 생성하는 검증 결과가 남는 위치**로, 사람이 편집하지 않습니다. |

이 표가 위 [신뢰 경계](#candidate-vs-accepted--신뢰-경계)와 맞물립니다. slash command
(`/factlog sync`)는 **후보**를 만들 뿐이고, accepted로의 확정은 터미널에서 사람이
실행하는 CLI 게이트(`factlog accept` / `factlog reject` / `factlog amend --accept`)를
거칩니다. 오직 그렇게 확정된 `accepted.dl` 만 엔진 입력이 됩니다.

## 동작 방식

![factlog 동작 방식: Claude가 제안하고, 엔진이 검증하며, 사람이 확인합니다](../how-it-works.svg)

<details>
<summary>텍스트 버전</summary>

```
sources/        →  Claude extracts        →  facts/candidates.csv, pages/, decisions/
candidates       →  human review           →  confirmed facts
confirmed        →  compile (deterministic) →  facts/accepted.dl
questions        →  Claude drafts query     →  facts/query.dl
accepted + query →  wirelog logic check     →  facts/logic_report.txt   ← 검증 가능한 리포트
review_required  →  Claude repairs (gated)  →  decisions/correction_trace.md
```

</details>
