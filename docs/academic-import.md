# 학술 서지 연동 통합 사용법

> 🌐 [English](academic-import.en.md) | **한국어**

factlog는 Zotero · OpenAlex · arXiv · PubMed 네 곳에서 서지 레코드를 `sources/`로
가져옵니다. 네 연동은 서로 다른 API를 쓰지만 **같은 계약**을 공유합니다 — 이 문서는 그
공유되는 부분을 한 번에 설명하고, 각 연동에만 있는 것은 상세 문서로 넘깁니다.

| 연동 | 상세 문서 |
| --- | --- |
| Zotero | [zotero-import.md](zotero-import.md) |
| OpenAlex | [openalex.md](openalex.md) |
| arXiv | [arxiv.md](arxiv.md) |
| PubMed | [pubmed.md](pubmed.md) |

## 어느 연동을 쓰나

| 상황 | 연동 |
| --- | --- |
| 이미 Zotero로 문헌을 관리하고 있다 | **Zotero** — 컬렉션/태그 단위 이관, PDF 전문·하이라이트까지 |
| 분야 무관하게 검색하거나 인용 그래프를 넓히고 싶다 | **OpenAlex** |
| 프리프린트를 id로 집어 오거나 버전을 추적하고 싶다 | **arXiv** |
| 생의학 문헌이고 MeSH·철회 판정이 중요하다 | **PubMed** |

한 논문이 여러 곳에 있어도 파일은 하나입니다. arXiv · OpenAlex · PubMed 임포트는 같은
DOI/PMID를 가진 원본이 이미 있으면 두 번째 파일을 쓰지 않고, 그 원본의 provenance 원장에
자기 레코드를 접습니다(`merged`). `doi` / `arxiv_id` / `pmid` 가 (`openalex_doi` 같은
접두어 없이) 맨 키인 이유가 이 교차 소스 색인입니다.

**Zotero만 접지 않습니다.** 중복이면 건너뛰고(`skipped`) 원장에 흔적을 남기지 않습니다 —
개인 라이브러리는 상류 데이터베이스가 아니라, 사람이 이미 자기 기준으로 큐레이션한
곳이기 때문입니다.

## 네 연동이 공유하는 계약

1. **가져온 것은 사실이 아니라 후보입니다.** 임포트 결과는 `sources/<slug>.md` 원본
   하나이고, `sync → review → accept` 게이트를 거쳐야 사실이 됩니다 (P1/P2). 네 데이터
   베이스는 factlog의 사실 저장소가 아니라 입력원입니다.
2. **기존 `sources/` 원본은 절대 수정되지 않습니다** (P4). `--auto-update` 도, 철회 종결
   명령도, 백필도 마찬가지입니다 — 이들의 쓰기는 **provenance 원장**
   (`<kb>/source-provenance/**/*.json`)과, refresh 계열의 경우 확인 기록
   (`<kb>/check-log/<이름>.json`)에 한정됩니다. Zotero 라이브러리 원본도 읽기 전용입니다.
3. **멱등합니다** (P3). 같은 항목을 다시 가져와도 이미 있는 정체 키(`zotero_key` /
   `openalex_id` / `arxiv_id` / `pmid`)는 건너뜁니다.
4. **임포트는 원장을 고쳐 쓸 권한이 없습니다** (#58, #63). 임포트는 레코드를 새로 만들
   뿐입니다. 새 값을 배우려고 상류에 다녀오는 것은 임포트가 아니라 갱신(refresh)입니다.
5. **철회·withdrawal 신호는 자동으로 흡수되지 않습니다.** 사람이 종결할 때까지 실행마다
   다시 올라옵니다 — 아래 [철회 신호](#철회-신호는-세-곳에서-서로-다른-것을-뜻합니다) 참조.

## 명령 대조표

같은 일을 하는 명령이 연동마다 이름만 다릅니다.

| 하는 일 | Zotero | OpenAlex | arXiv | PubMed |
| --- | --- | --- | --- | --- |
| 단건/배치 임포트 | `zotero-import --items` | `openalex-import --work-id\|--doi` | `arxiv-import --id`<br>(≤100/실행) | `pubmed-import --pmid`<br>(≤200/실행) |
| 묶음 가져오기 | `zotero-import --collection\|--tag` | — | — | — |
| 검색 후 선택 임포트 | — | `openalex-search` | `arxiv-search` | `pubmed-search` |
| 인용 그래프 확장 | — | `openalex-cite --for <slug>` | — | — |
| 상류 재조회·비교 | — | `openalex-refresh` | `arxiv-check-versions` | `pubmed-refresh` |
| 사람의 종결 | — | `openalex-acknowledge-retraction` | `arxiv-acknowledge-withdrawal` | `pubmed-acknowledge-retraction` |
| 원장 백필 | — | `openalex-backfill-provenance` | `arxiv-backfill-provenance` | `pubmed-backfill-provenance` |
| 그 밖 | `--pdf` · `--annotations` | — | — | `pubmed-mesh --for <slug>` |

Zotero에 refresh·종결·백필이 없는 것은 누락이 아닙니다. Zotero는 로컬 라이브러리이고
사람이 직접 관리하는 곳이므로, 상류가 몰래 바뀌는 문제 자체가 없습니다.

## 설치와 자격증명

연동마다 extra가 따로입니다. 필요한 것만 설치하세요.

```bash
pip install 'factlog-academic[zotero]   @ git+https://github.com/SeoyunL/factlog-academic'
pip install 'factlog-academic[openalex] @ git+https://github.com/SeoyunL/factlog-academic'
pip install 'factlog-academic[arxiv]    @ git+https://github.com/SeoyunL/factlog-academic'
pip install 'factlog-academic[pubmed]   @ git+https://github.com/SeoyunL/factlog-academic'
```

| 연동 | 추가 의존성 | 인증 | 사람이 준비할 것 |
| --- | --- | --- | --- |
| Zotero | pyzotero | 없음(로컬) | Zotero 7 앱 실행 + Settings → Advanced → "Allow other applications…" 체크 |
| OpenAlex | httpx | 없음 | (선택) `email` |
| arXiv | httpx, feedparser | 없음 | (선택) `email` |
| PubMed | httpx | 없음 | **`email` 필수**, `api_key` 권장 |

Zotero 연결 확인:

```bash
curl http://localhost:23119/api/users/0/collections   # JSON 배열이면 정상
```

### 요청 비용은 연동마다 다른 성질입니다

- **OpenAlex — 크레딧.** 하루 약 1000 크레딧. 검색은 결과 수와 무관하게 **1회당 10**,
  단건 조회는 0, 인용 그래프 확장(`openalex-cite`)은 요청당 1입니다. 그래서 검색에서는
  `--limit` 을 아껴도 비용이 줄지 않습니다 — 한 번에 넉넉히 요청하세요. 예산이 소진되면
  명령이 실패하고 아무것도 쓰지 않습니다.
- **PubMed — IP 차단 위험.** 비용을 세지 않는 대신 초당 상한(키 없이 3/s, 키 있으면 10/s)을
  넘기면 IP를 차단합니다. factlog가 클라이언트에서 최소 간격을 지키고 요청을 직렬화합니다.
  키가 없으면 같은 배치가 3배 이상 걸립니다.
- **arXiv — 예의.** 예산도 상한도 강제되지 않습니다. arXiv 권고인 요청 간 3초 지연을
  factlog가 스스로 지킵니다. 아무도 대신 지켜 주지 않습니다.
- **Zotero — 로컬.** 해당 없음.

### 자격증명 경계

**KB 정책 파일(`<KB>/policy/*.toml`)은 흔히 버전 관리되는 저장소입니다.** 그래서 진짜
자격증명은 거기서 읽지 않습니다.

| 값 | KB 정책 파일에서 읽나 | 왜 |
| --- | --- | --- |
| OpenAlex `email` | ✅ 읽습니다 | 인증이 아니라 신원 표기(쿼리 문자열에 실림) |
| arXiv `email` | ✅ 읽습니다 | 인증이 아니라 신원 표기(User-Agent에 실림) |
| PubMed `api_key` | ❌ 무시합니다 | 진짜 자격증명. `NCBI_API_KEY` 또는 사용자 레벨 파일에만 |
| Zotero `web_api_key` | ❌ 무시합니다 | 진짜 자격증명 |

`NCBI_API_KEY` 환경 변수는 **어떤 파일보다** 우선합니다(CI 러너가 키를 디스크에 쓰지 않고
넘기는 방식과 맞추기 위해). 이 키는 `eutils.ncbi.nlm.nih.gov` 밖으로 나가지 않으며 모델
제공자를 포함한 어떤 제3자에게도 전송되지 않습니다.

`email` 의 타입이 틀리면 OpenAlex · arXiv · PubMed 세 연동에서 **실패**합니다(다른 필드는
기본값으로 되돌아갑니다). Zotero는 로컬 API라 `email` 설정 자체가 없습니다.
모든 요청에 그대로 실리는 값이라 오타가 조용히 익명 요청으로 떨어지면 안 되기 때문입니다.

### 설정 파일 해석 순서

```
명시적으로 지정한 경로  >  <KB>/policy/<name>-config.toml  >  ${XDG_CONFIG_HOME:-~/.config}/factlog/<name>.toml  >  내장 기본값
```

`<name>` 은 `zotero` / `openalex` / `arxiv` / `pubmed` 입니다. 명시 경로는 라이브러리
인자이며 CLI 플래그로는 노출되지 않습니다.

`[import]` 섹션은 **공통이 아닙니다.** 읽는 연동과 키가 다릅니다.

```toml
[import]
default_limit = 25        # 1..200   — OpenAlex · arXiv 만
max_limit = 200           #          — OpenAlex · arXiv 만
skip_duplicates = true    # 같은 정체 키는 재임포트 시 건너뜀(멱등)
include_abstract = true   # 초록을 본문에 포함
```

| 연동 | `[import]` 을 읽나 | 비고 |
| --- | --- | --- |
| OpenAlex · arXiv | ✅ 네 키 전부 | |
| Zotero | ⚠️ `skip_duplicates` · `include_abstract` 만 | limit 키는 없음 |
| PubMed | ❌ 섹션 자체를 읽지 않음 | limit은 25/200 고정, 초록은 항상 포함 |

PubMed 설정 파일에 `[import]` 를 적으면 **오류 없이 조용히 무시됩니다.** 건수는
`--limit` 플래그로 조절하세요.

## 공통 플래그

| 플래그 | 뜻 | 받지 않는 명령 |
| --- | --- | --- |
| `--target <KB>` | 대상 KB. 없으면 활성 KB(`factlog where`) | 없음(전부 받음) |
| `--porcelain` | 스크립트용 탭 구분 출력 | `*-acknowledge-*` |
| `--dry-run` | 파일을 만들지 않음 | `*-acknowledge-*`, `openalex-refresh`, `arxiv-check-versions`, `pubmed-mesh` |
| `--all` | 검색 결과를 프롬프트 없이 전부 임포트 | `*-search` 전용 |
| `--older-than DAYS` | 최근 N일 안에 확인한 레코드는 건너뜀(기본 30, `0`=전부) | refresh 계열 전용 |
| `--auto-update` | 달라진 값을 원장에 기록 | refresh 계열 전용 |
| `--only-flagged` | 이미 철회로 표시된 것만 다시 확인 | `pubmed-refresh` 전용 |
| `--yes` | 확인 프롬프트 생략 | `*-acknowledge-*` 전용 |
| `--show-query` | 요청 없이 전송될 쿼리만 출력 | `arxiv-search` · `pubmed-search` |

### `--dry-run` 만으로는 계획이 안 나오는 명령이 있습니다

`--dry-run` 은 대화형 선택을 **끄기** 때문에 검색 명령에서는 아무것도 선택되지 않습니다.
계획을 보려면 선택까지 지정해야 합니다.

```bash
factlog openalex-search --query "..." --dry-run --all
factlog arxiv-search    --query "..." --dry-run --all
factlog pubmed-search   --query "..." --dry-run --all
factlog openalex-cite   --for <slug>  --dry-run --auto-import   # cite 는 --auto-import 없이는 그냥 반환
```

`zotero-import` / `*-import` / `*-backfill-provenance` 는 `--dry-run` 만으로 계획이 나옵니다.

### `--dry-run` 이 네트워크를 쓰는지도 다릅니다

- `arxiv-import` · `pubmed-import` 의 `--dry-run` 은 **네트워크를 씁니다** — 제목·철회
  신호·slug 를 알아야 결과를 예측할 수 있으니까요. 파일만 안 만듭니다.
- `pubmed-refresh --dry-run` 은 **네트워크를 치지 않습니다** — 무엇을 확인할지와 예상
  시간만 보여 줍니다(키가 없으면 "키가 있었다면 얼마나 빨랐을지"도 함께).
- `*-backfill-provenance` 는 `--dry-run` 이든 아니든 **절대 네트워크를 쓰지 않습니다.**

미리보기의 공통 한계: **실패할 쓰기는 보고할 수 없습니다.** 쓸 수 없는
`source-provenance/` 는 실제 실행에서만 드러납니다.

## 기본 작업 흐름

```bash
# 1. 가져온다
factlog zotero-import --collection "neurosymbolic AI"
factlog openalex-search --query "neurosymbolic AI" --year 2020-2025 --limit 50
factlog arxiv-import --id 2311.09277
factlog pubmed-import --pmid 32738937

# 2. 후보 사실을 추출한다
/factlog sync

# 3. 사람이 승인한다
factlog review
factlog accept <id>

# 4. 인용을 내보낸다
factlog export --bibtex > refs.bib
factlog export --csl -o refs.json
```

주기적으로 상류를 다시 확인합니다.

```bash
factlog openalex-refresh
factlog arxiv-check-versions
factlog pubmed-refresh
```

## 검색의 조용한 함정 — 세 API가 다르게 실패합니다

세 검색 API 모두 **틀린 쿼리에 오류가 아니라 "0건"으로 답합니다.** 운영자는 이를 "그런
문헌이 없다"로 읽습니다. factlog가 세 곳에서 각각 다르게 막습니다.

| | arXiv | PubMed | OpenAlex |
| --- | --- | --- | --- |
| 여러 단어 쿼리 | **자동으로 구로 감쌈** (`all:"..."`) | 감싸지 않음 — ATM에 맡김 | 감싸지 않음 — `search=` 가 직접 처리 |
| 잘못된 필드/카테고리 | 전송 **전** 거부 | 전송 **전** 거부(닫힌 태그 집합) | 해당 없음 |
| 상류의 진단 신호 | — | `PhraseNotFound` 등을 stderr로 표면화 | — |
| 미리보기 | `--show-query` | `--show-query` | — |

**arXiv는 감싸지 않으면 뜻이 조용히 바뀝니다.** 셸이 따옴표를 먹으므로
`--query "chain of thought"` 는 세 단어로 도착하고, arXiv는 87,029건을 돌려줍니다 —
`all:"chain of thought"` 의 5,669건이 아니라 `chain` 한 단어의 결과와 대체로 같습니다.
factlog는 감쌌다는 사실을 stderr에 알립니다. 한 단어·필드 프리픽스(`ti:` 등)·불리언
연산자·이미 들어 있는 큰따옴표 넷 중 하나면 그대로 전송됩니다.

**PubMed는 반대입니다.** 따옴표로 감싸면 Automatic Term Mapping이 **꺼져서** 오히려
`QuotedPhraseNotFound` 0건으로 무너질 수 있습니다. 그래서 그대로 보내되 PubMed 자신의
`<QueryTranslation>` 을 결과 끝에 표면화합니다 — 내 단어를 어떻게 읽었는지 보입니다.

자세한 규칙(감싸기를 끄는 법, 거부되는 두 경우, MeSH 텀 검증 결정, `--year` 범위 밖 연도가
기록되는 두 경로)은 [arxiv.md](arxiv.md#검색-쿼리의-조용한-함정) 과
[pubmed.md](pubmed.md#검색-쿼리의-조용한-함정) 에 있습니다.

## 철회 신호는 세 곳에서 서로 다른 것을 뜻합니다

같은 "철회"라는 말이 서로 다른 절차를 가리킵니다. 세 **데이터베이스** 연동은 각각
**자기 이름이 붙은 front matter 키와 자기 종결 명령**으로 다룹니다.

| | 무엇인가 | front matter 키 | 종결 명령 |
| --- | --- | --- | --- |
| arXiv | 프리프린트에 대한 **저자 또는 관리자**의 회수 | `arxiv_withdrawn` · `arxiv_withdrawn_by` | `arxiv-acknowledge-withdrawal` |
| PubMed | 저널 철회에 대한 **NLM 큐레이션의 사실** | `pubmed_retracted` · `pubmed_retraction_notice_pmid` | `pubmed-acknowledge-retraction` |
| OpenAlex | 자동 산출된 **OpenAlex의 의견** | `openalex_is_retracted` | `openalex-acknowledge-retraction` |
| Zotero | 사람이 항목에 붙인 **태그** (`retract` 를 포함하는 태그면 참) | `retracted` — 유일하게 접두어 없는 맨 키 | 없음(태그를 사람이 직접 고침) |

Zotero의 맨 `retracted:` 키가 접두어 없이 쓰이는 것은 상류 데이터베이스의 주장이 아니라
**사람이 자기 라이브러리에 남긴 판단**이기 때문입니다. 상류가 나중에 뒤집을 수 있는 값이
아니므로 종결 명령도 없습니다.

**데이터베이스가 어긋날 때 믿을 우선순위: PubMed > Zotero 태그 > OpenAlex.** OpenAlex는
Lancet Commission 치매 보고서를 철회로 표시하지만 PubMed에는 철회 기록이 없습니다 (#51).

**그럼에도 우선순위가 사람 게이트를 대체하지는 않습니다.** PubMed가 사실 출처라는 것은
factlog가 그 값을 조용히 접는다는 뜻이 아닙니다. 세 신호 모두 source-scoped로 남아 사람이
종결할 때까지 매 refresh마다 올라옵니다.

### `--yes` 는 기록할 수는 있어도 해제할 수는 없습니다 — arXiv · PubMed (#106)

상류가 철회를 더 이상 보고하지 않는다는 사실은 "진짜 되돌렸다"일 수도 있고 "철회 문장을
읽지 못했다 / 큐레이션이 늦다"일 수도 있으며, 코드는 이 둘을 구별하지 못합니다.
**기록은 소리를 내는 방향이고 해제는 침묵시키는 방향입니다.** 해제는 사람이 터미널에서
노트를 직접 보고 확인해야 하며, `arxiv-acknowledge-withdrawal` 과
`pubmed-acknowledge-retraction` 은 `--yes` 아래의 해제를 거부하고 아무것도 쓰지 않습니다.

**`openalex-acknowledge-retraction` 에는 이 게이트가 없습니다.** `--yes` 를 주면 프롬프트
없이 해제(원장에서 `is_retracted` 키 제거)까지 수행합니다. 비대화형 실행에서 OpenAlex
철회를 지울 생각이 없다면 `--yes` 를 붙이지 마세요. 이 비대칭이 의도인지 결함인지는
[#414](https://github.com/SeoyunL/factlog-academic/issues/414) 에서 다룹니다.

세 명령 모두 `--id` 하나만 받습니다 — `--all` 도 와일드카드도 없습니다. 영향 범위는 사람이
고른 id 하나입니다. 그리고 조회는 **원장을 확인한 뒤에** 일어납니다: 원장이 없는 논문은
요청을 0회 쓰고 거부하며 백필 명령을 가리킵니다.

## `--auto-update` 가 쓰는 필드는 좁습니다

refresh 계열은 기본적으로 **보고만** 합니다(check-log 타임스탬프 외에는 아무것도 쓰지
않음). `--auto-update` 를 줘도 아래 필드만 원장에 씁니다.

| 명령 | 쓰는 필드 | 절대 쓰지 않는 것 |
| --- | --- | --- |
| `openalex-refresh` | `doi` · `work_type` · `journal` | `is_retracted`, 병합된 id(`id superseded`) |
| `arxiv-check-versions` | `version` · `last_updated` · `comment` | `withdrawn_by`, 충돌 상태 |
| `pubmed-refresh` | `doi` · `journal` | `retracted`, 병합·삭제된 PMID |

이 값들은 *전사(transcription)* 사실입니다 — 임포트 때 없던 DOI가 지금 있거나, NLM이 그새
정규화한 저널 약칭. 상류의 답은 원장이 옮겨 적은 값에 대한 정정이지 세상에 대한 주장이
아닙니다. `sources/*.md` 는 front matter를 **읽기만 하고 쓰기로는 절대 열지 않으므로**
바이트도 `mtime_ns` 도 동일하게 유지됩니다(P4). 값이 이미 일치하면 파일을 다시 쓰지 않는 바이트 단위 no-op 입니다.

**정체(identity)의 변경은 따라가지 않습니다.** OpenAlex가 저작을 병합해 `W_a` 요청에
`W_b` 로 답하면 `id superseded` 라는 별도 신호로 보고하고 원장의 키를 바꾸지 않습니다.
PubMed의 병합된 PMID도 제안될 뿐 따라가지 않습니다 — PMID는 교차 소스 조인 키라 재키잉하면
향후 import가 무엇에 병합할지가 달라지므로 사람의 결정(P1)입니다. 삭제된 PMID도 KB
엔트리를 조용히 drop하지 않습니다. 그리고 **네트워크 실패를 삭제로 오인하지 않습니다.**

### arXiv에만 있는 두 상태

`arxiv-check-versions` 는 `unchanged`/`changed` 로 뭉뚱그리지 않는 상태 둘을 더 냅니다.

- **`no-version`** (#121) — 비교할 버전이 원장에 없습니다. `unchanged` 라고 하면 이 명령이
  존재하는 이유인 신호에서 그 논문이 조용히 빠집니다. 원인이 넷이고 고치는 명령도 넷이라,
  리포트가 논문마다 해당하는 답을 직접 출력합니다.
- **`version-conflict`** (#137) — 한 논문의 소스들이 서로 다른 버전을 주장합니다. 두 값 중
  하나를 고르는 것은 갱신의 권한이 아니라 추측이므로 `--auto-update` 도 해결하지 않고,
  사람이 소스를 조율할 때까지 실행마다 올라옵니다. KB가 자기 모순이면 종료 코드는 0이
  아닙니다.

## `*-backfill-provenance` — 원장 이전에 임포트한 것 구제하기

원장 도입(#82/#84) 이전에 임포트된 항목은 front matter만 있고 원장이 없습니다. 재임포트해도
원장이 생기지 않고(front matter 정체 일치에서 sidecar writer 전에 멈춤), **원장이 없으면
철회를 종결할 수 없습니다** — 결정을 적을 곳이 없기 때문입니다. 백필이 그 다리입니다.

```bash
factlog openalex-backfill-provenance --dry-run
factlog arxiv-backfill-provenance --dry-run
factlog pubmed-backfill-provenance --dry-run
```

새 주장을 만드는 것이 아니라 **믿음이 저장되는 위치만** 바꾸므로, acknowledge와 달리 확인
프롬프트도 `--yes` 도 TTY 게이트도 없습니다. **네트워크를 쓰면 이는 refresh가 되어 임포트
이후 나타난 철회를 흡수하게 되므로**, 백필은 그 경계를 넘지 않습니다.

refused 되는 경우는 연동마다 다릅니다.

| 연동 | refused 조건 |
| --- | --- |
| 공통 | `imported_at` 이 없음 |
| arXiv | `arxiv_version` 을 읽을 수 없음 — `version` 은 **식별 필드**라, 없는 채로 적으면 나중에 진짜 값을 가진 임포트가 가짜 divergence를 냅니다 |
| OpenAlex | `openalex_is_retracted` 가 YAML 불리언이 아님(`1`, `yes`, `on`) |
| PubMed | `pubmed_retracted` 가 YAML 불리언이 아님 |

불리언 아닌 값을 **추측으로 보정하지 않는** 이유는 양쪽 다 거짓말이기 때문입니다. 값을
버리면 "상류가 이 논문을 철회로 표시하지 않았다"고 주장해 `.md` 가 말하려던 철회를
침묵시키고, `1` 을 참으로 읽으면 어떤 소스도 하지 않은 철회를 주장하게 됩니다.

### 어떤 명령으로도 고칠 수 없는 한 경우

원장이 없고 front matter에 `arxiv_version` 도 없는 arXiv 논문입니다. `arxiv-import` 는
`already imported` 로 건너뛰고, 백필은 `refused` 합니다. **막힌 것을 푸는 것은 명령이 아니라
사람입니다** — `sources/*.md` front matter에 `arxiv_version: <N>` 을 손으로 추가해야 비로소
백필이 원장을 만들 수 있습니다. `<N>` 은 `https://arxiv.org/abs/<id>` 에서 사람이 직접
읽습니다. factlog가 대신 조회하면 백필이 네트워크 refresh가 되어 위 경계를 깹니다.

## Zotero에만 있는 것

Zotero는 검색 API가 아니라 **사람이 이미 큐레이션한 라이브러리**라, 다른 셋에 없는 두
기능이 있습니다.

- **`--pdf`** — 저장형 PDF 첨부를 `sources/<stem>-<attkey>.pdf` 로 받고, 기존 `ingest`
  파이프라인으로 `runs/sources/<stem>-<attkey>.pdf.txt` 를 만듭니다. `pdftotext`(poppler)가
  필요합니다. **KB를 버전 관리한다면 `.gitignore` 에 `*.pdf` 를 넣으세요**(저작권).
- **`--annotations`** — 하이라이트·노트를 `sources/<stem>-notes.md` 로 이관합니다. 내용이
  Zotero 상태의 순수 함수라 변화 없으면 그대로 두고(skipped), 늘면 다시 씁니다(updated).
  사용자가 직접 만든 같은 이름의 파일은 덮어쓰지 않습니다(P4).

둘 다 **P1 경계를 지킵니다** — 하이라이트·노트는 candidate로 직접 쓰이지 않고 소스 텍스트로만
들어갑니다. candidate는 여전히 `sync` 와 사람의 `accept` 를 거칩니다.

아직 지원하지 않는 것: 스캔 PDF의 OCR, image/ink 주석, 비-PDF 첨부 변환, 독립 노트, 양방향
동기화, 그룹 라이브러리, Web API.

## 인용 내보내기는 네 연동을 함께 읽습니다

```bash
factlog export --bibtex > refs.bib
factlog export --csl -o refs.json
```

엔트리 타입을 담는 front matter 키가 연동마다 다르므로, **먼저 답하는 키 하나**를
채택합니다.

| 순서 | 키 | 쓰는 연동 |
| --- | --- | --- |
| 1 | `item_type` | Zotero |
| 2 | `type` (단, `imported_from: openalex` 일 때만) | OpenAlex |
| 3 | `preprint: true` | arXiv |
| 4 | (아무 키도 없을 때) `journal` 유무 | PubMed |

4단계는 타입을 선언한 키가 하나도 없을 때만 동작합니다 — 선언된 타입을 `journal` 로
덮어쓰지 않습니다. arXiv 기탁본은 `journal` 이 후속 게재를 기록해도 여전히 preprint이기
때문입니다(#60). 게재지 값이 어느 필드로 가는지는
[zotero-import.md](zotero-import.md#게재지journal가-들어가는-필드) 를 보세요.

## 더 읽기

- [소스 파일 형식](reference/sources.md) — 지원 형식, `factlog ingest`, 변환본 명명 규칙
- [사실 검토](reference/review.md) — `review` · `accept` · `reject` · `amend`
- [활성 KB](reference/active-kb.md) — `factlog use` / `where`, KB 해석 우선순위
- [결정론과 한계](guide/determinism.md) — 무엇이 보장되고 무엇이 보장되지 않는지
- [소스 제외와 제거](reference/ignore-eject.md) — `factlog ignore` · `eject`
